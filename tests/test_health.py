"""
Health endpoints.

These exist to be pointed at by an external monitor, so what matters is the
STATUS CODE, not just the body: a check that always returns 200 is worse than no
check at all, because it reports healthy through an outage.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_db
from app.main import app


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def set_refreshed_at(db, when: datetime) -> None:
    db.execute(
        text("""
            INSERT INTO statistics_refresh (id, refreshed_at) VALUES (true, :w)
            ON CONFLICT (id) DO UPDATE SET refreshed_at = :w
        """),
        {"w": when},
    )
    db.commit()


def age_newest_insert(db, hours: float) -> None:
    """Backdate every insert so the newest is `hours` old."""
    db.execute(
        text("UPDATE inserts SET created_at = now() - (:h * interval '1 hour')"),
        {"h": hours},
    )
    db.commit()


class TestLiveness:
    def test_healthy_when_the_database_answers(self, client):
        r = client.get("/health")

        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_needs_no_api_key(self, db):
        """A monitor must be able to reach this, and an outage must not be
        masked by an auth failure that happens to need the same database."""
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as anon:
            r = anon.get("/health")
        app.dependency_overrides.clear()

        assert r.status_code == 200


class TestDataFreshness:
    def test_healthy_when_data_is_recent_and_view_is_current(
        self, client, build, refresh
    ):
        build.add("Acme", date.today(), ["a", "b"])
        refresh()

        r = client.get("/health/data")

        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["problems"] == []
        assert body["statistics_stale"] is False
        assert body["statistics_rows"] > 0

    def test_unhealthy_when_the_view_is_behind_the_data(
        self, client, db, build, refresh
    ):
        build.add("Acme", date.today(), ["a"])
        refresh()
        # New data lands after the refresh: the dashboard would keep serving the
        # previous numbers and look entirely normal.
        build.add("Acme", date.today() - timedelta(days=1), ["b"])

        r = client.get("/health/data")

        assert r.status_code == 503
        body = r.json()
        assert body["statistics_stale"] is True
        assert any("behind" in p for p in body["problems"])

    def test_unhealthy_when_data_is_older_than_the_limit(
        self, client, db, build, refresh
    ):
        build.add("Acme", date.today(), ["a"])
        refresh()
        # 31h exceeds the 30h default, i.e. the 02:00 run did not land.
        age_newest_insert(db, 31)
        set_refreshed_at(db, datetime.now(timezone.utc))

        r = client.get("/health/data")

        assert r.status_code == 503
        assert any("old" in p for p in r.json()["problems"])

    def test_healthy_just_inside_the_limit(self, client, db, build, refresh):
        build.add("Acme", date.today(), ["a"])
        refresh()
        age_newest_insert(db, 29)
        set_refreshed_at(db, datetime.now(timezone.utc))

        r = client.get("/health/data")

        assert r.status_code == 200

    def test_unhealthy_when_there_is_no_data_at_all(self, client, refresh):
        refresh()

        r = client.get("/health/data")

        assert r.status_code == 503
        assert any("no scrape data" in p for p in r.json()["problems"])

    def test_reports_both_problems_at_once(self, client, db, build, refresh):
        build.add("Acme", date.today(), ["a"])
        refresh()
        age_newest_insert(db, 40)
        # Refresh marker older than the data as well.
        set_refreshed_at(db, datetime.now(timezone.utc) - timedelta(hours=50))

        r = client.get("/health/data")

        assert r.status_code == 503
        assert len(r.json()["problems"]) == 2

    def test_needs_no_api_key(self, db, build, refresh):
        build.add("Acme", date.today(), ["a"])
        refresh()

        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as anon:
            r = anon.get("/health/data")
        app.dependency_overrides.clear()

        assert r.status_code == 200

    def test_refresh_endpoint_clears_staleness(self, client, build, admin_key):
        build.add("Acme", date.today(), ["a"])

        # Never refreshed through the application yet.
        assert client.get("/health/data").status_code == 503

        # The refresh endpoint needs write permission; the health endpoints
        # deliberately do not.
        r = client.post(
            "/api/statistics/refresh", headers={"X-API-Key": admin_key.key}
        )
        assert r.status_code == 200

        assert client.get("/health/data").status_code == 200
