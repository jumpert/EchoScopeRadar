from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE alert_reviews (
        item TEXT PRIMARY KEY,
        state TEXT NOT NULL CHECK (state IN ('verified', 'threat', 'dismissed')),
        changed TEXT NOT NULL
    )""")


def downgrade():
    op.execute("DROP TABLE alert_reviews")
