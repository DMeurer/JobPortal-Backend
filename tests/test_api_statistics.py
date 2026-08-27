"""
Endpoint-level tests for /api/jobs?statistics=true.

Covers the request validation, which lives in main.py rather than the service,
and the HTTPException handling that previously turned every 400 into a 500.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture
def client(db, admin_key):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        c.headers.update({"X-API-Key": admin_key.key})
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def seeded(build, days):
    span = days(10)
    for i, day in enumerate(span):
        build.add("Acme", day, [f"j{n}" for n in range(i, i + 3)])
    return span


class TestValidation:
    def test_future_date_from_is_rejected(self, client):
        tomorrow = date.today() + timedelta(days=1)
        r = client.get(f"/api/jobs?statistics=true&date_from={tomorrow}")

        assert r.status_code == 400
        assert "future" in r.json()["detail"]

    def test_future_date_to_is_rejected(self, client):
        tomorrow = date.today() + timedelta(days=1)
        r = client.get(f"/api/jobs?statistics=true&date_to={tomorrow}")

        assert r.status_code == 400
        assert "future" in r.json()["detail"]

    def test_inverted_range_is_rejected(self, client):
        r = client.get(
            "/api/jobs?statistics=true&date_from=2026-08-01&date_to=2026-07-01"
        )

        assert r.status_code == 400
        assert "after" in r.json()["detail"]

    def test_malformed_date_is_rejected(self, client):
        r = client.get("/api/jobs?statistics=true&date_from=not-a-date")

        assert r.status_code == 400
        assert "Invalid date_from" in r.json()["detail"]

    def test_validation_errors_are_400_not_500(self, client):
        """
        get_jobs wraps its body in `except Exception -> 500`. Without an
        `except HTTPException: raise` guard ahead of it, every validation error
        surfaced as a 500.
        """
        r = client.get("/api/jobs?statistics=true&date_from=nonsense")

        assert r.status_code == 400

    def test_today_is_accepted(self, client, seeded):
        r = client.get("/api/jobs?statistics=true&date_to=today")

        assert r.status_code == 200

    def test_today_boundary_is_not_treated_as_future(self, client, seeded):
        r = client.get(f"/api/jobs?statistics=true&date_to={date.today()}")

        assert r.status_code == 200


class TestResponse:
    def test_returns_statistics_shape(self, client, seeded):
        r = client.get("/api/jobs?statistics=true")

        assert r.status_code == 200
        body = r.json()
        assert "companies" in body
        entry = body["companies"][0]
        assert set(entry) == {"company_name", "dates"}
        assert set(entry["dates"][0]) == {
            "date", "open_positions", "newly_added", "removed"
        }

    def test_window_narrows_the_result(self, client, seeded):
        full = client.get("/api/jobs?statistics=true").json()
        cutoff = seeded[-3]

        windowed = client.get(
            f"/api/jobs?statistics=true&date_from={cutoff}"
        ).json()

        full_rows = sum(len(c["dates"]) for c in full["companies"])
        window_rows = sum(len(c["dates"]) for c in windowed["companies"])
        assert window_rows == 3
        assert window_rows < full_rows

    def test_window_is_a_pure_slice_over_http(self, client, seeded):
        full = client.get("/api/jobs?statistics=true").json()["companies"][0]
        cutoff = seeded[-4].isoformat()

        windowed = client.get(
            f"/api/jobs?statistics=true&date_from={cutoff}"
        ).json()["companies"][0]

        expected = [d for d in full["dates"] if d["date"] >= cutoff]
        assert windowed["dates"] == expected

    def test_requires_an_api_key(self, db):
        with TestClient(app) as anon:
            app.dependency_overrides[get_db] = lambda: db
            r = anon.get("/api/jobs?statistics=true")
            app.dependency_overrides.clear()

        assert r.status_code in (401, 403)
