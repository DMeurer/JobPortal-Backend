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
def seeded(build, days, refresh):
    span = days(10)
    for i, day in enumerate(span):
        build.add("Acme", day, [f"j{n}" for n in range(i, i + 3)])
    # Statistics are precomputed; nothing is visible to the API until the view
    # is rebuilt.
    refresh()
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


class TestCaching:
    def test_response_carries_an_etag(self, client, seeded):
        r = client.get("/api/jobs?statistics=true")

        assert r.status_code == 200
        assert r.headers.get("etag")
        # Responses vary by key permission, so they must never be shared.
        assert "private" in r.headers.get("cache-control", "")

    def test_matching_etag_returns_304_without_a_body(self, client, seeded):
        first = client.get("/api/jobs?statistics=true")
        etag = first.headers["etag"]

        second = client.get(
            "/api/jobs?statistics=true", headers={"If-None-Match": etag}
        )

        assert second.status_code == 304
        assert second.content == b""

    def test_stale_etag_returns_the_body(self, client, seeded):
        r = client.get(
            "/api/jobs?statistics=true", headers={"If-None-Match": '"not-the-tag"'}
        )

        assert r.status_code == 200
        assert r.json()["companies"]

    def test_different_windows_have_different_etags(self, client, seeded):
        a = client.get("/api/jobs?statistics=true")
        b = client.get(f"/api/jobs?statistics=true&date_from={seeded[-2]}")

        assert a.headers["etag"] != b.headers["etag"]

    def test_etag_changes_when_the_data_changes(self, client, seeded, build, refresh):
        before = client.get("/api/jobs?statistics=true").headers["etag"]

        build.add("Globex", seeded[-1], ["x"])
        refresh()

        after = client.get("/api/jobs?statistics=true").headers["etag"]
        assert before != after


class TestRefreshEndpoint:
    def test_refresh_rebuilds_the_view(self, client, build, days):
        span = days(3)
        for i, day in enumerate(span):
            build.add("Acme", day, [f"j{i}"])

        # Not yet visible.
        assert client.get("/api/jobs?statistics=true").json()["companies"] == []

        r = client.post("/api/statistics/refresh")

        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["rows"] > 0
        assert client.get("/api/jobs?statistics=true").json()["companies"]

    def test_refresh_requires_write_permission(self, db, public_key):
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as c:
            r = c.post(
                "/api/statistics/refresh",
                headers={"X-API-Key": public_key.key},
            )
        app.dependency_overrides.clear()

        assert r.status_code in (401, 403)

