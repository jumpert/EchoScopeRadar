import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Protocol

from echoscope.domain.models import (
    Availability,
    HistoryQuery,
    Kind,
    Observation,
    Result,
    State,
    category,
    utcnow,
)
from echoscope.domain.rules import evaluate

from .config import Configuration
from .ports import (
    BatchSink,
    ConnectorError,
    ConnectorType,
    CursorExpired,
    JobCommand,
    JobSnapshot,
    RateLimited,
    Request,
    SourceEnded,
    SourceUnavailable,
    SourceWaiting,
    StorageUnavailable,
    Transient,
)

LOG = logging.getLogger(__name__)


class Storage(BatchSink, Protocol):
    async def recover(self): ...
    async def snapshots(self) -> dict[str, JobSnapshot]: ...
    async def configuration(self) -> Configuration | None: ...
    async def start(self, snapshot: JobSnapshot) -> int: ...
    async def save(self, snapshot: JobSnapshot, execution_id=None, *, action=None): ...
    async def finish(self, snapshot: JobSnapshot, execution_id: int, outcome: str): ...
    async def coverage_gap(self, snapshot: JobSnapshot, execution_id: int | None): ...
    async def purge(self): ...
    async def messages(self, query: HistoryQuery) -> list[Result]: ...
    async def events(self, after: int, limit: int): ...


