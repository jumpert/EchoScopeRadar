"""SQLite capacity information and bounded, previewed retention maintenance."""

import asyncio
import shutil
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from echoscope.domain.models import utcnow


async def database_stats(store):
    async with store.reader() as conn:
        counts = {}
        for table in (
            "messages",
            "message_versions",
            "message_sources",
            "alerts",
            "executions",
            "events",
        ):
            counts[table] = await conn.scalar(text(f"SELECT count(*) FROM {table}"))
        oldest, newest = (
            await conn.execute(text("SELECT min(captured),max(captured) FROM message_sources"))
        ).one()
        kinds = dict(
            (
                await conn.execute(
                    text("""SELECT json_extract(metadata,'$.kind'),count(*)
            FROM message_sources GROUP BY 1""")
                )
            ).all()
        )
        pages = await conn.scalar(text("PRAGMA page_count"))
        page_size = await conn.scalar(text("PRAGMA page_size"))
        free_pages = await conn.scalar(text("PRAGMA freelist_count"))

    def sizes():
        files = {}
        for name, suffix in (("database_bytes", ""), ("wal_bytes", "-wal"), ("shm_bytes", "-shm")):
            path = Path(str(store.path) + suffix)
            try:
                files[name] = path.stat().st_size
            except FileNotFoundError:
                files[name] = 0
        usage = shutil.disk_usage(store.path.parent)
        return files | {"disk_free_bytes": usage.free, "disk_total_bytes": usage.total}

    files = await asyncio.to_thread(sizes)
    return {
        "engine": "SQLite",
        "path": str(store.path),
        "counts": counts,
        "kinds": kinds,
        "oldest": oldest,
        "newest": newest,
        "checked_at": utcnow().isoformat(),
        "logical_bytes": pages * page_size,
        "reusable_bytes": free_pages * page_size,
        "total_file_bytes": sum(files[key] for key in ("database_bytes", "wal_bytes", "shm_bytes")),
        **files,
    }


def selection(only_unmatched):
    return """s.captured < :cutoff AND s.id <= :max_id""" + (
        " AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.observation=s.id)"
        if only_unmatched
        else ""
    )


async def cleanup_plan(store, cutoff, only_unmatched):
    async with store.reader() as conn:
        max_id = await conn.scalar(text("SELECT coalesce(max(id),0) FROM message_sources"))
        params = {"cutoff": cutoff, "max_id": max_id}
        count = await conn.scalar(
            text("SELECT count(*) FROM message_sources s WHERE " + selection(only_unmatched)),
            params,
        )
        alerts = await conn.scalar(
            text(
                "SELECT count(*) FROM alerts WHERE observation IN ("
                "SELECT s.id FROM message_sources s WHERE " + selection(only_unmatched) + ")"
            ),
            params,
        )
        technical_events = await conn.scalar(
            text("SELECT count(*) FROM events WHERE observation IS NULL AND at<:cutoff"), params
        )
    return {
        "cutoff": cutoff,
        "max_id": max_id,
        "only_unmatched": only_unmatched,
        "captures": count,
        "alerts": alerts,
        "technical_events": technical_events,
    }


async def prune_orphans(conn):
    await conn.execute(
        text("""DELETE FROM alert_reviews WHERE item NOT IN (
        SELECT radar_alert_key(s.job,m.origin,m.external_id,v.body)
        FROM message_sources s JOIN message_versions v ON v.id=s.version
        JOIN messages m ON m.id=v.message)""")
    )
    await conn.execute(
        text("""DELETE FROM message_versions WHERE NOT EXISTS
        (SELECT 1 FROM message_sources WHERE version=message_versions.id)""")
    )
    await conn.execute(
        text("""DELETE FROM messages WHERE NOT EXISTS
        (SELECT 1 FROM message_versions WHERE message=messages.id)""")
    )


async def cleanup_before(store, plan):
    async with store.transaction() as conn:
        result = await conn.execute(
            text(
                "DELETE FROM message_sources WHERE id IN ("
                "SELECT s.id FROM message_sources s WHERE "
                + selection(plan["only_unmatched"])
                + ")"
            ),
            {"cutoff": plan["cutoff"], "max_id": plan["max_id"]},
        )
        removed = result.rowcount
        await prune_orphans(conn)
        # Keep technical events associated with surviving observations and executions.
        events = await conn.execute(
            text("DELETE FROM events WHERE observation IS NULL AND at<:cutoff"),
            {"cutoff": plan["cutoff"]},
        )
        executions = await conn.execute(
            text("""DELETE FROM executions WHERE ended<:cutoff
            AND NOT EXISTS (SELECT 1 FROM events WHERE execution=executions.id)"""),
            {"cutoff": plan["cutoff"]},
        )
        await store._audit(conn, "OldDataCleaned", f"before={plan['cutoff']};captures={removed}")
    compacted = False
    try:
        async with store._writer, store.engine.connect() as conn:
            conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
            await conn.exec_driver_sql("VACUUM")
            checkpoint = (await conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")).one()
            compacted = checkpoint[0] == 0
    except (SQLAlchemyError, OSError):
        # The deletion is already committed. Another reader may postpone compaction.
        compacted = False
    return {
        "removed": removed,
        "events_removed": events.rowcount,
        "executions_removed": executions.rowcount,
        "compacted": compacted,
    }
