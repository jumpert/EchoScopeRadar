import asyncio

from aiohttp.test_utils import TestClient, TestServer

from echoscope.domain.models import Match, Severity
from echoscope.presentation.web import KEY, create_app, fragments, safe_url


def test_highlights_use_original_unicode_offsets_and_reject_active_links():
    text = "👋 soldad0 <script>"
    matches = (
        Match(2, 9, "soldad0", "rule", "revision", Severity.IMPORTANT, 0, "disguised", "soldado"),
    )
    assert fragments(text, matches) == [
        ["👋 ", None],
        ["soldad0", "important"],
        [" <script>", None],
    ]
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("https://name@example.com/") is None
    assert safe_url("https://example.com/articulo") == "https://example.com/articulo"


async def test_local_dashboard_connects_streams_settings_and_controls(tmp_path):
    app = create_app(tmp_path / "web.sqlite", practice=True, auto_start=False)
    async with TestClient(TestServer(app)) as client:
        base = client.make_url("/")
        app[KEY].authority = base.authority
        origin = str(base).rstrip("/")

        response = await client.get("/")
        assert response.status == 200
        assert "Mesa de monitoreo" in await response.text()
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        for path in ("/app.css", "/app.js", "/radar.svg"):
            assert (await client.get(path)).status == 200
        assert (await client.get("/api/bootstrap", headers={"Host": "otro.example"})).status == 421
        assert (
            await client.get("/api/bootstrap", headers={"Sec-Fetch-Site": "cross-site"})
        ).status == 403
        settings = await (await client.get("/api/bootstrap")).json()
        assert settings["practice"] and settings["theme"] == "dark"
        assert "Reseñas de un sitio (RSS/Atom)" in settings["types"]
        assert not next(job for job in settings["jobs"] if job["categories"] == ["live"])["polling"]
        token = settings["token"]
        headers = {"Origin": origin, "X-EchoScope-Token": token}
        assert (await client.post("/api/monitor", json={"enabled": True})).status == 403
        assert (
            await client.post(
                "/api/monitor",
                json={"enabled": True},
                headers=headers | {"Origin": "https://other.example"},
            )
        ).status == 403
        assert (
            await client.post("/api/theme", json={"value": "light"}, headers=headers)
        ).status == 200
        settings = await (await client.get("/api/bootstrap")).json()
        assert settings["theme"] == "light"
        assert (
            await client.post("/api/monitor", json={"enabled": True}, headers=headers)
        ).status == 200
        async with asyncio.timeout(8):
            while True:
                data = await (await client.get("/api/board?panels=live,press,reviews")).json()
                if all(data["panels"].values()):
                    break
                await asyncio.sleep(0.1)
        assert data["running"]
        assert data["alerts"]
        assert all(item["kind"] == "REVIEW" for item in data["panels"]["reviews"])
        assert all(item["kind"] != "REVIEW" for item in data["panels"]["press"])
        assert any(mark for item in data["panels"]["press"] for _, mark in item["fragments"])
        hidden = await (await client.get("/api/board?panels=")).json()
        assert hidden["panels"] == {}
        filtered = await (await client.get("/api/board?panels=press&q=zzz-no-result")).json()
        assert filtered["panels"]["press"] == []
        assert (
            await client.post("/api/monitor", json={"enabled": False}, headers=headers)
        ).status == 200
        topic = await client.post(
            "/api/topic", json={"lines": ["Ejército | ejersito"]}, headers=headers
        )
        assert (await topic.json())["topic"] == ["Ejército | ejersito"]
        new = await client.post(
            "/api/source",
            json={
                "label": "Foro autorizado",
                "type_label": "Foro o comunidad (RSS/Atom)",
                "address": "https://example.com/forum.rss",
                "minutes": 15,
                "enabled": False,
                "token": "session-only-test",
            },
            headers=headers,
        )
        assert new.status == 200
        assert "session-only-test" not in await new.text()
        source = next(job for job in (await new.json())["jobs"] if job["name"] == "Foro autorizado")
        assert source["categories"] == ["forum"] and source["protected"]
        removed = await client.post("/api/remove", json={"value": source["id"]}, headers=headers)
        assert all(job["id"] != source["id"] for job in (await removed.json())["jobs"])
