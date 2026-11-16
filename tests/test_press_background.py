import asyncio
import json
import logging

import pytest
from aiohttp import ClientSession

from echoscope.application.administration import _example, expand_press_coverage
from echoscope.application.ports import Forbidden, Request
from echoscope.bootstrap import registry
from echoscope.connectors.discussion import discover_mechanisms, read_mechanism
from echoscope.connectors.press_feed import PressFeed
from echoscope.connectors.press_page import listing_articles
from echoscope.domain.models import Batch, Kind, Message
from echoscope.domain.rules import Rule, evaluate
from echoscope.presentation.lifecycle import configure_logging


async def test_montevideo_public_comments_pagination_and_article_identity(monkeypatch):
    async def get(url, **kwargs):
        return "MVD.CMS.Comentarios.init({UcId: 42, version: 2});"

    async def post(url, data):
        assert url == "https://www.montevideo.com.uy/ancomgetpag.aspx"
        assert data == {"uc": "42", "pag": "2", "order": "F"}
        return {
            "cantPag": 3,
            "coms": [
                {
                    "id": 7,
                    "txt": "Excelente acci&#243;n de Defensa",
                    "nick": "Lector",
                    "date": "13/11/2026 12:30:00",
                    "usr": 99,
                },
            ],
        }

    monkeypatch.setattr("echoscope.connectors.discussion.public_get", get)
    monkeypatch.setattr("echoscope.connectors.discussion.public_read_post", post)
    article = "https://www.montevideo.com.uy/auc.aspx?42"
    (mechanism,) = await discover_mechanisms(article)
    page = await read_mechanism(mechanism, article=article, title="Otra noticia", cursor="2")
    (message,) = page.messages
    assert page.partial and page.next_page == "3"
    assert message.origin == "montevideo:42" and message.resource_id == article
    assert message.resource_title == "Otra noticia" and message.author_id == "99"
    assert message.text == "Excelente acción de Defensa"
    assert message.published_at.hour == 12
    assert evaluate(message.text, (Rule("d", "Defensa"),))
    with pytest.raises(Forbidden):
        await read_mechanism(mechanism, article="https://unrelated.example/noticia")


async def test_all_press_follows_comment_when_title_has_no_whitelist_term(monkeypatch):
    source = (
        _example("defensa-uruguay.yaml")
        .sources[0]
        .model_copy(
            update={
                "params": {"url": "https://news.example/feed"},
                "tracking": "all",
            }
        )
    )
    article = "https://news.example/otro-tema"

    async def poll(self, request):
        yield Batch(
            (
                Message(
                    Kind.NEWS_ARTICLE,
                    "rss",
                    "1",
                    article,
                    "Otra noticia",
                    title="Otra noticia",
                    url=article,
                ),
            ),
            "feed",
        )

    async def feeds(url):
        return []

    async def mechanisms(url):
        return [{"type": "html", "url": url, "comments": True}]

    async def get(url, **kwargs):
        return '<div id="comment-1"><div class="comment-content">Gracias Defensa</div></div>'

    monkeypatch.setattr("echoscope.connectors.press_feed.Feed.poll", poll)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_discussion_feeds", feeds)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_mechanisms", mechanisms)
    monkeypatch.setattr("echoscope.connectors.discussion.public_get", get)
    request = Request(source, None, 15, (Rule("d", "Defensa"),))
    batches = [batch async for batch in PressFeed().poll(request)]
    comments = [m for b in batches for m in b.messages if m.kind == Kind.PRESS_COMMENT]
    assert len(comments) == 1 and comments[0].resource_id == article
    assert evaluate(comments[0].text, request.rules)
    assert article in json.loads(batches[-1].checkpoint)["targets"]


def test_portada_skips_navigation_foreign_links_and_deduplicates():
    body = """<nav><h2><a href="/long-path-navigation-section">Noticias de navegación</a></h2></nav>
    <h2><a href="/nacionales/una-noticia-importante">Una noticia sobre la economía nacional</a></h2>
    <a href="/nacionales/una-noticia-importante"><h3>Otra referencia a la misma noticia</h3></a>
    <h2><a href="https://external.example/anuncio-muy-largo">Publicidad ajena al medio original</a></h2>"""
    articles = listing_articles(body, "https://news.example/")
    assert len(articles) == 1 and articles[0].kind == Kind.NEWS_ARTICLE
    assert articles[0].url.endswith("/nacionales/una-noticia-importante")


def test_profile_upgrade_preserves_rules_disabled_jobs_and_custom_sources():
    preset = _example("defensa-uruguay.yaml")
    legacy = preset.model_copy(
        update={
            "desktop_profile": 2,
            "sources": [
                s for s in preset.sources if s.type != "press_page" and s.id != "cw33-florida"
            ],
            "jobs": [
                j.model_copy(update={"enabled": False})
                for j in preset.jobs
                if j.source
                not in {"el-pais", "medios-publicos", "radio-montecarlo", "cw33-florida"}
            ],
        }
    )
    result = expand_press_coverage(legacy)
    assert result.desktop_profile == 3 and len(result.sources) == 16
    assert result.rule_sets == legacy.rule_sets
    assert all(not job.enabled for job in result.jobs[:12])
    assert expand_press_coverage(result) is result


async def test_browser_idle_keeps_engine_alive_until_explicit_shutdown(tmp_path, monkeypatch):
    from echoscope.presentation import web as module

    create = module.create_app
    captured = []

    def create_app(*args, **kwargs):
        app = create(*args, **kwargs)
        app[module.KEY].last_seen = float("-inf")
        captured.append(app)
        return app

    monkeypatch.setattr(module, "create_app", create_app)
    monkeypatch.setattr(module.webbrowser, "open", lambda *args: True)
    worker = asyncio.create_task(
        module.serve(tmp_path / "idle.sqlite", practice=True, port=0, browser=True)
    )
    try:
        async with asyncio.timeout(8):
            while not captured or not captured[0][module.KEY].authority:
                await asyncio.sleep(0.02)
        state = captured[0][module.KEY]
        # Force a scheduling opportunity after the browser heartbeat is already expired.
        await asyncio.sleep(5.3)
        assert not worker.done() and state.service.worker is not None
        async with ClientSession() as client:
            url = "http://" + state.authority
            bootstrap = await (await client.get(url + "/api/bootstrap")).json()
            response = await client.post(
                url + "/api/shutdown",
                json={},
                headers={
                    "Origin": url,
                    "X-EchoScope-Token": bootstrap["token"],
                },
            )
            assert response.status == 200
        await asyncio.wait_for(worker, 5)
    finally:
        if captured:
            captured[0][module.KEY].closed.set()
        await asyncio.wait_for(worker, 5)


def test_file_log_is_created_without_copying_message_content(tmp_path):
    target = configure_logging(tmp_path)
    logger = logging.getLogger("echoscope")
    try:
        logger.info("monitor_started")
        assert "monitor_started" in target.read_text(encoding="utf-8")
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "baseFilename", None) == str(target.resolve()):
                logger.removeHandler(handler)
                handler.close()


def test_live_chats_are_persistent():
    assert registry()["youtube_live"].persistent
    assert registry()["youtube_channel_live"].persistent
