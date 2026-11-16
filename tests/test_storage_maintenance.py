import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text

from echoscope.domain.models import Kind, Message, Observation, utcnow
from echoscope.domain.rules import evaluate
from echoscope.presentation.web import KEY, create_app, reopen_existing, serve


async def test_capacity_preview_cleanup_preserves_matches_new_data_and_config(tmp_path):
    path = tmp_path / "real.sqlite"
    app = create_app(path, practice=True, auto_start=False)
    async with TestClient(TestServer(app)) as client:
        state = app[KEY]
        state.authority = client.make_url("/").authority
        config = state.config
        store = state.service.store
        snapshot = next(iter((await store.snapshots()).values()))
        snapshot = replace(snapshot, last_at=utcnow())
        execution = await store.start(snapshot)
        rules = tuple(rule.compile() for rule in config.rule_sets[snapshot.job.rule_set])
        old = utcnow() - timedelta(days=10)
        messages = [
            Message(
                Kind.COMMENT,
                "fixture",
                "old-unmatched",
                "article",
                "sin tema " * 30000,
                captured_at=old,
            ),
            Message(
                Kind.COMMENT, "fixture", "old-matched", "article", rules[0].phrase, captured_at=old
            ),
            Message(Kind.COMMENT, "fixture", "recent", "article", "mensaje reciente"),
        ]
        await store.apply(
            snapshot,
            execution,
            tuple(Observation(message, evaluate(message.text, rules)) for message in messages),
            True,
        )
        bootstrap = await (await client.get("/api/bootstrap")).json()
        headers = {
            "Origin": str(client.make_url("/")).rstrip("/"),
            "X-EchoScope-Token": bootstrap["token"],
        }
        assert (await client.post("/api/data-storage", json={})).status == 403
        stats = await (await client.post("/api/data-storage", json={}, headers=headers)).json()
        assert stats["path"] == str(path.resolve())
        assert stats["counts"]["message_sources"] == 3
        assert stats["total_file_bytes"] >= stats["database_bytes"] > 0
        assert stats["disk_free_bytes"] > 0
        assert stats["kinds"] == {"COMMENT": 3}
        async with store.reader() as conn:
            view = (await conn.execute(text("SELECT texto,tipo FROM capturas"))).all()
            assert len(view) == 3 and view[0].tipo == "COMMENT"
        preview = await (
            await client.post(
                "/api/data-cleanup-preview",
                json={"keep_days": 7, "only_unmatched": True},
                headers=headers,
            )
        ).json()
        assert preview["captures"] == 1 and preview["alerts"] == 0
        # Even an old-dated capture inserted after the preview must not be removed.
        await store.apply(
            snapshot,
            execution,
            (Observation(replace(messages[0], external_id="late-arrival", text="llegó después")),),
            True,
        )
        response = await client.post(
            "/api/data-cleanup-confirm", json={"token": preview["token"]}, headers=headers
        )
        assert response.status == 200
        result = await response.json()
        assert result["removed"] == 1 and result["compacted"]
        assert state.service.worker is None  # Was stopped before maintenance.
        async with store.reader() as conn:
            ids = set((await conn.execute(text("SELECT external_id FROM messages"))).scalars())
            assert ids == {"old-matched", "recent", "late-arrival"}
            assert await conn.scalar(text("SELECT count(*) FROM alerts")) > 0
            assert not (await conn.exec_driver_sql("PRAGMA foreign_key_check")).all()
        assert (await store.configuration()) == config
        assert (
            await client.post(
                "/api/data-cleanup-confirm", json={"token": preview["token"]}, headers=headers
            )
        ).status == 400
        assert (
            await client.post("/api/data-cleanup-preview", json={"keep_days": 0}, headers=headers)
        ).status == 400


async def test_cleanup_includes_old_matches_only_when_requested_and_resumes(tmp_path):
    app = create_app(tmp_path / "resume.sqlite", practice=True, auto_start=False)
    async with TestClient(TestServer(app)) as client:
        state = app[KEY]
        state.authority = client.make_url("/").authority
        store = state.service.store
        snapshot = next(iter((await store.snapshots()).values()))
        snapshot = replace(snapshot, last_at=utcnow())
        execution = await store.start(snapshot)
        rules = tuple(rule.compile() for rule in state.config.rule_sets[snapshot.job.rule_set])
        message = Message(
            Kind.COMMENT,
            "fixture",
            "old",
            "article",
            rules[0].phrase,
            captured_at=utcnow() - timedelta(days=10),
        )
        await store.apply(
            snapshot, execution, (Observation(message, evaluate(message.text, rules)),), True
        )
        plan = await store.cleanup_plan((utcnow() - timedelta(days=7)).isoformat(), False)
        assert plan["alerts"] > 0
        await state.service.set_running(True)
        old_worker = state.service.worker
        result = await state.service.cleanup_data(plan)
        assert result["removed"] == 1
        assert state.service.worker is not None and state.service.worker is not old_worker
        async with store.reader() as conn:
            assert not (await conn.exec_driver_sql("PRAGMA foreign_key_check")).all()
            assert not await conn.scalar(
                text("SELECT count(*) FROM messages WHERE origin='fixture'")
            )


async def test_reopen_running_browser_workspace_without_second_engine(tmp_path, monkeypatch):
    path = tmp_path / "running.sqlite"
    app = create_app(path, practice=True, auto_start=False)
    opened = []
    monkeypatch.setattr("echoscope.presentation.web.webbrowser.open", opened.append)
    async with TestClient(TestServer(app)) as client:
        state = app[KEY]
        state.authority = client.make_url("/").authority
        port = client.make_url("/").port
        assert await reopen_existing(path, practice=True, port=port, bind="127.0.0.1")
        assert not await reopen_existing(
            tmp_path / "other.sqlite", practice=True, port=port, bind="127.0.0.1"
        )
        assert not await reopen_existing(path, practice=False, port=port, bind="127.0.0.1")
        await asyncio.wait_for(serve(path, practice=True, port=port, browser=True), 5)
        assert len(opened) == 1
        await asyncio.wait_for(serve(path, practice=True, port=port, browser=False), 5)
        assert len(opened) == 1  # Repeated startup does not open a browser or a second writer.


async def test_cleanup_restart_happens_even_on_failure(tmp_path, monkeypatch):
    app = create_app(tmp_path / "failure.sqlite", practice=True, auto_start=False)
    async with TestClient(TestServer(app)):
        service = app[KEY].service
        await service.set_running(True)

        async def fail(plan):
            raise ValueError("fallo de prueba")

        monkeypatch.setattr(service.store, "cleanup_before", fail)
        with pytest.raises(ValueError, match="fallo de prueba"):
            await service.cleanup_data({})
        assert service.worker is not None
