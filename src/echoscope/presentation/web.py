"""Loopback-only administrative workspace for the local Radar engine."""

import argparse
import asyncio
import hmac
import json
import logging
import os
import re
import secrets
import signal
import ssl
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

import aiohttp
from aiohttp import web
from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from echoscope.application.administration import (
    RSS_TYPES,
    SOURCE_TYPES,
    YOUTUBE_KEY,
    Administration,
    SourceForm,
)
from echoscope.application.config import Credential, StrictModel
from echoscope.application.conversations import Conversations
from echoscope.application.credentials import CredentialVault
from echoscope.application.discovery import BRAVE_KEY, TopicDiscovery, public_result_url
from echoscope.application.ports import AuthRequired, ConnectorError, StorageUnavailable
from echoscope.application.secrets import account_secrets, secrets_for_request
from echoscope.connectors.youtube import youtube_headers
from echoscope.connectors.youtube_comments import VIDEO_ID, video_id, video_titles
from echoscope.domain.identity import alert_key
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
from echoscope.settings import load_environment, runtime_settings

from .accounts import COOKIE, Accounts, set_password
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
    "/login.js": ("login.js", "text/javascript"),
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
    resource_url: str | None = Field(default=None, max_length=2048)
    tracking: Literal["topic", "owned"] = "topic"
    resource_id: str | None = Field(default=None, max_length=256)
    comment_provider: Literal["disqus"] | None = None


class ControlInput(StrictModel):
    enabled: bool


class TextInput(StrictModel):
    value: str = Field(min_length=1, max_length=4096)


class TopicInput(StrictModel):
    lines: list[str] = Field(max_length=100)


class ThemeInput(StrictModel):
    value: Literal["light", "middle-light", "dark", "darkest"]


SOURCE_GROUPS = {
    "youtube": "YouTube",
    "press": "Prensa",
    "social": "Redes sociales",
    "other": "Otros",
}


class SourceGroup(StrictModel):
    id: str = Field(pattern=r"^custom-[a-f0-9-]{36}$")
    name: str = Field(min_length=1, max_length=50)


class SourceLayout(StrictModel):
    categories: list[SourceGroup] = Field(max_length=20)
    groups: dict[str, list[str]] = Field(max_length=24)


class DiscoveryInput(StrictModel):
    value: str = Field(min_length=1, max_length=200)


class ConversationInput(StrictModel):
    kind: Literal["article", "web", "video", "live", "social"]
    url: str = Field(min_length=1, max_length=2048)


class ReportInput(StrictModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    layout: Literal["brief", "complete"] = "brief"


class LoginInput(StrictModel):
    model_config = ConfigDict(str_strip_whitespace=False)
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)


class NewCredential(StrictModel):
    provider: str = Field(max_length=30)
    name: str = Field(min_length=1, max_length=80)
    value: str = Field(min_length=1, max_length=4096)
    provider_label: str | None = Field(default=None, max_length=80)


class ReviewInput(StrictModel):
    state: Literal["open", "verified", "threat", "dismissed"]
    keys: list[str] = Field(min_length=1, max_length=500)


class Workspace:
    def __init__(self, path, practice, auto_start, *, username=None, cipher=None):
        self.service = Administration(path, practice)
        self.username = username
        self.secrets = {} if username else None
        self.vault = CredentialVault(self.service.store, cipher)
        self.credential_guard = asyncio.Lock()
        self.discovery = TopicDiscovery(self.service)
        self.conversations = Conversations()
        self.recent_discoveries = {}
        self.video_titles = {}
        self.video_guard = asyncio.Lock()
        self.report_guard = asyncio.Lock()
        self.practice = practice
        self.auto_start = auto_start
        self.authority = None
        self.token = secrets.token_hex(32)
        self.closed = asyncio.Event()
        self.last_seen = monotonic()
        self.config = None

    async def open(self):
        scope = account_secrets.set(self.secrets)
        try:
            self.config = await self.service.open()
            try:
                await self.vault.load()
                resume = (
                    self.username
                    and await self.service.store.desktop_setting("monitoring_enabled") == "true"
                )
                if self.auto_start or resume:
                    await self.service.set_running(True)
            except BaseException:
                await self.service.close()
                raise
        finally:
            account_secrets.reset(scope)

    async def lifecycle(self, _app):
        await self.open()
        try:
            yield
        finally:
            await self.service.close()


