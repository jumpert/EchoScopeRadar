import asyncio
import os
import sys
from dataclasses import replace

import pytest
from conftest import demo_config, demo_radar, until
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from echoscope.application.engine import Radar
from echoscope.application.ports import ConnectorType, JobCommand
from echoscope.bootstrap import registry
from echoscope.connectors.simulated import SimParams, Simulator
from echoscope.domain.models import HistoryQuery, State
from echoscope.storage.sqlite import Store


async def test_demo_concurrency_reconnect_and_persistent_pause(tmp_path):
    path = tmp_path / "radar.sqlite"
    async with demo_radar(path) as (radar, store):
        await until(lambda: all(key in radar.tasks for key in radar.jobs))
        await until(lambda: radar.jobs["resenas"].state == State.RETRYING)
        await until(lambda: int(radar.jobs["chat"].checkpoint or 0) >= 8)
        await radar.execute(JobCommand("chat", "pause"))
        await until(lambda: "chat" not in radar.tasks)
        snapshots = await store.snapshots()
        checkpoint = snapshots["chat"].checkpoint
        assert snapshots["chat"].paused
        assert any(item.kind == "AlertRaised" for item in await store.events())
    async with demo_radar(path) as (radar, store):
        assert radar.jobs["chat"].state == State.PAUSED
        assert radar.jobs["chat"].checkpoint == checkpoint
        assert await store.messages(HistoryQuery(job_id="chat"))
        await radar.execute(JobCommand("chat", "resume"))
        await until(lambda: int(radar.jobs["chat"].checkpoint or 0) > int(checkpoint))


async def test_commit_failure_rolls_back_batch_then_retries(tmp_path, monkeypatch):
    store = Store(tmp_path / "radar.sqlite")
    config = demo_config()
    config.jobs = [config.jobs[0]]
    async with store.opened(write=True):
        await store.configure(config)
        old = store._observe
        failures = 0

        async def interrupted(*args):
            nonlocal failures
            result = await old(*args)
            if not failures:
                failures += 1
                raise OperationalError(None, None, RuntimeError("simulated disk error"))
            return result

        monkeypatch.setattr(store, "_observe", interrupted)
        radar = Radar(store, registry(), delay=lambda _: asyncio.sleep(0))
        snapshot = await radar.run_once("comentarios")
        assert snapshot.checkpoint == "2"
        assert len(await store.messages(HistoryQuery())) == 2
        async with store.engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM alerts")) == 2
        assert failures == 1


async def test_custom_connector_deduplicates_across_jobs_and_recovers(tmp_path):
    store = Store(tmp_path / "radar.sqlite")
    config = demo_config()
    config.sources[0].type = "new_connector"
    job = config.jobs[0]
    config.jobs = [job, job.model_copy(update={"id": "same-source"})]
    definitions = registry() | {
        "new_connector": ConnectorType("new_connector", "poll", SimParams, Simulator)
    }
    async with store.opened(write=True):
        await store.configure(config)
        radar = Radar(store, definitions)
        await radar.run_once(job.id)
        await radar.run_once("same-source")
        pending = replace((await store.snapshots())[job.id], state=State.RUNNING)
        execution = await store.start(pending)
        await store.recover()
        assert (await store.executions())[0].outcome == "INTERRUPTED"
        assert (await store.executions())[0].id == execution
        async with store.engine.connect() as conn:
            assert await conn.scalar(text("SELECT count(*) FROM messages")) == 2
            assert await conn.scalar(text("SELECT count(*) FROM message_sources")) == 4
        await store.purge(job.source)
        assert not await store.messages(HistoryQuery())
        assert not any(event.kind == "AlertRaised" for event in await store.events())


async def test_single_writer(tmp_path):
    store = Store(tmp_path / "radar.sqlite")
    async with store.opened(write=True):
        with pytest.raises(ValueError, match="escritor"):
            async with Store(store.path).opened(write=True):
                pytest.fail("a second writer was accepted")


async def test_abrupt_headless_process_restart(tmp_path):
    path = tmp_path / "interrupted.sqlite"
    worker = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "echoscope",
        "--db",
        str(path),
        "demo",
        "--headless",
        env=os.environ | {"PYTHONUTF8": "1"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output = await asyncio.wait_for(worker.stdout.readline(), 10)
        assert b"Radar activo" in output
        store = Store(path)
        async with store.opened():
            async with asyncio.timeout(10):
                while not (checkpoint := (await store.snapshots())["chat"].checkpoint):
                    await asyncio.sleep(0.05)
    finally:
        if worker.returncode is None:
            worker.kill()
        await worker.communicate()
    async with Store(path).opened(write=True) as store:
        radar = Radar(store, registry())
        await radar.initialize()
        assert int(radar.jobs["chat"].checkpoint) >= int(checkpoint)
        assert any(item.outcome == "INTERRUPTED" for item in await store.executions("chat"))
        assert await store.messages(HistoryQuery(job_id="chat"))
