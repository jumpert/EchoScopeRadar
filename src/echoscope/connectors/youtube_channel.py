import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

import aiohttp
from pydantic import Field, field_validator

from echoscope.application.config import StrictModel
from echoscope.application.ports import (
    LiveChatPending,
    SourceEnded,
    SourceUnavailable,
    SourceWaiting,
)
from echoscope.domain.models import Batch, Kind, Message, utcnow
from echoscope.domain.rules import evaluate

from .policy import current_targets, publication_selected
from .syndication import parse_date
from .youtube import YouTubeLive, youtube_headers
from .youtube_comments import CommentsUnavailable, YouTubeComments, _get

CHANNEL = re.compile(r"UC[A-Za-z0-9_-]{22}\Z")
HANDLE = re.compile(r"@[\w.-]{3,30}\Z")


def channel_reference(value):
    value = value.strip().rstrip("/")
    if CHANNEL.fullmatch(value) or HANDLE.fullmatch(value):
        return value
    link = urlsplit(value)
    if (
        link.scheme == "https"
        and link.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}
        and link.username is None
    ):
        parts = link.path.strip("/").split("/")
        if parts[0].startswith("@") and HANDLE.fullmatch(parts[0]):
            return parts[0]
        if len(parts) >= 2 and parts[0] == "channel" and CHANNEL.fullmatch(parts[1]):
            return parts[1]
    raise ValueError("Pegá el enlace de un canal de YouTube, su @nombre o su ID de canal.")


class ChannelParams(StrictModel):
    channel: str = Field(min_length=3, max_length=31)

    @field_validator("channel")
    @classmethod
    def known_format(cls, value):
        return channel_reference(value)


def _session(timeout):
    return aiohttp.ClientSession(
        trust_env=False, timeout=aiohttp.ClientTimeout(total=min(timeout, 12))
    )


async def check_access(credential):
    headers = youtube_headers(credential)
    async with _session(10) as session:
        await _get(session, "channels", {"part": "id", "id": "UCeeEsGE06kae6DF-yOGT1Tw"}, headers)


def _text(snippet):
    return "\n".join(part for part in (snippet.get("title"), snippet.get("description")) if part)[
        :16000
    ]


class _Channel:
    def __init__(self):
        self.channel = None

    async def resolve(self, session, request, headers):
        if not self.channel:
            reference = channel_reference(
                ChannelParams.model_validate(request.source.params).channel
            )
            field = "forHandle" if reference.startswith("@") else "id"
            data = await _get(
                session, "channels", {"part": "contentDetails", field: reference}, headers
            )
            if not data.get("items"):
                raise SourceUnavailable()
            self.channel = data["items"][0]
        return self.channel


class YouTubeChannel(_Channel):
    async def poll(self, request):
        headers = youtube_headers(request.source.credential)
        async with _session(request.timeout_s) as session:
            channel = await self.resolve(session, request, headers)
            playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
            data = await _get(
                session,
                "playlistItems",
                {"part": "snippet", "playlistId": playlist, "maxResults": 12},
                headers,
            )
        state = (
            json.loads(request.checkpoint)
            if request.checkpoint and request.checkpoint.startswith("{")
            else {}
        )
        targets = state.setdefault("targets", {})
        messages = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            identifier = snippet.get("resourceId", {}).get("videoId")
            body = _text(snippet)
            if not identifier or not body:
                continue
            matches = evaluate(body, request.rules)
            if matches or request.source.tracking == "owned":
                messages.append(
                    Message(
                        Kind.YOUTUBE_VIDEO,
                        "youtube:video",
                        identifier,
                        identifier,
                        body,
                        url=f"https://www.youtube.com/watch?v={identifier}",
                        published_at=parse_date(snippet.get("publishedAt")),
                        title=snippet.get("title") or "",
                    )
                )
            published = parse_date(snippet.get("publishedAt"))
            if publication_selected(request, snippet.get("title"), published):
                targets[identifier] = {
                    "title": (snippet.get("title") or "")[:300],
                    "published": published.isoformat() if published else None,
                    "seen": targets.get(identifier, {}).get("seen") or utcnow().isoformat(),
                    "cursor": targets.get(identifier, {}).get("cursor"),
                }
        targets = state["targets"] = current_targets(targets, request.source)
        follow = list(targets)
        yield Batch(tuple(messages), request.checkpoint)
        if not follow:
            return
        start = state.get("offset", 0) % len(follow)
        count = min(request.source.resources_per_cycle, len(follow))
        for offset in range(count):
            identifier = follow[(start + offset) % len(follow)]
            title = targets[identifier]["title"]
            child = request.source.model_copy(
                update={
                    "params": {
                        "video_id": identifier,
                        "video_title": title,
                        "max_pages": 1,
                        "reply_requests": 2,
                    }
                }
            )
            try:
                async for batch in YouTubeComments().poll(
                    replace(request, source=child, checkpoint=targets[identifier].get("cursor"))
                ):
                    targets[identifier]["cursor"] = batch.checkpoint
                    yield replace(batch, checkpoint=json.dumps(state))
            except CommentsUnavailable:
                yield Batch((), request.checkpoint, detail="COMENTARIOS CERRADOS O NO DISPONIBLES")
        state["offset"] = (start + count) % len(follow)
        yield Batch((), json.dumps(state))


class YouTubeChannelLive(_Channel):
    async def stream(self, request):
        headers = youtube_headers(request.source.credential)
        async with _session(request.timeout_s) as session:
            channel = await self.resolve(session, request, headers)
            data = await _get(
                session,
                "search",
                {
                    "part": "snippet",
                    "channelId": channel["id"],
                    "eventType": "live",
                    "type": "video",
                    "maxResults": 5,
                },
                headers,
            )
        found = connected = False
        for item in data.get("items", []):
            identifier = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})
            body = _text(snippet)
            if not identifier or not publication_selected(request, snippet.get("title"), None):
                continue
            found = True
            yield Batch(
                (
                    Message(
                        Kind.YOUTUBE_LIVE,
                        "youtube:live:video",
                        identifier,
                        identifier,
                        body,
                        url=f"https://www.youtube.com/watch?v={identifier}",
                        published_at=parse_date(snippet.get("publishedAt")),
                        title=snippet.get("title") or "",
                    ),
                ),
                request.checkpoint,
                stream_ready=False,
            )
            source = request.source.model_copy(update={"params": {"video_id": identifier}})
            try:
                async for batch in YouTubeLive().stream(replace(request, source=source)):
                    connected |= batch.stream_ready
                    yield batch
            except (SourceEnded, SourceUnavailable, SourceWaiting):
                continue
        raise LiveChatPending() if found and not connected else SourceWaiting()