KEY = web.AppKey("workspace", Workspace)
ACCOUNTS = web.AppKey("accounts", Accounts)
LOG = logging.getLogger(__name__)


def error(message, status):
    return web.json_response({"error": message}, status=status)


@web.middleware
async def security_headers(request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    except SQLAlchemyError:
        response = error("El almacenamiento está temporalmente inaccesible.", 503)
    except Exception as exc:
        LOG.error("request_failed", extra={"error_type": type(exc).__name__})
        response = error("No se pudo completar la operación.", 500)
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


@web.middleware
async def boundary(request, handler):
    accounts = request.app.get(ACCOUNTS)
    state = request.app.get(KEY)
    origin = accounts.origin if accounts else f"http://{state.authority}"
    if request.host != urlsplit(origin).netloc or (accounts and not request.secure):
        return error("Dirección local no válida.", 421)
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return error("Solicitud de otro sitio rechazada.", 403)
    if accounts:
        username = accounts.username(request.cookies.get(COOKIE))
        if request.path.startswith("/api/") and request.path != "/api/login":
            if not username:
                return error("Iniciá sesión para continuar.", 401)
            try:
                state = await accounts.workspace(username)
            except (ValueError, StorageUnavailable) as exc:
                return error(str(exc), 503)
        request["username"] = username
    if request.method not in {"GET", "HEAD"}:
        token = request.headers.get("X-EchoScope-Token", "")
        is_login = bool(accounts and request.path == "/api/login")
        if request.headers.get("Origin") != origin or (
            not is_login
            and (
                state is None or not token.isascii() or not hmac.compare_digest(token, state.token)
            )
        ):
            return error("La sesión cambió. Actualizá la página.", 403)
        if request.content_type != "application/json":
            return error("Formato de solicitud no válido.", 415)
    request["workspace"] = state
    scope = account_secrets.set(state.secrets if state else None)
    try:
        response = await handler(request)
    except AuthRequired:
        response = error("Cargá una clave válida en Claves API.", 422)
    except ConnectorError as exc:
        response = error(exc.label, 422)
    except StorageUnavailable:
        response = error("El historial está temporalmente inaccesible.", 503)
    except (ValidationError, json.JSONDecodeError):
        response = error("Revisá los campos del formulario.", 400)
    except ValueError as exc:
        response = error(str(exc), 400)
    finally:
        account_secrets.reset(scope)
    if state and response.status < 400 and request.path.startswith("/api/"):
        state.last_seen = monotonic()
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
    body = message.text[body_start:].strip()
    preview = " ".join(body[:141].split())
    if len(body) > 140:
        cut = preview[:140].rfind(" ")
        preview = preview[: cut if cut > 95 else 140].rstrip() + "…"
    return {
        "title": title,
        "title_fragments": header,
        "fragments": match_context(message.text, matches, body_start),
        "preview": preview,
    }


def resource_link(message):
    if message.origin.startswith("youtube:") and VIDEO_ID.fullmatch(message.resource_id):
        return f"https://www.youtube.com/watch?v={message.resource_id}"
    if message.kind in {
        Kind.PRESS_COMMENT,
        Kind.REVIEW,
        Kind.FORUM_POST,
        Kind.SOCIAL_COMMENT,
        Kind.LIVE_CHAT,
    }:
        return safe_url(message.resource_id) or safe_url(message.url)
    return safe_url(message.url)


def result_data(result, sources, *, report=False):
    message = result.observation.message
    matches = result.observation.matches
    confirmed = [item for item in matches if item.confirmed]
    resource = resource_link(message)
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
        "message_key": [message.origin, message.external_id],
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
        "resource_url": resource,
        "resource_id": message.resource_id if message.origin.startswith("youtube:") else None,
        "resource_key": (resource or (message.origin, message.resource_id or message.external_id)),
        "resource_title": message.resource_title,
        "title": publication_title(message) if report else None,
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
    if source.type == "pending_social":
        return ["social"]
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
        if source.type == "pending_social":
            label = source.params["platform"] + " · acceso pendiente"
        jobs.append(
            {
                "id": job.id,
                "default_group": (
                    "youtube"
                    if source.type.startswith("youtube_")
                    else "social"
                    if source.type in {"bluesky_thread", "pending_social"}
                    else "press"
                    if set(source_categories(source)) & {"news", "press"}
                    else "other"
                ),
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
                "resource_url": source.params.get("resource_url"),
                "enabled": job.enabled,
                "tracking": source.tracking,
                "platform": source.params.get("platform")
                or (
                    "YouTube"
                    if source.type.startswith("youtube")
                    else ("Bluesky" if source.type == "bluesky_thread" else "Sitio o feed")
                ),
                "resource_id": source.params.get("resource_id")
                or source.params.get("channel")
                or source.params.get("video_id")
                or source.params.get("url"),
                "credential_env": source.credential.env if source.credential else None,
                "comment_provider": "disqus" if source.comment_credential else None,
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
    state = request["workspace"]
    return web.json_response(
        {
            **config_data(state.config),
            "token": state.token,
            "practice": state.practice,
            "username": state.username,
            "credentials": state.vault.public(),
            "theme": await state.service.store.desktop_setting("theme") or "dark",
            "source_layout": json.loads(
                await state.service.store.desktop_setting("source_layout")
                or '{"categories":[],"groups":{}}'
            ),
            "source_groups": SOURCE_GROUPS,
            "version": version("echoscope-radar"),
        }
    )


async def board(request):
    state = request["workspace"]
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
    review = request.query.get("review", "all")
    tone = request.query.get("tone", "all")
    if review not in {"all", "open", "verified", "threat", "dismissed"} or tone not in {
        "all",
        "positive",
        "negative",
        "mixed",
        "neutral",
    }:
        raise ValueError("Filtro de alertas desconocido.")
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
        limit=min(max(int(request.query.get("alert_limit", 20)), 1), 500),
        matches_only=alerts_mode == "confirmed",
        review_only=alerts_mode == "review",
    )
    *pages, alerts = await asyncio.gather(
        *panels, filtered_alerts(service, alert_query, review, tone, extra=session_previews(state))
    )
    rendered = {
        view: [result_data(item, sources) for item in rows] for view, rows in zip(views, pages)
    }
    await group_video_titles(
        state,
        [
            row
            for view in ("youtube", "live")
            for row in rendered.get(view, [])
            if row["provider"] == "YouTube"
        ],
    )
    return web.json_response(
        {
            "running": bool(service.radar),
            "key_loaded": bool(secrets_for_request().get(YOUTUBE_KEY)),
            "web_key_loaded": bool(secrets_for_request().get(BRAVE_KEY)),
            "panels": rendered,
            "alerts": [
                {**result_data(item, sources), "review_key": key, "review_state": state}
                for item, key, state in alerts
            ],
            "statuses": [
                {
                    "id": key,
                    "name": snap.source.label or snap.source.id,
                    "source_id": snap.source.id,
                    "enabled": snap.job.enabled,
                    "state": snap.state,
                    "availability": snap.availability,
                    "detail": snap.detail,
                    "gap": snap.coverage_gap,
                    "next": snap.next_at.isoformat() if snap.next_at else None,
                    "last": snap.last_at.isoformat() if snap.last_at else None,
                    "categories": source_categories(snap.source),
                    "uses_session_key": bool(
                        snap.source.credential and snap.source.credential.env == YOUTUBE_KEY
                    ),
                }
                for key, snap in snapshots.items()
            ],
        }
    )


async def group_video_titles(state, rows):
    titles = {
        item["resource_id"]: item["resource_title"] or item["title"]
        for item in rows
        if item["resource_id"] and (item["resource_title"] or item["title"])
    }
    if not state.practice and secrets_for_request().get(YOUTUBE_KEY):
        async with state.video_guard:
            now = monotonic()
            state.video_titles = {
                identifier: value
                for identifier, value in state.video_titles.items()
                if value[0] > now
            }
            missing = list(
                dict.fromkeys(
                    item["resource_id"]
                    for item in rows
                    if item["resource_id"]
                    and VIDEO_ID.fullmatch(item["resource_id"])
                    and item["resource_id"] not in titles
                    and item["resource_id"] not in state.video_titles
                )
            )[:50]
            if missing:
                try:
                    async with aiohttp.ClientSession(
                        trust_env=False, timeout=aiohttp.ClientTimeout(total=4)
                    ) as session:
                        headers = youtube_headers(Credential(kind="api_key", env=YOUTUBE_KEY))
                        found = await video_titles(session, missing, headers)
                except (ConnectorError, TimeoutError):
                    found = {}
                state.video_titles.update(
                    {
                        identifier: (
                            now + (900 if identifier in found else 120),
                            found.get(identifier),
                        )
                        for identifier in missing
                    }
                )
                while len(state.video_titles) > 1000:
                    del state.video_titles[next(iter(state.video_titles))]
    for item in rows:
        identifier = item["resource_id"]
        item["resource_title"] = (
            item["resource_title"]
            or titles.get(identifier)
            or state.video_titles.get(identifier, (0, None))[1]
        )


def session_previews(state):
    return [
        item
        for (_, url), (_, conversation) in tuple(state.conversations.cache.items())
        for item in preview_results(state, url, conversation)
    ]


async def filtered_alerts(service, query, review, tone, *, extra=()):
    rows = await service.store.messages(
        query,
        review_state=None if review == "all" else review,
        tone=None if tone == "all" else tone,
    )
    if radar := service.radar:
        for identifier in tuple(radar.session):
            rows.extend(await radar.messages(replace(query, job_id=identifier, limit=500)))
    rows.extend(
        item
        for item in extra
        if (not query.text or query.text.casefold() in item.observation.message.text.casefold())
        and (not query.matches_only or any(m.confirmed for m in item.observation.matches))
        and (not query.review_only or any(m.method == "review" for m in item.observation.matches))
    )
    keyed = [(item, key) for key, item in {alert_key(item): item for item in rows}.items()]
    states = await service.store.alert_reviews(key for _, key in keyed)
    result = [
        (item, key, states.get(key, "open"))
        for item, key in keyed
        if (review == "all" or states.get(key, "open") == review)
        and (tone == "all" or message_tone(item.observation.message.text) == tone)
    ]
    result.sort(key=lambda entry: entry[0].observation.message.captured_at, reverse=True)
    return result[: query.limit]


async def action(request):
    state = request["workspace"]
    service = state.service
    name = request.match_info["name"]
    data = await request.json()
    if name == "monitor":
        await service.set_running(ControlInput.model_validate(data).enabled)
    elif name == "theme":
        await service.set_theme(ThemeInput.model_validate(data).value)
    elif name == "source-layout":
        layout = SourceLayout.model_validate(data)
        ids = set(SOURCE_GROUPS) | {item.id for item in layout.categories}
        names = [name.casefold() for name in SOURCE_GROUPS.values()]
        names.extend(item.name.casefold() for item in layout.categories)
        ordered = [identifier for group in layout.groups.values() for identifier in group]
        if (
            len(ids) != len(SOURCE_GROUPS) + len(layout.categories)
            or len(set(names)) != len(names)
            or layout.groups.keys() - ids
            or len(ordered) > 100
            or len(set(ordered)) != len(ordered)
        ):
            raise ValueError("Revisá que cada categoría y fuente aparezca una sola vez.")
        current = {job.id for job in state.config.jobs}
        layout.groups = {
            key: [identifier for identifier in group if identifier in current]
            for key, group in layout.groups.items()
        }
        saved = layout.model_dump()
        await service.store.set_desktop_setting("source_layout", json.dumps(saved))
        return web.json_response(saved)
    elif name == "topic":
        state.config = await service.save_topic(TopicInput.model_validate(data).lines)
    elif name == "alert-review":
        fields = ReviewInput.model_validate(data)
        if any(not re.fullmatch(r"[a-f0-9]{64}", key) for key in fields.keys):
            raise ValueError("Revisá las alertas seleccionadas.")
        allowed = await service.store.reviewable_keys(fields.keys)
        allowed.update(
            alert_key(item) for item in session_previews(state) if item.observation.matches
        )
        if service.radar:
            allowed.update(
                alert_key(item)
                for window in service.radar.session.values()
                for item in window.values()
                if item.observation.matches
            )
        if set(fields.keys) - allowed:
            raise ValueError(
                "Alguna alerta ya no está disponible en esta cuenta. Actualizá la vista."
            )
        await service.store.set_alert_reviews(fields.keys, fields.state)
        return web.json_response({"detail": "Estado de alertas actualizado."})
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
            fields.resource_url,
            fields.tracking,
            fields.resource_id,
            fields.comment_provider,
        )
        state.config = await service.save_source(form, fields.id, fields.token)
    elif name == "remove":
        state.config = await service.remove_source(TextInput.model_validate(data).value)
    elif name == "probe":
        result = await service.probe(TextInput.model_validate(data).value)
        return web.json_response({"detail": result.detail or "Consulta completada."})
    elif name == "run-source":
        await service.run_source(TextInput.model_validate(data).value)
        return web.json_response({"detail": "Consulta programada. Revisá el estado en Fuentes."})
    elif name == "discover":
        return web.json_response(
            {"url": await service.detect_comments(TextInput.model_validate(data).value)}
        )
    elif name == "discover-reviews":
        return web.json_response(
            {"url": await service.detect_reviews(TextInput.model_validate(data).value)}
        )
    elif name == "check-youtube":
        await service.check_youtube()
        return web.json_response({"detail": "YouTube aceptó la clave de esta sesión."})
    elif name == "key":
        if state.username:
            raise ValueError("Guardá la clave en Claves API.")
        await service.credentials(TextInput.model_validate(data).value)
    elif name == "web-key":
        if state.username:
            raise ValueError("Guardá la clave en Claves API.")
        key = TextInput.model_validate(data).value
        if not key.isascii() or not key.isprintable() or any(char.isspace() for char in key):
            raise ValueError("Ingresá una clave de API sin espacios.")
        secrets_for_request()[BRAVE_KEY] = key
    elif name in {"credential-add", "credential-use", "credential-remove"}:
        async with state.credential_guard:
            previous = secrets_for_request().get(YOUTUBE_KEY)
            if name == "credential-add":
                fields = NewCredential.model_validate(data)
                await state.vault.add(
                    fields.provider, fields.name, fields.value, fields.provider_label
                )
            else:
                await state.vault.change(
                    TextInput.model_validate(data).value, remove=name == "credential-remove"
                )
            if previous != secrets_for_request().get(YOUTUBE_KEY) and service.radar:
                await service.set_running(False)
                await service.set_running(True)
            return web.json_response(state.vault.public())
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
        if state.username:
            raise web.HTTPForbidden()
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
    resource = url or ""
    if url and origin.startswith("youtube:"):
        try:
            resource = video_id(url)
        except ValueError:
            pass
    message = Message(kind, origin, url or "", resource, body, url=url, title=candidate["title"])
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
        observations = {}

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
                if since <= message.captured_at <= until and any(
                    m.confirmed for m in item.observation.matches
                ):
                    observations.setdefault(key, {})[alert_key(item)] = item
                    if len(observations) > 5000:
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
        states = await state.service.store.alert_reviews(
            key for entries in observations.values() for key in entries
        )
        priority = {"threat": 4, "verified": 3, "dismissed": 2, "open": 1}
        records = []
        for entries in observations.values():
            key = max(
                entries,
                key=lambda key: (
                    priority[states.get(key, "open")],
                    entries[key].job_id != "preview",
                    bool(entries[key].observation.message.resource_title),
                    key,
                ),
            )
            records.append(
                {
                    **result_data(entries[key], sources, report=True),
                    "review_state": states.get(key, "open"),
                }
            )
        youtube = [item for item in records if item["provider"] == "YouTube"]
        if youtube:
            await group_video_titles(state, youtube)
        records.sort(key=lambda item: item["captured"], reverse=True)
        body = await asyncio.to_thread(
            report_pdf, records, start, end, state.practice, layout=fields.layout
        )
    return web.Response(
        body=body,
        content_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="EchoScope-alertas-{start}-{end}.pdf"'
        },
    )


