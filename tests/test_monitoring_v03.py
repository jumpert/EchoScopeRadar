from dataclasses import replace

import pytest
from conftest import demo_config

from echoscope.application.administration import upgrade_desktop_profile
from echoscope.application.config import Credential, RuleSpec, Source
from echoscope.application.ports import Request, SourceEnded, SourceWaiting
from echoscope.connectors.press_feed import PressFeed
from echoscope.connectors.youtube_channel import YouTubeChannel, YouTubeChannelLive
from echoscope.domain.models import Batch, HistoryQuery, Kind, Message, Observation, State, utcnow
from echoscope.domain.rules import Rule, evaluate
from echoscope.storage.sqlite import Store


def test_variants_preserve_original_spans_and_separate_approvals():
    text = "soldad0 y d e f e n s a. ejersito xejersitox d\u200befensa"
    rules = tuple(
        Rule(term, term, detect_variants=True) for term in ("soldado", "defensa", "ejército")
    )
    found = evaluate(text, rules)
    assert [(item.term, item.method) for item in found] == [
        ("soldad0", "disguised"),
        ("d e f e n s a", "disguised"),
        ("ejersito", "review"),
        ("d\u200befensa", "disguised"),
    ]
    assert all(text[item.start : item.end] == item.term for item in found)
    alias = replace(rules[-1], aliases=("ejersito",))
    assert evaluate("ejersito", (alias,))[0].method == "approved"
    assert not evaluate("sin soldad0", (replace(rules[0], exclusions=("sin soldad0",)),))


async def test_review_is_persisted_without_triggering_an_alert(tmp_path):
    store = Store(tmp_path / "review.sqlite")
    config = demo_config()
    rule = RuleSpec(id="topic", phrase="ejército", detect_variants=True)
    config.rule_sets["avisos"] = [rule]
    async with store.opened(write=True):
        await store.configure(config)
        snapshot = (await store.snapshots())["comentarios"]
        snapshot = replace(snapshot, state=State.RUNNING, last_at=utcnow())
        execution = await store.start(snapshot)
        content = ("ejersito", "ejercit0")
        observations = tuple(
            Observation(
                Message(Kind.FORUM_POST, "fixture", str(i), "forum", value),
                evaluate(value, (rule.compile(),)),
            )
            for i, value in enumerate(content)
        )
        await store.apply(snapshot, execution, observations, True)
        reviewed = await store.messages(HistoryQuery(category="forum", review_only=True))
        confirmed = await store.messages(HistoryQuery(category="forum", matches_only=True))
        assert reviewed[0].observation.matches[0].canonical == "ejército"
        assert reviewed[0].observation.message.text == "ejersito"
        assert confirmed[0].observation.message.text == "ejercit0"
        assert sum(event.kind == "AlertRaised" for event in await store.events()) == 1


def test_upgrade_preserves_edits_and_is_idempotent():
    from echoscope.application.administration import _example

    preset = _example("defensa-uruguay.yaml")
    legacy = preset.model_copy(
        update={
            "desktop_profile": None,
            "sources": [
                item.model_copy(update={"type": "syndication"}) for item in preset.sources[:3]
            ],
            "jobs": preset.jobs[:3],
        }
    )
    result = upgrade_desktop_profile(legacy)
    assert len(result.sources) == 7
    assert "el-observador" not in {item.id for item in result.sources}
    assert upgrade_desktop_profile(result) is result


