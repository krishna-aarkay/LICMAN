"""Iteration 8 — Usage history, kill checkout, sortable headers, TZ toggle.
Backend tests: /api/usage*, POST /api/servers/{id}/checkouts/kill, regression sweep.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "adminpass123"


def _admin_session() -> requests.Session:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def admin():
    return _admin_session()


@pytest.fixture(scope="module")
def populated(admin):
    """Hit /api/checkouts so usage_history is populated before queries."""
    r = admin.get(f"{BASE_URL}/api/checkouts", timeout=20)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def first_server(admin):
    r = admin.get(f"{BASE_URL}/api/servers", timeout=15)
    assert r.status_code == 200
    servers = r.json()
    assert servers, "no servers available"
    return servers[0]


# ---------------- /api/usage ----------------

class TestUsageList:
    def test_usage_returns_list_after_checkouts(self, admin, populated):
        r = admin.get(f"{BASE_URL}/api/usage", timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) > 0, "usage_history should have rows after /api/checkouts"
        sample = data[0]
        # Records must have first_seen_iso + last_seen_iso (TTL spec)
        assert "first_seen_iso" in sample, f"missing first_seen_iso, got keys={list(sample.keys())}"
        assert "last_seen_iso" in sample
        # _id must NOT leak
        assert "_id" not in sample

    def test_date_from_filter(self, admin, populated):
        r = admin.get(f"{BASE_URL}/api/usage", params={"date_from": "2026-01-01"}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert row["last_seen_iso"] >= "2026-01-01"

    def test_date_from_future_returns_empty(self, admin, populated):
        r = admin.get(f"{BASE_URL}/api/usage", params={"date_from": "2099-01-01"}, timeout=15)
        assert r.status_code == 200
        assert r.json() == []

    def test_user_filter(self, admin, populated):
        # First find an actual user from facets
        f = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15).json()
        users = f.get("users") or []
        if not users:
            pytest.skip("no users in usage_history")
        target = users[0]
        r = admin.get(f"{BASE_URL}/api/usage", params={"user": target}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert rows, f"expected some rows for user {target}"
        for row in rows:
            assert row["user"].lower() == target.lower()

    def test_feature_filter(self, admin, populated):
        f = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15).json()
        feats = f.get("features") or []
        if not feats:
            pytest.skip("no features")
        target = "VCS-RuntimeNetlist" if "VCS-RuntimeNetlist" in feats else feats[0]
        r = admin.get(f"{BASE_URL}/api/usage", params={"feature": target}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert row["feature"].lower() == target.lower()


# ---------------- /api/usage/facets ----------------

class TestUsageFacets:
    def test_facets_non_empty(self, admin, populated):
        r = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15)
        assert r.status_code == 200
        data = r.json()
        for key in ("users", "features", "vendors", "servers", "total_rows"):
            assert key in data
        assert data["total_rows"] > 0
        # Most should be non-empty after /api/checkouts
        assert isinstance(data["users"], list)
        assert isinstance(data["features"], list)
        assert isinstance(data["vendors"], list)
        assert isinstance(data["servers"], list)
        # At least one user, feature, vendor, server should exist
        assert data["features"], "features list should be non-empty"
        assert data["vendors"], "vendors list should be non-empty"
        assert data["servers"], "servers list should be non-empty"


# ---------------- /api/usage/summary ----------------

class TestUsageSummary:
    @pytest.mark.parametrize("group_by", ["user", "feature", "vendor", "server_name"])
    def test_summary_grouping(self, admin, populated, group_by):
        r = admin.get(f"{BASE_URL}/api/usage/summary", params={"group_by": group_by}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert data["group_by"] == group_by
        rows = data["rows"]
        assert isinstance(rows, list)
        if rows:
            # Sorted by sessions desc
            sessions = [row["sessions"] for row in rows]
            assert sessions == sorted(sessions, reverse=True)
            # Each row has required fields
            for row in rows:
                for k in ("key", "sessions", "user_count", "feature_count", "first_seen", "last_seen"):
                    assert k in row, f"row missing {k}: {row}"


# ---------------- /api/usage/export ----------------

class TestUsageExport:
    def test_export_csv(self, admin, populated):
        r = admin.get(f"{BASE_URL}/api/usage/export", timeout=15)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        body = r.text
        first_line = body.splitlines()[0]
        expected_header = "first_seen,last_seen,duration_seconds,vendor,server_name,feature,version,user,host,display,pid,checkout_time"
        assert first_line == expected_header

    def test_export_filter_user(self, admin, populated):
        f = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15).json()
        users = f.get("users") or []
        if not users:
            pytest.skip("no users")
        target = users[0]
        r = admin.get(f"{BASE_URL}/api/usage/export", params={"user": target}, timeout=15)
        assert r.status_code == 200
        lines = r.text.splitlines()
        if len(lines) > 1:
            for line in lines[1:]:
                # user column index = 7
                cols = line.split(",")
                if len(cols) >= 8:
                    assert cols[7].lower() == target.lower()


# ---------------- Kill checkout ----------------

class TestKillCheckout:
    def test_kill_admin_mock(self, admin, populated, first_server):
        # pick a checkout
        co_resp = admin.get(f"{BASE_URL}/api/checkouts", timeout=15).json()
        srv_checkouts = [c for c in co_resp if c["server_id"] == first_server["id"]]
        if not srv_checkouts:
            # try another server
            for srv_co in co_resp:
                if srv_co.get("server_id"):
                    first_server_id = srv_co["server_id"]
                    break
            else:
                pytest.skip("no checkouts available")
            target_co = co_resp[0]
            srv_id = target_co["server_id"]
        else:
            target_co = srv_checkouts[0]
            srv_id = first_server["id"]
        payload = {
            "feature": target_co["feature"],
            "user": target_co["user"],
            "host": target_co["host"],
            "display": target_co.get("display", ""),
        }
        r = admin.post(f"{BASE_URL}/api/servers/{srv_id}/checkouts/kill",
                       json=payload, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["exec"]["mode"] == "mock"

    def test_kill_requires_admin_403_for_engineer(self, admin, first_server):
        # Create engineer user
        email = f"TEST_eng_{uuid.uuid4().hex[:8]}@example.com"
        pw = "engineerpass123"
        r = admin.post(f"{BASE_URL}/api/users",
                       json={"email": email, "password": pw, "name": "Eng",
                             "role": "engineer"}, timeout=15)
        assert r.status_code in (200, 201, 409), r.text

        eng = requests.Session()
        lr = eng.post(f"{BASE_URL}/api/auth/login",
                      json={"email": email, "password": pw}, timeout=15)
        assert lr.status_code == 200, lr.text

        payload = {"feature": "X", "user": "x", "host": "y"}
        kill = eng.post(f"{BASE_URL}/api/servers/{first_server['id']}/checkouts/kill",
                        json=payload, timeout=15)
        assert kill.status_code == 403, f"engineer should be 403, got {kill.status_code}"

    def test_kill_invalid_server_404(self, admin):
        r = admin.post(f"{BASE_URL}/api/servers/nonexistent-id/checkouts/kill",
                       json={"feature": "f", "user": "u", "host": "h"}, timeout=15)
        assert r.status_code == 404


# ---------------- Usage history TTL / upsert idempotency ----------------

class TestUsageUpsert:
    def test_no_duplicates_on_repeated_checkouts(self, admin):
        # Snapshot facets count
        before = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15).json()["total_rows"]
        # Repeat /api/checkouts -- different random checkouts each time, so count
        # may grow when new sessions appear. But upserts on existing keys
        # should NOT create duplicates. We can verify by checking the unique
        # index exists implicitly: counts are bounded by feature*total seats.
        for _ in range(3):
            admin.get(f"{BASE_URL}/api/checkouts", timeout=20)
        after = admin.get(f"{BASE_URL}/api/usage/facets", timeout=15).json()["total_rows"]
        # After must still be >= before, but we accept growth (new random
        # sessions). Just sanity check: total_rows isn't multiplying.
        assert after >= before
        assert after < before * 5 + 100, f"unexpected explosion before={before} after={after}"


# ---------------- Regression ----------------

class TestIter7Regression:
    def test_setup_status_open(self, admin):
        r = admin.get(f"{BASE_URL}/api/setup-status", timeout=10)
        assert r.status_code == 200

    def test_me(self, admin):
        r = admin.get(f"{BASE_URL}/api/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"

    def test_servers_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/servers", timeout=10)
        assert r.status_code == 200
        assert len(r.json()) > 0

    def test_expiry(self, admin):
        r = admin.get(f"{BASE_URL}/api/expiry", timeout=10)
        assert r.status_code == 200

    def test_expiry_export(self, admin):
        r = admin.get(f"{BASE_URL}/api/expiry/export", timeout=10)
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    def test_audit_export(self, admin):
        r = admin.get(f"{BASE_URL}/api/audit/export", timeout=10)
        assert r.status_code == 200

    def test_reread_all(self, admin):
        r = admin.post(f"{BASE_URL}/api/servers/reread-all", timeout=20)
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_logout(self):
        s = _admin_session()
        r = s.post(f"{BASE_URL}/api/auth/logout", timeout=10)
        assert r.status_code == 200
