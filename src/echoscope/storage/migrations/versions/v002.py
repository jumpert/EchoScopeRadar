from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE alerts ADD COLUMN confirmed INTEGER NOT NULL DEFAULT 1")
    op.execute("ALTER TABLE match_occurrences ADD COLUMN method TEXT NOT NULL DEFAULT 'exact'")
    op.execute("CREATE TABLE desktop_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def downgrade():
    op.execute("DELETE FROM alerts WHERE confirmed=0")
    op.execute("DROP TABLE desktop_settings")
    op.execute("ALTER TABLE match_occurrences DROP COLUMN method")
    op.execute("ALTER TABLE alerts DROP COLUMN confirmed")
