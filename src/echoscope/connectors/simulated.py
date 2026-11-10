import asyncio
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field

from echoscope.application.config import StrictModel
from echoscope.application.ports import Request, Transient
from echoscope.domain.models import Batch, Kind, Message

FIXTURES = {
    "comments": (
        "Me encantó la atención, excelente servicio.",
        "Gracias por responder.",
        "La atención al cliente fue excelente. Excelente atención.",
        "El soldad0 habló de d e f e n s a.",
        "Un comentario menciona al ejersito.",
    ),
    "reviews": (
        "Tuvieron una demora importante con mi compra.",
        "Llegó en perfecto estado. Muy recomendable.",
        "El paquete llegó hoy.",
    ),
    "chat": (
        "¿Cuándo empieza?",
        "Excelente directo, saludos a todos 👋",
        "Hay una demora en el audio.",
        "La atención al cliente fue excelente.",
    ),
}


class SimParams(StrictModel):
    scenario: Literal["comments", "reviews", "chat"]
    cadence_s: float = Field(default=1, ge=0.005, le=60)
    batch_size: int = Field(default=2, ge=1, le=200)
    disconnect_at: int | None = Field(default=None, ge=1)
    fail_attempts: int = Field(default=0, ge=0, le=10)


class Simulator:
    def __init__(self):
        self.attempts = 0
        self.disconnected = False

    def _batch(self, request: Request, params: SimParams, start: int) -> Batch:
        texts = FIXTURES[params.scenario]
        kind = {"comments": Kind.COMMENT, "reviews": Kind.REVIEW, "chat": Kind.LIVE_CHAT}
        end = start + params.batch_size
        messages = tuple(
            Message(
                kind[params.scenario],
                "sim",
                f"{params.scenario}:{index}",
                params.scenario,
                texts[index % len(texts)],
                f"@visitante_{index % 7 + 1:02}",
                published_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
            )
            for index in range(max(0, start - 1), end)
        )
        return Batch(messages, str(end))

    async def poll(self, request: Request):
        params = SimParams.model_validate(request.source.params)
        await asyncio.sleep(params.cadence_s)
        self.attempts += 1
        if self.attempts <= params.fail_attempts:
            raise Transient()
        yield self._batch(request, params, int(request.checkpoint or 0))

    async def stream(self, request: Request):
        params = SimParams.model_validate(request.source.params)
        start = int(request.checkpoint or 0)
        while True:
            await asyncio.sleep(params.cadence_s)
            if params.disconnect_at and start >= params.disconnect_at and not self.disconnected:
                self.disconnected = True
                raise Transient()
            yield self._batch(request, params, start)
            start += params.batch_size
