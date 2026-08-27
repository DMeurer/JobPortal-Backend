"""
Insert deduplication.

create_insert() checks for an existing (job_id, scrape_date) then inserts. That
is a check-then-act, so migration b7e1a4c92f03 added a unique index behind it.
These tests cover both the happy path and the race the index now catches.
"""
from datetime import date

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import models
from app.services import JobService


class TestCreateInsert:
    def test_creates_a_row(self, db, build):
        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")

        created = JobService.create_insert(db, job.id, date(2026, 1, 2))

        assert created is not None
        assert created.scrape_date == date(2026, 1, 2)

    def test_returns_none_when_already_recorded(self, db, build):
        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")

        assert JobService.create_insert(db, job.id, date(2026, 1, 1)) is None

    def test_same_job_on_different_dates_is_allowed(self, db, build):
        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")

        assert JobService.create_insert(db, job.id, date(2026, 1, 2)) is not None
        assert JobService.create_insert(db, job.id, date(2026, 1, 3)) is not None

    def test_unique_index_rejects_a_duplicate_written_directly(self, db, build):
        """The constraint exists, not just the application-level check."""
        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")

        raised = False
        try:
            # The index is checked when the statement executes, not at commit.
            db.execute(
                text("INSERT INTO inserts (job_id, scrape_date) VALUES (:j, :d)"),
                {"j": job.id, "d": date(2026, 1, 1)},
            )
            db.commit()
        except IntegrityError:
            db.rollback()
            raised = True

        assert raised, "expected the unique index to reject the duplicate"

    def test_concurrent_insert_is_reported_as_already_existing(self, db, build, engine):
        """
        Simulate the race: another session inserts the row between this session's
        existence check and its commit. create_insert must absorb the resulting
        IntegrityError rather than propagate it, since the caller's intent - the
        row exists - is satisfied either way.
        """
        from sqlalchemy.orm import sessionmaker

        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")
        target = date(2026, 1, 2)

        # This session sees no existing row.
        assert db.query(models.Insert).filter(
            models.Insert.job_id == job.id,
            models.Insert.scrape_date == target,
        ).first() is None

        # A competing session writes it first.
        Other = sessionmaker(bind=engine)
        other = Other()
        other.add(models.Insert(job_id=job.id, scrape_date=target))
        other.commit()
        other.close()

        assert JobService.create_insert(db, job.id, target) is None

        count = db.query(models.Insert).filter(
            models.Insert.job_id == job.id,
            models.Insert.scrape_date == target,
        ).count()
        assert count == 1
