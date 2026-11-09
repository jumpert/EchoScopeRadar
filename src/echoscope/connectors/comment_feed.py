from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import aiohttp

from echoscope.application.ports import ConnectorError, Forbidden, Transient

from .syndication import PublicResolver, public_url


class CommentFeedLinks(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.page = page
        self.links = []

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


async def discover_comment_feed(page):
    parser = CommentFeedLinks(public_url(page))
    try:
        async with (
            aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False),
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=12),
            ) as session,
            session.get(
                page,
                allow_redirects=False,
                headers={"Accept": "text/html", "User-Agent": "EchoScopeRadar/0.2"},
            ) as response,
        ):
            if response.status in {401, 403}:
                raise Forbidden()
            if response.status >= 500:
                raise Transient()
            if response.status != 200 or response.content_type not in {
                "text/html",
                "application/xhtml+xml",
            }:
                raise ConnectorError()
            header = bytearray()
            async for chunk in response.content.iter_chunked(8192):
                header.extend(chunk)
                if b"</head" in header.lower() or len(header) >= 256 * 1024:
                    break
    except (aiohttp.ClientError, TimeoutError):
        raise Transient() from None
    parser.feed(bytes(header[: 256 * 1024]).decode("utf-8", errors="replace").split("</head", 1)[0])
    return parser.links[0] if parser.links else None
