import json
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from conftest import demo_config, demo_radar, until
from cryptography.fernet import Fernet

from echoscope.application.config import Credential, Source
from echoscope.application.ports import Request
from echoscope.application.secrets import account_secrets
from echoscope.connectors.discussion import discover_mechanisms, read_mechanism
from echoscope.connectors.policy import publication_selected
from echoscope.connectors.press_feed import PressFeed
from echoscope.connectors.youtube_channel import YouTubeChannel
from echoscope.domain.models import Batch, Kind, Message, utcnow
from echoscope.domain.rules import Rule, evaluate
from echoscope.presentation.accounts import Accounts, set_password
from echoscope.presentation.web import Workspace


async def test_wordpress_discovery_comments_and_reply_pagination(monkeypatch):
    article = "https://example.org/nota"

    async def get(url, **kwargs):
        if not kwargs.get("json_body", True):
            return '<link rel="https://api.w.org/" href="https://example.org/wp-json/"><link rel="shortlink" href="https://example.org/?p=123">'
        assert kwargs["params"]["post"] == "123" and kwargs["params"]["page"] == 1
        return [
            {
                "id": 4,
                "parent": 2,
                "author_name": "Lector",
                "date_gmt": "2026-11-12T12:00:00",
                "content": {"rendered": "<p>Una alerta sobre Defensa</p>"},
            }
        ], {"X-WP-TotalPages": "2"}

    monkeypatch.setattr("echoscope.connectors.discussion.public_get", get)
    mechanisms = await discover_mechanisms(article)
    result = await read_mechanism(mechanisms[0], article=article, title="Nota original")
    assert result.partial and result.next_page == "2"
    item = result.messages[0]
    assert item.parent_id == "2" and item.resource_id == article
    assert evaluate(item.text, (Rule("defensa", "Defensa"),))


async def test_disqus_uses_explicit_key_and_preserves_parent(monkeypatch):
    monkeypatch.setenv("ECHOSCOPE_DISQUS_KEY", "test-only")

    async def get(url, **kwargs):
        if not kwargs.get("json_body", True):
            return '<script src="https://medio.disqus.com/embed.js"></script>'
        assert kwargs["params"]["api_key"] == "test-only"
        assert kwargs["params"]["thread"] == "link:https://example.org/nota"
        return {
            "code": 0,
            "response": [
                {"id": "5", "parent": "3", "raw_message": "Defensa", "author": {"name": "Lector"}}
            ],
            "cursor": {"hasNext": True, "next": "opaque"},
        }, {}

    monkeypatch.setattr("echoscope.connectors.discussion.public_get", get)
    mechanism = (await discover_mechanisms("https://example.org/nota"))[0]
    result = await read_mechanism(mechanism, article="https://example.org/nota")
    assert result.messages[0].parent_id == "3" and result.next_page == "opaque"


def test_title_only_and_owned_policy_with_date_window():
    source = Source(id="test", type="press_feed")
    request = Request(source, None, 15, (Rule("defensa", "Defensa"),))
    assert not publication_selected(request, "Otra noticia", utcnow())
    assert publication_selected(request, "Defensa publica informe", utcnow())
    assert not publication_selected(request, "Defensa", utcnow() - timedelta(days=8))
    assert publication_selected(
        replace(request, source=source.model_copy(update={"tracking": "owned"})),
        "Otra noticia",
        utcnow(),
    )


