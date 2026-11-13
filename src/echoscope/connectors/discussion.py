"""Public discussion mechanisms, resolved without executing page scripts."""

import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit

import aiohttp

from echoscope.application.config import Credential
from echoscope.application.ports import AuthRequired, Forbidden, RateLimited, Transient
from echoscope.domain.models import Kind, Message

from .syndication import PublicResolver, _plain, parse_date, public_url


class DiscussionLinks(HTMLParser):
    def __init__(self, url):
        super().__init__()
        self.url, self.post, self.api, self.forum = url, None, None, None

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        href = attrs.get("href", "") if tag == "link" else ""
        if attrs.get("rel") == "https://api.w.org/":
            self.api = urljoin(self.url, href)
        match = re.search(r"/wp-json/wp/v2/posts/(\d+)", href)
        if match:
            self.post = match[1]
            self.api = urljoin(self.url, href.split("wp/v2/posts/")[0])
        if attrs.get("rel") == "shortlink":
            self.post = parse_qs(urlsplit(href).query).get("p", [self.post])[0]
        src = attrs.get("src", "")
        match = re.fullmatch(r"https://([\w-]+)\.disqus\.com/embed\.js", src)
        if match:
            self.forum = match[1]


async def public_get(url, *, params=None, json_body=True):
    try:
        return await _public_get(url, params=params, json_body=json_body)
    except (aiohttp.ClientError, TimeoutError):
        raise Transient() from None


async def _public_get(url, *, params=None, json_body=True):
    public_url(url)
    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False),
        trust_env=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=aiohttp.ClientTimeout(total=8),
    ) as session:
        async with session.get(url, params=params, allow_redirects=False) as response:
            if response.status == 401:
                raise AuthRequired()
            if response.status == 403:
                raise Forbidden()
            if response.status == 429:
                raise RateLimited()
            if response.status != 200:
                raise Transient()
            if json_body:
                # WordPress returns an array, unlike most API responses.
                body = await limited_bytes(response, 1024 * 1024)
                try:
                    return json.loads(body), dict(response.headers)
                except ValueError:
                    raise Transient() from None
            return (await limited_bytes(response, 256 * 1024, truncate=True)).decode(
                "utf-8", errors="replace"
            )


async def limited_bytes(response, limit, *, truncate=False):
    body = bytearray()
    async for chunk in response.content.iter_chunked(8192):
        body.extend(chunk)
        if len(body) > limit:
            if truncate:
                return bytes(body[:limit])
            raise Transient()
    return bytes(body)


async def discover_mechanisms(url):
    body = await public_get(url, json_body=False)
    parser = DiscussionLinks(url)
    parser.feed(body)
    mechanisms = []
    if parser.api and parser.post and urlsplit(parser.api).hostname == urlsplit(url).hostname:
        mechanisms.append(
            {
                "type": "wordpress",
                "url": public_url(parser.api.rstrip("/") + "/wp/v2/comments"),
                "post": parser.post,
            }
        )
    forum = parser.forum
    if not forum:
        match = re.search(
            r"(?:disqus_shortname\s*=\s*|https://)(?:['\"])?([\w-]+)(?:['\"]\s*;|\.disqus\.com/embed\.js)",
            body,
        )
        forum = match[1] if match else None
    if forum:
        mechanisms.append({"type": "disqus", "forum": forum, "article": url})
    return mechanisms


@dataclass(frozen=True)
class DiscussionPage:
    messages: tuple[Message, ...]
    next_page: str | None = None
    partial: bool = False


async def read_mechanism(mechanism, *, article, title=None, cursor=None, credential=None):
    if mechanism["type"] == "wordpress":
        endpoint = mechanism["url"]
        if urlsplit(endpoint).hostname != urlsplit(article).hostname:
            raise Forbidden()
        page = max(1, int(cursor or 1))
        rows, headers = await public_get(
            endpoint,
            params={
                "post": mechanism["post"],
                "per_page": 50,
                "page": page,
                "orderby": "date",
                "order": "desc",
                "status": "approve",
            },
        )
        if not isinstance(rows, list):
            raise Transient()
        messages = tuple(
            Message(
                Kind.PRESS_COMMENT,
                "wordpress:" + urlsplit(article).hostname,
                str(row["id"]),
                article,
                _plain(row.get("content", {}).get("rendered", ""))[:65536],
                row.get("author_name"),
                url=row.get("link") or article,
                published_at=parse_date(row.get("date_gmt", "") + "Z"),
                resource_title=title,
                parent_id=str(row["parent"]) if row.get("parent") else None,
            )
            for row in rows
            if row.get("id") and row.get("content", {}).get("rendered")
        )
        pages = int(
            next((value for key, value in headers.items() if key.lower() == "x-wp-totalpages"), "1")
        )
        next_page = str(page + 1) if page < pages else None
        return DiscussionPage(messages, next_page, bool(next_page))

    key = (credential or Credential(kind="api_key", env="ECHOSCOPE_DISQUS_KEY")).resolve()
    if not key:
        raise AuthRequired()
    params = {
        "api_key": key,
        "forum": mechanism["forum"],
        "thread": "link:" + article,
        "limit": 50,
        "order": "desc",
    }
    if cursor:
        params["cursor"] = cursor
    data, _ = await public_get("https://disqus.com/api/3.0/threads/listPosts.json", params=params)
    if not isinstance(data, dict) or data.get("code") != 0:
        raise Forbidden()
    messages = tuple(
        Message(
            Kind.PRESS_COMMENT,
            "disqus:" + mechanism["forum"],
            str(row["id"]),
            article,
            _plain(row.get("raw_message") or row.get("message", ""))[:65536],
            row.get("author", {}).get("name"),
            url=row.get("url") or article,
            published_at=parse_date(row.get("createdAt")),
            resource_title=title,
            parent_id=str(row["parent"]) if row.get("parent") else None,
        )
        for row in data.get("response", [])
        if row.get("id") and not row.get("isDeleted")
    )
    pagination = data.get("cursor", {})
    next_page = pagination.get("next") if pagination.get("hasNext") else None
    return DiscussionPage(messages, next_page, bool(next_page))
