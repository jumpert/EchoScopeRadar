from dataclasses import replace

from conftest import until

from echoscope.application.administration import Administration, SourceForm
from echoscope.domain.models import HistoryQuery, Kind


async def test_administrative_setup_edit_topic_and_reopen(tmp_path, monkeypatch):
    path = tmp_path / "administration.sqlite"
    service = Administration(path)
    config = await service.open()
    try:
        assert {source.id for source in config.sources if source.type == "press_feed"} == {
            "subrayado",
            "telenoche",
            "el-observador",
            "montevideo-portal",
            "la-diaria",
            "brecha",
            "caras-caretas",
            "teledoce",
        }
        assert all(
            job.relevant_only
            for job in config.jobs
            if job.id in {"subrayado", "telenoche", "el-observador", "montevideo-portal"}
        )
        assert len(config.sources) == 12
        form = SourceForm(
            "Video de prueba",
            "Comentarios de un video de YouTube",
            "https://youtu.be/01234567890",
            15,
        )
        config = await service.save_source(form)
        new = config.sources[-1]
        assert new.params == {"video_id": "01234567890"}
        assert new.retention_days == 7
        feed = SourceForm(
            "Comentarios", "Comentarios de un sitio (RSS)", "https://example.com/comments.xml", 15
        )
        config = await service.save_source(feed, token="session-only-token")
        source = config.sources[-1]
        monkeypatch.setenv(source.credential.env, "session-only-token")
        assert "session-only-token" not in config.model_dump_json()
        config = await service.save_source(
            replace(
                feed, address="https://different.example.com/feed", token_env=source.credential.env
            ),
            source.id,
        )
        assert config.sources[-1].credential is None
        await service.save_topic(["Ejército | ejersito", "Defensa Nacional", "ejército"])
        await service.set_theme("dark")
    finally:
        await service.close()
    service = Administration(path)
    config = await service.open()
    try:
        assert len(config.sources) == 14
        assert len(config.rule_sets["defensa"]) == 2
        assert config.rule_sets["defensa"][0].aliases == ["ejersito"]
        assert await service.theme() == "dark"
    finally:
        await service.close()


async def test_practice_starts_and_reads_filtered_history(tmp_path):
    service = Administration(tmp_path / "practice.sqlite", practice=True)
    await service.open()
    try:
        await service.set_running(True)
        await until(lambda: service.radar.jobs["chat"].checkpoint is not None)
        _, messages, running, _ = await service.snapshot(HistoryQuery(kind=Kind.LIVE_CHAT))
        assert running and messages
        assert all(item.observation.message.kind == Kind.LIVE_CHAT for item in messages)
        await service.set_running(False)
        _, retained, running, _ = await service.snapshot(HistoryQuery(kind=Kind.LIVE_CHAT))
        assert not running and retained == messages
    finally:
        await service.close()
