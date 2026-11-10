import asyncio
from contextlib import aclosing
from dataclasses import dataclass, replace
from time import monotonic

from echoscope.connectors.bluesky import BlueskyThread
from echoscope.connectors.comment_feed import discover_discussion_feeds
from echoscope.connectors.syndication import Feed
from echoscope.connectors.youtube import YouTubeLive
from echoscope.connectors.youtube_comments import YouTubeComments, video_id
from echoscope.domain.models import Message

from .administration import YOUTUBE_KEY
from .config import Credential, Source
from .ports import ConnectorError, Request, SourceEnded


@dataclass(frozen=True, slots=True)
class Conversation:
    messages: tuple[Message, ...] = ()
    feeds: tuple[tuple[str, str], ...] = ()
    status: str = ""
    partial: bool = False


class Conversations:
    def __init__(self):
        self.slots = asyncio.Semaphore(3)
        self.cache = {}

    async def read(self, kind, url):
        key = (kind, url)
        async with self.slots:
            if key in self.cache and self.cache[key][0] > monotonic():
                return self.cache[key][1]
            try:
                async with asyncio.timeout(14):
                    if kind in {"video", "live"}:
                        result = await self._youtube(kind, url)
                    elif kind == "social":
                        result = await self._bluesky(url)
                    else:
                        result = await self._site(url)
            except ConnectorError as exc:
                result = Conversation(status=exc.label)
            except TimeoutError:
                result = Conversation(status="La fuente tardó en responder. Volvé a consultar.")
            if key not in self.cache and len(self.cache) >= 32:
                del self.cache[next(iter(self.cache))]
            self.cache.pop(key, None)
            self.cache[key] = (monotonic() + 60, result)
            return result

    async def _site(self, url):
        feeds = await discover_discussion_feeds(url)
        if not feeds:
            return Conversation(
                status="El sitio no anuncia un feed de comentarios o reseñas accesible."
            )
        messages = []
        partial = len(feeds) > 3
        failures = []
        for address, kind in feeds[:3]:
            source = Source(id="preview", type="syndication", params={"url": address, "kind": kind})
            try:
                async with aclosing(Feed().poll(Request(source, None, 3))) as reader:
                    async for batch in reader:
                        messages.extend(
                            replace(item, resource_id=url, url=item.url or url)
                            for item in batch.messages
                        )
                        if len(messages) >= 120:
                            partial = True
                            break
            except (ConnectorError, TimeoutError) as exc:
                partial = True
                failures.append(exc.label if isinstance(exc, ConnectorError) else "TIEMPO AGOTADO")
            if len(messages) >= 120:
                break
        status = (
            f"Algún feed no respondió: {', '.join(dict.fromkeys(failures))}." if failures else ""
        )
        return Conversation(tuple(messages[:120]), tuple(feeds[:3]), status, partial)

    async def _bluesky(self, url):
        source = Source(id="preview", type="bluesky_thread", params={"url": url})
        messages = []
        partial = False
        async for batch in BlueskyThread().poll(Request(source, None, 6)):
            messages.extend(batch.messages)
            partial |= batch.coverage_gap
        return Conversation(
            tuple(messages), status="Respuestas públicas de Bluesky.", partial=partial
        )

    async def _youtube(self, kind, url):
        live = kind == "live"
        params = {"video_id": video_id(url)}
        if not live:
            params.update(max_pages=2, reply_requests=4)
        source = Source(
            id="preview",
            type="youtube_live" if live else "youtube_comments",
            params=params,
            credential=Credential(kind="api_key", env=YOUTUBE_KEY),
        )
        request = Request(source, None, 5)
        reader = YouTubeLive().stream(request) if live else YouTubeComments().poll(request)
        messages = []
        partial = live
        status = "Ventana reciente del chat en vivo." if live else ""
        try:
            async with aclosing(reader):
                async for batch in reader:
                    messages.extend(batch.messages)
                    partial |= batch.coverage_gap
                    if live or len(messages) >= 120:
                        partial |= len(messages) >= 120
                        break
        except SourceEnded:
            if not live:
                raise
            return await self._youtube("video", url)
        except (ConnectorError, TimeoutError):
            if not messages:
                raise
            partial = True
        return Conversation(tuple(messages[:120]), status=status, partial=partial)
