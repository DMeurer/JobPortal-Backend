"""Track when the statistics view was last refreshed

Revision ID: e8b2f6c04d19
Revises: d5a9c71e3f82
Create Date: 2026-08-27 11:30:00.000000

Health checks need to know whether company_date_statistics is behind the data it
summarises. Postgres does not expose a materialized view's last refresh time,
and comparing max(scrape_date) between the view and `inserts` is not sufficient:
a re-run that adds rows to a date already present would leave the maximum
unchanged while still making the view wrong.

Recording the refresh timestamp and comparing it against max(inserts.created_at)
detects every case.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e8b2f6c04d19'
down_revision = 'd5a9c71e3f82'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `id boolean PRIMARY KEY CHECK (id)` constrains the table to a single row.
    op.execute("""
        CREATE TABLE statistics_refresh (
            id           boolean     PRIMARY KEY DEFAULT true,
            refreshed_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT statistics_refresh_single_row CHECK (id)
        )
    """)
    # Seed it, since the view is populated by its own migration.
    op.execute("INSERT INTO statistics_refresh (id) VALUES (true)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS statistics_refresh")
