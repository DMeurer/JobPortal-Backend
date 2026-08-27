"""
Date window behaviour.

The subtle requirement: a window must be a pure slice. Restricting the reported
range must not change any number, because newly_added/removed for the first
reported date are still measured against the last scrape date BEFORE the window.
Getting this wrong makes the first bar of every chart report the entire backlog
as newly added.
"""
from datetime import date

import pytest

from app.services import JobService


class TestWindowIsAPureSlice:
    @pytest.fixture
    def history(self, build):
        build.add("Acme", "2026-01-01", ["a", "b"])
        build.add("Acme", "2026-01-02", ["a", "b", "c"])
        build.add("Acme", "2026-01-03", ["a", "c"])
        build.add("Acme", "2026-01-04", ["a", "c", "d"])
        build.add("Acme", "2026-01-05", ["d"])
        return build

    @pytest.mark.parametrize("date_from,date_to", [
        (date(2026, 1, 1), None),
        (date(2026, 1, 2), None),
        (date(2026, 1, 3), date(2026, 1, 4)),
        (date(2026, 1, 5), date(2026, 1, 5)),
        (None, date(2026, 1, 3)),
        (date(2026, 1, 2), date(2026, 1, 4)),
    ])
    def test_window_matches_the_unwindowed_slice(
        self, db, stats, admin_key, history, date_from, date_to
    ):
        full = stats(admin_key)["Acme"]
        expected = {
            d: v for d, v in full.items()
            if (date_from is None or d >= date_from)
            and (date_to is None or d <= date_to)
        }

        windowed = stats(admin_key, date_from=date_from, date_to=date_to)

        assert windowed["Acme"] == expected

    def test_first_date_in_window_diffs_against_the_date_before_it(
        self, db, stats, admin_key, history
    ):
        # On 01-03, b was dropped and c carried over from 01-02. A window
        # starting at 01-03 must still report that, not "2 new".
        result = stats(admin_key, date_from=date(2026, 1, 3))

        assert result["Acme"][date(2026, 1, 3)] == (2, 0, 1)

    def test_window_starting_at_the_very_first_date_has_no_lead_in(
        self, db, stats, admin_key, history
    ):
        result = stats(admin_key, date_from=date(2026, 1, 1))

        assert result["Acme"][date(2026, 1, 1)] == (2, 2, 0)


class TestWindowEdges:
    def test_window_before_all_data_is_empty(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])

        result = JobService.get_jobs_statistics(
            db, admin_key, date_from=date(2020, 1, 1), date_to=date(2020, 6, 1)
        )

        assert result == []

    def test_window_after_all_data_is_empty(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])

        result = JobService.get_jobs_statistics(
            db, admin_key, date_from=date(2026, 6, 1)
        )

        assert result == []

    def test_lead_in_is_per_company_not_global(self, db, stats, admin_key, build):
        # Acme's previous scrape is far older than Globex's. A single global
        # lead-in boundary would mis-attribute one of them.
        build.add("Acme", "2026-01-01", ["a", "b"])
        build.add("Globex", "2026-01-09", ["x"])
        build.add("Acme", "2026-01-10", ["a"])
        build.add("Globex", "2026-01-10", ["x", "y"])

        result = stats(admin_key, date_from=date(2026, 1, 10))

        assert result["Acme"][date(2026, 1, 10)] == (1, 0, 1)
        assert result["Globex"][date(2026, 1, 10)] == (2, 1, 0)

    def test_window_combined_with_company_filter(self, db, stats, admin_key, build):
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Acme", "2026-01-02", ["a", "b"])
        build.add("Globex", "2026-01-02", ["x"])

        result = stats(
            admin_key, company_name="Acme", date_from=date(2026, 1, 2)
        )

        assert list(result) == ["Acme"]
        assert result["Acme"][date(2026, 1, 2)] == (2, 1, 0)

    def test_hidden_filtering_still_applies_inside_a_window(
        self, db, stats, public_key, build
    ):
        build.add("Secret", "2026-01-01", ["s"], hidden=True)
        build.add("Acme", "2026-01-01", ["a"])
        build.add("Acme", "2026-01-02", ["a"])

        result = stats(public_key, date_from=date(2026, 1, 2))

        assert "Secret" not in result


class TestWindowScales:
    def test_large_history_window_is_a_pure_slice(self, db, stats, admin_key, build, days):
        """
        Guards the bug that took production down: the presence scan was bounded
        by a subquery, which the planner could not estimate. It stayed correct on
        tiny inputs, so only a non-trivial volume exercises the real plan.
        """
        span = days(120)
        for i, day in enumerate(span):
            # A rolling window of ids so there is churn on every date.
            build.add("Acme", day, [f"j{n}" for n in range(i, i + 25)])

        full = stats(admin_key)["Acme"]
        cutoff = span[-90]

        windowed = stats(admin_key, date_from=cutoff)["Acme"]

        assert windowed == {d: v for d, v in full.items() if d >= cutoff}
        assert len(windowed) == 90
