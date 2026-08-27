"""Drop redundant indexes on primary key columns

Revision ID: c3f8d2a15b47
Revises: b7e1a4c92f03
Create Date: 2026-08-27 09:10:00.000000

Every model declared `id = Column(Integer, primary_key=True, index=True)`.
primary_key=True already creates a unique index, so index=True added a second,
non-unique index on the same column. The duplicates cost disk and, more
importantly, every INSERT and UPDATE maintains two B-trees instead of one - on
`inserts`, which is appended to on every scrape, the redundant index was as
large as the primary key itself.

The two are interchangeable for lookups, so dropping the non-unique one simply
moves those scans onto the primary key with no loss of query performance.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f8d2a15b47'
down_revision = 'b7e1a4c92f03'
branch_labels = None
depends_on = None


_REDUNDANT = [
    ('ix_companies_id', 'companies'),
    ('ix_jobs_id', 'jobs'),
    ('ix_inserts_id', 'inserts'),
    ('ix_api_keys_id', 'api_keys'),
]


def upgrade() -> None:
    for index_name, table in _REDUNDANT:
        op.execute(f'DROP INDEX IF EXISTS {index_name}')


def downgrade() -> None:
    for index_name, table in _REDUNDANT:
        op.create_index(index_name, table, ['id'], unique=False)
