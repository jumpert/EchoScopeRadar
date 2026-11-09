import asyncio
import json

import aiohttp
from pydantic import Field

from echoscope.application.config import StrictModel
from echoscope.application.ports import (
    AuthRequired,
    CursorExpired,
    Forbidden,
    RateLimited,
    Request,
    SourceEnded,
    SourceUnavailable,
    SourceWaiting,
    Transient,
)
from echoscope.domain.models import Batch, Kind, Message

from .syndication import parse_date

VIDEO_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"
CHAT_ENDPOINT = "youtube.googleapis.com:443"
STREAM_RPC = "/youtube.api.v3.V3DataLiveChatMessageService/StreamList"


class YouTubeParams(StrictModel):
    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")


def grpc_failure(error, page_token):
    from grpc import StatusCode

    code = error.code()
    detail = (error.details() or "").upper()
    if "LIVE_CHAT_ENDED" in detail or "LIVECHATENDED" in detail:
        return SourceEnded()
    if "LIVE_CHAT_DISABLED" in detail or code in {
        StatusCode.FAILED_PRECONDITION,
        StatusCode.NOT_FOUND,
    }:
        return SourceUnavailable()
    if code == StatusCode.UNAUTHENTICATED:
        return AuthRequired()
    if code == StatusCode.PERMISSION_DENIED:
        return Forbidden()
    if code == StatusCode.RESOURCE_EXHAUSTED:
        return RateLimited()
    if code == StatusCode.INVALID_ARGUMENT:
        return CursorExpired() if page_token else SourceUnavailable()
    return Transient()


class YouTubeLive:
    def _channel(self, grpc):
        return grpc.aio.secure_channel(
            CHAT_ENDPOINT,
            grpc.ssl_channel_credentials(),
            options=(
                ("grpc.enable_http_proxy", 0),
                ("grpc.max_receive_message_length", 4 * 1024 * 1024),
            ),
        )

    async def _chat(self, video_id, headers, timeout):
        try:
            async with aiohttp.ClientSession(
                trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(
                    VIDEO_ENDPOINT,
                    params={"part": "liveStreamingDetails", "id": video_id},
                    headers=headers,
                    allow_redirects=False,
                ) as response:
                    if response.status == 401:
                        raise AuthRequired()
                    if response.status == 429:
                        raise RateLimited()
                    if response.status >= 500:
                        raise Transient()
                    data = await response.json(content_type=None)
                    reasons = {
                        item.get("reason") for item in data.get("error", {}).get("errors", [])
                    }
                    if reasons & {
                        "quotaExceeded",
                        "dailyLimitExceeded",
                        "rateLimitExceeded",
                        "userRateLimitExceeded",
                    }:
                        raise RateLimited()
                    if reasons & {"keyInvalid", "authError"} or response.status == 400:
                        raise AuthRequired()
                    if response.status == 403:
                        raise Forbidden()
                    if response.status != 200 or not data.get("items"):
                        raise SourceUnavailable()
        except (aiohttp.ClientError, ValueError):
            raise Transient() from None
        details = data["items"][0].get("liveStreamingDetails", {})
        if chat := details.get("activeLiveChatId"):
            return chat
        if details.get("actualEndTime"):
            raise SourceEnded()
        if details.get("scheduledStartTime") and not details.get("actualStartTime"):
            raise SourceWaiting()
        raise SourceUnavailable()

    async def stream(self, request: Request):
        try:
            import grpc

            from . import stream_list_pb2 as pb
        except ImportError:
            raise SourceUnavailable() from None
        credential = request.source.credential
        token = credential.resolve() if credential else None
        if (
            not token
            or not token.isascii()
            or not token.isprintable()
            or any(character.isspace() for character in token)
        ):
            raise AuthRequired()
        headers = (
            {"x-goog-api-key": token}
            if credential.kind == "api_key"
            else {"authorization": f"Bearer {token}"}
        )
        video_id = YouTubeParams.model_validate(request.source.params).video_id
        chat = await self._chat(video_id, headers, request.timeout_s)
        checkpoint = json.loads(request.checkpoint) if request.checkpoint else {}
        gap = bool(checkpoint and checkpoint.get("chat") != chat)
        page = None if gap else checkpoint.get("page")
        payload = pb.LiveChatMessageListRequest(
            live_chat_id=chat, part=["id", "snippet", "authorDetails"], max_results=200
        )
        if page:
            payload.page_token = page
        async with self._channel(grpc) as channel:
            await asyncio.wait_for(channel.channel_ready(), request.timeout_s)
            rpc = channel.unary_stream(
                STREAM_RPC,
                request_serializer=pb.LiveChatMessageListRequest.SerializeToString,
                response_deserializer=pb.LiveChatMessageListResponse.FromString,
            )
            call = rpc(payload, metadata=list(headers.items()))
            try:
                response = await asyncio.wait_for(call.read(), request.timeout_s)
                while response is not grpc.aio.EOF:
                    messages = []
                    ended = bool(response.offline_at)
                    for item in response.items:
                        snippet = item.snippet
                        types = pb.LiveChatMessageSnippet.TypeWrapper
                        if snippet.type == types.CHAT_ENDED_EVENT:
                            ended = True
                        body = {
                            types.TEXT_MESSAGE_EVENT: snippet.text_message_details.message_text,
                            types.SUPER_CHAT_EVENT: snippet.super_chat_details.user_comment,
                            types.MEMBER_MILESTONE_CHAT_EVENT: snippet.member_milestone_chat_details.user_comment,
                        }.get(snippet.type)
                        if not body and snippet.type == types.TEXT_MESSAGE_EVENT:
                            body = snippet.display_message
                        if item.id and body:
                            messages.append(
                                Message(
                                    Kind.LIVE_CHAT,
                                    "youtube:live",
                                    item.id,
                                    video_id,
                                    body,
                                    item.author_details.display_name or None,
                                    item.author_details.channel_id
                                    or snippet.author_channel_id
                                    or None,
                                    f"https://www.youtube.com/watch?v={video_id}",
                                    parse_date(snippet.published_at),
                                )
                            )
                    page = response.next_page_token or page
                    yield Batch(tuple(messages), json.dumps({"chat": chat, "page": page}), gap)
                    gap = False
                    if ended:
                        raise SourceEnded()
                    response = await call.read()
            except grpc.aio.AioRpcError as error:
                raise grpc_failure(error, page) from None
            finally:
                call.cancel()
