import asyncio
import json
import os
import socket
import ssl
from contextlib import aclosing
from dataclasses import replace

import aiohttp
import grpc
import pytest
import trustme
from aiohttp import web
from conftest import demo_config, until

from echoscope.application.config import Credential, Source
from echoscope.application.engine import Radar
from echoscope.application.ports import (
    AuthRequired,
    ConnectorError,
    CursorExpired,
    Forbidden,
    RateLimited,
    Request,
    SourceEnded,
    Transient,
)
from echoscope.bootstrap import registry
from echoscope.connectors import stream_list_pb2 as pb
from echoscope.connectors.syndication import Feed, FeedParams, PublicResolver, parse_feed
from echoscope.connectors.youtube import YouTubeLive
from echoscope.domain.models import HistoryQuery, Kind
from echoscope.storage.sqlite import Store

ATOM = b"""<feed xmlns="http://www.w3.org/2005/Atom">
  <author><name>Example</name></author>
  <entry><id>urn:example:1</id><title>Una demora</title>
  <link href="/noticia"/><summary type="html">&lt;p&gt;Texto&lt;/p&gt;</summary>
  <updated>2026-01-02T03:04:05Z</updated></entry></feed>"""


async def batch_from(iterator):
    async with aclosing(iterator) as source:
        return await anext(source)


def test_rss_and_hostile_xml():
    params = FeedParams(url="https://comments.example.com/feed", kind="COMMENT")
    rss = b"""<rss version='2.0'><channel><item><guid>abc</guid><description>
      &lt;script&gt;hide()&lt;/script&gt;Hola &amp;amp; adios</description></item></channel></rss>"""
    (item,) = parse_feed(rss, params)
    assert item.kind == Kind.COMMENT and item.text == "Hola & adios"
    with pytest.raises(ConnectorError):
        parse_feed(b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]><rss>&x;</rss>', params)


async def test_dns_rejects_private_addresses(monkeypatch):
    async def private(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", private)
    with pytest.raises(Forbidden):
        await PublicResolver().resolve("comments.example.com", 443)


async def test_protected_https_feed_auth_conditional_and_rate_limit(monkeypatch):
    authority = trustme.CA()
    server_tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    authority.issue_cert("fixture.example.com").configure_cert(server_tls)
    client_tls = ssl.create_default_context()
    authority.configure_trust(client_tls)

    async def serve(request):
        if request.headers.get("Authorization") != "Bearer prueba-local":
            return web.Response(status=401)
        if request.query.get("limited"):
            return web.Response(status=429, headers={"Retry-After": "120"})
        if request.headers.get("If-None-Match") == '"one"':
            return web.Response(status=304)
        return web.Response(
            body=ATOM, headers={"ETag": '"one"'}, content_type="application/atom+xml"
        )

    server = web.Application()
    server.router.add_get("/feed", serve)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_tls)
    await site.start()
    port = runner.addresses[0][1]

    class LocalResolver(PublicResolver):
        async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": runner.addresses[0][1],
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]

    real_connector = aiohttp.TCPConnector
    monkeypatch.setattr("echoscope.connectors.syndication.PublicResolver", LocalResolver)
    monkeypatch.setattr(
        aiohttp, "TCPConnector", lambda **kwargs: real_connector(ssl=client_tls, **kwargs)
    )
    source = Source(
        id="feed",
        type="syndication",
        params={"url": "https://fixture.example.com/feed"},
        credential=Credential(kind="bearer", env="ECHOSCOPE_FIXTURE_TOKEN"),
    )
    monkeypatch.setenv("ECHOSCOPE_FIXTURE_TOKEN", "incorrecto")
    request = Request(source, None, 5)
    try:
        assert port > 0
        with pytest.raises(AuthRequired):
            await batch_from(Feed().poll(request))
        monkeypatch.setenv("ECHOSCOPE_FIXTURE_TOKEN", "prueba-local")
        first = await batch_from(Feed().poll(request))
        assert first.messages[0].text == "Una demora\nTexto"
        assert first.messages[0].author == "Example"
        empty = await batch_from(Feed().poll(replace(request, checkpoint=first.checkpoint)))
        assert not empty.messages and empty.checkpoint == first.checkpoint
        source.params["url"] += "?limited=1"
        with pytest.raises(RateLimited) as error:
            await batch_from(Feed().poll(request))
        assert error.value.retry_after == 120
    finally:
        await runner.cleanup()


