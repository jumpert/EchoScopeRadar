import asyncio
import json
import os
import re
from contextlib import aclosing
from time import monotonic
from urllib.parse import urlsplit

import aiohttp

from echoscope.connectors.syndication import Feed, PublicResolver, public_url
from echoscope.connectors.youtube_comments import video_id
from echoscope.domain.models import category, publication_title
from echoscope.domain.tone import folded

from .administration import RSS_TYPES, YOUTUBE_KEY
from .ports import AuthRequired, ConnectorError, RateLimited, Request, Transient
from .secrets import secrets_for_request

BRAVE_KEY = "ECHOSCOPE_BRAVE_KEY"
SOCIAL_DOMAINS = ("facebook.com", "instagram.com", "x.com", "tiktok.com", "reddit.com", "bsky.app")


def public_result_url(url):
    if not url or any(ord(char) < 32 for char in url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme in {"http", "https"} and parsed.hostname and parsed.username is None:
            return url
    except ValueError:
        pass
    return None


def indexed_candidate(url):
    host = urlsplit(url).hostname
    try:
        identifier = video_id(url)
    except ValueError:
        kind = (
            "social"
            if any(host == domain or host.endswith(f".{domain}") for domain in SOCIAL_DOMAINS)
            else "web"
        )
        return url, host, kind
    return f"https://www.youtube.com/watch?v={identifier}", "YouTube", "video"


async def search_web(terms, key, *, social=False):
    query = (
        f"{terms} Uruguay AND (" + " OR ".join(f"site:{domain}" for domain in SOCIAL_DOMAINS) + ")"
        if social
        else f"{terms} loc:uy"
    )
    async with (
        aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=10)) as session,
        session.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": 20, "search_lang": "es", "text_decorations": "false"},
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            allow_redirects=False,
        ) as response,
    ):
        if response.status in {401, 403}:
            raise AuthRequired()
        if response.status == 429:
            raise RateLimited()
        if response.status != 200:
            raise Transient()
        data = await response.json()
    return [
        {
            "title": item.get("title", "")[:300],
            "url": url,
            "source": host,
            "excerpt": item.get("description", "")[:500],
            "kind": kind,
            "provider": "Brave",
        }
        for item in data.get("web", {}).get("results", [])[:20]
        if (address := public_result_url(item.get("url", "")))
        for url, host, kind in (indexed_candidate(address),)
        if not social or kind == "social"
    ]


async def query_search(method, url, *, headers=None, payload=None, params=None, public_only=False):
    connector = aiohttp.TCPConnector(resolver=PublicResolver()) if public_only else None
    async with (
        aiohttp.ClientSession(
            connector=connector, trust_env=False, timeout=aiohttp.ClientTimeout(total=10)
        ) as session,
        session.request(
            method, url, headers=headers, json=payload, params=params, allow_redirects=False
        ) as response,
    ):
        if response.status in {401, 403}:
            raise AuthRequired()
        if response.status in {402, 429}:
            raise RateLimited()
        if response.status != 200:
            raise Transient()
        body = bytearray()
        async for chunk in response.content.iter_chunked(65536):
            body.extend(chunk)
            if len(body) > 1024 * 1024:
                raise Transient()
        return json.loads(body)


def indexed_results(rows, provider, address_field, excerpt_field):
    results = []
    for row in rows[:20]:
        if url := public_result_url(row.get(address_field) or ""):
            url, host, kind = indexed_candidate(url)
            results.append(
                {
                    "url": url,
                    "source": host,
                    "kind": kind,
                    "provider": provider,
                    "title": (row.get("title") or "")[:300],
                    "excerpt": (row.get(excerpt_field) or "")[:500],
                }
            )
    return results


async def tavily_search(terms, key):
    data = await query_search(
        "POST",
        "https://api.tavily.com/search",
        headers={"Authorization": f"Bearer {key}"},
        payload={"query": f"{terms} Uruguay", "max_results": 12, "search_depth": "basic"},
    )
    return indexed_results(data.get("results", []), "Tavily", "url", "content")


async def serper_search(terms, key):
    data = await query_search(
        "POST",
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key},
        payload={"q": terms, "gl": "uy", "hl": "es", "num": 12},
    )
    return indexed_results(data.get("organic", []), "Google mediante Serper", "link", "snippet")


async def searx_search(terms, endpoint):
    url = public_url(endpoint.rstrip("/") + "/search")
    data = await query_search(
        "GET",
        url,
        params={"q": f"{terms} Uruguay", "format": "json", "language": "es"},
        public_only=True,
    )
    return indexed_results(data.get("results", []), "SearXNG", "url", "content")