async def test_press_only_discovers_on_topic_and_tracks_comments_after_304(monkeypatch):
    article = "https://example.com/nota"
    feed = "https://example.com/noticias.xml"
    comments = "https://example.com/comentarios.xml"
    seen = []

    async def fetch(self, request):
        endpoint = request.source.params["url"]
        seen.append((endpoint, request.checkpoint))
        if endpoint == feed:
            yield Batch(
                ()
                if request.checkpoint
                else (
                    Message(
                        Kind.NEWS_ARTICLE, "rss:example.com", "1", feed, "Ejército", url=article
                    ),
                    Message(
                        Kind.NEWS_ARTICLE,
                        "rss:example.com",
                        "2",
                        feed,
                        "Otro tema",
                        url=article + "-otro",
                    ),
                ),
                "main-v1",
            )
        else:
            assert request.source.credential is None
            yield Batch(
                (Message(Kind.PRESS_COMMENT, "rss:example.com", "c", comments, "Comentario"),),
                "child-v1",
            )

    async def discover(link):
        assert link == article
        return comments

    monkeypatch.setattr("echoscope.connectors.press_feed.Feed.poll", fetch)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_comment_feed", discover)
    source = Source(id="press", type="press_feed", params={"url": feed, "kind": "NEWS_ARTICLE"})
    request = Request(source, None, 15, (Rule("army", "Ejército"),))
    first = [batch async for batch in PressFeed().poll(request)]
    second = [
        batch async for batch in PressFeed().poll(replace(request, checkpoint=first[-1].checkpoint))
    ]
    assert [item.url for batch in second for item in batch.messages] == [article]
    assert (comments, "child-v1") in seen


async def test_channel_discovery_only_fetches_confirmed_topic_comments(monkeypatch):
    calls = []
    live = False

    async def api(session, endpoint, params, headers):
        calls.append(endpoint)
        if endpoint == "channels":
            assert params["forHandle"] == "@CanalPrueba"
            return {
                "items": [
                    {
                        "id": "UCeeEsGE06kae6DF-yOGT9Tw",
                        "contentDetails": {"relatedPlaylists": {"uploads": "uploads"}},
                    }
                ]
            }
        if endpoint == "playlistItems":
            return {
                "items": [
                    {"snippet": {"title": title, "resourceId": {"videoId": identifier}}}
                    for title, identifier in [
                        ("Ejército", "01234567890"),
                        ("ejersito", "11111111111"),
                        ("Otro", "22222222222"),
                    ]
                ]
            }
        assert endpoint == "search" and params["eventType"] == "live"
        if live:
            return {
                "items": [
                    {"id": {"videoId": "01234567890"}, "snippet": {"title": "Ejército en directo"}}
                ]
            }
        return {"items": []}

    async def comments(self, request):
        assert request.source.params["video_id"] == "01234567890"
        yield Batch((Message(Kind.COMMENT, "youtube:comment", "1", "video", "Público"),), None)

    monkeypatch.setattr("echoscope.connectors.youtube_channel._get", api)
    monkeypatch.setattr("echoscope.connectors.youtube_channel.YouTubeComments.poll", comments)
    monkeypatch.setenv("TEST_CHANNEL_KEY", "test-only")
    source = Source(
        id="channel",
        type="youtube_channel",
        params={"channel": "@CanalPrueba"},
        credential=Credential(kind="api_key", env="TEST_CHANNEL_KEY"),
    )
    request = Request(source, None, 15, (Rule("army", "Ejército", detect_variants=True),))
    batches = [batch async for batch in YouTubeChannel().poll(request)]
    assert [item.text for batch in batches for item in batch.messages] == [
        "Ejército",
        "ejersito",
        "Público",
    ]
    with pytest.raises(SourceWaiting):
        await anext(YouTubeChannelLive().stream(request))
    assert calls == ["channels", "playlistItems", "channels", "search"]

    async def chat(self, request):
        assert request.source.params["video_id"] == "01234567890"
        yield Batch(
            (Message(Kind.LIVE_CHAT, "youtube:live", "1", "video", "Comentario en vivo"),), "resume"
        )
        raise SourceEnded()

    live = True
    monkeypatch.setattr("echoscope.connectors.youtube_channel.YouTubeLive.stream", chat)
    stream = YouTubeChannelLive().stream(request)
    assert (await anext(stream)).messages[0].kind == Kind.YOUTUBE_LIVE
    assert (await anext(stream)).messages[0].kind == Kind.LIVE_CHAT
    with pytest.raises(SourceWaiting):
        await anext(stream)
