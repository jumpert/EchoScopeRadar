from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncContextManager, Literal, Protocol

from pydantic import BaseModel

from echoscope.domain.models import Availability, Batch, HistoryQuery, Observation, Result, State
from echoscope.domain.rules import Rule

from .config import Configuration, Job, Source


@dataclass(frozen=True, slots=True)
class Request:
    source: Source
    checkpoint: str | None
    timeout_s: float
    rules: tuple[Rule, ...] = ()


class PollConnector(Protocol):
    def poll(self, request: Request) -> AsyncIterator[Batch]: ...


class StreamConnector(Protocol):
    def stream(self, request: Request) -> AsyncIterator[Batch]: ...


@dataclass(frozen=True, slots=True)
class ConnectorType:
    name: str
    mode: Literal["poll", "stream"]
    schema: type[BaseModel]
    factory: Callable[[], PollConnector | StreamConnector]
    credentials: tuple[str, ...] = ()
    version: int = 1
    persistent: bool = True
    simulated: bool = False
    min_interval_s: float = 0
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job: Job
    source: Source
    state: State
    paused: bool = False
    availability: Availability | None = None
    detail: str | None = None
    last_at: datetime | None = None
    next_at: datetime | None = None
    checkpoint: str | None = None
    coverage_gap: bool = False


@dataclass(frozen=True, slots=True)
class JobCommand:
    job_id: str | None
    action: Literal["pause", "resume", "run_now", "enable", "disable", "interval", "recover"]
    interval_s: float | None = None


class RadarCommands(Protocol):
    async def execute(self, command: JobCommand) -> tuple[JobSnapshot, ...]: ...


class RadarQueries(Protocol):
    async def messages(self, query: HistoryQuery) -> list[Result]: ...
    async def events(self, after: int = 0, limit: int = 200): ...


class BatchSink(Protocol):
    async def apply(
        self,
        snapshot: JobSnapshot,
        execution_id: int,
        observations: tuple[Observation, ...],
        persistent: bool,
        *,
        coverage_gap=False,
    ) -> int: ...


class EngineStore(BatchSink, Protocol):
    async def recover(self): ...
    async def snapshots(self) -> dict[str, JobSnapshot]: ...
    async def configuration(self) -> Configuration | None: ...
    async def start(self, snapshot: JobSnapshot) -> int: ...
    async def save(self, snapshot: JobSnapshot, execution_id=None, *, action=None): ...
    async def finish(self, snapshot: JobSnapshot, execution_id: int, outcome: str): ...
    async def coverage_gap(self, snapshot: JobSnapshot, execution_id: int | None): ...
    async def purge(self, source=None): ...
    async def messages(
        self, query: HistoryQuery, *, review_state=None, tone=None
    ) -> list[Result]: ...
    async def events(self, after=0, limit=200): ...


class RadarStore(EngineStore, Protocol):
    def opened(self, *, write=False) -> AsyncContextManager: ...
    def writer_available(self) -> bool: ...
    async def configure(self, config: Configuration): ...
    async def executions(self, job=None): ...
    async def desktop_setting(self, key): ...
    async def set_desktop_setting(self, key, value): ...
    async def alert_reviews(self, keys): ...
    async def reviewable_keys(self, keys) -> set[str]: ...
    async def set_alert_reviews(self, keys, state): ...


class ConnectorError(Exception):
    label = "ERROR DE FUENTE"

    def __init__(self):
        super().__init__(self.label)


class StorageUnavailable(Exception):
    pass


class Transient(ConnectorError):
    label = "CONEXIÓN INTERRUMPIDA"


class Forbidden(ConnectorError):
    label = "SIN PERMISO"


class AuthRequired(Forbidden):
    label = "CREDENCIAL AUSENTE O INVÁLIDA"


class RateLimited(ConnectorError):
    label = "LÍMITE DE CONSUMO"

    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__()


class CursorExpired(ConnectorError):
    label = "CAPTURA PARCIAL"


class SourceWaiting(ConnectorError):
    label = "ESPERANDO DIRECTO"


class LiveChatPending(SourceWaiting):
    label = "DIRECTO ENCONTRADO, CHAT NO DISPONIBLE"


class SourceEnded(ConnectorError):
    label = "DIRECTO FINALIZADO"


class SourceUnavailable(ConnectorError):
    label = "CHAT NO DISPONIBLE"
