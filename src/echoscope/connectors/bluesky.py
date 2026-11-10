import json
import re
from collections import deque
from urllib.parse import urlsplit

import aiohttp
from pydantic import field_validator

from echoscope.application.config import StrictModel
from echoscope.application.ports import ConnectorError, Forbidden, RateLimited, Transient
from echoscope.domain.models import Batch, Kind, Message

from .syndication import parse_date

API = "https://public.api.bsky.app/xrpc"
ACTOR = re.compile(r"[A-Za-z0-9._:%-]{1,253}")
POST = re.compile(r"[A-Za-z0-9._~-]{1,120}")


def post_address(url):
    parsed = urlsplit(url)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme == "https"
        and parsed.hostname == "bsky.app"
        and parsed.username is None
        and parsed.port in (None, 443)
        and len(parts) == 4
        and parts[0] == "profile"
        and parts[2] == "post"
        and ACTOR.fullmatch(parts[1])
        and POST.fullmatch(parts[3])
    ):
        return parts[1], parts[3]
    raise ValueError("Pegá el enlace público de una publicación de Bluesky.")


class BlueskyParams(StrictModel):
    url: str

    @field_validator("url")
    @classmethod
    def normalize(cls, value):
        actor, key = post_address(value)
        return f"https://bsky.app/profile/{actor}/post/{key}"


async def _get(session, endpoint, params):
    try:
        async with session.get(
            f"{API}/{endpoint}", params=params, allow_redirects=False
        ) as response:
            if response.status in {401, 403}:
                raise Forbidden()
            if response.status == 429:
                raise RateLimited()
            if response.status != 200:
                raise ConnectorError()
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > 4 * 1024 * 1024:
                    raise ConnectorError()
            return json.loads(body)
    except (aiohttp.ClientError, ValueError) as exc:
        raise Transient() from exc


def link_for(uri):
    if uri.startswith("at://"):
        parts = uri[5:].split("/")
        if (
            len(parts) == 3
            and parts[1] == "app.bsky.feed.post"
            and ACTOR.fullmatch(parts[0])
            and POST.fullmatch(parts[2])
        ):
            return f"https://bsky.app/profile/{parts[0]}/post/{parts[2]}"
    return None


class BlueskyThread:
    async def poll(self, request):
        params = BlueskyParams.model_validate(request.source.params)
        actor, key = post_address(params.url)
        async with aiohttp.ClientSession(
            trust_env=False, timeout=aiohttp.ClientTimeout(total=request.timeout_s)
        ) as session:
            if not actor.startswith("did:"):
                profile = await _get(session, "app.bsky.actor.getProfile", {"actor": actor})
                actor = profile.get("did", "")
                if not ACTOR.fullmatch(actor) or not actor.startswith("did:"):
                    raise ConnectorError()
            result = await _get(
                session,
                "app.bsky.feed.getPostThread",
                {
                    "uri": f"at://{actor}/app.bsky.feed.post/{key}",
                    "depth": 6,
                    "parentHeight": 0,
                },
            )
        root = result.get("thread", {})
        if not root.get("post"):
            raise Forbidden()
        pending = deque(root.get("replies", []))
        messages = []
        partial = root["post"].get("replyCount", 0) > len(pending)
        while pending and len(messages) < 120:
            node = pending.popleft()
            post = node.get("post", {})
            replies = node.get("replies", [])
            pending.extend(replies)
            partial |= not post or post.get("replyCount", 0) > len(replies)
            identifier = post.get("uri", "")
            record = post.get("record", {})
            if (body := record.get("text")) and (url := link_for(identifier)):
                author = post.get("author", {})
                messages.append(
                    Message(
                        Kind.SOCIAL_COMMENT,
                        "bluesky:reply",
                        identifier,
                        params.url,
                        body,
                        author.get("handle"),
                        author.get("did"),
                        url,
                        parse_date(record.get("createdAt")),
                    )
                )
        partial |= bool(pending)
        for start in range(0, len(messages), 50):
            yield Batch(
                tuple(messages[start : start + 50]), None, partial and start + 50 >= len(messages)
            )
        if not messages:
            yield Batch((), None, partial)