async def asset(request):
    name, mime = ASSETS[request.path]
    if request.path == "/" and request.app.get(ACCOUNTS) and not request["username"]:
        name = "login.html"
    body = files("echoscope").joinpath("web_assets", name).read_bytes()
    return web.Response(
        body=body, content_type=mime, charset=None if mime == "image/png" else "utf-8"
    )


async def login(request):
    accounts = request.app.get(ACCOUNTS)
    if not accounts:
        return error("El inicio de sesión requiere el modo servidor.", 404)
    data = LoginInput.model_validate(await request.json())
    token = await accounts.authenticate(data.username, data.password, request.remote or "")
    if not token:
        return error(
            "Acceso rechazado. Revisá los datos o esperá un minuto para volver a intentar.", 401
        )
    accounts.sessions.pop(request.cookies.get(COOKIE), None)
    response = web.json_response({"detail": "Sesión iniciada."})
    response.set_cookie(
        COOKIE, token, path="/", secure=True, httponly=True, samesite="Strict", max_age=28800
    )
    return response


async def logout(request):
    accounts = request.app.get(ACCOUNTS)
    if not accounts:
        return error("El cierre de sesión requiere el modo servidor.", 404)
    accounts.sessions.pop(request.cookies.get(COOKIE), None)
    response = web.json_response({"detail": "Sesión cerrada."})
    response.set_cookie(
        COOKIE, "", path="/", secure=True, httponly=True, samesite="Strict", max_age=0
    )
    return response


