"""Loopback-only administrative workspace for the local Radar engine."""

import argparse
import asyncio
import hmac
import json
import os
import re
import secrets
import sys
import webbrowser
from bisect import bisect_left, bisect_right
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit

from aiohttp import web
from platformdirs import user_data_path
from pydantic import Field, ValidationError

from echoscope.application.administration import (
    RSS_TYPES,
    SOURCE_TYPES,
    YOUTUBE_KEY,
    Administration,
    SourceForm,
)
from echoscope.application.config import StrictModel
from echoscope.application.conversations import Conversations
from echoscope.application.discovery import BRAVE_KEY, TopicDiscovery, public_result_url
from echoscope.application.ports import AuthRequired, ConnectorError, StorageUnavailable
from echoscope.connectors.youtube_comments import VIDEO_ID
from echoscope.domain.models import (
    HistoryQuery,
    Kind,
    Message,
    Observation,
    Result,
    category,
    publication_title,
)
from echoscope.domain.rules import evaluate
from echoscope.domain.tone import message_tone

from .report import report_pdf

PANELS = {
    "news": HistoryQuery(category="news"),
    "press": HistoryQuery(category="press", exclude_kind=Kind.REVIEW),
    "youtube": HistoryQuery(category="youtube"),
    "live": HistoryQuery(category="live"),
    "forum": HistoryQuery(category="forum"),
    "reviews": HistoryQuery(kind=Kind.REVIEW),
    "social": HistoryQuery(category="social"),
}
ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.css": ("app.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
    "/ciberdefensa.png": ("ciberdefensa.png", "image/png"),
}
WORDS = re.compile(r"\S+")


