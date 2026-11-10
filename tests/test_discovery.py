from types import SimpleNamespace

from echoscope.application.config import Job, Source
from echoscope.application.discovery import TopicDiscovery
from echoscope.application.ports import RateLimited
from echoscope.connectors.youtube_comments import Video
from echoscope.domain.models import Batch, Kind, Message
from echoscope.domain.tone import message_tone


def test_tone_is_independent_of_alert_rules():
    assert message_tone("¡Excelente! Gracias por el apoyo.") == "positive"
    assert message_tone("No fue bueno.") == "negative"
    assert message_tone("La atención fue excelente, aunque hubo demora.") == "mixed"
    assert message_tone("El Ministerio presentó el informe.") == "neutral"


async def test_discovery_uses_active_feeds_and_both_youtube_queries(monkeypatch):
    queries = []

    async def youtube(terms, *, live):
        queries.append((terms, live))
        if live:
            return [Video("01234567890", "Directo", "Canal A")]
        return [
            Video("01234567890", "Directo", "Canal A"),
            Video("12345678901", "Video", "Canal B"),
        ]

    async def feed(_connector, request):
        queries.append(request.source.id)
        yield Batch(
            (
                Message(
                    Kind.NEWS_ARTICLE,
                    "rss:example.com",
                    "1",
                    request.source.id,
                    "Uruguay y su Ejército\nInforme",
                    url="https://example.com/nota",
                ),
            ),
            None,
        )

    async def brave(terms, _key):
        queries.append(terms)
        raise RateLimited()

    monkeypatch.setenv("ECHOSCOPE_YOUTUBE_KEY", "test")
    monkeypatch.setenv("ECHOSCOPE_BRAVE_KEY", "test")
    monkeypatch.setattr("echoscope.application.discovery.Feed.poll", feed)
    monkeypatch.setattr("echoscope.application.discovery.search_web", brave)
    sources = [
        Source(id=name, type="press_feed", params={"url": f"https://example.com/{name}"})
        for name in ("medio", "inactivo")
    ]
    config = SimpleNamespace(
        sources=sources,
        jobs=[
            Job(id="medio", source="medio", rule_set="tema"),
            Job(id="inactivo", source="inactivo", rule_set="tema", enabled=False),
        ],
    )
    discovery = TopicDiscovery(SimpleNamespace(practice=False, search=youtube))
    candidates, notes = await discovery.search("ejercito uruguay", config)
    assert [item["kind"] for item in candidates] == ["article", "live", "video"]
    assert any("LÍMITE DE CONSUMO" in note for note in notes)
    assert ("ejercito uruguay", True) in queries and ("ejercito uruguay", False) in queries
    assert "inactivo" not in queries
    await discovery.search("ejército", config)
    assert queries.count("medio") == 1
