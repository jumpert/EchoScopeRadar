import asyncio
import json
import logging
import signal
import sys
from contextlib import aclosing, contextmanager, suppress
from dataclasses import replace
from datetime import UTC
from importlib.resources import as_file, files
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from sqlalchemy.exc import SQLAlchemyError
from yaml import YAMLError

from echoscope.application.config import Job, read_config
from echoscope.application.engine import Radar, validate_config
from echoscope.application.ports import ConnectorError, Request, StorageUnavailable
from echoscope.bootstrap import create_store, registry
from echoscope.connectors.syndication import parse_date
from echoscope.domain.models import HistoryQuery, Severity, State
from echoscope.domain.rules import evaluate
from echoscope.settings import load_environment, runtime_settings

from .render import display, line

app = typer.Typer(
    no_args_is_help=True, help="EchoScope Radar · monitoreo de comentarios y directos."
)
config_app = typer.Typer(no_args_is_help=True)
job_app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(job_app, name="job")
app.add_typer(data_app, name="data")


@app.callback()
def options(
    ctx: typer.Context,
    db: Annotated[Path | None, typer.Option(help="Ruta de SQLite local.")] = None,
    database_url: Annotated[
        str | None, typer.Option(help="URL del adaptador de persistencia.")
    ] = None,
    env_file: Annotated[Path | None, typer.Option(help="Archivo de entorno explícito.")] = None,
):
    load_environment(env_file)
    if db and database_url:
        raise ValueError("Elegí --db o --database-url.")
    ctx.obj = db or database_url


def _store(ctx, demo=False):
    settings = runtime_settings()
    target = ctx.obj or (
        settings.data_dir / "demo.sqlite" if demo else settings.database_target("radar.sqlite")
    )
    return create_store(target)


def _config(path, connectors=None):
    config = read_config(path)
    validate_config(config, connectors or registry())
    return config


@config_app.command("validate")
def validate(path: Path):
    _config(path)
    typer.echo("Configuración válida")


@config_app.command("apply")
def apply(ctx: typer.Context, path: Path):
    config = _config(path)

    async def operation():
        store = _store(ctx)
        async with store.opened(write=True):
            await store.configure(config)

    asyncio.run(operation())
    typer.echo("Configuración aplicada")


@config_app.command("example")
def example(name: str = "public"):
    if name not in {"demo", "public", "defensa-uruguay"}:
        raise ValueError("Ejemplos disponibles: demo, public y defensa-uruguay")
    typer.echo(
        files("echoscope.examples").joinpath(f"{name}.yaml").read_text(encoding="utf-8"), nl=False
    )


@contextmanager
def _terminate(callback):
    previous = signal.getsignal(signal.SIGTERM)
    loop = asyncio.get_running_loop()
    signal.signal(signal.SIGTERM, lambda *_: loop.call_soon_threadsafe(callback))
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


async def _serve(store, radar, headless, seconds=None):
    worker = asyncio.create_task(radar.run())
    ready = asyncio.create_task(radar.ready.wait())
    try:
        await asyncio.wait({worker, ready}, return_when=asyncio.FIRST_COMPLETED)
        if worker.done():
            await worker
            return
        if headless:
            typer.echo(f"EchoScope Radar activo · {len(radar.jobs)} tareas configuradas")
            with _terminate(radar.stop):
                if seconds is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(worker), seconds)
                    except TimeoutError:
                        radar.stop()
                else:
                    await asyncio.shield(worker)
        else:
            from .tui import RadarConsole

            console = RadarConsole(radar, store.executions)
            with _terminate(console.exit):
                await console.run_async()
    finally:
        radar.stop()
        ready.cancel()
        with suppress(asyncio.CancelledError):
            await ready
        await worker


async def _open_and_run(ctx, *, headless, demo=False, seconds=None):
    connectors = registry()
    store = _store(ctx, demo)
    async with store.opened(write=True):
        if demo:
            with as_file(files("echoscope.examples").joinpath("demo.yaml")) as path:
                await store.configure(_config(path, connectors))
        await _serve(store, Radar(store, connectors), headless, seconds)


@app.command()
def demo(
    ctx: typer.Context,
    headless: bool = False,
    seconds: Annotated[float | None, typer.Option(min=0.1)] = None,
):
    if seconds is not None and not headless:
        raise ValueError("--seconds requiere --headless")
    asyncio.run(_open_and_run(ctx, headless=headless, demo=True, seconds=seconds))


@app.command()
def run(ctx: typer.Context, seconds: Annotated[float | None, typer.Option(min=0.1)] = None):
    asyncio.run(_open_and_run(ctx, headless=True, seconds=seconds))


@app.command()
def console(ctx: typer.Context):
    asyncio.run(_open_and_run(ctx, headless=False))


@job_app.command("run-once")
def run_once(ctx: typer.Context, job_id: str):
    async def operation():
        store = _store(ctx)
        async with store.opened(write=True):
            return await Radar(store, registry()).run_once(job_id)

    snapshot = asyncio.run(operation())
    typer.echo(f"{snapshot.job.id} · {snapshot.state} · {snapshot.detail or 'OK'}")
    if snapshot.state in {State.ERROR, State.RATE_LIMITED}:
        raise typer.Exit(1)


@job_app.command("clone")
def clone(ctx: typer.Context, job_id: str, new_id: str):
    async def operation():
        store = _store(ctx)
        async with store.opened(write=True):
            config = await store.configuration()
            if config is None or not (
                job := next((job for job in config.jobs if job.id == job_id), None)
            ):
                raise ValueError("Tarea desconocida")
            if any(job.id == new_id for job in config.jobs):
                raise ValueError("El nuevo ID ya existe")
            cloned = Job.model_validate(job.model_dump() | {"id": new_id, "enabled": False})
            await store.configure(config.model_copy(update={"jobs": [*config.jobs, cloned]}))

    asyncio.run(operation())
    typer.echo("Tarea clonada y deshabilitada")


