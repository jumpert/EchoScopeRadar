import asyncio
import json
from contextlib import aclosing
from dataclasses import replace
from urllib.parse import urlsplit

from echoscope.application.ports import ConnectorError, Request, Transient
from echoscope.domain.models import Batch, Kind, utcnow

from .comment_feed import discover_discussion_feeds
from .discussion import discover_mechanisms, read_mechanism
from .policy import current_targets, publication_selected
from .syndication import Feed


def _site(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


class PressFeed:
    def publications(self, request):
        return Feed().poll(request)

    async def poll(self, request: Request):
        state = json.loads(request.checkpoint or "{}")
        targets = state.setdefault("targets", {})
        feed_url = request.source.params["url"]
        async with aclosing(self.publications(replace(request, checkpoint=state.get("main")))) as reader:
            async for batch in reader:
                state["main"] = batch.checkpoint
                for item in batch.messages:
                    if (
                        item.url
                        and _site(item.url) == _site(feed_url)
                        and publication_selected(
                            request, item.title or item.text.split("\n")[0], item.published_at
                        )
                    ):
                        targets.setdefault(
                            item.url, {"feed": None, "checked": False, "cursor": None}
                        )
                        if item.title:
                            targets[item.url]["title"] = item.title[:300]
                        targets[item.url].setdefault("seen", utcnow().isoformat())
                        if item.published_at:
                            targets[item.url]["published"] = item.published_at.isoformat()
                yield replace(batch, checkpoint=request.checkpoint)

        # Bound discovery and follow-up traffic. URLs and validators survive a 304 on the main RSS.
        state["targets"] = targets = current_targets(targets, request.source)
        pending = [
            (url, target) for url, target in targets.items() if not target.get("discussion_checked")
        ]
        for article, target in pending[: request.source.resources_per_cycle]:
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
                global_feed = any(
                    urlsplit(url).path.rstrip("/").endswith("/comments/feed")
                    for url, _ in candidates
                )
                try:
                    target["mechanisms"] = await discover_mechanisms(article)
                    if global_feed and any(
                        item["type"] != "html" or item.get("comments")
                        for item in target["mechanisms"]
                    ):
                        target["feed"] = None
                except (ConnectorError, TimeoutError):
                    target["discussion_checked"] = False
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
        issues = []
        for offset in range(min(request.source.resources_per_cycle, len(active))):
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
                                replace(
                                    item,
                                    resource_id=article,
                                    resource_title=target.get("title"),
                                    url=item.url or article,
                                )
                                for item in batch.messages
                                if (
                                    not urlsplit(endpoint)
                                    .path.rstrip("/")
                                    .endswith("/comments/feed")
                                    or item.url
                                    and item.url.split("#", 1)[0].rstrip("/") == article.rstrip("/")
                                )
                            ),
                            json.dumps(state),
                            detail="COMENTARIOS CONSULTADOS"
                            if batch.messages
                            else "SIN COMENTARIOS",
                        )
            except (ConnectorError, TimeoutError) as exc:
                issues.append(exc.label if isinstance(exc, ConnectorError) else "TIEMPO AGOTADO")
        state["offset"] = start + min(request.source.resources_per_cycle, len(active))
        api_targets = [
            (article, target, mechanism)
            for article, target in targets.items()
            for mechanism in target.get("mechanisms", [])
        ]
        api_start = state.get("api_offset", 0) % max(1, len(api_targets))
        for offset in range(min(request.source.resources_per_cycle, len(api_targets))):
            article, target, mechanism = api_targets[(api_start + offset) % len(api_targets)]
            try:
                selected = mechanism
                if mechanism["type"] == "html" and target.get("api_failed"):
                    selected = {**mechanism, "comments": True}
                page = await read_mechanism(
                    selected,
                    article=article,
                    title=target.get("title"),
                    cursor=mechanism.get("cursor"),
                    credential=request.source.comment_credential,
                )
                mechanism["cursor"] = page.next_page
                if mechanism["type"] != "html":
                    target["api_failed"] = False
                yield Batch(
                    page.messages,
                    json.dumps(state),
                    page.partial,
                    detail="CAPTURA PARCIAL"
                    if page.partial
                    else (
                        "COMENTARIOS CONSULTADOS"
                        if any(item.kind == Kind.PRESS_COMMENT for item in page.messages)
                        else "NOTA LEÍDA · SIN COMENTARIOS HTML IDENTIFICABLES"
                        if page.messages
                        else "SIN COMENTARIOS"
                    ),
                )
            except (ConnectorError, TimeoutError) as exc:
                if mechanism["type"] != "html":
                    target["api_failed"] = True
                issues.append(exc.label if isinstance(exc, ConnectorError) else "TIEMPO AGOTADO")
        state["api_offset"] = api_start + min(request.source.resources_per_cycle, len(api_targets))
        unreadable = sum(not target.get("mechanisms") and not target.get("feed")
                         for target in targets.values() if target.get("discussion_checked"))
        detail = (
            "COMENTARIOS · " + " · ".join(dict.fromkeys(issues))
            if issues
            else "SIN ACCESO A COMENTARIOS"
            if targets and not active and not api_targets
            else f"{unreadable} NOTAS SIN MECANISMO DE COMENTARIOS COMPATIBLE"
            if unreadable
            else None
        )
        yield Batch((), json.dumps(state), bool(issues), detail=detail)
