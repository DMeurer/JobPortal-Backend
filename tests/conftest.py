"""
Shared test fixtures.

These are integration tests against a real PostgreSQL. That is deliberate: the
statistics query relies on window functions, FILTER aggregates and the planner's
behaviour, none of which SQLite reproduces, and the bugs worth catching here are
exactly the ones that only appear against the real engine.

The suite creates and drops its own database, so it never touches development or
production data. Point it at a server with:

    TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres pytest

The URL names any existing database on the target server; the suite connects
there only to create/drop `jobportal_test`.
"""
import os
from datetime import date, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import models

ADMIN_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://root:root@localhost:5432/postgres",
)
TEST_DB_NAME = "jobportal_test"


def _test_db_url() -> str:
    base, _, _ = ADMIN_URL.rpartition("/")
    return f"{base}/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def engine():
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    admin.dispose()

    eng = create_engine(_test_db_url())
    # The application schema is owned by Alembic in production. For tests the
    # models are the source of truth, which keeps the suite independent of
    # migration history while still exercising the real DDL.
    models.Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()

    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{TEST_DB_NAME}' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME}"))
    admin.dispose()


@pytest.fixture
def db(engine):
    """A session against an empty schema. Every test starts from a clean slate."""
    Session = sessionmaker(bind=engine)
    session = Session()
    for table in reversed(models.Base.metadata.sorted_tables):
        session.execute(text(f'TRUNCATE TABLE "{table.name}" RESTART IDENTITY CASCADE'))
    session.commit()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def admin_key(db):
    key = models.APIKey(
        key="test-admin", name="Test Admin",
        admin=True, read=True, write=True, read_hidden=True, is_active=True,
    )
    db.add(key)
    db.commit()
    return key


@pytest.fixture
def public_key(db):
    """Read-only, cannot see hidden companies - what the frontend uses."""
    key = models.APIKey(
        key="test-public", name="Test Public",
        admin=False, read=True, write=False, read_hidden=False, is_active=True,
    )
    db.add(key)
    db.commit()
    return key


class Builder:
    """
    Builds job/insert history from a compact description.

    `add("Acme", "2026-01-01", ["a", "b"])` records that on that date Acme was
    seen advertising jobs a and b. Job identity is per company, so the same
    external id under two companies is two different jobs.
    """

    def __init__(self, db):
        self.db = db
        self._companies = {}
        self._jobs = {}

    def company(self, name: str, hidden: bool = False) -> models.Company:
        key = (name, hidden)
        if key not in self._companies:
            c = models.Company(name=name, hidden=hidden)
            self.db.add(c)
            self.db.commit()
            self._companies[key] = c
        return self._companies[key]

    def add(self, company_name, day, job_ids, hidden=False):
        company = self.company(company_name, hidden)
        if isinstance(day, str):
            day = date.fromisoformat(day)
        for jid in job_ids:
            key = (company.id, jid)
            if key not in self._jobs:
                job = models.Job(company_id=company.id, job_id=str(jid),
                                 title=f"{company_name} {jid}")
                self.db.add(job)
                self.db.commit()
                self._jobs[key] = job
            self.db.add(models.Insert(job_id=self._jobs[key].id, scrape_date=day))
        self.db.commit()

    def job(self, company_name, jid, hidden=False):
        return self._jobs[(self.company(company_name, hidden).id, jid)]


@pytest.fixture
def build(db):
    return Builder(db)


@pytest.fixture
def days():
    """Consecutive dates, oldest first, ending today."""
    def _days(n: int):
        today = date.today()
        return [today - timedelta(days=n - 1 - i) for i in range(n)]
    return _days


@pytest.fixture
def stats(db):
    """
    get_jobs_statistics reshaped for assertions:
    {company: {date: (open_positions, newly_added, removed)}}
    """
    from app.services import JobService

    def _stats(api_key, **kwargs):
        raw = JobService.get_jobs_statistics(db, api_key, **kwargs)
        return {
            c["company_name"]: {
                d["date"]: (d["open_positions"], d["newly_added"], d["removed"])
                for d in c["dates"]
            }
            for c in raw
        }
    return _stats