class Radar:
    def __init__(
        self,
        store: Storage,
        registry: dict[str, ConnectorType],
        *,
        now: Callable[[], datetime] = utcnow,
        jitter: Callable[[], float] = random.random,
        delay: Callable[[float], Awaitable] = asyncio.sleep,
    ):
        self.store = store
        self.registry = registry
        self.now = now
        self.jitter = jitter
        self.delay = delay
        self.jobs: dict[str, JobSnapshot] = {}
        self.rules = {}
        self.connectors = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.interrupts: dict[str, asyncio.Event] = {}
        self.session: dict[str, dict[tuple, Result]] = {}
        self.session_sequence = 0
        self.changed = asyncio.Event()
        self.revision = 0
        self.wake = asyncio.Event()
        self.stopping = False
        self.ready = asyncio.Event()
        self.controls = asyncio.Lock()
        self.database_ok = True
        self.last_batch_received: dict[str, float] = {}

    async def initialize(self):
        await self.store.recover()
        await self.store.purge()
        config = await self.store.configuration()
        if config is None:
            raise ValueError("Aplicá una configuración antes de iniciar el motor")
        validate_config(config, self.registry)
        self.rules = {
            name: tuple(rule.compile() for rule in rules)
            for name, rules in config.rule_sets.items()
        }
        self.jobs = await self.store.snapshots()
        for key, snapshot in self.jobs.items():
            definition = self.registry[snapshot.source.type]
            if not definition.persistent and snapshot.availability == Availability.LIVE:
                updated = replace(snapshot, coverage_gap=True, availability=Availability.WAITING)
                await self.store.coverage_gap(updated, None)
                self.jobs[key] = updated
        self.ready.set()

    def _notify(self):
        self.revision += 1
        self.changed.set()
        self.wake.set()

    def stop(self):
        self.stopping = True
        for event in self.interrupts.values():
            event.set()
        self.wake.set()

    async def run(self):
        await self.initialize()
        next_purge = asyncio.get_running_loop().time() + 86400
        try:
            while not self.stopping:
                self.wake.clear()
                if asyncio.get_running_loop().time() >= next_purge:
                    try:
                        await self.store.purge()
                    except StorageUnavailable:
                        LOG.warning("retention_retry")
                        next_purge = asyncio.get_running_loop().time() + 60
                    else:
                        next_purge = asyncio.get_running_loop().time() + 86400
                        self._notify()
                self._launch_due()
                try:
                    await asyncio.wait_for(self.wake.wait(), self._wait_time())
                except TimeoutError:
                    pass
        finally:
            self.stop()
            pending = list(self.tasks.values())
            if pending:
                _, unfinished = await asyncio.wait(pending, timeout=3)
                for task in unfinished:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

    def _eligible(self):
        return [
            snapshot
            for key, snapshot in self.jobs.items()
            if key not in self.tasks
            and snapshot.job.enabled
            and not snapshot.paused
            and snapshot.state not in {State.ERROR, State.IDLE}
            and (snapshot.state != State.RATE_LIMITED or snapshot.next_at is not None)
        ]

    def _launch_due(self):
        free = {"poll": 4, "stream": 2}
        for key in self.tasks:
            free[self.registry[self.jobs[key].source.type].mode] -= 1
        now = self.now()
        for snapshot in sorted(
            self._eligible(), key=lambda item: (item.next_at or now, item.job.id)
        ):
            key = snapshot.job.id
            mode = self.registry[snapshot.source.type].mode
            if free[mode] and (snapshot.next_at is None or snapshot.next_at <= now):
                free[mode] -= 1
                task = asyncio.create_task(self._cycle(key), name=f"radar:{key}")
                self.tasks[key] = task
                task.add_done_callback(lambda completed, job=key: self._completed(job, completed))

    def _completed(self, key, task):
        self.tasks.pop(key, None)
        if not task.cancelled() and task.exception():
            LOG.error(
                "worker_failed", extra={"job": key, "error_type": type(task.exception()).__name__}
            )
            self.jobs[key] = replace(self.jobs[key], state=State.ERROR, detail="ERROR INTERNO")
        self._notify()

    def _wait_time(self):
        now = self.now()
        future = [
            (item.next_at - now).total_seconds()
            for item in self._eligible()
            if item.next_at is not None and item.next_at > now
        ]
        return min([1.0, *future])

    async def _write(self, operation, *args, **kwargs):
        while True:
            try:
                result = await operation(*args, **kwargs)
            except StorageUnavailable:
                self.database_ok = False
                self._notify()
                if self.stopping:
                    raise
                LOG.warning("database_retry")
                await self.delay(1)
            else:
                self.database_ok = True
                return result

    def _durable(self, snapshot):
        return (
            snapshot
            if self.registry[snapshot.source.type].persistent
            else replace(snapshot, checkpoint=None)
        )

    def _active(self, key):
        item = self.jobs[key]
        return item.job.enabled and not item.paused and not self.stopping

    async def _cycle(self, key: str):
        async with self.controls:
            if not self._active(key):
                return
            snapshot = replace(
                self.jobs[key], state=State.RUNNING, last_at=self.now(), next_at=None, detail=None
            )
            execution = await self._write(self.store.start, self._durable(snapshot))
            self.jobs[key] = snapshot
            self._notify()
        outcome, count = "OK", 0
        try:
            count = await self._consume(key, execution)
            if self.stopping:
                outcome = "INTERRUPTED"
        except asyncio.CancelledError:
            outcome = "INTERRUPTED"
            raise
        except ConnectorError as error:
            outcome = error.label
            await self._failure(key, error, execution)
        except Exception as error:
            outcome = "ERROR INTERNO"
            LOG.error("cycle_failed", extra={"job": key, "error_type": type(error).__name__})
            async with self.controls:
                if self._active(key):
                    self.jobs[key] = replace(self.jobs[key], state=State.ERROR, detail=outcome)
        finally:
            async with self.controls:
                current = self.jobs[key]
                if current.state == State.RUNNING:
                    live = self.registry[current.source.type].mode == "stream"
                    next_at = (
                        None if live else self.now() + timedelta(seconds=current.job.interval_s)
                    )
                    current = replace(
                        current,
                        state=State.SCHEDULED,
                        next_at=next_at,
                        detail=None if count else "SIN RESULTADOS",
                    )
                if current.state in {State.PAUSED, State.DISABLED}:
                    outcome = current.state
                await self._write(self.store.finish, self._durable(current), execution, outcome)
                self.jobs[key] = current
                self._notify()

    async def _consume(self, key, execution):
        definition = self.registry[self.jobs[key].source.type]
        if key not in self.connectors:
            self.connectors[key] = definition.factory()
        connector = self.connectors[key]
        interrupted = self.interrupts.setdefault(key, asyncio.Event())
        interrupted.clear()
        retries, received, reset_cursor = 0, 0, False
        while self._active(key):
            snapshot = self.jobs[key]
            request = Request(
                snapshot.source,
                snapshot.checkpoint,
                snapshot.job.timeout_s,
                self.rules[snapshot.job.rule_set],
            )
            method = connector.poll if definition.mode == "poll" else connector.stream
            try:
                async with aclosing(method(request)) as iterator:
                    while self._active(key):
                        try:
                            if definition.mode == "poll":
                                async with asyncio.timeout(request.timeout_s):
                                    batch = await anext(iterator)
                            else:
                                batch = await self._live_next(iterator, interrupted)
                                if batch is None:
                                    return received
                        except StopAsyncIteration:
                            if definition.mode == "stream" and self._active(key):
                                raise Transient()
                            return received
                        received_at = asyncio.get_running_loop().time()
                        await self._batch(key, execution, definition, batch, received_at)
                        received += len(batch.messages)
                return received
            except CursorExpired:
                if reset_cursor or request.checkpoint is None:
                    raise
                reset_cursor = True
                async with self.controls:
                    updated = replace(self.jobs[key], checkpoint=None, coverage_gap=True)
                    await self._write(self.store.coverage_gap, self._durable(updated), execution)
                    self.jobs[key] = updated
                    self._notify()
            except (TimeoutError, Transient) as error:
                if retries >= 3:
                    raise Transient() from error
                retries += 1
                minimum = definition.min_interval_s if definition.mode == "poll" else 0
                wait = max(minimum, 2 ** (retries - 1) + self.jitter())
                async with self.controls:
                    if not self._active(key):
                        return received
                    await self._change(
                        key,
                        execution,
                        state=State.RETRYING,
                        detail=Transient.label,
                        next_at=self.now() + timedelta(seconds=wait),
                    )
                await self.delay(wait)
                async with self.controls:
                    if self._active(key):
                        await self._change(
                            key, execution, state=State.RUNNING, next_at=None, detail=None
                        )
        return received

    async def _live_next(self, iterator, interrupted):
        # Do not time out a quiet chat. Stop the blocked read on pause or shutdown.
        next_batch = asyncio.create_task(anext(iterator))
        stop = asyncio.create_task(interrupted.wait())
        try:
            completed, _ = await asyncio.wait(
                {next_batch, stop}, return_when=asyncio.FIRST_COMPLETED
            )
            return next_batch.result() if next_batch in completed else None
        finally:
            for task in (next_batch, stop):
                if not task.done():
                    task.cancel()
            await asyncio.gather(next_batch, stop, return_exceptions=True)

    async def _batch(self, key, execution, definition, batch, received_at):
        rules = self.rules[self.jobs[key].job.rule_set]

        def evaluate_batch():
            matches_by_text = {}
            observations = []
            for item in batch.messages:
                if item.text not in matches_by_text:
                    matches_by_text[item.text] = evaluate(item.text, rules)
                observations.append(Observation(item, matches_by_text[item.text]))
            return tuple(observations)

        observations = await asyncio.to_thread(evaluate_batch)
        async with self.controls:
            current = self.jobs[key]
            if current.job.relevant_only:
                observations = tuple(
                    item
                    for item in observations
                    if item.matches or item.message.kind == Kind.PRESS_COMMENT
                )
            snapshot = replace(
                current,
                checkpoint=batch.checkpoint,
                coverage_gap=current.coverage_gap or batch.coverage_gap,
                availability=Availability.LIVE if definition.mode == "stream" else None,
            )
            await self._write(
                self.store.apply,
                self._durable(snapshot),
                execution,
                observations,
                definition.persistent,
                coverage_gap=batch.coverage_gap,
            )
            if not definition.persistent:
                self._remember(snapshot, observations)
            self.jobs[key] = snapshot
            if observations:
                self.last_batch_received[key] = received_at
            self._notify()

    def _remember(self, snapshot, observations):
        window = self.session.setdefault(snapshot.job.id, {})
        for item in observations:
            key = item.message.origin, item.message.external_id, item.message.text
            if key not in window:
                self.session_sequence -= 1
                window[key] = Result(
                    self.session_sequence, snapshot.job.id, snapshot.source.id, item
                )
            if len(window) > 200:
                del window[next(iter(window))]

    async def _change(self, key, execution=None, *, action=None, **changes):
        snapshot = replace(self.jobs[key], **changes)
        await self._write(self.store.save, self._durable(snapshot), execution, action=action)
        self.jobs[key] = snapshot
        self._notify()
        return snapshot

    async def _failure(self, key, error, execution):
        async with self.controls:
            if not self._active(key):
                return
            state, availability, next_at = State.ERROR, self.jobs[key].availability, None
            if isinstance(error, RateLimited):
                state = State.RATE_LIMITED
                if error.retry_after is not None:
                    minimum = self.registry[self.jobs[key].source.type].min_interval_s
                    next_at = self.now() + timedelta(seconds=max(minimum, error.retry_after, 1))
            elif isinstance(error, SourceWaiting):
                state, availability = State.SCHEDULED, Availability.WAITING
                next_at = self.now() + timedelta(seconds=self.jobs[key].job.interval_s)
            elif isinstance(error, SourceEnded):
                state, availability = State.IDLE, Availability.ENDED
            elif isinstance(error, SourceUnavailable):
                availability = Availability.UNAVAILABLE
            await self._change(
                key,
                execution,
                state=state,
                availability=availability,
                detail=error.label,
                next_at=next_at,
            )

    async def execute(self, command: JobCommand) -> tuple[JobSnapshot, ...]:
        keys = [command.job_id] if command.job_id is not None else sorted(self.jobs)
        results = []
        async with self.controls:
            for key in keys:
                current = self.jobs.get(key)
                if current is None:
                    raise ValueError("Tarea desconocida")
                action = command.action
                if action in {"pause", "resume"} and not current.job.enabled:
                    continue
                if action == "pause":
                    changes = {"paused": True, "state": State.PAUSED}
                elif action == "disable":
                    changes = {
                        "paused": False,
                        "state": State.DISABLED,
                        "job": current.job.model_copy(update={"enabled": False}),
                    }
                elif action == "interval":
                    definition = self.registry[current.source.type]
                    interval = command.interval_s
                    if (
                        interval is None
                        or not max(0.05, definition.min_interval_s) <= interval <= 86400
                    ):
                        raise ValueError("Intervalo fuera de rango para esta fuente")
                    changes = {"job": current.job.model_copy(update={"interval_s": interval})}
                    if current.state == State.SCHEDULED:
                        changes["next_at"] = self.now() + timedelta(seconds=interval)
                else:
                    if action in {"run_now", "recover"} and (
                        current.paused or not current.job.enabled
                    ):
                        raise ValueError("Primero habilitá y reanudá la tarea")
                    if action == "run_now" and key in self.tasks:
                        raise ValueError("La tarea ya está en ejecución")
                    if current.detail == RateLimited.label:
                        if current.next_at and current.next_at > self.now():
                            if command.job_id is None:
                                continue
                            raise ValueError("La fuente sigue limitada por cuota")
                        if current.next_at is None and action != "recover":
                            if command.job_id is None:
                                continue
                            raise ValueError("La cuota requiere recuperación manual")
                    definition = self.registry[current.source.type]
                    next_at = None
                    if definition.mode == "poll" and current.last_at and definition.min_interval_s:
                        earliest = current.last_at + timedelta(seconds=definition.min_interval_s)
                        if action == "run_now" and self.now() < earliest:
                            raise ValueError("Todavía rige el intervalo mínimo de la fuente")
                        if self.now() < earliest:
                            next_at = earliest
                    changes = {
                        "paused": False,
                        "state": State.RUNNING if key in self.tasks else State.SCHEDULED,
                        "detail": None,
                        "next_at": next_at,
                        "job": current.job.model_copy(update={"enabled": True}),
                    }
                results.append(await self._change(key, action=action, **changes))
                if action in {"pause", "disable"} and key in self.interrupts:
                    self.interrupts[key].set()
        return tuple(results)

    async def run_once(self, key):
        await self.initialize()
        current = self.jobs.get(key)
        if current is None or self.registry[current.source.type].mode != "poll":
            raise ValueError("Indicá una tarea de polling válida")
        if not current.job.enabled or current.paused:
            raise ValueError("La tarea está deshabilitada o pausada")
        if current.next_at and current.next_at > self.now():
            raise ValueError(
                f"El próximo ciclo está habilitado a las {current.next_at.isoformat()}"
            )
        await self._cycle(key)
        return self.jobs[key]

    async def events(self, after=0, limit=200):
        return await self.store.events(after, limit)

    async def messages(self, query: HistoryQuery):
        if query.job_id in self.session:
            window = reversed(list(self.session[query.job_id].values()))
            return [
                item
                for item in window
                if (
                    (query.source_id is None or item.source_id == query.source_id)
                    and (
                        not query.text
                        or query.text.casefold() in item.observation.message.text.casefold()
                    )
                    and (
                        query.severity is None
                        or any(
                            match.confirmed and match.severity == query.severity
                            for match in item.observation.matches
                        )
                    )
                    and (
                        not query.matches_only
                        or any(match.confirmed for match in item.observation.matches)
                    )
                    and (
                        not query.review_only
                        or any(not match.confirmed for match in item.observation.matches)
                    )
                    and (query.kind is None or item.observation.message.kind == query.kind)
                    and (query.exclude_kind is None or item.observation.message.kind != query.exclude_kind)
                    and (
                        query.category is None
                        or category(item.observation.message.kind, item.observation.message.origin)
                        == query.category
                    )
                    and (query.since is None or item.observation.message.captured_at >= query.since)
                    and (query.until is None or item.observation.message.captured_at <= query.until)
                    and (query.before is None or item.id > query.before)
                )
            ][: query.limit]
        return await self.store.messages(query)


def validate_config(config, registry):
    sources = {source.id: source for source in config.sources}
    for source in config.sources:
        definition = registry.get(source.type)
        if definition is None:
            raise ValueError(f"Conector desconocido en {source.id}")
        try:
            definition.schema.model_validate(source.params)
        except ValueError:
            raise ValueError(f"Parámetros inválidos para {source.id} ({definition.name})") from None
        if source.credential and source.credential.kind not in definition.credentials:
            raise ValueError(f"Tipo de credencial incompatible con {source.id}")
    for job in config.jobs:
        definition = registry[sources[job.source].type]
        if job.interval_s < definition.min_interval_s:
            raise ValueError(f"Intervalo mínimo para {job.id}: {definition.min_interval_s:g}s")
