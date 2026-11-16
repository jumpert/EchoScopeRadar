"""Public news listings for outlets without an announced RSS feed."""

from urllib.parse import urljoin, urlsplit, urlunsplit

from echoscope.domain.models import Batch, Kind, Message

from .discussion import public_get
from .html_discussion import Document, ancestors, descendants, plain
from .press_feed import PressFeed, _site
from .syndication import public_url


def listing_articles(body, url):
    document = Document(body)
    articles = {}
    for heading in document.elements:
        if heading.tag not in {"h1", "h2", "h3"} and not (
            heading.tag == "a" and "bt-title" in heading.classes
        ):
            continue
        if any(parent.tag in {"nav", "footer", "header", "aside"} for parent in ancestors(heading)):
            continue
        anchor = (
            heading
            if heading.tag == "a"
            else next((n for n in descendants(heading) if n.tag == "a"), None)
        )
        if anchor is None:
            anchor = next((n for n in ancestors(heading) if n.tag == "a"), None)
        if anchor is None:
            continue
        title = plain(heading)
        if len(title) < 25:
            continue
        parsed = urlsplit(urljoin(url, anchor.attrs.get("href", "")))
        address = urlunsplit(parsed._replace(fragment=""))
        try:
            public_url(address)
        except ValueError:
            continue
        if _site(address) != _site(url) or len(parsed.path.strip("/")) < 20:
            continue
        articles.setdefault(
            address,
            Message(
                Kind.NEWS_ARTICLE,
                "web:" + _site(url),
                address,
                address,
                title[:300],
                url=address,
                title=title[:300],
            ),
        )
        if len(articles) >= 100:
            break
    return tuple(articles.values())


class PressPage(PressFeed):
    async def publications(self, request):
        url = request.source.params["url"]
        body = await public_get(url, json_body=False)
        items = listing_articles(body, url)
        yield Batch(
            items,
            None,
            len(items) == 100,
            detail=None if items else "PORTADA SIN NOTAS IDENTIFICABLES",
        )
