from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE INDEX captures_by_date ON message_sources(captured,id)")
    op.execute("""CREATE VIEW capturas AS
        SELECT s.id, s.source AS fuente, s.job AS tarea,
            s.captured AS capturado_utc, s.expires AS vence_utc,
            json_extract(s.metadata,'$.kind') AS tipo,
            coalesce(json_extract(s.metadata,'$.resource_title'),
                     json_extract(s.metadata,'$.title')) AS titulo,
            json_extract(s.metadata,'$.author') AS autor,
            v.body AS texto, json_extract(s.metadata,'$.url') AS enlace,
            json_extract(s.metadata,'$.resource_id') AS publicacion,
            (SELECT count(*) FROM alerts a WHERE a.observation=s.id) AS coincidencias
        FROM message_sources s JOIN message_versions v ON v.id=s.version""")


def downgrade():
    op.execute("DROP VIEW capturas")
    op.execute("DROP INDEX captures_by_date")
