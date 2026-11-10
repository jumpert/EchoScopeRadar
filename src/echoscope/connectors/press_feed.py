import asyncio
import json
from contextlib import aclosing
from dataclasses import replace
from urllib.parse import urlsplit

from echoscope.application.ports import ConnectorError, Request, Transient
from echoscope.domain.models import Batch, Kind
from echoscope.domain.rules import evaluate

from .comment_feed import discover_discussion_feeds
from .syndication import Feed


def _site(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


class PressFeed:
    async def poll(self, request: Request):
        state = json.loads(request.checkpoint or "{}")
        targets = state.setdefault("targets", {})
        feed_url = request.source.params["url"]
        async with aclosing(Feed().poll(replace(request, checkpoint=state.get("main")))) as reader:
            async for batch in reader:
                state["main"] = batch.checkpoint
                for item in batch.messages:
                    if (
                        item.url
                        and _site(item.url) == _site(feed_url)
                        and any(match.confirmed for match in evaluate(item.text, request.rules))
                    ):
                        targets.setdefault(
                            item.url, {"feed": None, "checked": False, "cursor": None}
                        )
                yield replace(batch, checkpoint=request.checkpoint)

        # Bound discovery and follow-up traffic. URLs and validators survive a 304 on the main RSS.
        state["targets"] = targets = dict(list(targets.items())[-12:])
        pending = [
            (url, target) for url, target in targets.items() if not target.get("discussion_checked")
        ]
        for article, target in pending[:2]:
            try:
                candidates = await asyncio.wait_for(discover_discussion_feeds(article), timeout=4)
            except (Transient, TimeoutError):
                continue
            except (ConnectorError, ValueError):
                target["discussion_checked"] = True
            else:
                target["discussion_checked"] = True
                for field, kind in (("feed", Kind.PRESS_COMMENT), ("review_feed", Kind.REVIEW)):
                    candidate = next(
                        (
                            url
                            for url, value in candidates
                            if kind == value and _site(url) == _site(article)
                        ),
                        None,
                    )
                    if candidate and candidate != target.get(field):
                        target[field] = candidate
                        target.pop("cursor" if field == "feed" else "review_cursor", None)
            yield Batch((), json.dumps(state))

        active = [
            (url, target, target[field], kind, cursor)
            for url, target in targets.items()
            for field, kind, cursor in (
                ("feed", Kind.PRESS_COMMENT, "cursor"),
                ("review_feed", Kind.REVIEW, "review_cursor"),
            )
            if target.get(field)
        ]
        start = state.get("offset", 0) % max(1, len(active))
        for offset in range(min(2, len(active))):
            article, target, endpoint, kind, cursor = active[(start + offset) % len(active)]
            # Never send credentials from the main feed to a discovered endpoint.
            source = request.source.model_copy(
                update={
                    "credential": None,
                    "params": {"url": endpoint, "kind": kind.value},
                }
            )
            try:
                async with aclosing(
                    Feed().poll(
                        replace(
                            request,
                            source=source,
                            checkpoint=target.get(cursor),
                            timeout_s=min(8, request.timeout_s),
                        )
                    )
                ) as reader:
                    async for batch in reader:
                        target[cursor] = batch.checkpoint
                        yield Batch(
                            tuple(
                                replace(item, resource_id=article, url=item.url or article)
                                for item in batch.messages
                            ),
                            json.dumps(state),
                        )
            except (ConnectorError, TimeoutError):
                continue
        state["offset"] = start + min(2, len(active))
        yield Batch((), json.dumps(state))
