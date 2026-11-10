import asyncio
import ipaddress
import json
import socket
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pydantic import model_validator

from echoscope.application.config import StrictModel
from echoscope.application.ports import (
    AuthRequired,
    ConnectorError,
    Forbidden,
    RateLimited,
    Request,
    Transient,
)
from echoscope.domain.models import Batch, Kind, Message, utcnow

MAX_BODY = 5 * 1024 * 1024
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
CREATOR = "{http://purl.org/dc/elements/1.1/}creator"


def _ip_is_public(value):
    address = ipaddress.ip_address(value.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast and not address.is_reserved


def public_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Se requiere una URL HTTPS sin credenciales ni redirecciones")
    host = parsed.hostname.rstrip(".")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if "." not in host or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError("Se requiere un dominio público") from None
    else:
        raise ValueError("Configurá un dominio público en vez de una IP literal")
    return url


class FeedParams(StrictModel):
    url: str
    kind: str = "FEED_ENTRY"
    resource_url: str | None = None

    @model_validator(mode="after")
    def endpoint(self):
        public_url(self.url)
        if self.resource_url:
            public_url(self.resource_url)
        if Kind(self.kind) == Kind.LIVE_CHAT:
            raise ValueError("Un feed no declara chat en vivo")
        return self


class PublicResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        records = await asyncio.get_running_loop().getaddrinfo(
            host, port, family=family, type=socket.SOCK_STREAM
        )
        if not records or any(not _ip_is_public(record[4][0]) for record in records):
            raise Forbidden()
        return [
            {
                "hostname": host,
                "host": addr[0],
                "port": addr[1],
                "family": family,
                "proto": proto,
                "flags": socket.AI_NUMERICHOST,
            }
            for family, _, proto, _, addr in records
        ]

    async def close(self):
        pass


class _PlainHTML(HTMLParser):
    blocks = {"p", "li", "div", "tr", "dt", "dd", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        if not self.hidden and (tag == "br" or tag in self.blocks):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        if not self.hidden and tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _plain(value):
    parser = _PlainHTML()
    parser.feed(value)
    parser.close()
    return "\n".join(part.strip() for part in "".join(parser.parts).splitlines() if part.strip())


def parse_date(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _link(base, value):
    if not value:
        return None
    try:
        link = urljoin(base, value)
        parsed = urlsplit(link)
        return (
            link
            if parsed.scheme in {"https", "http"} and parsed.hostname and parsed.username is None
            else None
        )
    except ValueError:
        return None


def parse_feed(body: bytes, params: FeedParams) -> tuple[Message, ...]:
    try:
        root = ElementTree.fromstring(body, forbid_dtd=True)
    except (ElementTree.ParseError, DefusedXmlException):
        raise ConnectorError() from None
    atom = root.tag == ATOM + "feed"
    if not atom and root.tag != "rss":
        raise ConnectorError()
    entries = root.findall(ATOM + "entry" if atom else "./channel/item")
    if len(entries) > 5000:
        raise ConnectorError()
    messages = []
    for entry in entries:
        if atom:
            link = next(
                (
                    item.get("href")
                    for item in entry.findall(ATOM + "link")
                    if item.get("rel", "alternate") == "alternate"
                ),
                None,
            )
            identifier = entry.findtext(ATOM + "id")
            title = entry.findtext(ATOM + "title") or ""
            content = entry.find(ATOM + "content")
            if content is None:
                content = entry.find(ATOM + "summary")
            description = "" if content is None else "".join(content.itertext()).strip()
            if content is not None and content.get("type") == "html":
                description = _plain(description)
            author = entry.findtext(f"{ATOM}author/{ATOM}name") or root.findtext(
                f"{ATOM}author/{ATOM}name"
            )
            published = entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated")
        else:
            link = entry.findtext("link")
            identifier = entry.findtext("guid")
            title = _plain(entry.findtext("title") or "")
            description = _plain(entry.findtext(CONTENT) or entry.findtext("description") or "")
            author = entry.findtext(CREATOR)  # RSS author commonly contains an email address.
            published = entry.findtext("pubDate")
        link = _link(params.url, link)
        identifier = (identifier or "").strip() or link
        content = "\n".join(part for part in (title.strip(), description) if part)
        if identifier and content:
            if len(content) > 65536:
                raise ConnectorError()
            origin = f"{'atom' if atom else 'rss'}:{urlsplit(params.url).hostname}"
            messages.append(
                Message(
                    Kind(params.kind),
                    origin,
                    identifier,
                    params.resource_url or params.url,
                    content,
                    author,
                    url=link,
                    published_at=parse_date(published),
                    title=title.strip(),
                )
            )
    return tuple(messages)


class Feed:
    async def poll(self, request: Request):
        params = FeedParams.model_validate(request.source.params)
        checkpoint = json.loads(request.checkpoint) if request.checkpoint else {}
        headers = {
            "User-Agent": "EchoScopeRadar/0.1",
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml",
        }
        if checkpoint.get("etag"):
            headers["If-None-Match"] = checkpoint["etag"]
        if checkpoint.get("last_modified"):
            headers["If-Modified-Since"] = checkpoint["last_modified"]
        if request.source.credential:
            token = request.source.credential.resolve()
            if (
                not token
                or not token.isascii()
                or not token.isprintable()
                or any(character.isspace() for character in token)
            ):
                raise AuthRequired()
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with (
                aiohttp.ClientSession(
                    connector=aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False),
                    cookie_jar=aiohttp.DummyCookieJar(),
                    trust_env=False,
                    timeout=aiohttp.ClientTimeout(total=request.timeout_s),
                ) as session,
                session.get(params.url, headers=headers, allow_redirects=False) as response,
            ):
                if response.status == 304:
                    yield Batch((), request.checkpoint)
                    return
                if response.status == 401:
                    raise AuthRequired()
                if response.status == 403:
                    raise Forbidden()
                if response.status == 429:
                    value = response.headers.get("Retry-After", "")
                    date = parse_date(value) if not value.isdecimal() else None
                    seconds = int(value) if value.isdecimal() and len(value) < 10 else 60
                    raise RateLimited(
                        max(0, (date - utcnow()).total_seconds()) if date else seconds
                    )
                if response.status >= 500:
                    raise Transient()
                if response.status != 200:
                    raise ConnectorError()
                body = bytearray()
                async for chunk in response.content.iter_chunked(65536):
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        raise ConnectorError()
                next_cursor = json.dumps(
                    {
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                    }
                )
        except aiohttp.ClientError:
            raise Transient() from None
        messages = await asyncio.to_thread(parse_feed, bytes(body), params)
        for start in range(0, len(messages), 50):
            end = start + 50
            yield Batch(
                messages[start:end], next_cursor if end >= len(messages) else request.checkpoint
            )
        if not messages:
            yield Batch((), next_cursor)
