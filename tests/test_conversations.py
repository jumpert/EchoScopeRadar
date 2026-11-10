from echoscope.application.config import Source
from echoscope.application.conversations import Conversations
from echoscope.application.ports import Request
from echoscope.connectors.bluesky import BlueskyThread
from echoscope.domain.models import Batch, Kind, Message
from echoscope.presentation.web import resource_link


async def test_site_reads_announced_comments_and_reviews(monkeypatch):
    article = "https://noticias.example/nota"

    async def discover(url):
        assert url == article
        return [
            ("https://noticias.example/comments/feed", "PRESS_COMMENT"),
            ("https://noticias.example/reviews/feed", "REVIEW"),
        ]

    async def feed(_connector, request):
        params = request.source.params
        assert request.source.credential is None
        yield Batch(
            (
                Message(
                    Kind(params["kind"]),
                    "rss:example",
                    params["kind"],
                    params["url"],
                    "Mensaje",
                    url=f"{article}#mensaje",
                ),
            ),
            None,
        )

    monkeypatch.setattr("echoscope.application.conversations.discover_discussion_feeds", discover)
    monkeypatch.setattr("echoscope.application.conversations.Feed.poll", feed)
    result = await Conversations().read("article", article)
    assert [item.kind for item in result.messages] == [Kind.PRESS_COMMENT, Kind.REVIEW]
    assert all(resource_link(item) == article for item in result.messages)
    assert not result.partial


async def test_bluesky_returns_reply_permalink_and_indicates_missing_replies(monkeypatch):
    async def get(_session, endpoint, params):
        assert endpoint == "app.bsky.feed.getPostThread"
        assert params["uri"] == "at://did:plc:root/app.bsky.feed.post/post"
        return {
            "thread": {
                "post": {"replyCount": 2},
                "replies": [
                    {
                        "post": {
                            "uri": "at://did:plc:author/app.bsky.feed.post/reply",
                            "record": {"text": "Defensa"},
                            "author": {"handle": "author.bsky.social"},
                        }
                    }
                ],
            }
        }

    monkeypatch.setattr("echoscope.connectors.bluesky._get", get)
    url = "https://bsky.app/profile/did:plc:root/post/post"
    source = Source(id="social", type="bluesky_thread", params={"url": url})
    batches = [batch async for batch in BlueskyThread().poll(Request(source, None, 5))]
    assert batches[0].coverage_gap
    message = batches[0].messages[0]
    assert message.kind == Kind.SOCIAL_COMMENT
    assert message.url == "https://bsky.app/profile/did:plc:author/post/reply"
    assert resource_link(message) == url