async def test_press_selects_title_and_never_attaches_foreign_global_feed_comments(monkeypatch):
    article = "https://example.org/defensa"
    other = "https://example.org/otra"
    main = "https://example.org/feed"
    comment_feed = "https://example.org/comments/feed/"

    async def poll(self, request):
        if request.source.params["url"] == main:
            yield Batch(
                (
                    Message(
                        Kind.FEED_ENTRY,
                        "feed",
                        "one",
                        main,
                        "Defensa",
                        title="Defensa",
                        url=article,
                    ),
                    Message(
                        Kind.FEED_ENTRY,
                        "feed",
                        "two",
                        main,
                        "Defensa en el cuerpo",
                        title="Otra noticia",
                        url=other,
                    ),
                ),
                "main-cursor",
            )
        else:
            assert request.source.credential is None
            yield Batch(
                (
                    Message(
                        Kind.PRESS_COMMENT,
                        "feed",
                        "a",
                        comment_feed,
                        "Defensa",
                        url=article + "#comment-1",
                    ),
                    Message(
                        Kind.PRESS_COMMENT,
                        "feed",
                        "b",
                        comment_feed,
                        "Ajeno",
                        url=other + "#comment-2",
                    ),
                ),
                "comments-cursor",
            )

    async def discover(url):
        assert url == article
        return [(comment_feed, Kind.PRESS_COMMENT)]

    async def mechanisms(url):
        return []

    monkeypatch.setattr("echoscope.connectors.press_feed.Feed.poll", poll)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_discussion_feeds", discover)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_mechanisms", mechanisms)
    request = Request(
        Source(id="press", type="press_feed", params={"url": main}),
        None,
        15,
        (Rule("d", "Defensa"),),
    )
    batches = [batch async for batch in PressFeed().poll(request)]
    comments = [
        item for batch in batches for item in batch.messages if item.kind == Kind.PRESS_COMMENT
    ]
    assert len(comments) == 1 and comments[0].resource_id == article
    assert comments[0].resource_title == "Defensa"
    assert list(json.loads(batches[-1].checkpoint)["targets"]) == [article]


async def test_owned_youtube_checks_comments_without_matching_title(monkeypatch):
    async def api(session, endpoint, params, headers):
        if endpoint == "channels":
            return {
                "items": [
                    {
                        "id": "channel",
                        "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}},
                    }
                ]
            }
        return {
            "items": [
                {
                    "snippet": {
                        "title": "Saludos a la audiencia",
                        "resourceId": {"videoId": "01234567890"},
                    }
                }
            ]
        }

    async def comments(self, request):
        yield Batch(
            (
                Message(
                    Kind.COMMENT,
                    "youtube:comment",
                    "one",
                    "01234567890",
                    "Defensa",
                    resource_title=request.source.params["video_title"],
                ),
            ),
            None,
        )

    monkeypatch.setattr("echoscope.connectors.youtube_channel._get", api)
    monkeypatch.setattr("echoscope.connectors.youtube_channel.YouTubeComments.poll", comments)
    monkeypatch.setenv("TEST_YOUTUBE", "test")
    source = Source(
        id="owned",
        type="youtube_channel",
        tracking="owned",
        params={"channel": "@CanalPrueba"},
        credential=Credential(kind="api_key", env="TEST_YOUTUBE"),
    )
    batches = [
        batch
        async for batch in YouTubeChannel().poll(Request(source, None, 15, (Rule("d", "Defensa"),)))
    ]
    comment = next(
        item for batch in batches for item in batch.messages if item.kind == Kind.COMMENT
    )
    assert comment.text == "Defensa" and comment.resource_title == "Saludos a la audiencia"
    assert json.loads(batches[-1].checkpoint)["targets"]


async def test_server_restores_active_account_without_login_and_respects_pause(tmp_path):
    set_password(tmp_path, "alice", "password-for-test-only")
    master = Fernet.generate_key()
    accounts = Accounts(tmp_path, "https://localhost", master, Workspace)
    state = await accounts.workspace("alice")
    scope = account_secrets.set(state.secrets)
    try:
        await state.service.store.configure(demo_config())
        await state.service.set_running(True)
    finally:
        account_secrets.reset(scope)
        await state.service.close()
    restored = Accounts(tmp_path, "https://localhost", master, Workspace)
    async with asynccontextmanager(restored.lifecycle)(None):
        assert restored.workspaces["alice"].service.radar is not None
        await restored.workspaces["alice"].service.set_running(False)
    paused = Accounts(tmp_path, "https://localhost", master, Workspace)
    async with asynccontextmanager(paused.lifecycle)(None):
        assert paused.workspaces == {}


async def test_native_sql_guide_queries_work_without_application_functions(tmp_path):
    path = tmp_path / "guide.sqlite"
    async with demo_radar(path) as (radar, store):
        await until(lambda: bool(radar.last_batch_received))
        content = Path("docs/consulta-base-datos.md").read_text(encoding="utf-8")
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            for block in re.findall(r"```sql\n(.*?)```", content, flags=re.S):
                for statement in block.split(";"):
                    if statement.strip():
                        db.execute(statement).fetchall()
