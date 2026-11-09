import asyncio
import os
from statistics import quantiles

import pytest
from conftest import demo_config, until
from sqlalchemy import text

from echoscope.application.engine import Radar
from echoscope.application.ports import ConnectorType, SourceEnded
from echoscope.bootstrap import registry
from echoscope.connectors.simulated import SimParams
from echoscope.domain.models import Batch, Kind, Message
from echoscope.presentation.tui import RadarConsole
from echoscope.storage.sqlite import Store


class Burst:
    async def poll(self, request):
        for start in range(0, 1000, 50):
            await asyncio.sleep(0.03)
            messages = tuple(
                Message(
                    Kind.COMMENT,
                    "load",
                    f"{request.source.id}:{index}",
                    request.source.id,
                    "Excelente atención al cliente. Sin novedades.",
                )
                for index in range(start, start + 50)
            )
            yield Batch(messages, str(start + 50))

    async def stream(self, request):
        async for batch in self.poll(request):
            yield batch
        raise SourceEnded()


class MeasuredConsole(RadarConsole):
    key_sent = None

    def __init__(self, *args):
        super().__init__(*args)
        self.key_delays = []
        self.capture_delays = []

    def action_next_panel(self):
        super().action_next_panel()
        if self.key_sent is not None:
            self.key_delays.append(asyncio.get_running_loop().time() - self.key_sent)
            self.key_sent = None

    def _displayed(self, key, revision, received_at):
        self.capture_delays.append(asyncio.get_running_loop().time() - received_at)


@pytest.mark.performance
@pytest.mark.skipif(os.environ.get("ECHOSCOPE_TEST_LOAD") != "1", reason="prueba de carga optativa")
async def test_ten_sources_10000_messages(tmp_path):
    config = demo_config()
    source, job = config.sources[0], config.jobs[0]
    config.sources = [
        source.model_copy(
            update={
                "id": f"s-{i}",
                "label": f"Fuente {i}",
                "type": "burst_stream" if i < 2 else "burst_poll",
            }
        )
        for i in range(10)
    ]
    config.jobs = [
        job.model_copy(update={"id": item.id, "source": item.id, "interval_s": 3600})
        for item in config.sources
    ]
    definitions = registry() | {
        "burst_stream": ConnectorType("burst_stream", "stream", SimParams, Burst),
        "burst_poll": ConnectorType("burst_poll", "poll", SimParams, Burst),
    }
    store = Store(tmp_path / "load.sqlite")
    async with store.opened(write=True):
        await store.configure(config)
        radar = Radar(store, definitions)
        worker = asyncio.create_task(radar.run())
        try:
            await until(radar.ready.is_set)
            app = MeasuredConsole(radar, store.executions)
            clock = asyncio.get_running_loop().time
            started = clock()
            async with app.run_test(size=(140, 36)) as pilot:
                while not all(item.checkpoint == "1000" for item in radar.jobs.values()):
                    app.key_sent = clock()
                    await pilot.press("tab")
                    await pilot.pause(0.12)
                    assert clock() - started < 90, "la carga no terminó en 90 segundos"
                assert all(len(rows) <= 200 for rows in app.panel_rows.values())
            async with store.engine.connect() as conn:
                assert await conn.scalar(text("SELECT count(*) FROM messages")) == 10000
            assert len(app.capture_delays) >= 10
            capture_p95 = quantiles(app.capture_delays, n=20)[18]
            key_p95 = quantiles(app.key_delays, n=20)[18]
            print(f"10,000 messages · render p95={capture_p95:.3f}s · keyboard p95={key_p95:.3f}s")
            assert capture_p95 <= 1.0
            assert key_p95 <= 0.250
        finally:
            radar.stop()
            await worker