class SourceInput(StrictModel):
    id: str | None = Field(default=None, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    type_label: str
    address: str = Field(min_length=1, max_length=2048)
    minutes: int = Field(ge=1, le=1440)
    enabled: bool = True
    relevant_only: bool = False
    token: str = Field(default="", max_length=4096)


class ControlInput(StrictModel):
    enabled: bool


class TextInput(StrictModel):
    value: str = Field(min_length=1, max_length=4096)


class TopicInput(StrictModel):
    lines: list[str] = Field(max_length=100)


class ThemeInput(StrictModel):
    value: Literal["light", "dark"]


class DiscoveryInput(StrictModel):
    value: str = Field(min_length=1, max_length=200)


class ConversationInput(StrictModel):
    kind: Literal["article", "web", "video", "live", "social"]
    url: str = Field(min_length=1, max_length=2048)


class ReportInput(StrictModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class Workspace:
    def __init__(self, path, practice, auto_start):
        self.service = Administration(path, practice)
        self.discovery = TopicDiscovery(self.service)
        self.conversations = Conversations()
        self.recent_discoveries = {}
        self.report_guard = asyncio.Lock()
        self.practice = practice
        self.auto_start = auto_start
        self.authority = None
        self.token = secrets.token_hex(32)
        self.closed = asyncio.Event()
        self.last_seen = monotonic()
        self.config = None

    async def lifecycle(self, _app):
        self.config = await self.service.open()
        try:
            if self.auto_start:
                await self.service.set_running(True)
            yield
        finally:
            await self.service.close()


KEY = web.AppKey("workspace", Workspace)


def error(message, status):
    return web.json_response({"error": message}, status=status)


@web.middleware
async def boundary(request, handler):
    state = request.app[KEY]
    if not state.authority or request.host != state.authority:
        return error("Dirección local no válida.", 421)
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return error("Solicitud de otro sitio rechazada.", 403)
    if request.method != "GET" and request.method != "HEAD":
        origin = request.headers.get("Origin")
        token = request.headers.get("X-EchoScope-Token", "")
        if (
            origin != f"http://{state.authority}"
            or not token.isascii()
            or not hmac.compare_digest(token, state.token)
        ):
            return error("La sesión cambió. Actualizá la página.", 403)
        if request.content_type != "application/json":
            return error("Formato de solicitud no válido.", 415)
    try:
        response = await handler(request)
    except AuthRequired:
        response = error("Cargá una clave válida en Tema y acceso.", 422)
    except ConnectorError as exc:
        response = error(exc.label, 422)
    except StorageUnavailable:
        response = error("El historial está temporalmente inaccesible.", 503)
    except (ValidationError, json.JSONDecodeError):
        response = error("Revisá los campos del formulario.", 400)
    except ValueError as exc:
        response = error(str(exc), 400)
    if response.status < 400 and request.path.startswith("/api/"):
        state.last_seen = monotonic()
    response.headers.update(
        {
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Cache-Control": "no-store",
        }
    )
    return response


safe_url = public_result_url


def fragments(text, matches):
    """Keep Unicode offsets on the Python side and resolve overlapping highlights."""
    intervals = [item for item in matches if 0 <= item.start < item.end <= len(text)]
    weight = {"info": 1, "important": 2, "critical": 3}
    points = sorted({0, len(text), *(i for match in intervals for i in (match.start, match.end))})
    result = []
    for left, right in zip(points, points[1:]):
        match = max(
            (m for m in intervals if m.start <= left < m.end),
            default=None,
            key=lambda m: (m.confirmed, weight[m.severity], m.priority, m.end - m.start),
        )
        style = (match.severity if match.confirmed else "review") if match else None
        if result and result[-1][1] == style:
            result[-1][0] += text[left:right]
        else:
            result.append([text[left:right], style])
    return result


def marked_slice(text, matches, start, end):
    return fragments(
        text[start:end],
        [
            replace(match, start=max(match.start, start) - start, end=min(match.end, end) - start)
            for match in matches
            if match.start < end and match.end > start
        ],
    )


def match_context(text, matches, body_start):
    body_matches = [
        replace(match, start=max(match.start, body_start))
        for match in matches
        if 0 <= match.start < match.end <= len(text) and match.end > body_start
    ]
    if not body_matches:
        return []
    words = list(WORDS.finditer(text, pos=body_start))
    starts = [word.start() for word in words]
    ends = [word.end() for word in words]
    windows = []
    for match in sorted(body_matches, key=lambda match: (not match.confirmed, match.start)):
        first = bisect_right(ends, match.start)
        last = bisect_left(starts, match.end)
        left = max(0, first - 6, bisect_left(starts, match.start - 84))
        right = min(len(words), last + 6, bisect_right(ends, match.end + 84))
        start = min(match.start, starts[left]) if left < len(starts) else match.start
        end = max(match.end, ends[right - 1]) if right else match.end
        if any(start < old_end and end > old_start for old_start, old_end in windows):
            continue
        windows.append((start, end))
        if len(windows) == 3:
            break
    contexts = []
    for start, end in sorted(windows):
        if contexts:
            contexts.append(["\n", None])
        if text[body_start:start].strip():
            contexts.append(["… ", None])
        contexts.extend(marked_slice(text, body_matches, start, end))
        if text[end:].strip():
            contexts.append([" …", None])
    return contexts


def publication_display(message, matches):
    title = publication_title(message)
    if title and message.text.startswith(title):
        header = marked_slice(message.text, matches, 0, len(title))
        body_start = len(title)
    else:
        header = [[title, None]] if title else []
        body_start = 0
    return {
        "title": title,
        "title_fragments": header,
        "fragments": match_context(message.text, matches, body_start),
    }


def resource_link(message):
    if message.origin.startswith("youtube:") and VIDEO_ID.fullmatch(message.resource_id):
        return f"https://www.youtube.com/watch?v={message.resource_id}"
    if message.kind in {Kind.PRESS_COMMENT, Kind.REVIEW, Kind.FORUM_POST, Kind.SOCIAL_COMMENT}:
        return safe_url(message.resource_id) or safe_url(message.url)
    return safe_url(message.url)


def result_data(result, sources, *, report=False):
    message = result.observation.message
    matches = result.observation.matches
    confirmed = [item for item in matches if item.confirmed]
    severity = next(
        (
            key
            for key in ("critical", "important", "info")
            if any(item.severity == key for item in confirmed)
        ),
        None,
    )
    return {
        "id": result.id,
        "job": result.job_id,
        "source": sources.get(result.source_id, result.source_id),
        "kind": message.kind,
        "category": "reviews"
        if message.kind == Kind.REVIEW
        else category(message.kind, message.origin),
        "author": message.author,
        "date": (message.published_at or message.captured_at).isoformat(),
        "captured": message.captured_at.isoformat(),
        "url": safe_url(message.url or ""),
        "resource_url": resource_link(message),
        "provider": "YouTube" if message.origin.startswith("youtube:") else None,
        "tone": message_tone(message.text),
        **(
            {"fragments": fragments(message.text, matches)}
            if report
            else publication_display(message, matches)
        ),
        "severity": severity,
        "confirmed_terms": list(dict.fromkeys(m.canonical or m.term for m in confirmed)),
        "matches": [
            list(item) for item in dict.fromkeys((m.term, m.canonical, m.method) for m in matches)
        ],
    }


def source_categories(source):
    if source.type == "bluesky_thread":
        return ["social"]
    if source.type == "press_feed":
        return ["news", "press", "reviews"]
    if source.type in {"youtube_live", "youtube_channel_live", "sim_live"}:
        return ["live"]
    if source.type in {"youtube_comments", "youtube_channel"}:
        return ["youtube"]
    if source.params.get("scenario") == "reviews" or source.params.get("kind") == "REVIEW":
        return ["reviews"]
    return [category(Kind(source.params.get("kind", "COMMENT")), "rss")]


def config_data(config):
    sources = {source.id: source for source in config.sources}
    rules = next(iter(config.rule_sets.values()), [])
    jobs = []
    for job in config.jobs:
        source = sources[job.source]
        kind = source.params.get(
            "kind", "SOCIAL_COMMENT" if source.type == "bluesky_thread" else "NEWS_ARTICLE"
        )
        pair = (source.type, "PRESS_COMMENT" if kind == "COMMENT" else kind)
        label = next(
            (
                label
                for label, item in SOURCE_TYPES.items()
                if item == pair or item[0] == source.type and source.type.startswith("youtube_")
            ),
            None,
        )
        if (
            label is None
            and source.type == "syndication"
            and kind in {"NEWS_ARTICLE", "FEED_ENTRY"}
        ):
            label = "Noticias de un sitio (RSS)"
        jobs.append(
            {
                "id": job.id,
                "name": source.label or source.id,
                "type_label": label,
                "address": next(
                    (
                        source.params[key]
                        for key in ("url", "video_id", "channel")
                        if key in source.params
                    ),
                    "",
                ),
                "minutes": job.interval_s / 60,
                "enabled": job.enabled,
                "relevant_only": job.relevant_only,
                "polling": source.type not in {"sim_live", "youtube_live", "youtube_channel_live"},
                "categories": source_categories(source),
                "protected": bool(source.credential and source.credential.kind == "bearer"),
            }
        )
    return {
        "jobs": jobs,
        "types": list(SOURCE_TYPES),
        "topic": [" | ".join((rule.phrase, *rule.aliases)) for rule in rules],
    }


async def bootstrap(request):
    state = request.app[KEY]
    return web.json_response(
        {
            **config_data(state.config),
            "token": state.token,
            "practice": state.practice,
            "theme": await state.service.store.desktop_setting("theme") or "dark",
            "version": version("echoscope-radar"),
        }
    )


async def board(request):
    state = request.app[KEY]
    service = state.service
    views = list(dict.fromkeys(request.query.get("panels", "news,youtube,live").split(",")))
    if views == [""]:
        views = []
    if any(view not in PANELS for view in views):
        raise ValueError("Panel desconocido.")
    text = request.query.get("q", "").strip()[:200] or None
    mode = request.query.get("mode", "all")
    alerts_mode = request.query.get("alerts", "confirmed")
    if mode not in {"all", "confirmed", "review"} or alerts_mode not in {"confirmed", "review"}:
        raise ValueError("Filtro desconocido.")
    limit = min(max(int(request.query.get("limit", 45)), 10), 200)
    snapshots = dict(service.radar.jobs) if service.radar else await service.store.snapshots()
    sources = {source.id: source.label or source.id for source in state.config.sources}
    panels = [
        service.messages(
            replace(
                PANELS[view],
                text=text,
                limit=limit,
                matches_only=mode == "confirmed",
                review_only=mode == "review",
            )
        )
        for view in views
    ]
    alert_query = HistoryQuery(
        text=text,
        limit=20,
        matches_only=alerts_mode == "confirmed",
        review_only=alerts_mode == "review",
    )
    *pages, alerts = await asyncio.gather(*panels, service.messages(alert_query))
    return web.json_response(
        {
            "running": bool(service.radar),
            "key_loaded": bool(os.environ.get(YOUTUBE_KEY)),
            "web_key_loaded": bool(os.environ.get(BRAVE_KEY)),
            "panels": {
                view: [result_data(item, sources) for item in rows]
                for view, rows in zip(views, pages)
            },
            "alerts": [result_data(item, sources) for item in alerts],
            "statuses": [
                {
                    "id": key,
                    "name": snap.source.label or snap.source.id,
                    "state": snap.state,
                    "availability": snap.availability,
                    "detail": snap.detail,
                    "gap": snap.coverage_gap,
                    "next": snap.next_at.isoformat() if snap.next_at else None,
                    "categories": source_categories(snap.source),
                }
                for key, snap in snapshots.items()
            ],
        }
    )


async def action(request):
    state = request.app[KEY]
    service = state.service
    name = request.match_info["name"]
    data = await request.json()
    if name == "monitor":
        await service.set_running(ControlInput.model_validate(data).enabled)
    elif name == "theme":
        await service.set_theme(ThemeInput.model_validate(data).value)
    elif name == "topic":
        state.config = await service.save_topic(TopicInput.model_validate(data).lines)
    elif name == "source":
        fields = SourceInput.model_validate(data)
        if fields.type_label not in SOURCE_TYPES:
            raise ValueError("Seleccioná un tipo de fuente de la lista.")
        old = next((job for job in state.config.jobs if job.id == fields.id), None)
        if fields.id and old is None:
            raise ValueError("La fuente cambió. Actualizá la página.")
        source = next(
            (item for item in state.config.sources if old and item.id == old.source), None
        )
        token_env = (
            source.credential.env
            if source and source.credential and source.type in RSS_TYPES
            else ""
        )
        form = SourceForm(
            fields.label,
            fields.type_label,
            fields.address,
            fields.minutes,
            fields.enabled,
            fields.relevant_only,
            token_env,
        )
        state.config = await service.save_source(form, fields.id, fields.token)
    elif name == "remove":
        state.config = await service.remove_source(TextInput.model_validate(data).value)
    elif name == "probe":
        result = await service.probe(TextInput.model_validate(data).value)
        return web.json_response({"detail": result.detail or "Consulta completada."})
    elif name == "discover":
        return web.json_response(
            {"url": await service.detect_comments(TextInput.model_validate(data).value)}
        )
    elif name == "key":
        await service.credentials(TextInput.model_validate(data).value)
    elif name == "web-key":
        key = TextInput.model_validate(data).value
        if not key.isascii() or not key.isprintable() or any(char.isspace() for char in key):
            raise ValueError("Ingresá una clave de API sin espacios.")
        os.environ[BRAVE_KEY] = key
    elif name == "topic-search":
        terms = DiscoveryInput.model_validate(data).value.strip()
        candidates, notes = await state.discovery.search(terms, state.config)
        projected = []
        for candidate in candidates:
            display = {key: value for key, value in candidate.items() if key != "excerpt"}
            if (item := discovery_record(state, candidate)) is not None:
                display.update(
                    publication_display(item.observation.message, item.observation.matches)
                )
                address = candidate["url"]
                if (
                    address
                    and candidate["kind"] != "feed"
                    and any(m.confirmed for m in item.observation.matches)
                ):
                    state.recent_discoveries.pop(address, None)
                    state.recent_discoveries[address] = item
                    if len(state.recent_discoveries) > 200:
                        del state.recent_discoveries[next(iter(state.recent_discoveries))]
            projected.append(display)
        names = {item.id: item.label or item.id for item in state.config.sources}
        history = await service.messages(HistoryQuery(text=terms, limit=25))
        return web.json_response(
            {
                "candidates": projected,
                "notes": notes,
                "history": [result_data(item, names) for item in history],
            }
        )
    elif name == "conversation":
        fields = ConversationInput.model_validate(data)
        url = safe_url(fields.url)
        if not url or not url.startswith("https://"):
            raise ValueError("Se requiere un enlace HTTPS público.")
        if state.practice:
            return web.json_response(
                {"messages": [], "feeds": [], "status": "Modo de práctica.", "partial": False}
            )
        result = await state.conversations.read(fields.kind, url)
        return web.json_response(
            {
                "messages": [result_data(item, {}) for item in preview_results(state, url, result)],
                "feeds": result.feeds,
                "status": result.status,
                "partial": result.partial,
            }
        )
    elif name == "report":
        return await export_report(state, ReportInput.model_validate(data))
    elif name == "search":
        return web.json_response(
            {
                "videos": [
                    asdict(item)
                    for item in await service.search(TextInput.model_validate(data).value)
                ]
            }
        )
    elif name == "shutdown":
        asyncio.get_running_loop().call_later(0.2, state.closed.set)
    else:
        raise web.HTTPNotFound()
    return web.json_response(config_data(state.config))


def active_rules(state):
    return tuple(spec.compile() for spec in next(iter(state.config.rule_sets.values()), []))


def discovery_record(state, candidate):
    kind = {
        "live": Kind.YOUTUBE_LIVE,
        "video": Kind.YOUTUBE_VIDEO,
        "article": Kind.NEWS_ARTICLE,
        "web": Kind.FEED_ENTRY,
        "social": Kind.FEED_ENTRY,
        "feed": Kind.FEED_ENTRY,
    }.get(candidate["kind"])
    url = safe_url(candidate["url"])
    if kind is None:
        return None
    body = "\n".join(part for part in (candidate["title"], candidate["excerpt"]) if part)
    matches = evaluate(body, active_rules(state))
    origin = (
        "youtube:discovery" if kind in {Kind.YOUTUBE_VIDEO, Kind.YOUTUBE_LIVE} else "search:index"
    )
    message = Message(kind, origin, url or "", url or "", body, url=url, title=candidate["title"])
    return Result(-1, "preview", candidate["source"], Observation(message, matches))


def preview_results(state, url, conversation):
    rules = active_rules(state)
    source = urlsplit(url).hostname or "Vista previa"
    return [
        Result(-(index + 1), "preview", source, Observation(message, evaluate(message.text, rules)))
        for index, message in enumerate(conversation.messages)
    ]


async def export_report(state, fields):
    try:
        start = date.fromisoformat(fields.start)
        end = date.fromisoformat(fields.end)
    except ValueError:
        raise ValueError("Elegí fechas válidas.") from None
    if start > end:
        raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
    if state.report_guard.locked():
        raise ValueError("Ya se está preparando un reporte.")
    async with state.report_guard:
        since = datetime.combine(start, time.min, UTC)
        until = min(datetime.combine(end, time.max, UTC), datetime.now(UTC))
        query = HistoryQuery(since=since, until=until, matches_only=True, limit=500)
        sources = {source.id: source.label or source.id for source in state.config.sources}
        records = []
        seen = set()

        def collect(items):
            for item in items:
                message = item.observation.message
                if message.url and message.kind in {
                    Kind.NEWS_ARTICLE,
                    Kind.FEED_ENTRY,
                    Kind.YOUTUBE_VIDEO,
                    Kind.YOUTUBE_LIVE,
                }:
                    key = ("publication", message.url)
                else:
                    key = (message.origin, message.external_id, message.text)
                if (
                    key not in seen
                    and since <= message.captured_at <= until
                    and any(m.confirmed for m in item.observation.matches)
                ):
                    seen.add(key)
                    records.append(result_data(item, sources, report=True))
                    if len(records) > 5000:
                        raise ValueError(
                            "El período supera los 5.000 registros. Elegí un intervalo más corto."
                        )

        while True:
            page = await state.service.store.messages(query)
            collect(page)
            if len(page) < query.limit:
                break
            query = replace(query, before=page[-1].id)
        radar = state.service.radar
        if radar:
            for identifier in tuple(radar.session):
                collect(await radar.messages(replace(query, job_id=identifier, before=None)))
        for (_, url), (_, discussion) in tuple(state.conversations.cache.items()):
            collect(preview_results(state, url, discussion))
        collect(tuple(state.recent_discoveries.values()))
        records.sort(key=lambda item: item["captured"], reverse=True)
        body = await asyncio.to_thread(report_pdf, records, start, end, state.practice)
    return web.Response(
        body=body,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="EchoScope-alertas-{start}-{end}.pdf"'
        },
    )


async def asset(request):
    name, mime = ASSETS[request.path]
    body = files("echoscope").joinpath("web_assets", name).read_bytes()
    return web.Response(
        body=body, content_type=mime, charset=None if mime == "image/png" else "utf-8"
    )


def create_app(path, *, practice=False, auto_start=True):
    state = Workspace(path, practice, auto_start)
    app = web.Application(middlewares=[boundary], client_max_size=64 * 1024)
    app[KEY] = state
    app.cleanup_ctx.append(state.lifecycle)
    for route in ASSETS:
        app.router.add_get(route, asset)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/board", board)
    app.router.add_post("/api/{name}", action)
    return app


async def serve(path, *, practice, port, browser):
    app = create_app(path, practice=practice)
    state = app[KEY]
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=5)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        state.authority = f"127.0.0.1:{runner.addresses[0][1]}"
        url = f"http://{state.authority}/"
        if sys.stdout:
            print(f"EchoScope Radar · {url}", flush=True)
        if browser:
            await asyncio.to_thread(webbrowser.open, url)
        while not state.closed.is_set():
            try:
                await asyncio.wait_for(state.closed.wait(), timeout=5)
            except TimeoutError:
                if browser and monotonic() - state.last_seen > 180:
                    break
    finally:
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description="EchoScope Radar · estación web local")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    port = args.port if args.port is not None else (8766 if args.demo else 8765)
    path = args.db or user_data_path("EchoScopeRadar", appauthor=False) / (
        "practica.sqlite" if args.demo else "administracion.sqlite"
    )
    try:
        asyncio.run(serve(path, practice=args.demo, port=port, browser=not args.no_browser))
    except KeyboardInterrupt:
        pass
    except (ValueError, OSError, StorageUnavailable) as exc:
        if sys.stderr:
            print(f"EchoScope Radar · {exc}", file=sys.stderr)
        elif sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, str(exc), "EchoScope Radar", 0x10)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