@pytest.fixture
async def live_fixture(monkeypatch):
    seen = []

    async def stream(request, context):
        seen.append((request.page_token, dict(context.invocation_metadata()).get("x-goog-api-key")))
        if request.page_token == "stale":
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "invalid page token")
        if request.page_token == "limited":
            await context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, "quota")
        if request.page_token == "forbidden":
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "permission")
        response = pb.LiveChatMessageListResponse(next_page_token="next")
        item = response.items.add(id="message-id")
        item.snippet.type = pb.LiveChatMessageSnippet.TypeWrapper.TEXT_MESSAGE_EVENT
        item.snippet.text_message_details.message_text = "Demora privada de prueba"
        item.author_details.display_name = "Autor gRPC"
        if request.page_token == "next":
            response.offline_at = "2026-02-02T12:00:00Z"
        yield response
        if not request.page_token:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "disconnected")

    server = grpc.aio.server()
    handler = grpc.unary_stream_rpc_method_handler(
        stream,
        request_deserializer=pb.LiveChatMessageListRequest.FromString,
        response_serializer=pb.LiveChatMessageListResponse.SerializeToString,
    )
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "youtube.api.v3.V3DataLiveChatMessageService", {"StreamList": handler}
            ),
        )
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()

    async def chat(*args):
        return "chat-1", "Directo de prueba"

    monkeypatch.setattr(YouTubeLive, "_chat", chat)
    monkeypatch.setattr(
        YouTubeLive, "_channel", lambda self, grpc: grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    )
    monkeypatch.setenv("ECHOSCOPE_FIXTURE_YOUTUBE", "test-key")
    source = Source(
        id="youtube",
        type="youtube_live",
        params={"video_id": "01234567890"},
        credential=Credential(kind="api_key", env="ECHOSCOPE_FIXTURE_YOUTUBE"),
    )
    try:
        yield source, seen
    finally:
        await server.stop(0)


async def test_youtube_grpc_reconnect_and_terminal_states(live_fixture):
    source, seen = live_fixture
    adapter = YouTubeLive()
    async with aclosing(adapter.stream(Request(source, None, 4))) as connection:
        first = await anext(connection)
        assert first.messages[0].author == "Autor gRPC"
        assert first.messages[0].resource_id == "01234567890"
        assert first.messages[0].resource_title == "Directo de prueba"
        with pytest.raises(Transient):
            await anext(connection)
    async with aclosing(adapter.stream(Request(source, first.checkpoint, 4))) as connection:
        assert (await anext(connection)).messages[0].external_id == "message-id"
        with pytest.raises(SourceEnded):
            await anext(connection)
    for page, failure in [
        ("stale", CursorExpired),
        ("forbidden", Forbidden),
        ("limited", RateLimited),
    ]:
        with pytest.raises(failure):
            await batch_from(
                adapter.stream(Request(source, json.dumps({"chat": "chat-1", "page": page}), 4))
            )
    assert seen[:2] == [("", "test-key"), ("next", "test-key")]


async def test_youtube_chat_survives_restart(tmp_path, live_fixture):
    source, seen = live_fixture
    config = demo_config()
    config.sources = [source]
    config.jobs = [config.jobs[0].model_copy(update={"source": source.id, "interval_s": 60})]
    path = tmp_path / "youtube.sqlite"
    store = Store(path)
    async with store.opened(write=True):
        await store.configure(config)
        radar = Radar(store, registry(), jitter=lambda: 0)
        worker = asyncio.create_task(radar.run())
        try:
            await until(lambda: len(seen) >= 2 and not radar.tasks)
            assert len(await radar.messages(HistoryQuery(job_id="comentarios"))) == 1
            assert len(await store.messages(HistoryQuery())) == 1
            assert (await store.snapshots())["comentarios"].checkpoint is not None
        finally:
            radar.stop()
            await worker
    async with Store(path).opened() as reopened:
        assert len(await reopened.messages(HistoryQuery())) == 1


@pytest.mark.internet
@pytest.mark.skipif(
    os.environ.get("ECHOSCOPE_TEST_INTERNET") != "1", reason="requiere conexión real"
)
async def test_public_usgs():
    source = Source(
        id="usgs",
        type="syndication",
        params={
            "url": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.atom",
        },
    )
    batch = await batch_from(Feed().poll(Request(source, None, 20)))
    assert batch.messages and batch.messages[0].kind == Kind.FEED_ENTRY
