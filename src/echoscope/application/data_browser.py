"""Read-only, account-scoped queries of persisted observations."""

from dataclasses import replace
from datetime import UTC, date, datetime, time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from echoscope.application.config import StrictModel
from echoscope.domain.identity import alert_key
from echoscope.domain.models import HistoryQuery, Kind, Severity, publication_title
from echoscope.domain.tone import message_tone


class DataQuery(StrictModel):
    text: str = Field(default="", max_length=200)
    source: str | None = Field(default=None, max_length=64)
    kind: Kind | None = None
    severity: Severity | None = None
    review: Literal["all", "open", "verified", "threat", "dismissed"] = "all"
    tone: Literal["all", "negative", "positive", "mixed", "neutral"] = "all"
    matches_only: bool = False
    start: date | None = None
    end: date | None = None
    before: int | None = Field(default=None, gt=0)
    snapshot: datetime | None = None
    format: Literal["xlsx", "csv", "pdf"] | None = None

    @field_validator("kind", "severity", "start", "end", "snapshot", mode="before")
    @classmethod
    def parse_wire_values(cls, value, info):
        if isinstance(value, str):
            types = {
                "kind": Kind,
                "severity": Severity,
                "start": date.fromisoformat,
                "end": date.fromisoformat,
                "snapshot": datetime.fromisoformat,
            }
            return types[info.field_name](value)
        return value

    @model_validator(mode="after")
    def valid_dates(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("La fecha inicial debe ser anterior o igual a la final.")
        if self.snapshot and self.snapshot.tzinfo is None:
            raise ValueError("La fecha de consulta debe incluir zona horaria.")
        return self


async def query_data(store, config, fields, *, exporting=False):
    snapshot = min(fields.snapshot or datetime.now(UTC), datetime.now(UTC))
    until = min(datetime.combine(fields.end, time.max, UTC), snapshot) if fields.end else snapshot
    query = HistoryQuery(
        text=fields.text or None,
        source_id=fields.source,
        kind=fields.kind,
        severity=fields.severity,
        matches_only=fields.matches_only,
        since=datetime.combine(fields.start, time.min, UTC) if fields.start else None,
        until=until,
        before=None if exporting else fields.before,
        limit=51,
    )
    options = dict(
        review_state=None if fields.review == "all" else fields.review,
        tone=None if fields.tone == "all" else fields.tone,
    )
    if exporting:
        query = replace(query, limit=500)
        rows = []
        size = 0
        while True:
            page = await store.messages(query, **options)
            rows.extend(page)
            size += sum(len(item.observation.message.text.encode("utf-8")) for item in page)
            if len(rows) > 5000 or size > 20 * 1024 * 1024:
                raise ValueError(
                    "La exportación supera 5.000 registros o 20 MB. Acotá los filtros."
                )
            if len(page) < query.limit:
                break
            query = replace(query, before=page[-1].id)
        more = False
    else:
        rows = await store.messages(query, **options)
        more = len(rows) > 50
        rows = rows[:50]
    reviews = await store.alert_reviews([alert_key(item) for item in rows])
    sources = {item.id: item.label or item.id for item in config.sources}
    records = []
    for item in rows:
        message = item.observation.message
        matches = item.observation.matches
        confirmed = [match for match in matches if match.confirmed]
        records.append(
            {
                "id": item.id,
                "source_id": item.source_id,
                "source": sources.get(item.source_id, item.source_id),
                "kind": message.kind.value,
                "title": message.resource_title or publication_title(message) or "Sin título",
                "author": message.author or "Sin autor",
                "text": message.text,
                "captured": message.captured_at.isoformat(),
                "published": message.published_at.isoformat() if message.published_at else "",
                "url": message.url or "",
                "resource": message.resource_id,
                "terms": list(dict.fromkeys(match.canonical or match.term for match in confirmed)),
                "approximate_terms": list(
                    dict.fromkeys(
                        match.canonical or match.term for match in matches if not match.confirmed
                    )
                ),
                "severity": next(
                    (
                        value
                        for value in ("critical", "important", "info")
                        if any(match.severity == value for match in confirmed)
                    ),
                    "",
                ),
                "review": reviews.get(alert_key(item), "open") if matches else "none",
                "tone": message_tone(message.text),
            }
        )
    return {
        "rows": records,
        "has_more": more,
        "next_before": rows[-1].id if more else None,
        "snapshot": snapshot.isoformat(),
    }
