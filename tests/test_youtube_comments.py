from contextlib import aclosing

import pytest
from aiohttp import web

from echoscope.application.config import Credential, Source
from echoscope.application.ports import AuthRequired, Request
from echoscope.connectors.comment_feed import CommentFeedLinks
from echoscope.connectors.youtube_comments import (
    CommentsUnavailable,
    YouTubeComments,
    find_videos,
    video_id,
)
from echoscope.domain.models import Kind


def test_user_can_paste_video_link():
    assert video_id("https://www.youtube.com/watch?v=01234567890&feature=share") == "01234567890"
    assert video_id("https://youtu.be/01234567890") == "01234567890"
    assert video_id("https://www.youtube.com/live/01234567890") == "01234567890"
    with pytest.raises(ValueError, match="YouTube"):
        video_id("https://www.youtube.com.example.com/watch?v=01234567890")


def test_discovery_requires_explicit_comment_feed():
    parser = CommentFeedLinks("https://example.com/articulo/")
    parser.feed("""<link rel="alternate" type="application/rss+xml" title="Noticias" href="/feed/">
    <link rel="alternate" type="application/rss+xml" title="Comentarios de esta nota" href="feed/">
    <link rel="alternate" type="application/rss+xml" title="Comments" href="http://127.0.0.1/feed/">""")
    assert parser.links == ["https://example.com/articulo/feed/"]


async def test_youtube_search_threads_and_replies_via_http(monkeypatch):
    calls = []

    def comment(identifier, text):
        return {
            "id": identifier,
            "snippet": {
                "textOriginal": text,
                "authorDisplayName": "Visitante",
                "publishedAt": "2026-01-01T00:00:00Z",
            },
        }

    async def api(request):
        assert request.headers["x-goog-api-key"] == "test-key"
        endpoint = request.match_info["endpoint"]
        calls.append(endpoint)
        if endpoint == "search":
            assert request.query["regionCode"] == "UY"
            assert "Defensa" in request.query["q"]
            assert request.query.get("eventType") == (
                "live" if calls.count("search") == 2 else None
            )
            return web.json_response(
                {
                    "items": [
                        {
                            "id": {"videoId": "01234567890"},
                            "snippet": {"title": "Defensa", "channelTitle": "Noticias"},
                        }
                    ]
                }
            )
        if endpoint == "commentThreads" and request.query["videoId"] == "11111111111":
            return web.json_response(
                {"error": {"errors": [{"reason": "commentsDisabled"}]}}, status=403
            )
        if endpoint == "commentThreads":
            assert request.query["textFormat"] == "plainText"
            return web.json_response(
                {
                    "nextPageToken": "more",
                    "items": [
                        {
                            "snippet": {
                                "topLevelComment": comment("parent", "Ejército Nacional"),
                                "totalReplyCount": 2,
                            },
                            "replies": {"comments": [comment("reply-a", "Primera respuesta")]},
                        }
                    ],
                }
            )
        assert request.query["parentId"] == "parent"
        return web.json_response(
            {
                "items": [
                    comment("reply-a", "Primera respuesta"),
                    comment("reply-b", "Segunda respuesta"),
                ]
            }
        )

    server = web.Application()
    server.router.add_get("/{endpoint}", api)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    monkeypatch.setattr(
        "echoscope.connectors.youtube_comments.API", f"http://127.0.0.1:{runner.addresses[0][1]}"
    )
    monkeypatch.setenv("ECHOSCOPE_TEST_API_KEY", "test-key")
    credential = Credential(kind="api_key", env="ECHOSCOPE_TEST_API_KEY")
    source = Source(
        id="video",
        type="youtube_comments",
        params={"video_id": "01234567890", "max_pages": 1},
        credential=credential,
    )
    try:
        videos = await find_videos("Defensa Uruguay", credential)
        assert videos[0].id == "01234567890"
        batches = [batch async for batch in YouTubeComments().poll(Request(source, None, 5))]
        assert [item.external_id for item in batches[0].messages] == [
            "parent",
            "reply-a",
            "reply-b",
        ]
        assert all(item.kind == Kind.COMMENT for item in batches[0].messages)
        assert batches[0].coverage_gap
        assert calls == ["search", "commentThreads", "comments"]
        videos = await find_videos("Defensa Uruguay", credential, live=True)
        assert videos[0].id == "01234567890"
        source.params["video_id"] = "11111111111"
        async with aclosing(YouTubeComments().poll(Request(source, None, 5))) as stream:
            with pytest.raises(CommentsUnavailable):
                await anext(stream)
        monkeypatch.delenv("ECHOSCOPE_TEST_API_KEY")
        with pytest.raises(AuthRequired):
            await find_videos("Defensa Uruguay", credential)
    finally:
        await runner.cleanup()
