import asyncio
from datetime import UTC, datetime

from aiohttp.test_utils import TestClient, TestServer

from echoscope.domain.models import Kind, Match, Message, Severity
from echoscope.domain.rules import Rule, evaluate
from echoscope.presentation.report import report_pdf
from echoscope.presentation.web import KEY, create_app, fragments, publication_display, safe_url


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


def test_publications_keep_title_separate_and_omit_unrelated_body():
    title = "Defensa presenta un informe"
    body = "intro-lejana " * 30 + "El Ejército publicó el resumen. " + "cierre-lejano " * 30
    text = f"{title}\n{body}"
    matches = evaluate(text, (Rule("a", "Defensa"), Rule("b", "Ejército")))
    for stored_title in (title, None):
        message = Message(Kind.NEWS_ARTICLE, "rss:medio", "id", "feed", text, title=stored_title)
        display = publication_display(message, matches)
        assert display["title_fragments"][0] == ["Defensa", "info"]
        assert ["Ejército", "info"] in display["fragments"]
        excerpt = "".join(part for part, _ in display["fragments"])
        assert "publicó el resumen" in excerpt and "presenta un informe" not in excerpt
        assert len(excerpt) < 180
        without_body_match = publication_display(message, matches[:1])
        assert without_body_match["fragments"] == []
        assert without_body_match["preview"].startswith("intro-lejana")
        assert (
            without_body_match["preview"].endswith("…")
            and len(without_body_match["preview"]) <= 141
        )


async def test_review_guide_saves_publication_address_with_detected_list(tmp_path, monkeypatch):
    app = create_app(tmp_path / "review-source.sqlite", practice=True, auto_start=False)
    page = "https://example.com/experiencias"
    feed = "https://example.com/resenas.atom"

    async def detect(self, address):
        assert address == page
        return feed

    monkeypatch.setattr(
        "echoscope.application.administration.Administration.detect_reviews", detect
    )
    async with TestClient(TestServer(app)) as client:
        app[KEY].authority = client.make_url("/").authority
        bootstrap = await (await client.get("/api/bootstrap")).json()
        headers = {
            "Origin": str(client.make_url("/")).rstrip("/"),
            "X-EchoScope-Token": bootstrap["token"],
        }
        detected = await client.post("/api/discover-reviews", json={"value": page}, headers=headers)
        address = (await detected.json())["url"]
        saved = await client.post(
            "/api/source",
            json={
                "label": "Reseñas del sitio",
                "type_label": "Reseñas de un sitio (RSS/Atom)",
                "address": address,
                "resource_url": page,
                "minutes": 15,
            },
            headers=headers,
        )
        assert saved.status == 200
        config = await app[KEY].service.store.configuration()
        source = next(item for item in config.sources if item.label == "Reseñas del sitio")
        assert source.params == {"kind": "REVIEW", "url": feed, "resource_url": page}


async def test_local_dashboard_connects_streams_settings_and_controls(tmp_path, monkeypatch):
    exported = []

    def capture(rows, *args):
        exported.extend(rows)
        return report_pdf(rows, *args)

    monkeypatch.setattr("echoscope.presentation.web.report_pdf", capture)
    app = create_app(tmp_path / "web.sqlite", practice=True, auto_start=False)
    async with TestClient(TestServer(app)) as client:
        base = client.make_url("/")
        app[KEY].authority = base.authority
        origin = str(base).rstrip("/")

        response = await client.get("/")
        assert response.status == 200
        assert "Mesa de monitoreo" in await response.text()
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        for path in ("/app.css", "/app.js", "/ciberdefensa.png"):
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
        alert = data["alerts"][0]
        assert alert["review_state"] == "open"
        assert (
            await client.post(
                "/api/alert-review",
                json={"keys": [alert["review_key"]], "state": "threat"},
                headers=headers,
            )
        ).status == 200
        marked = await (
            await client.get(f"/api/board?panels=&review=threat&tone={alert['tone']}")
        ).json()
        assert [(row["review_key"], row["review_state"]) for row in marked["alerts"]] == [
            (alert["review_key"], "threat")
        ]
        assert all(
            item["tone"] in {"positive", "negative", "mixed", "neutral"} for item in data["alerts"]
        )
        search = await client.post("/api/topic-search", json={"value": "atención"}, headers=headers)
        discovery = await search.json()
        assert search.status == 200 and discovery["candidates"] == [] and discovery["history"]
        today = datetime.now(UTC).date().isoformat()
        report = await client.post(
            "/api/report", json={"start": today, "end": today}, headers=headers
        )
        assert report.status == 200 and report.content_type == "application/pdf"
        assert (await report.read()).startswith(b"%PDF-")
        assert sum(row["review_state"] == "threat" for row in exported) == 1
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
