from types import SimpleNamespace

import pytest
from sqlalchemy import URL

from echoscope.settings import load_environment, runtime_settings
from echoscope.storage.factory import create_store


def test_persistent_environment_is_shared_by_launcher_and_startup(tmp_path, monkeypatch):
    data = tmp_path / "data"
    work = tmp_path / "program"
    data.mkdir()
    work.mkdir()
    (data / "instalacion.env").write_text("ECHOSCOPE_PORT=18700\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("ECHOSCOPE_DATA_DIR", str(data))
    monkeypatch.delenv("ECHOSCOPE_ENV_FILE", raising=False)
    monkeypatch.delenv("ECHOSCOPE_PORT", raising=False)
    assert load_environment().port == 18700
    monkeypatch.delenv("ECHOSCOPE_PORT", raising=False)
    (work / ".env").write_text("ECHOSCOPE_PORT=18701\n", encoding="utf-8")
    assert load_environment().port == 18701
    monkeypatch.delenv("ECHOSCOPE_PORT", raising=False)


def test_env_precedence_and_safe_validation(tmp_path, monkeypatch):
    env = tmp_path / "settings.env"
    env.write_text("ECHOSCOPE_PORT=18799\nECHOSCOPE_POLL_SLOTS=7\n", encoding="utf-8")
    monkeypatch.delenv("ECHOSCOPE_POLL_SLOTS", raising=False)
    monkeypatch.setenv("ECHOSCOPE_PORT", "18800")
    settings = load_environment(env)
    assert settings.port == 18800 and settings.poll_slots == 7
    monkeypatch.setenv("ECHOSCOPE_PORT", "secret-must-not-be-printed")
    with pytest.raises(ValueError) as error:
        runtime_settings()
    assert "secret-must-not-be-printed" not in str(error.value)
    monkeypatch.delenv("ECHOSCOPE_POLL_SLOTS", raising=False)


async def test_storage_url_preserves_existing_database(tmp_path):
    path = tmp_path / "radar.sqlite"
    url = URL.create("sqlite+aiosqlite", database=str(path)).render_as_string()
    async with create_store(url).opened(write=True) as store:
        await store.set_desktop_setting("roundtrip", "persistido")
    async with create_store(path).opened() as store:
        assert await store.desktop_setting("roundtrip") == "persistido"


def test_external_backend_uses_registered_adapter(monkeypatch):
    marker = object()
    observed = []

    def factory(url, settings):
        observed.append((url.get_backend_name(), settings.poll_slots))
        return marker

    plugin = SimpleNamespace(name="postgresql", load=lambda: factory)
    monkeypatch.setattr("echoscope.storage.factory.entry_points", lambda **_: [plugin])
    assert create_store("postgresql+asyncpg://example.invalid/radar") is marker
    assert observed[0][0] == "postgresql"
    monkeypatch.setattr("echoscope.storage.factory.entry_points", lambda **_: [])
    with pytest.raises(ValueError, match="adaptador"):
        create_store("postgresql+asyncpg://admin:private@example.invalid/radar")


async def test_http_response_is_bounded(monkeypatch):
    from echoscope.application.ports import Transient
    from echoscope.connectors.http import bounded_json

    monkeypatch.setenv("ECHOSCOPE_API_MAX_BODY_BYTES", "65536")

    async def chunks(size):
        yield b"x" * (size + 1)

    response = SimpleNamespace(content=SimpleNamespace(iter_chunked=chunks))
    with pytest.raises(Transient):
        await bounded_json(response)
