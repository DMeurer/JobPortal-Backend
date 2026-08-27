"""Materialize per-company per-date statistics

Revision ID: d5a9c71e3f82
Revises: c3f8d2a15b47
Create Date: 2026-08-27 09:25:00.000000

The statistics were recomputed from every insert row on each request. That
history is immutable - yesterday's counts cannot change - so it is computed once
here and refreshed after each scrape.

Note the include_hidden dimension. The numbers are NOT permission-independent:
`companies` has a unique index on (name, hidden), so one name can be two rows,
and the API merges them by name. An admin therefore sees the hidden and visible
halves combined while a public key sees only the visible half, and those are
different numbers for the same (name, date). Summing per-company rows at query
time would not reproduce this, because the merged entity's "previous scrape
date" is drawn from the union of both halves' dates and can differ from either
one's. Both scopes are materialized instead, which is exact and only doubles a
very small table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5a9c71e3f82'
down_revision = 'c3f8d2a15b47'
branch_labels = None
depends_on = None


STATISTICS_VIEW_SQL = """
CREATE MATERIALIZED VIEW company_date_statistics AS
WITH scopes(include_hidden) AS (
    VALUES (true), (false)
),
company_key AS (
    SELECT
        s.include_hidden,
        c.id AS company_id,
        min(c.id) OVER (PARTITION BY s.include_hidden, c.name) AS name_key,
        c.name AS company_name
    FROM scopes s
    JOIN companies c
      ON (s.include_hidden OR c.hidden = false)
),
presence AS (
    SELECT DISTINCT
        ck.include_hidden,
        ck.name_key,
        i.scrape_date,
        i.job_id
    FROM inserts i
    JOIN jobs        j  ON i.job_id     = j.id
    JOIN company_key ck ON j.company_id = ck.company_id
),
day AS (
    SELECT
        include_hidden,
        name_key,
        scrape_date,
        LAG(scrape_date) OVER (
            PARTITION BY include_hidden, name_key ORDER BY scrape_date
        ) AS prev_date
    FROM (
        SELECT DISTINCT include_hidden, name_key, scrape_date FROM presence
    ) d
),
agg AS (
    SELECT
        d.include_hidden,
        d.name_key,
        d.scrape_date,
        count(*)                                 AS open_positions,
        count(*) FILTER (WHERE p.job_id IS NULL) AS newly_added
    FROM day d
    JOIN presence c
      ON c.include_hidden = d.include_hidden
     AND c.name_key       = d.name_key
     AND c.scrape_date    = d.scrape_date
    LEFT JOIN presence p
      ON p.include_hidden = d.include_hidden
     AND p.name_key       = d.name_key
     AND p.scrape_date    = d.prev_date
     AND p.job_id         = c.job_id
    GROUP BY d.include_hidden, d.name_key, d.scrape_date
),
final AS (
    SELECT
        include_hidden,
        name_key,
        scrape_date,
        open_positions,
        newly_added,
        -- removed = |P \\ D| = |P| - |P n D| = open(prev) - open(d) + new(d)
        COALESCE(
            LAG(open_positions) OVER (
                PARTITION BY include_hidden, name_key ORDER BY scrape_date
            ) - open_positions + newly_added,
            0
        ) AS removed
    FROM agg
),
names AS (
    SELECT DISTINCT include_hidden, name_key, company_name FROM company_key
)
SELECT
    n.include_hidden,
    n.company_name,
    f.scrape_date,
    f.open_positions,
    f.newly_added,
    f.removed
FROM final f
JOIN names n
  ON n.include_hidden = f.include_hidden
 AND n.name_key       = f.name_key
"""


def upgrade() -> None:
    op.execute(STATISTICS_VIEW_SQL)

    # Unique index is required for REFRESH ... CONCURRENTLY, which keeps the view
    # readable while it rebuilds.
    op.execute("""
        CREATE UNIQUE INDEX ix_company_date_statistics_key
            ON company_date_statistics (include_hidden, company_name, scrape_date)
    """)
    # Serves the common access pattern: one scope, a date window, newest first.
    op.execute("""
        CREATE INDEX ix_company_date_statistics_scope_date
            ON company_date_statistics (include_hidden, scrape_date DESC)
    """)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS company_date_statistics")
