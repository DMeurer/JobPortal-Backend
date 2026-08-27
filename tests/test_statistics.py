"""
Statistics correctness.

open_positions / newly_added / removed are computed entirely in SQL. These tests
pin the semantics against hand-checked expectations rather than against the
previous implementation, so they stay meaningful if the query is rewritten again.
"""
from datetime import date

from app.services import JobService


class TestBasicCounts:
    def test_first_date_reports_everything_as_new(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a", "b", "c"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 1)] == (3, 3, 0)

    def test_steady_state_has_no_churn(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a", "b"])
        build.add("Acme", "2026-01-02", ["a", "b"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 2)] == (2, 0, 0)

    def test_added_and_removed_in_the_same_step(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a", "b"])
        # b disappears, c and d appear
        build.add("Acme", "2026-01-02", ["a", "c", "d"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 2)] == (3, 2, 1)

    def test_a_job_that_returns_counts_as_removed_then_added_again(
        self, db, stats, admin_key, build
    ):
        # This is why a single first_seen/last_seen span cannot model presence:
        # it would erase both of these events.
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Acme", "2026-01-02", [])
        build.add("Acme", "2026-01-03", ["a"])

        result = stats(admin_key)

        # 2026-01-02 has no inserts at all, so it is not a scrape date for Acme.
        # The previous date for 01-03 is therefore 01-01, where "a" was present.
        assert result["Acme"][date(2026, 1, 3)] == (1, 0, 0)

    def test_gap_day_with_other_jobs_shows_the_removal(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a", "keep"])
        build.add("Acme", "2026-01-02", ["keep"])
        build.add("Acme", "2026-01-03", ["a", "keep"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 2)] == (1, 0, 1)
        assert result["Acme"][date(2026, 1, 3)] == (2, 1, 0)

    def test_previous_date_means_previous_scrape_not_previous_calendar_day(
        self, db, stats, admin_key, build
    ):
        build.add("Acme", "2026-01-01", ["a"])
        # Nothing scraped for a week
        build.add("Acme", "2026-01-08", ["a", "b"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 8)] == (2, 1, 0)

    def test_dates_are_returned_newest_first(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Acme", "2026-01-02", ["a"])
        build.add("Acme", "2026-01-03", ["a"])

        raw = JobService.get_jobs_statistics(db, admin_key)
        dates = [d["date"] for d in raw[0]["dates"]]

        assert dates == sorted(dates, reverse=True)

    def test_duplicate_inserts_cannot_occur(self, db, stats, admin_key, build):
        """
        The statistics query still applies DISTINCT when collecting presence, but
        since migration b7e1a4c92f03 the database cannot hold a duplicate
        (job_id, scrape_date) at all, so the defensive path is unreachable. This
        records that guarantee; see test_inserts.py for the constraint itself.
        """
        build.add("Acme", "2026-01-01", ["a"])
        job = build.job("Acme", "a")

        from sqlalchemy.exc import IntegrityError
        from app import models

        rejected = False
        try:
            db.add(models.Insert(job_id=job.id, scrape_date=date(2026, 1, 1)))
            db.commit()
        except IntegrityError:
            db.rollback()
            rejected = True

        assert rejected
        assert stats(admin_key)["Acme"][date(2026, 1, 1)] == (1, 1, 0)


class TestCompanyIsolation:
    def test_companies_are_counted_separately(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Globex", "2026-01-01", ["a", "b"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 1)] == (1, 1, 0)
        assert result["Globex"][date(2026, 1, 1)] == (2, 2, 0)

    def test_one_company_scrape_gap_does_not_shift_another(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Acme", "2026-01-03", ["a"])
        build.add("Globex", "2026-01-02", ["x"])
        build.add("Globex", "2026-01-03", ["x", "y"])

        result = stats(admin_key)

        assert result["Acme"][date(2026, 1, 3)] == (1, 0, 0)
        assert result["Globex"][date(2026, 1, 3)] == (2, 1, 0)

    def test_same_name_hidden_and_visible_merge_for_an_admin(
        self, db, stats, admin_key, build
    ):
        # companies has a unique index on (name, hidden), so one name can be two
        # rows. The original implementation keyed its dict on the name, merging
        # them, and that behaviour is preserved.
        build.add("Dual", "2026-01-01", ["a"], hidden=False)
        build.add("Dual", "2026-01-01", ["b"], hidden=True)

        result = stats(admin_key)

        assert list(result) == ["Dual"]
        assert result["Dual"][date(2026, 1, 1)] == (2, 2, 0)

    def test_hidden_company_excluded_without_read_hidden(
        self, db, stats, public_key, build
    ):
        build.add("Dual", "2026-01-01", ["a"], hidden=False)
        build.add("Dual", "2026-01-01", ["b"], hidden=True)
        build.add("Secret", "2026-01-01", ["s"], hidden=True)

        result = stats(public_key)

        assert "Secret" not in result
        assert result["Dual"][date(2026, 1, 1)] == (1, 1, 0)


class TestFilters:
    def test_company_name_filter(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Globex", "2026-01-01", ["x"])

        result = stats(admin_key, company_name="Acme")

        assert list(result) == ["Acme"]

    def test_company_names_filter(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Globex", "2026-01-01", ["x"])
        build.add("Initech", "2026-01-01", ["i"])

        result = stats(admin_key, company_names=["Acme", "Initech"])

        assert sorted(result) == ["Acme", "Initech"]

    def test_found_on_date_filters_output_but_not_the_diff(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a", "b"])
        build.add("Acme", "2026-01-02", ["a", "c"])

        result = stats(admin_key, found_on_date=date(2026, 1, 2))

        # Only the requested date is returned, but newly_added/removed are still
        # measured against 01-01 rather than treating 01-02 as the first date.
        assert list(result["Acme"]) == [date(2026, 1, 2)]
        assert result["Acme"][date(2026, 1, 2)] == (2, 1, 1)

    def test_empty_database_returns_nothing(self, db, stats, admin_key):
        assert JobService.get_jobs_statistics(db, admin_key) == []