class TopicDiscovery:
    def __init__(self, service):
        self.service = service
        self.guard = asyncio.Lock()
        self.cache = {}
        self.slots = asyncio.Semaphore(6)

    async def _feed(self, source, words):
        key = (
            source.id,
            source.params["url"],
            source.params.get("kind"),
            source.credential.env if source.credential else None,
        )
        async with self.slots:
            cached = self.cache.get(key)
            if cached is None or cached[0] <= monotonic():
                messages = []
                delay = 60
                problem = None
                try:
                    async with aclosing(Feed().poll(Request(source, None, 4))) as reader:
                        async for batch in reader:
                            messages.extend(batch.messages)
                except (ConnectorError, TimeoutError) as exc:
                    problem = exc.label if isinstance(exc, ConnectorError) else "TIEMPO AGOTADO"
                    if isinstance(exc, RateLimited):
                        delay = max(delay, exc.retry_after or 0)
                cached = (monotonic() + delay, messages, problem)
                if key not in self.cache and len(self.cache) >= 32:
                    self.cache.pop(min(self.cache, key=lambda entry: self.cache[entry][0]))
                self.cache[key] = cached
        _, messages, problem = cached
        if problem:
            return [], f"{source.label or source.id}: {problem}"
        results = []
        for message in messages:
            if not words.issubset(re.findall(r"\w+", folded(message.text))):
                continue
            title = publication_title(message)
            excerpt = message.text.removeprefix(title).lstrip("\n") if title else message.text
            results.append(
                {
                    "title": title[:300],
                    "url": public_result_url(message.url or ""),
                    "source": source.label or source.id,
                    "excerpt": excerpt,
                    "kind": "article"
                    if category(message.kind, message.origin) == "news"
                    else "feed",
                }
            )
            if len(results) == 8:
                break
        return results, None

    async def _youtube(self, terms, *, live):
        return [
            {
                "title": item.title,
                "url": f"https://www.youtube.com/watch?v={item.id}",
                "source": item.channel or "YouTube",
                "excerpt": item.description,
                "kind": "live" if live else "video",
            }
            for item in await self.service.search(terms, live=live)
        ]

    async def search(self, terms, config):
        words = set(re.findall(r"\w+", folded(terms)))
        if not words:
            raise ValueError("Escribí un tema para iniciar la búsqueda.")
        if self.guard.locked():
            raise ValueError("Hay una búsqueda en curso. Esperá a que termine.")
        async with self.guard:
            return await self._search(terms, config, words)

    async def _search(self, terms, config, words):
        if self.service.practice:
            return [], ["Modo de práctica. Se consultó el historial simulado."]
        enabled = {job.source for job in config.jobs if job.enabled}
        sources = [
            source for source in config.sources if source.id in enabled and source.type in RSS_TYPES
        ]
        providers = []
        notes = []
        if secrets_for_request().get(YOUTUBE_KEY):
            providers.extend(
                [
                    ("Videos de YouTube", self._youtube(terms, live=False)),
                    ("Directos de YouTube", self._youtube(terms, live=True)),
                ]
            )
        else:
            notes.append("Cargá una clave de YouTube para descubrir videos y directos.")
        if key := secrets_for_request().get(BRAVE_KEY):
            providers.append(("Web abierta", search_web(terms, key)))
            providers.append(("Redes sociales públicas", search_web(terms, key, social=True)))
        if key := secrets_for_request().get("ECHOSCOPE_TAVILY_KEY"):
            providers.append(("Tavily", tavily_search(terms, key)))
        if key := secrets_for_request().get("ECHOSCOPE_SERPER_KEY"):
            providers.append(("Google mediante Serper", serper_search(terms, key)))
        if endpoint := os.environ.get("ECHOSCOPE_SEARXNG_URL"):
            providers.append(("SearXNG", searx_search(terms, endpoint)))
        if not any(
            label in {"Web abierta", "Tavily", "Google mediante Serper", "SearXNG"}
            for label, _ in providers
        ):
            notes.append(
                "Agregá una clave de un buscador en Claves API para ampliar la consulta a la web abierta."
            )
        if len(sources) > 18:
            notes.append("Se consultaron los primeros 18 feeds habilitados.")
        feeds = sources[:18]
        responses = await asyncio.gather(
            *(self._feed(source, words) for source in feeds),
            *(call for _, call in providers),
            return_exceptions=True,
        )
        matches = []
        for source, response in zip(feeds, responses):
            if isinstance(response, BaseException):
                notes.append(f"{source.label or source.id}: no se pudo consultar.")
            else:
                items, problem = response
                matches.extend(items)
                if problem:
                    notes.append(problem)
        for (provider, _), response in zip(providers, responses[len(feeds) :]):
            if isinstance(response, BaseException):
                label = (
                    response.label
                    if isinstance(response, ConnectorError)
                    else "no se pudo consultar"
                )
                notes.append(f"{provider}: {label}.")
            else:
                matches.extend(response)

        unique = {}
        for item in matches:
            identity = item["url"] or (item["source"], item["title"], item["excerpt"])
            labels = list(
                dict.fromkeys(
                    [
                        *unique.get(identity, {}).get("providers", []),
                        *([item["provider"]] if item.get("provider") else []),
                    ]
                )
            )
            if identity not in unique or item["kind"] == "live":
                unique[identity] = dict(item)
            if labels:
                unique[identity]["providers"] = labels
        return list(unique.values()), notes
