from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel

from echoscope.domain.models import Availability, Batch, HistoryQuery, Observation, Result, State
from echoscope.domain.rules import Rule

from .config import Job, Source


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
