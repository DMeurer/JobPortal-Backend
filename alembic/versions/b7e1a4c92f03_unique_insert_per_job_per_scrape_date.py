"""Enforce one insert per job per scrape date

Revision ID: b7e1a4c92f03
Revises: 8d4c2d09abc1
Create Date: 2026-08-27 08:05:00.000000

JobService.create_insert() queries for an existing (job_id, scrape_date) row and
inserts only if none is found. That is a check-then-act with no constraint
behind it, so two scrapers running concurrently can both pass the check and both
insert. Duplicates would then inflate open_positions in the statistics.

This adds the constraint the code already assumes. Any pre-existing duplicates
are collapsed first, keeping the lowest id, so the migration does not fail on a
database where the race has already happened.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7e1a4c92f03'
down_revision = '8d4c2d09abc1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Collapse any duplicates the race may already have produced.
    op.execute("""
        DELETE FROM inserts a
        USING inserts b
        WHERE a.job_id = b.job_id
          AND a.scrape_date = b.scrape_date
          AND a.id > b.id
    """)

    op.create_index(
        'ix_inserts_job_id_scrape_date',
        'inserts',
        ['job_id', 'scrape_date'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_inserts_job_id_scrape_date', table_name='inserts')