def create_app(path, *, practice=False, auto_start=True, accounts=None):
    app = web.Application(
        middlewares=[security_headers, boundary],
        client_max_size=runtime_settings().request_max_bytes,
    )
    if accounts:
        app[ACCOUNTS] = accounts
        app.cleanup_ctx.append(accounts.lifecycle)
    else:
        state = Workspace(path, practice, auto_start)
        app[KEY] = state
        app.cleanup_ctx.append(state.lifecycle)
    for route in ASSETS:
        app.router.add_get(route, asset)
    app.router.add_get("/api/bootstrap", bootstrap)
    app.router.add_get("/api/board", board)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/logout", logout)
    app.router.add_post("/api/{name}", action)
    return app


async def serve(path, *, practice, port, browser, bind="127.0.0.1"):
    app = create_app(path, practice=practice)
    state = app[KEY]
    settings = runtime_settings()
    runner = web.AppRunner(app, access_log=None, shutdown_timeout=settings.shutdown_timeout_s)
    await runner.setup()
    previous = signal.getsignal(signal.SIGTERM)
    loop = asyncio.get_running_loop()
    signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(state.closed.set))
    try:
        site = web.TCPSite(runner, bind, port)
        await site.start()
        host = f"[{bind}]" if ":" in bind else bind
        state.authority = f"{host}:{runner.addresses[0][1]}"
        url = f"http://{state.authority}/"
        if sys.stdout:
            print(f"EchoScope Radar · {url}", flush=True)
        if browser:
            await asyncio.to_thread(webbrowser.open, url)
        while not state.closed.is_set():
            try:
                await asyncio.wait_for(state.closed.wait(), timeout=5)
            except TimeoutError:
                if browser and monotonic() - state.last_seen > settings.local_idle_timeout_s:
                    break
    finally:
        signal.signal(signal.SIGTERM, previous)
        await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description="EchoScope Radar · estación web local")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--database-url")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--server-dir", type=Path, help="Carpeta privada del servidor multiusuario")
    parser.add_argument(
        "--set-password", metavar="USUARIO", help="Crea o actualiza una cuenta del servidor"
    )
    parser.add_argument("--origin", help="Dirección HTTPS exacta del servidor")
    parser.add_argument("--bind")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    args = parser.parse_args()
    try:
        settings = load_environment(args.env_file)
        port = (
            args.port
            if args.port is not None
            else (settings.demo_port if args.demo else settings.port)
        )
        if not 1 <= port <= 65535:
            raise ValueError("El puerto debe estar entre 1 y 65535.")
        if args.db and args.database_url:
            raise ValueError("Elegí --db o --database-url.")
        args.bind = args.bind or settings.bind
        args.server_dir = args.server_dir or settings.server_dir
        args.origin = args.origin or settings.origin
        args.tls_cert = args.tls_cert or settings.tls_cert
        args.tls_key = args.tls_key or settings.tls_key
        path = (
            args.db
            or args.database_url
            or (
                settings.data_dir / "practica.sqlite"
                if args.demo
                else settings.database_target("administracion.sqlite")
            )
        )
        if args.set_password:
            from getpass import getpass

            if not args.server_dir or not sys.stdin or not sys.stdin.isatty():
                raise ValueError(
                    "Usá --server-dir y una terminal interactiva para administrar usuarios."
                )
            password = getpass("Nueva contraseña: ")
            if password != getpass("Repetí la contraseña: "):
                raise ValueError("Las contraseñas no coinciden.")
            set_password(args.server_dir, args.set_password, password)
            print("Cuenta guardada. Reiniciá el servidor para aplicar el cambio.")
            return
        if args.server_dir:
            url = urlsplit(args.origin or "")
            if (
                args.demo
                or args.db
                or args.database_url
                or url.scheme != "https"
                or not url.hostname
                or url.username
                or url.path
                or url.query
                or url.fragment
                or not args.tls_cert
                or not args.tls_key
            ):
                raise ValueError(
                    "El modo servidor requiere --origin HTTPS sin barra final, --tls-cert y --tls-key."
                )
            key = os.environ.get("ECHOSCOPE_MASTER_KEY")
            if not key:
                raise ValueError(
                    "Configurá ECHOSCOPE_MASTER_KEY para cifrar las claves API del servidor."
                )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.tls_cert, args.tls_key)
            accounts = Accounts(args.server_dir.resolve(), args.origin, key, Workspace)
            web.run_app(
                create_app(None, accounts=accounts),
                host=args.bind,
                port=port,
                ssl_context=context,
                access_log=None,
            )
            return
        if args.bind not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("Para acceso por red usá el modo servidor HTTPS con cuentas.")
        asyncio.run(
            serve(path, practice=args.demo, port=port, browser=not args.no_browser, bind=args.bind)
        )
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
