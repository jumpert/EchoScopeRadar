import asyncio
import json
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

from alembic import command
from alembic.config import Config
from filelock import FileLock, Timeout
from sqlalchemy import URL, event, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from echoscope.application.config import Configuration
from echoscope.application.ports import JobSnapshot, StorageUnavailable
from echoscope.domain.identity import alert_identity
from echoscope.domain.models import (
    Availability,
    HistoryQuery,
    Kind,
    Match,
    Message,
    Observation,
    Result,
    Severity,
    State,
    category,
    utcnow,
)
from echoscope.domain.tone import message_tone
from echoscope.settings import runtime_settings


def _date(value):
    return datetime.fromisoformat(value) if value else None


def _iso(value):
    return value.astimezone(UTC).isoformat() if value is not None else None


def _source_identity(source):
    return (
        source.id,
        source.type,
        source.params,
        source.credential,
        source.tracking,
        source.initial_days,
        source.follow_days,
        source.comment_credential,
    )


def _migrate(path: Path):
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    url = URL.create("sqlite", database=str(path)).render_as_string(hide_password=False)
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


class Store:
    def __init__(self, path: Path):
        self.path = path.resolve()
        settings = runtime_settings()
        self.engine = create_async_engine(
            URL.create("sqlite+aiosqlite", database=str(self.path)),
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=0,
            pool_timeout=settings.database_pool_timeout_s,
            hide_parameters=True,
        )
        self._lock = FileLock(str(self.path) + ".writer.lock", timeout=0, thread_local=False)
        self._writer = asyncio.Lock()
        self.match_methods = True

        @event.listens_for(self.engine.sync_engine, "connect")
        def initialize(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
            cursor.execute("PRAGMA secure_delete=ON")
            cursor.close()
            connection.create_function(
                "fold", 1, lambda value: value.casefold(), deterministic=True
            )
            connection.create_function("radar_category", 2, category, deterministic=True)
            connection.create_function("radar_tone", 1, message_tone, deterministic=True)
            connection.create_function("radar_alert_key", 4, alert_identity, deterministic=True)

    @asynccontextmanager
    async def opened(self, *, write=False):
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._lock.acquire()
            except Timeout:
                raise ValueError("Ya hay un motor u otro escritor usando esta base") from None
        try:
            if write:
                await asyncio.to_thread(_migrate, self.path)
                self.match_methods = True
                async with self.engine.connect() as connection:
                    await connection.exec_driver_sql("PRAGMA journal_mode=WAL")
            elif not self.path.is_file():
                raise ValueError("La base aún no existe. Aplicá una configuración primero.")
            else:
                async with self.engine.connect() as connection:
                    columns = await connection.exec_driver_sql("PRAGMA table_info(alerts)")
                    self.match_methods = any(row[1] == "confirmed" for row in columns)
            yield self
        finally:
            try:
                await self.engine.dispose()
            finally:
                if write:
                    self._lock.release()

    @asynccontextmanager
    async def transaction(self):
        if not self._lock.is_locked:
            raise RuntimeError("La operación requiere el bloqueo de escritura")
        try:
            async with self._writer, self.engine.begin() as conn:
                yield conn
        except DBAPIError:
            raise StorageUnavailable("El almacenamiento está temporalmente inaccesible") from None

    @asynccontextmanager
    async def reader(self):
        try:
            async with self.engine.connect() as conn:
                yield conn
        except DBAPIError:
            raise StorageUnavailable("El almacenamiento está temporalmente inaccesible") from None

    async def configuration(self, conn=None):
        if conn is None:
            async with self.engine.connect() as reader:
                return await self.configuration(reader)
        payload = await conn.scalar(text("SELECT payload FROM configuration WHERE id=1"))
        return Configuration.model_validate_json(payload) if payload else None

    async def configure(self, config: Configuration):
        async with self.transaction() as conn:
            previous = await self.configuration(conn)
            sources = {source.id: source for source in config.sources}
            old_sources = {source.id: source for source in previous.sources} if previous else {}
            old_jobs = {job.id: job for job in previous.jobs} if previous else {}
            for job in config.jobs:
                source = sources[job.source]
                old = old_jobs.get(job.id)
                old_source = old_sources.get(old.source) if old else None
                press_upgrade = (
                    old_source is not None
                    and old_source.type == "syndication"
                    and source.type == "press_feed"
                    and _source_identity(source.model_copy(update={"type": "syndication"}))
                    == _source_identity(old_source)
                )
                changed = old_source is None or (
                    not press_upgrade and _source_identity(source) != _source_identity(old_source)
                )
                if changed:
                    await conn.execute(text("DELETE FROM runtime WHERE job=:job"), {"job": job.id})
                state = State.SCHEDULED if job.enabled else State.DISABLED
                await conn.execute(
                    text("""
                    INSERT INTO runtime(job, enabled, paused, interval_s, state)
                    VALUES(:job,:enabled,0,:interval,:state) ON CONFLICT(job) DO NOTHING
                """),
                    {
                        "job": job.id,
                        "enabled": job.enabled,
                        "interval": job.interval_s,
                        "state": state,
                    },
                )
                if press_upgrade:
                    await conn.execute(
                        text("UPDATE runtime SET checkpoint=NULL WHERE job=:job"), {"job": job.id}
                    )
                if old and not changed and old.interval_s != job.interval_s:
                    await conn.execute(
                        text("UPDATE runtime SET interval_s=:i,next_at=NULL WHERE job=:j"),
                        {"i": job.interval_s, "j": job.id},
                    )
                if old and not changed and old.enabled != job.enabled:
                    await conn.execute(
                        text("""UPDATE runtime SET enabled=:enabled, paused=0,
                        state=:state, detail=NULL, next_at=NULL WHERE job=:job"""),
                        {"enabled": job.enabled, "state": state, "job": job.id},
                    )
                if old and not changed and (old.relevant_only or job.relevant_only):
                    old_rules = previous.rule_sets.get(old.rule_set)
                    if (
                        old.relevant_only != job.relevant_only
                        or old_rules != config.rule_sets[job.rule_set]
                    ):
                        await conn.execute(
                            text("UPDATE runtime SET checkpoint=NULL WHERE job=:job"),
                            {"job": job.id},
                        )
            removed = set(old_jobs) - {job.id for job in config.jobs}
            for job_id in removed:
                await conn.execute(text("DELETE FROM runtime WHERE job=:job"), {"job": job_id})
            for source in config.sources:
                if (
                    source.id in old_sources
                    and source.retention_days < old_sources[source.id].retention_days
                ):
                    rows = (
                        await conn.execute(
                            text("""SELECT id, captured, expires FROM message_sources
                                                       WHERE source=:source"""),
                            {"source": source.id},
                        )
                    ).all()
                    updates = [
                        {
                            "id": row.id,
                            "expires": min(
                                row.expires,
                                _iso(_date(row.captured) + timedelta(days=source.retention_days)),
                            ),
                        }
                        for row in rows
                    ]
                    if updates:
                        await conn.execute(
                            text("UPDATE message_sources SET expires=:expires WHERE id=:id"),
                            updates,
                        )
            await conn.execute(
                text("""INSERT INTO configuration VALUES(1,:payload)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload"""),
                {"payload": config.model_dump_json()},
            )
            rules = [spec.compile() for specs in config.rule_sets.values() for spec in specs]
            if rules:
                await conn.execute(
                    text("""INSERT INTO rule_versions VALUES(:revision,:id,:definition)
                    ON CONFLICT(revision) DO NOTHING"""),
                    [
                        {
                            "revision": rule.revision,
                            "id": rule.id,
                            "definition": json.dumps(asdict(rule)),
                        }
                        for rule in rules
                    ],
                )
            await self._audit(conn, "ConfigApplied")

    async def snapshots(self) -> dict[str, JobSnapshot]:
        async with self.engine.connect() as conn:
            config = await self.configuration(conn)
            rows = (await conn.execute(text("SELECT * FROM runtime"))).mappings().all()
        if config is None:
            return {}
        sources = {source.id: source for source in config.sources}
        jobs = {job.id: job for job in config.jobs}
        return {
            row.job: JobSnapshot(
                jobs[row.job].model_copy(
                    update={"enabled": bool(row.enabled), "interval_s": row.interval_s}
                ),
                sources[jobs[row.job].source],
                State(row.state),
                bool(row.paused),
                Availability(row.availability) if row.availability else None,
                row.detail,
                _date(row.last_at),
                _date(row.next_at),
                row.checkpoint,
                bool(row.coverage_gap),
            )
            for row in rows
            if row.job in jobs
        }

    async def recover(self):
        async with self.transaction() as conn:
            await conn.execute(
                text("UPDATE executions SET ended=:now,outcome='INTERRUPTED' WHERE ended IS NULL"),
                {"now": _iso(utcnow())},
            )
            await conn.execute(
                text("""UPDATE runtime SET state='SCHEDULED'
                WHERE enabled=1 AND paused=0 AND state='RUNNING'""")
            )

    async def save(self, snapshot: JobSnapshot, execution_id=None, *, action=None):
        async with self.transaction() as conn:
            await self._save(conn, snapshot)
            await self._event(
                conn, "JobStateChanged", snapshot.job.id, execution_id, snapshot.state
            )
            if action:
                await self._audit(conn, action, snapshot.job.id)

    async def _save(self, conn, snapshot: JobSnapshot):
        await conn.execute(
            text("""UPDATE runtime SET enabled=:enabled,paused=:paused,interval_s=:interval,
            state=:state,availability=:availability,detail=:detail,last_at=:last_at,next_at=:next_at,
            checkpoint=:checkpoint,coverage_gap=:gap WHERE job=:job"""),
            {
                "job": snapshot.job.id,
                "enabled": snapshot.job.enabled,
                "paused": snapshot.paused,
                "interval": snapshot.job.interval_s,
                "state": snapshot.state,
                "availability": snapshot.availability,
                "detail": snapshot.detail,
                "last_at": _iso(snapshot.last_at),
                "next_at": _iso(snapshot.next_at),
                "checkpoint": snapshot.checkpoint,
                "gap": snapshot.coverage_gap,
            },
        )

    async def start(self, snapshot: JobSnapshot) -> int:
        async with self.transaction() as conn:
            execution = await conn.scalar(
                text("""INSERT INTO executions(job,started,outcome)
                VALUES(:job,:at,'RUNNING') RETURNING id"""),
                {"job": snapshot.job.id, "at": _iso(snapshot.last_at)},
            )
            await self._save(conn, snapshot)
            await self._event(conn, "JobStateChanged", snapshot.job.id, execution, snapshot.state)
            return execution

    async def finish(self, snapshot: JobSnapshot, execution_id: int, outcome: str):
        async with self.transaction() as conn:
            await self._save(conn, snapshot)
            await conn.execute(
                text("UPDATE executions SET ended=:at,outcome=:outcome WHERE id=:id"),
                {"id": execution_id, "outcome": outcome, "at": _iso(utcnow())},
            )
            await self._event(conn, "ExecutionFinished", snapshot.job.id, execution_id, outcome)

    async def apply(self, snapshot, execution_id, observations, persistent, *, coverage_gap=False):
        async with self.transaction() as conn:
            await self._save(conn, snapshot)
            added = 0
            if persistent and observations:
                added = await self._observe(conn, snapshot, execution_id, observations)
            if added:
                await self._event(
                    conn, "MessagesIngested", snapshot.job.id, execution_id, str(added)
                )
            if coverage_gap:
                await self._event(conn, "CoverageGapDetected", snapshot.job.id, execution_id)
            return added

    async def _observe(self, conn, snapshot, execution_id, observations):
        payload, rules_by_message = {}, {}
        for item in observations:
            message = item.message
            digest = sha256(message.text.encode()).hexdigest()
            key = message.origin, message.external_id, digest
            if key in payload:
                continue
            metadata = asdict(message)
            metadata.pop("text")
            metadata["published_at"] = _iso(message.published_at)
            metadata["captured_at"] = _iso(message.captured_at)
            payload[key] = {
                "origin": message.origin,
                "external": message.external_id,
                "digest": digest,
                "body": message.text,
                "metadata": metadata,
                "captured": metadata["captured_at"],
                "expires": _iso(
                    message.captured_at + timedelta(days=snapshot.source.retention_days)
                ),
            }
            if item.matches:
                rules_by_message[key] = item.matches
        args = {
            "batch": json.dumps(list(payload.values()), ensure_ascii=False),
            "job": snapshot.job.id,
            "source": snapshot.source.id,
        }
        await conn.execute(
            text("""INSERT OR IGNORE INTO messages(origin,external_id)
            SELECT entry.value->>'origin', entry.value->>'external' FROM json_each(:batch) entry"""),
            args,
        )
        await conn.execute(
            text("""INSERT OR IGNORE INTO message_versions(message,digest,body)
            SELECT m.id, entry.value->>'digest', entry.value->>'body' FROM json_each(:batch) entry
            CROSS JOIN messages m ON m.origin=entry.value->>'origin' AND m.external_id=entry.value->>'external'"""),
            args,
        )
        # SQLite can otherwise loop over every stored observation and scan the JSON for each one.
        versions = """FROM json_each(:batch) entry
            CROSS JOIN messages m ON m.origin=entry.value->>'origin' AND m.external_id=entry.value->>'external'
            CROSS JOIN message_versions v ON v.message=m.id AND v.digest=entry.value->>'digest'"""
        inserted = (
            await conn.execute(
                text(f"""INSERT OR IGNORE INTO message_sources
            (job,source,version,metadata,captured,expires)
            SELECT :job,:source,v.id,entry.value->'metadata',entry.value->>'captured',entry.value->>'expires'
            {versions} ORDER BY entry.key RETURNING id"""),
                args,
            )
        ).all()
        if any(item["metadata"].get("resource_title") for item in payload.values()):
            await conn.execute(
                text(f"""UPDATE message_sources AS s SET metadata=json_set(s.metadata, '$.resource_title', t.title)
                FROM (SELECT v.id AS version, entry.value->>'$.metadata.resource_title' AS title {versions}) AS t
                WHERE s.job=:job AND s.source=:source AND s.version=t.version AND t.title IS NOT NULL
                  AND json_extract(s.metadata, '$.resource_title') IS NOT t.title"""),
                args,
            )
        if any(item["metadata"].get("parent_id") for item in payload.values()):
            await conn.execute(
                text(f"""UPDATE message_sources AS s
                SET metadata=json_set(s.metadata, '$.parent_id', t.parent)
                FROM (SELECT v.id AS version, entry.value->>'$.metadata.parent_id' AS parent {versions}) AS t
                WHERE s.job=:job AND s.source=:source AND s.version=t.version
                  AND t.parent IS NOT NULL"""),
                args,
            )
        if rules_by_message:
            rows = (
                await conn.execute(
                    text(f"""SELECT m.origin,m.external_id,v.digest,s.id {versions}
                CROSS JOIN message_sources s ON s.version=v.id AND s.job=:job AND s.source=:source"""),
                    args,
                )
            ).all()
            matches = {}
            for origin, external_id, digest, observation in rows:
                for match in rules_by_message.get((origin, external_id, digest), ()):
                    matches.setdefault((observation, match.rule_revision), []).append(match)
            await self._save_alerts(conn, snapshot.job.id, execution_id, matches)
        return len(inserted)

    async def _save_alerts(self, conn, job_id, execution_id, matches):
        payload = [
            {
                "observation": observation,
                "rule": rule,
                "severity": items[0].severity,
                "priority": items[0].priority,
                "confirmed": int(any(item.confirmed for item in items)),
            }
            for (observation, rule), items in matches.items()
        ]
        alerts = (
            await conn.execute(
                text("""INSERT OR IGNORE INTO alerts(observation,rule,severity,priority,confirmed)
            SELECT value->>'observation',value->>'rule',value->>'severity',value->>'priority',value->>'confirmed'
            FROM json_each(:payload) RETURNING id,observation,rule,confirmed"""),
                {"payload": json.dumps(payload)},
            )
        ).all()
        if not alerts:
            return
        await conn.execute(
            text("INSERT INTO match_occurrences VALUES(:alert,:start,:end,:term,:method)"),
            [
                {
                    "alert": alert,
                    "start": match.start,
                    "end": match.end,
                    "term": match.term,
                    "method": match.method,
                }
                for alert, observation, rule, _ in alerts
                for match in matches[observation, rule]
            ],
        )
        now = _iso(utcnow())
        events = [
            {
                "at": now,
                "job": job_id,
                "execution": execution_id,
                "detail": str(alert),
                "observation": observation,
            }
            for alert, observation, _, confirmed in alerts
            if confirmed
        ]
        if events:
            await conn.execute(
                text("""INSERT INTO events(at,kind,job,execution,detail,observation)
                VALUES(:at,'AlertRaised',:job,:execution,:detail,:observation)"""),
                events,
            )

    async def _event(self, conn, kind, job, execution=None, detail=None, observation=None):
        await conn.execute(
            text("""INSERT INTO events(at,kind,job,execution,detail,observation)
            VALUES(:at,:kind,:job,:execution,:detail,:observation)"""),
            {
                "at": _iso(utcnow()),
                "kind": kind,
                "job": job,
                "execution": execution,
                "detail": detail,
                "observation": observation,
            },
        )

    async def coverage_gap(self, snapshot, execution):
        async with self.transaction() as conn:
            await self._save(conn, snapshot)
            await self._event(conn, "CoverageGapDetected", snapshot.job.id, execution)

    async def _audit(self, conn, action, target=None):
        await conn.execute(
            text("INSERT INTO audit_events(at,action,target) VALUES(:at,:action,:target)"),
            {"at": _iso(utcnow()), "action": action, "target": target},
        )

    async def events(self, after=0, limit=200):
        async with self.reader() as conn:
            return (
                (
                    await conn.execute(
                        text("SELECT * FROM events WHERE id>:after ORDER BY id LIMIT :limit"),
                        {"after": after, "limit": limit},
                    )
                )
                .mappings()
                .all()
            )

    async def executions(self, job=None):
        async with self.reader() as conn:
            return (
                (
                    await conn.execute(
                        text("""SELECT * FROM executions WHERE (:job IS NULL OR job=:job)
                ORDER BY id DESC LIMIT 200"""),
                        {"job": job},
                    )
                )
                .mappings()
                .all()
            )

    async def messages(self, query: HistoryQuery, *, review_state=None, tone=None) -> list[Result]:
        conditions = ["s.expires > :now"]
        confirmed = " AND a.confirmed=1" if self.match_methods else ""
        if query.matches_only:
            conditions.append(f"EXISTS(SELECT 1 FROM alerts a WHERE a.observation=s.id{confirmed})")
        if query.review_only:
            if not self.match_methods:
                return []
            conditions.append("""EXISTS(SELECT 1 FROM alerts a JOIN match_occurrences m ON m.alert=a.id
                               WHERE a.observation=s.id AND m.method='review')""")
        arguments = {"now": _iso(utcnow()), "limit": min(500, max(1, query.limit))}
        if review_state:
            conditions.append("""coalesce((SELECT r.state FROM alert_reviews r WHERE r.item =
                radar_alert_key(s.job,json_extract(s.metadata,'$.origin'),json_extract(s.metadata,'$.external_id'),v.body)), 'open')=:review_state""")
            arguments["review_state"] = review_state
        if tone:
            conditions.append("radar_tone(v.body)=:tone")
            arguments["tone"] = tone
        for name, clause, value in (
            ("job", "s.job=:job", query.job_id),
            ("source", "s.source=:source", query.source_id),
            (
                "search",
                "instr(fold(v.body), :search)>0",
                query.text.casefold() if query.text else None,
            ),
            (
                "severity",
                f"EXISTS(SELECT 1 FROM alerts a WHERE a.observation=s.id AND a.severity=:severity{confirmed})",
                query.severity,
            ),
            ("since", "s.captured>=:since", _iso(query.since)),
            ("until", "s.captured<=:until", _iso(query.until)),
            ("before", "s.id<:before", query.before),
            ("after", "s.id>:after", query.after),
            ("kind", "json_extract(s.metadata, '$.kind')=:kind", query.kind),
            (
                "exclude_kind",
                "json_extract(s.metadata, '$.kind')<>:exclude_kind",
                query.exclude_kind,
            ),
            (
                "category",
                "radar_category(json_extract(s.metadata, '$.kind'),json_extract(s.metadata, '$.origin'))=:category",
                query.category,
            ),
        ):
            if value is not None:
                conditions.append(clause)
                arguments[name] = value
        order = "ASC" if query.after is not None else "DESC"
        method = "m.method" if self.match_methods else "'exact'"
        sql = f"""SELECT s.*,v.body,(
                    SELECT json_group_array(json_array(m.start,m.end,m.term,r.rule_id,a.rule,a.severity,a.priority,
                        {method},CASE WHEN {method}<>'exact' THEN json_extract(r.definition, '$.phrase') END))
                    FROM alerts a JOIN rule_versions r ON r.revision=a.rule
                    JOIN match_occurrences m ON m.alert=a.id WHERE a.observation=s.id
                  ) AS matches
                  FROM message_sources s JOIN message_versions v ON v.id=s.version
                  WHERE {" AND ".join(conditions)} ORDER BY s.id {order} LIMIT :limit"""
        async with self.reader() as conn:
            rows = (await conn.execute(text(sql), arguments)).mappings().all()
        results = []
        for row in rows:
            metadata = json.loads(row.metadata)
            metadata["kind"] = Kind(metadata["kind"])
            for field in ("published_at", "captured_at"):
                metadata[field] = _date(metadata[field])
            occurrences = sorted(
                json.loads(row.matches), key=lambda value: (value[0], value[1], value[3])
            )
            matches = tuple(
                Match(
                    start,
                    end,
                    term,
                    rule_id,
                    revision,
                    Severity(severity),
                    priority,
                    method,
                    canonical if method != "exact" else None,
                )
                for start, end, term, rule_id, revision, severity, priority, method, canonical in occurrences
            )
            results.append(
                Result(
                    row.id,
                    row.job,
                    row.source,
                    Observation(Message(text=row.body, **metadata), matches),
                )
            )
        return results

    async def alert_reviews(self, keys):
        if not keys:
            return {}
        async with self.reader() as conn:
            rows = await conn.execute(
                text(
                    "SELECT item,state FROM alert_reviews WHERE item IN (SELECT value FROM json_each(:items))"
                ),
                {"items": json.dumps(list(keys))},
            )
            return dict(rows.tuples().all())

    async def reviewable_keys(self, keys):
        async with self.reader() as conn:
            result = await conn.execute(
                text("""
                SELECT DISTINCT radar_alert_key(s.job,m.origin,m.external_id,v.body) AS item
                FROM message_sources s
                JOIN message_versions v ON v.id=s.version
                JOIN messages m ON m.id=v.message
                WHERE s.expires>:now
                AND EXISTS (SELECT 1 FROM alerts a WHERE a.observation=s.id)
                AND radar_alert_key(s.job,m.origin,m.external_id,v.body)
                    IN (SELECT value FROM json_each(:items))
            """),
                {"now": _iso(utcnow()), "items": json.dumps(list(keys))},
            )
            return set(result.scalars())

    async def set_alert_reviews(self, keys, state):
        if state not in {"open", "verified", "threat", "dismissed"}:
            raise ValueError("Estado de revisión no válido.")
        async with self.transaction() as conn:
            params = {"items": json.dumps(keys), "state": state, "changed": _iso(utcnow())}
            if state == "open":
                await conn.execute(
                    text(
                        "DELETE FROM alert_reviews WHERE item IN (SELECT value FROM json_each(:items))"
                    ),
                    params,
                )
            else:
                await conn.execute(
                    text("""INSERT INTO alert_reviews(item,state,changed)
                    SELECT value,:state,:changed FROM json_each(:items) WHERE true
                    ON CONFLICT(item) DO UPDATE SET state=excluded.state, changed=excluded.changed"""),
                    params,
                )
            await self._audit(conn, "AlertReviewChanged", state)

    def writer_available(self):
        try:
            with FileLock(str(self.path) + ".writer.lock", timeout=0):
                return True
        except Timeout:
            return False

    async def desktop_setting(self, key):
        async with self.reader() as conn:
            return await conn.scalar(
                text("SELECT value FROM desktop_settings WHERE key=:key"), {"key": key}
            )

    async def set_desktop_setting(self, key, value):
        async with self.transaction() as conn:
            await conn.execute(
                text("""INSERT INTO desktop_settings VALUES(:key,:value)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value"""),
                {"key": key, "value": value},
            )

    async def purge(self, source=None):
        async with self.transaction() as conn:
            if source is None:
                await conn.execute(
                    text("DELETE FROM message_sources WHERE expires<=:now"), {"now": _iso(utcnow())}
                )
            else:
                await conn.execute(
                    text("DELETE FROM message_sources WHERE source=:s"), {"s": source}
                )
                await self._audit(conn, "SourcePurged", source)
            await conn.execute(
                text("""DELETE FROM alert_reviews WHERE item NOT IN (
                SELECT radar_alert_key(s.job,m.origin,m.external_id,v.body)
                FROM message_sources s
                JOIN message_versions v ON v.id=s.version
                JOIN messages m ON m.id=v.message
            )""")
            )
            await conn.execute(
                text("""DELETE FROM message_versions WHERE NOT EXISTS
                (SELECT 1 FROM message_sources WHERE version=message_versions.id)""")
            )
            await conn.execute(
                text("""DELETE FROM messages WHERE NOT EXISTS
                (SELECT 1 FROM message_versions WHERE message=messages.id)""")
            )
        if source is not None:
            async with self._writer, self.engine.connect() as conn:
                with suppress(Exception):
                    await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
