from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .discussion import public_get
from .syndication import public_url


class CommentFeedLinks(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.links = []
        self.reviews = []

    def handle_starttag(self, tag, attributes):
        if tag != "link":
            return
        attrs = dict(attributes)
        if "alternate" not in (attrs.get("rel") or "").casefold().split():
            return
        if attrs.get("type") not in {"application/rss+xml", "application/atom+xml"}:
            return
        title = (attrs.get("title") or "").casefold()
        href = attrs.get("href") or ""
        if not href:
            return
        try:
            url = public_url(urljoin(self.page, href))
        except ValueError:
            return
        path = urlsplit(url).path.casefold().rstrip("/")
        if "comment" in title or "comentario" in title or path.endswith("/comments/feed"):
            if url not in self.links:
                self.links.append(url)
        elif "review" in title or "reseña" in title or path.endswith("/reviews/feed"):
            if url not in self.reviews:
                self.reviews.append(url)


async def discover_discussion_feeds(page):
    parser = CommentFeedLinks(public_url(page))
    body = await public_get(page, json_body=False)
    parser.feed(body[:256 * 1024].split("</head", 1)[0])
    return [(url, "PRESS_COMMENT") for url in parser.links] + [
        (url, "REVIEW") for url in parser.reviews
    ]


async def discover_comment_feed(page):
    return next(
        (url for url, kind in await discover_discussion_feeds(page) if kind == "PRESS_COMMENT"),
        None,
    )
