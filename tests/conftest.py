import asyncio
from contextlib import asynccontextmanager
from importlib.resources import as_file, files

from echoscope.application.config import read_config
from echoscope.application.engine import Radar
from echoscope.bootstrap import registry
from echoscope.storage.sqlite import Store


def demo_config():
    with as_file(files("echoscope.examples").joinpath("demo.yaml")) as path:
        return read_config(path)


async def until(predicate, seconds=8):
    async with asyncio.timeout(seconds):
        while not predicate():
            await asyncio.sleep(0.02)


@asynccontextmanager
async def demo_radar(path, config=None):
    store = Store(path)
    async with store.opened(write=True):
        await store.configure(config or demo_config())
        radar = Radar(store, registry(), jitter=lambda: 0)
        worker = asyncio.create_task(radar.run())
        ready = asyncio.create_task(radar.ready.wait())
        try:
            await asyncio.wait({worker, ready}, return_when=asyncio.FIRST_COMPLETED)
            if worker.done():
                await worker
            yield radar, store
        finally:
            radar.stop()
            ready.cancel()
            await worker
