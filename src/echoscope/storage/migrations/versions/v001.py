from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = {
    "configuration": "id INTEGER PRIMARY KEY CHECK(id = 1), payload TEXT NOT NULL",
    "runtime": """job TEXT PRIMARY KEY, enabled INTEGER NOT NULL, paused INTEGER NOT NULL,
        interval_s REAL NOT NULL, state TEXT NOT NULL, availability TEXT, detail TEXT,
        last_at TEXT, next_at TEXT, checkpoint TEXT, coverage_gap INTEGER NOT NULL DEFAULT 0""",
    "executions": """id INTEGER PRIMARY KEY, job TEXT NOT NULL, started TEXT NOT NULL,
        ended TEXT, outcome TEXT NOT NULL""",
    "messages": """id INTEGER PRIMARY KEY, origin TEXT NOT NULL, external_id TEXT NOT NULL,
        UNIQUE(origin, external_id)""",
    "message_versions": """id INTEGER PRIMARY KEY, message INTEGER NOT NULL REFERENCES messages(id),
        digest TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(message, digest)""",
    "message_sources": """id INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT NOT NULL,
        source TEXT NOT NULL, version INTEGER NOT NULL REFERENCES message_versions(id),
        metadata TEXT NOT NULL, captured TEXT NOT NULL, expires TEXT NOT NULL,
        UNIQUE(job, source, version)""",
    "rule_versions": "revision TEXT PRIMARY KEY, rule_id TEXT NOT NULL, definition TEXT NOT NULL",
    "alerts": """id INTEGER PRIMARY KEY, observation INTEGER NOT NULL REFERENCES message_sources(id)
        ON DELETE CASCADE, rule TEXT NOT NULL REFERENCES rule_versions(revision),
        severity TEXT NOT NULL, priority INTEGER NOT NULL, UNIQUE(observation, rule)""",
    "match_occurrences": """alert INTEGER NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
        start INTEGER NOT NULL, end INTEGER NOT NULL, term TEXT NOT NULL,
        PRIMARY KEY(alert, start, end)""",
    "events": """id INTEGER PRIMARY KEY AUTOINCREMENT, version INTEGER NOT NULL DEFAULT 1,
        at TEXT NOT NULL, kind TEXT NOT NULL, job TEXT, execution INTEGER, detail TEXT,
        observation INTEGER REFERENCES message_sources(id) ON DELETE CASCADE""",
    "audit_events": "id INTEGER PRIMARY KEY, at TEXT NOT NULL, action TEXT NOT NULL, target TEXT",
}


def upgrade():
    for name, ddl in TABLES.items():
        op.execute(f"CREATE TABLE {name} ({ddl})")
    op.execute("CREATE INDEX history_by_job ON message_sources(job, id DESC)")
    op.execute("CREATE INDEX history_by_source ON message_sources(source, id DESC)")
    op.execute("CREATE INDEX retention ON message_sources(expires)")
    op.execute("CREATE INDEX events_by_observation ON events(observation)")
    op.execute("CREATE INDEX executions_by_job ON executions(job, id DESC)")


def downgrade():
    for name in reversed(TABLES):
        op.execute(f"DROP TABLE {name}")
