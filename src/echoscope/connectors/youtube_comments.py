import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp
from pydantic import Field

from echoscope.application.ports import (
    AuthRequired,
    ConnectorError,
    Forbidden,
    RateLimited,
    Request,
    Transient,
)
from echoscope.domain.models import Batch, Kind, Message

from .http import bounded_json
from .syndication import parse_date
from .youtube import YouTubeParams, youtube_headers

API = "https://www.googleapis.com/youtube/v3"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


class CommentsUnavailable(ConnectorError):
    label = "COMENTARIOS NO DISPONIBLES"


class YouTubeCommentsParams(YouTubeParams):
    video_title: str | None = Field(default=None, max_length=300)
    max_pages: int = Field(default=2, ge=1, le=5)
    reply_requests: int = Field(default=8, ge=0, le=30)


@dataclass(frozen=True, slots=True)
class Video:
    id: str
    title: str
    channel: str
    description: str = ""


def video_id(value: str) -> str:
    value = value.strip()
    if VIDEO_ID.fullmatch(value):
        return value
    try:
        url = urlsplit(value)
        if url.scheme in {"http", "https"} and url.username is None and url.port in {None, 80, 443}:
            parts = url.path.strip("/").split("/")
            if url.hostname == "youtu.be" and len(parts) == 1:
                candidate = parts[0]
            elif url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
                if parts == ["watch"]:
                    candidate = parse_qs(url.query).get("v", [""])[0]
                elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
                    candidate = parts[1]
                else:
                    candidate = ""
            else:
                candidate = ""
            if VIDEO_ID.fullmatch(candidate):
                return candidate
    except ValueError:
        pass
    raise ValueError("Pegá el enlace de un video de YouTube o su ID de 11 caracteres.")


async def _get(session, endpoint, params, headers):
    try:
        async with session.get(
            f"{API}/{endpoint}", params=params, headers=headers, allow_redirects=False
        ) as response:
            if response.status == 401:
                raise AuthRequired()
            if response.status == 429:
                raise RateLimited()
            if response.status >= 500:
                raise Transient()
            data = await bounded_json(response)
            reasons = {item.get("reason") for item in data.get("error", {}).get("errors", [])}
            if reasons & {
                "quotaExceeded",
                "dailyLimitExceeded",
                "rateLimitExceeded",
                "userRateLimitExceeded",
            }:
                raise RateLimited()
            if reasons & {"keyInvalid", "authError", "API_KEY_INVALID"}:
                raise AuthRequired()
            if (
                reasons & {"commentsDisabled", "videoNotFound", "commentNotFound"}
                or response.status == 404
            ):
                raise CommentsUnavailable()
            if response.status == 403:
                raise Forbidden()
            if response.status != 200:
                raise ConnectorError()
            return data
    except (aiohttp.ClientError, ValueError):
        raise Transient() from None


async def video_titles(session, ids, headers):
    data = await _get(session, "videos", {"part": "snippet", "id": ",".join(ids)}, headers)
    return {
        item["id"]: item["snippet"]["title"]
        for item in data.get("items", [])
        if item.get("id") and item.get("snippet", {}).get("title")
    }


def _message(item, resource, title=None):
    snippet = item.get("snippet", {})
    body = snippet.get("textOriginal") or snippet.get("textDisplay")
    if not item.get("id") or not body:
        return None
    return Message(
        Kind.COMMENT,
        "youtube:comment",
        item["id"],
        resource,
        body,
        snippet.get("authorDisplayName"),
        url=f"https://www.youtube.com/watch?{urlencode({'v': resource, 'lc': item['id']})}",
        published_at=parse_date(snippet.get("publishedAt")),
        resource_title=title,
    )


class YouTubeComments:
    def __init__(self):
        self.title = None

    async def poll(self, request: Request):
        params = YouTubeCommentsParams.model_validate(request.source.params)
        headers = youtube_headers(request.source.credential)
        page = None
        remaining_replies = params.reply_requests
        async with aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=request.timeout_s)
        ) as session:
            title = params.video_title or self.title
            if not title:
                try:
                    title = await video_titles(session, [params.video_id], headers)
                    title = title.get(params.video_id)
                except (ConnectorError, TimeoutError):
                    title = None
            self.title = title
            for index in range(params.max_pages):
                query = {
                    "part": "snippet,replies",
                    "videoId": params.video_id,
                    "textFormat": "plainText",
                    "order": "time",
                    "maxResults": 50,
                }
                if page:
                    query["pageToken"] = page
                data = await _get(session, "commentThreads", query, headers)
                page = data.get("nextPageToken")
                partial = bool(page and index == params.max_pages - 1)
                messages = []
                for thread in data.get("items", []):
                    details = thread.get("snippet", {})
                    root = details.get("topLevelComment", {})
                    if message := _message(root, params.video_id, title):
                        messages.append(message)
                    replies = {
                        item["id"]: item
                        for item in thread.get("replies", {}).get("comments", [])
                        if item.get("id")
                    }
                    total = details.get("totalReplyCount", 0)
                    reply_page = None
                    while root.get("id") and len(replies) < total and remaining_replies:
                        reply_query = {
                            "part": "snippet",
                            "parentId": root["id"],
                            "textFormat": "plainText",
                            "maxResults": 100,
                        }
                        if reply_page:
                            reply_query["pageToken"] = reply_page
                        remaining_replies -= 1
                        try:
                            response = await _get(session, "comments", reply_query, headers)
                        except CommentsUnavailable:
                            break
                        replies.update(
                            {
                                item["id"]: item
                                for item in response.get("items", [])
                                if item.get("id")
                            }
                        )
                        reply_page = response.get("nextPageToken")
                        if not reply_page:
                            break
                    partial |= len(replies) < total
                    messages.extend(
                        message
                        for item in replies.values()
                        if (message := _message(item, params.video_id, title))
                    )
                # Upstream pagination can shift between polls. The store deduplicates this recent window.
                for start in range(0, len(messages), 50):
                    yield Batch(
                        tuple(messages[start : start + 50]),
                        None,
                        partial and start + 50 >= len(messages),
                    )
                if not messages:
                    yield Batch((), None, partial)
                if not page:
                    break


async def find_videos(terms, credential, *, live=False):
    query = {
        "part": "snippet",
        "type": "video",
        "q": terms,
        "regionCode": "UY",
        "relevanceLanguage": "es",
        "maxResults": 12,
    }
    if live:
        query["eventType"] = "live"
    async with aiohttp.ClientSession(
        trust_env=False, timeout=aiohttp.ClientTimeout(total=15)
    ) as session:
        data = await _get(session, "search", query, youtube_headers(credential))
    return [
        Video(
            item["id"]["videoId"],
            item["snippet"]["title"],
            item["snippet"].get("channelTitle", ""),
            item["snippet"].get("description") or "",
        )
        for item in data.get("items", [])
        if VIDEO_ID.fullmatch(item.get("id", {}).get("videoId", ""))
    ]
