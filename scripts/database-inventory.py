"""Read an existing SQLite file without creating or modifying it."""

import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


def inventory(path):
    path = Path(path).resolve(strict=True)
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("messages", "message_sources", "alerts", "executions", "events")
                  if table in tables}
        dates = db.execute("SELECT min(captured),max(captured) FROM message_sources").fetchone()
        kinds = db.execute("SELECT json_extract(metadata,'$.kind'),count(*) "
                           "FROM message_sources GROUP BY 1").fetchall()
        reusable = db.execute("PRAGMA freelist_count").fetchone()[0] * db.execute(
            "PRAGMA page_size").fetchone()[0]
    sizes = {name: file.stat().st_size if file.exists() else 0 for name, file in (
        ("database_bytes", path), ("wal_bytes", Path(str(path) + "-wal")),
        ("shm_bytes", Path(str(path) + "-shm")))}
    return {"path": str(path), "checked_at": datetime.now(UTC).isoformat(), "counts": counts,
            "oldest": dates[0], "newest": dates[1], "kinds": dict(kinds),
            "reusable_bytes": reusable, "disk_free_bytes": shutil.disk_usage(path.parent).free,
            "total_file_bytes": sum(sizes.values()), **sizes}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python scripts/database-inventory.py "RUTA_COMPLETA.sqlite"')
    print(json.dumps(inventory(sys.argv[1]), ensure_ascii=True, indent=2))
