from dataclasses import replace

from echoscope.application.config import Source
from echoscope.application.conversations import Conversations
from echoscope.application.ports import Forbidden, Request
from echoscope.connectors.html_discussion import parse_discussion
from echoscope.connectors.press_feed import PressFeed
from echoscope.domain.models import Batch, Kind, Message, utcnow
from echoscope.domain.rules import Rule, evaluate

HTML = """<article class="post"><h1>Defensa presenta informe</h1>
<div class="entry-content">El Ejército presentó el informe completo. <script>contenido oculto</script></div></article>
<section id="comments"><div class="post" id="comment-1"><span class="author">Ana</span>
<time datetime="2026-11-13T12:00:00Z"></time><div class="post-message">No comparto la demora del Ejército.</div>
<div class="post" id="comment-2"><span class="author">Luis</span><div class="comment-content">Gracias por informar.</div></div></div>
<div class="post" id="comment-3"><span class="author">Sol</span><div class="comment-text">Defensa debe explicarlo.</div></div></section>"""


def test_html_posts_are_comments_only_within_discussion_and_preserve_replies():
    rows, partial = parse_discussion(HTML, "https://example.org/nota", "Defensa presenta informe")
    assert not partial
    article, *comments = rows
    assert article.kind == Kind.NEWS_ARTICLE and "informe completo" in article.text
    assert "contenido oculto" not in article.text
    assert len(comments) == 3
    assert comments[0].author == "Ana" and comments[1].parent_id == "comment-1"
    assert "Gracias" not in comments[0].text
    rules = (Rule("e", "Ejército"), Rule("d", "Defensa"))
    assert [bool(evaluate(row.text, rules)) for row in comments] == [True, False, True]
    assert all(row.resource_title == article.title for row in comments)


async def test_user_story_select_news_then_read_article_and_evaluate_reader_comments(monkeypatch):
    article = "https://example.org/nota"

    async def feed(self, request):
        yield Batch(
            (
                Message(
                    Kind.NEWS_ARTICLE,
                    "rss:site",
                    "one",
                    "feed",
                    "Defensa presenta informe",
                    url=article,
                    title="Defensa presenta informe",
                    published_at=utcnow(),
                ),
            ),
            "cursor",
        )

    async def no_feeds(url):
        return []

    async def html(url, **kwargs):
        assert url == article
        return HTML

    monkeypatch.setattr("echoscope.connectors.press_feed.Feed.poll", feed)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_discussion_feeds", no_feeds)
    monkeypatch.setattr("echoscope.connectors.discussion.public_get", html)
    rules = (Rule("d", "Defensa"), Rule("e", "Ejército"))
    request = Request(
        Source(id="site", type="press_feed", params={"url": "https://example.org/feed"}),
        None,
        15,
        rules,
    )
    batches = [batch async for batch in PressFeed().poll(request)]
    messages = [row for batch in batches for row in batch.messages]
    comments = [row for row in messages if row.kind == Kind.PRESS_COMMENT]
    assert len(comments) == 3 and sum(bool(evaluate(row.text, rules)) for row in comments) == 2
    assert any(row.origin.startswith("html:article") for row in messages)
    # A third-party article with an unrelated title never triggers comment acquisition.
    unrelated = replace(request, rules=(Rule("x", "Término ausente"),))
    assert not any(
        row.kind == Kind.PRESS_COMMENT
        for batch in [batch async for batch in PressFeed().poll(unrelated)]
        for row in batch.messages
    )


def test_author_is_not_evaluated_as_comment_and_ids_are_scoped_to_article():
    html = '<div id="comments"><div class="comment" id="comment-1"><div class="comment-body"><span class="author">Defensa</span><time datetime="2026-11-13">Hoy</time><p>Gracias por informar.</p></div></div></div>'
    first, _ = parse_discussion(html, "https://example.org/nota-a")
    second, _ = parse_discussion(html, "https://example.org/nota-b")
    assert first[0].text == "Gracias por informar."
    assert not evaluate(first[0].text, (Rule("d", "Defensa"),))
    assert first[0].origin != second[0].origin


async def test_public_html_comments_remain_available_when_wordpress_rejects_api(monkeypatch):
    article = "https://example.org/nota"
    body = (
        '<link rel="https://api.w.org/" href="https://example.org/wp-json/"><link rel="shortlink" href="https://example.org/?p=1">'
        + HTML
    )

    async def feed(self, request):
        yield Batch(
            (
                Message(
                    Kind.NEWS_ARTICLE,
                    "rss:site",
                    "one",
                    "feed",
                    "Defensa",
                    url=article,
                    title="Defensa",
                ),
            ),
            "one",
        )

    async def no_feeds(url):
        return []

    async def get(url, **kwargs):
        if kwargs.get("json_body", True):
            raise Forbidden()
        return body

    monkeypatch.setattr("echoscope.connectors.press_feed.Feed.poll", feed)
    monkeypatch.setattr("echoscope.connectors.press_feed.discover_discussion_feeds", no_feeds)
    monkeypatch.setattr("echoscope.connectors.discussion.public_get", get)
    request = Request(
        Source(id="site", type="press_feed", params={"url": "https://example.org/feed"}),
        None,
        15,
        (Rule("d", "Defensa"),),
    )
    batches = [batch async for batch in PressFeed().poll(request)]
    assert sum(item.kind == Kind.PRESS_COMMENT for batch in batches for item in batch.messages) == 3
    assert any(batch.coverage_gap for batch in batches)
    monkeypatch.setattr("echoscope.application.conversations.discover_discussion_feeds", no_feeds)
    preview = await Conversations().read("article", article)
    assert (
        preview.partial and sum(item.kind == Kind.PRESS_COMMENT for item in preview.messages) == 3
    )
    truncated, partial = parse_discussion(
        '<div id="comments"><div class="post"><div class="content">'
        + "a" * 65537
        + "</div></div></div>",
        article,
    )
    assert partial and len(truncated[0].text) == 65536