@app.command()
def status(ctx: typer.Context, executions: bool = False):
    async def operation():
        store = _store(ctx)
        async with store.opened():
            if executions:
                for item in await store.executions():
                    typer.echo(f"{item.started} · {item.job} · {item.outcome}")
                return
            for item in (await store.snapshots()).values():
                next_at = (
                    item.next_at.astimezone().isoformat(timespec="seconds") if item.next_at else "—"
                )
                typer.echo(
                    f"{item.job.id} · {item.state} · próximo {next_at} · {item.detail or '—'}"
                )

    asyncio.run(operation())


@app.command()
def doctor(
    ctx: typer.Context,
    network: Annotated[str | None, typer.Option(help="Probar una fuente configurada.")] = None,
):
    async def operation():
        store = _store(ctx)
        async with store.opened():
            config = await store.configuration()
            if config is None:
                raise ValueError("La base no tiene configuración activa")
            connectors = registry()
            validate_config(config, connectors)
            if store.writer_available():
                typer.echo("Almacenamiento accesible · bloqueo disponible")
            else:
                typer.echo("Almacenamiento accesible · escritor activo")
                if network:
                    raise ValueError("Detené el motor antes de probar una fuente") from None
            for source in config.sources:
                if source.credential:
                    typer.echo(
                        f"{source.id} · credencial {'presente' if source.credential.resolve() else 'ausente'}"
                    )
            if network:
                source = next((item for item in config.sources if item.id == network), None)
                if not source:
                    raise ValueError("Fuente desconocida")
                definition = connectors[source.type]
                connector = definition.factory()
                method = connector.poll if definition.mode == "poll" else connector.stream
                try:
                    async with aclosing(method(Request(source, None, 15))) as iterator:
                        batch = await asyncio.wait_for(anext(iterator), 20)
                except (TimeoutError, StopAsyncIteration):
                    raise ValueError(
                        "La fuente no entregó un lote en la ventana de diagnóstico"
                    ) from None
                typer.echo(
                    f"{source.id} · fuente accesible · {len(batch.messages)} mensajes en el primer lote"
                )

    asyncio.run(operation())


def _when(value):
    if value is None:
        return None
    timestamp = parse_date(value)
    if timestamp is None:
        raise ValueError("Usá fecha ISO-8601. Las fechas sin zona se interpretan en UTC")
    return timestamp.astimezone(UTC)


@app.command()
def history(
    ctx: typer.Context,
    source: str | None = None,
    job: str | None = None,
    text: str | None = None,
    severity: Severity | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 50,
    before: Annotated[int | None, typer.Option(min=1)] = None,
):
    query = HistoryQuery(job, source, text, severity, _when(since), _when(until), limit, before)

    async def operation():
        store = _store(ctx)
        async with store.opened():
            output = Console()
            for result in await store.messages(query):
                output.print(f"#{result.id} · {line(result.source_id)}", markup=False)
                output.print(display(result.observation, details=True))

    asyncio.run(operation())


@app.command()
def replay(
    ctx: typer.Context,
    source: str | None = None,
    job: str | None = None,
    rules: Path | None = None,
    rule_set: str | None = None,
    limit: Annotated[int, typer.Option(min=1, max=500)] = 100,
    after: Annotated[int, typer.Option(min=0)] = 0,
):
    if (rules is None) != (rule_set is None):
        raise ValueError("Para ensayar reglas, indicá --rules y --rule-set juntos")
    compiled = None
    if rules:
        config = _config(rules)
        if rule_set not in config.rule_sets:
            raise ValueError("Conjunto de reglas desconocido")
        compiled = tuple(rule.compile() for rule in config.rule_sets[rule_set])

    async def operation():
        store = _store(ctx)
        async with store.opened():
            output = Console()
            for result in await store.messages(
                HistoryQuery(job_id=job, source_id=source, limit=limit, after=after)
            ):
                item = result.observation
                if compiled is not None:
                    item = replace(item, matches=evaluate(item.message.text, compiled))
                output.print(f"REPLAY #{result.id} · {line(result.source_id)}", markup=False)
                output.print(display(item, details=True))

    asyncio.run(operation())


@data_app.command("purge")
def purge(ctx: typer.Context, source: Annotated[str, typer.Option()]):
    async def operation():
        store = _store(ctx)
        async with store.opened(write=True):
            await store.purge(source)

    asyncio.run(operation())
    typer.echo("Datos locales de la fuente eliminados")


class JsonLog(logging.Formatter):
    def format(self, record):
        return json.dumps(
            {
                "level": record.levelname,
                "event": record.getMessage(),
                "job": getattr(record, "job", None),
                "error": getattr(record, "error_type", None),
            }
        )


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLog())
    logging.getLogger("echoscope").addHandler(handler)
    try:
        app()
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (
        ValueError,
        OSError,
        YAMLError,
        SQLAlchemyError,
        ConnectorError,
        StorageUnavailable,
    ) as error:
        if isinstance(error, (SQLAlchemyError, YAMLError)):
            detail = (
                "Almacenamiento inaccesible o esquema incompatible"
                if isinstance(error, SQLAlchemyError)
                else "YAML inválido"
            )
        elif hasattr(error, "errors"):
            detail = ", ".join(
                ".".join(map(str, item["loc"])) or "configuración" for item in error.errors()
            )
            detail = f"Configuración inválida en {detail}"
        else:
            detail = str(error)
        typer.echo(line(detail), err=True)
        raise SystemExit(1) from None
