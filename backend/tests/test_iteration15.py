"""
Iteration 15 — Feature-priority auto-preempt v2 (background daemon)

Covers:
  - REGRESSION smoke: list/upsert/delete/request feature-priorities
  - POST /api/feature-priorities/auto-tick (admin-only)
  - GET  /api/feature-priorities/auto-status
  - Idempotency: hipri_already_holds_seat
  - Idempotency: each (server,feature) acted at most once per tick
  - Background loop preempts within ~15s when enabled
  - Background loop is a no-op when disabled
"""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient
from datetime import datetime, timezone

def _load_frontend_env():
    p = "/app/frontend/.env"
    if os.path.exists(p):
        for line in open(p):
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("REACT_APP_BACKEND_URL", "")

BASE_URL = _load_frontend_env().rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be configured"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "adminpass123"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME") or "test_database"


def _load_backend_env():
    p = "/app/backend/.env"
    if os.path.exists(p):
        for line in open(p):
            line = line.strip()
            if line.startswith("DB_NAME="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


_bn = _load_backend_env()
if _bn:
    DB_NAME = _bn

# ----- helpers ----------------------------------------------------------------

@pytest.fixture(scope="session")
def admin_client():
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def db():
    c = MongoClient(MONGO_URL)
    return c[DB_NAME]


@pytest.fixture(scope="session")
def cadence_server(admin_client):
    r = admin_client.get(f"{BASE_URL}/api/servers")
    assert r.status_code == 200
    srv = next(s for s in r.json() if s["name"] == "cadence-prod-01")
    return srv


def _saturate(db, server_id, feature, lopri_users, hipri_holder=None):
    """Insert enough checkouts to saturate `feature` on `server_id`.
    Returns the user-list inserted (in order so we can pick the oldest)."""
    # clear any prior test checkouts for this feature
    db.checkouts.delete_many({"server_id": server_id, "feature": feature})
    holders = []
    # Insert lopri users (older timestamps first)
    base = datetime.now(timezone.utc).timestamp()
    for i, u in enumerate(lopri_users):
        ts = datetime.fromtimestamp(base - (len(lopri_users) - i) * 60,
                                    tz=timezone.utc).isoformat()
        db.checkouts.insert_one({
            "id": str(uuid.uuid4()),
            "server_id": server_id,
            "feature": feature,
            "user": u,
            "host": f"workstation-{i}",
            "display": "",
            "count": 1,
            "checkout_time": ts,
        })
        holders.append(u)
    if hipri_holder:
        ts = datetime.fromtimestamp(base, tz=timezone.utc).isoformat()
        db.checkouts.insert_one({
            "id": str(uuid.uuid4()),
            "server_id": server_id,
            "feature": feature,
            "user": hipri_holder,
            "host": "workstation-hi",
            "display": "",
            "count": 1,
            "checkout_time": ts,
        })
        holders.append(hipri_holder)
    return holders


def _cleanup_feature(db, admin_client, server_id, feature):
    db.checkouts.delete_many({"server_id": server_id, "feature": feature})
    # delete the priority config if present
    cfg = db.feature_priorities.find_one(
        {"server_id": server_id, "feature": feature}, {"_id": 0})
    if cfg:
        admin_client.delete(f"{BASE_URL}/api/feature-priorities/{cfg['id']}")


def _set_auto(admin_client, enabled: bool, interval: int = 10):
    """PUT /api/settings without losing other fields."""
    r = admin_client.get(f"{BASE_URL}/api/settings")
    cur = r.json()
    cur.pop("smtp_password_set", None)
    cur["smtp_password"] = ""  # masked '********' would otherwise be saved literally
    cur["auto_preempt_enabled"] = enabled
    cur["auto_preempt_interval_sec"] = interval
    r = admin_client.put(f"{BASE_URL}/api/settings", json=cur)
    assert r.status_code == 200, f"put settings failed: {r.status_code} {r.text}"


# ----- REGRESSION smoke -------------------------------------------------------

class TestRegressionSmoke:
    """Light regression on v2 CRUD + /request — one of each, not the full iter14 suite."""

    def test_list_feature_priorities(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/feature-priorities")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_upsert_and_delete_feature_priority(self, admin_client, cadence_server, db):
        feature = "Tempus"
        # upsert
        payload = {
            "server_id": cadence_server["id"],
            "feature": feature,
            "hipri_users": ["TEST_iter15_hi1", "TEST_iter15_hi2"],
            "lopri_users": ["TEST_iter15_lo1"],
        }
        r = admin_client.put(f"{BASE_URL}/api/feature-priorities", json=payload)
        assert r.status_code in (200, 201), r.text
        cfg = r.json()
        assert cfg["feature"] == feature
        assert "TEST_iter15_hi1" in cfg["hipri_users"]
        # delete
        r = admin_client.delete(f"{BASE_URL}/api/feature-priorities/{cfg['id']}")
        assert r.status_code in (200, 204)
        # verify
        r = admin_client.get(f"{BASE_URL}/api/feature-priorities")
        assert all(c["id"] != cfg["id"] for c in r.json())

    def test_request_endpoint_responds(self, admin_client, cadence_server, db):
        # On Genus with hipri user 'ramkella' — feature is not saturated so we expect 'available'
        db.checkouts.delete_many(
            {"server_id": cadence_server["id"], "feature": "Genus"})
        r = admin_client.post(f"{BASE_URL}/api/feature-priorities/request", json={
            "server_id": cadence_server["id"], "feature": "Genus", "user": "ramkella",
        })
        assert r.status_code == 200
        outcome = r.json().get("action") or r.json().get("outcome")
        assert outcome in ("available", "already_holding"), r.json()


# ----- /auto-status -----------------------------------------------------------

class TestAutoStatus:
    def test_auto_status_shape(self, admin_client):
        r = admin_client.get(f"{BASE_URL}/api/feature-priorities/auto-status")
        assert r.status_code == 200
        body = r.json()
        for k in ("running", "enabled_in_settings", "interval_sec"):
            assert k in body

    def test_auto_status_reflects_settings_toggle(self, admin_client):
        _set_auto(admin_client, True, 10)
        time.sleep(0.5)
        r = admin_client.get(f"{BASE_URL}/api/feature-priorities/auto-status").json()
        assert r["enabled_in_settings"] is True
        assert r["running"] is True
        assert r["interval_sec"] == 10


# ----- /auto-tick on-demand ---------------------------------------------------

class TestAutoTickOnDemand:
    def test_auto_tick_requires_admin(self):
        s = requests.Session()
        r = s.post(f"{BASE_URL}/api/feature-priorities/auto-tick", json={})
        assert r.status_code in (401, 403), r.status_code

    def test_auto_tick_returns_summary_shape(self, admin_client):
        r = admin_client.post(
            f"{BASE_URL}/api/feature-priorities/auto-tick", json={})
        assert r.status_code == 200
        body = r.json()
        for k in ("scanned", "actioned", "results", "reasons", "ts"):
            assert k in body, f"missing key {k} in summary: {body}"

    def test_auto_tick_preempts_oldest_lopri(self, admin_client, cadence_server, db):
        """Saturated feature, ALL holders are lopri, no hipri holder -> 1 preemption."""
        # Pause loop so it doesn't race us
        _set_auto(admin_client, False, 10)
        time.sleep(0.5)
        feature = "Innovus"  # total=8
        srv_id = cadence_server["id"]
        try:
            # config: lopri jdev1..jdev8 (must be 8 to saturate total=8), hipri ramkella
            lopri = [f"TEST_lo{i}" for i in range(1, 9)]
            payload = {
                "server_id": srv_id, "feature": feature,
                "hipri_users": ["TEST_hi1"], "lopri_users": lopri,
            }
            r = admin_client.put(f"{BASE_URL}/api/feature-priorities", json=payload)
            assert r.status_code in (200, 201), r.text
            _saturate(db, srv_id, feature, lopri)  # all 8 lopri holders

            r = admin_client.post(
                f"{BASE_URL}/api/feature-priorities/auto-tick", json={})
            assert r.status_code == 200
            body = r.json()
            assert body["actioned"] >= 1
            ours = [x for x in body["results"]
                    if x.get("feature") == feature and x.get("server") == cadence_server["name"]]
            assert ours, f"no result for {feature}: {body}"
            assert ours[0]["preempted_user"] == lopri[0], (
                f"expected oldest lopri {lopri[0]}, got {ours[0]['preempted_user']}")
            # checkout for that holder should be gone
            still = db.checkouts.find_one(
                {"server_id": srv_id, "feature": feature, "user": lopri[0]})
            assert still is None, f"victim checkout NOT removed: {still}"
        finally:
            _cleanup_feature(db, admin_client, srv_id, feature)

    def test_auto_tick_skips_when_hipri_holds_seat(self, admin_client, cadence_server, db):
        """If a hipri user is among holders, skip with reason hipri_already_holds_seat."""
        _set_auto(admin_client, False, 10)
        time.sleep(0.5)
        feature = "Innovus"
        srv_id = cadence_server["id"]
        try:
            lopri = [f"TEST_lo{i}" for i in range(1, 8)]  # 7 lopri
            hipri_holder = "TEST_hi1"
            payload = {
                "server_id": srv_id, "feature": feature,
                "hipri_users": [hipri_holder], "lopri_users": lopri,
            }
            r = admin_client.put(f"{BASE_URL}/api/feature-priorities", json=payload)
            assert r.status_code in (200, 201), r.text
            # Saturate: 7 lopri + 1 hipri = 8 (total)
            _saturate(db, srv_id, feature, lopri, hipri_holder=hipri_holder)

            r = admin_client.post(
                f"{BASE_URL}/api/feature-priorities/auto-tick", json={})
            body = r.json()
            skips = [x for x in body["reasons"]
                     if x.get("feature") == feature
                     and x.get("skip") == "hipri_already_holds_seat"]
            assert skips, f"expected hipri_already_holds_seat skip, got reasons={body['reasons']}"
            # No lopri removed
            remaining = list(db.checkouts.find(
                {"server_id": srv_id, "feature": feature}))
            assert len(remaining) == 8, f"unexpected preemption: {len(remaining)} holders"
        finally:
            _cleanup_feature(db, admin_client, srv_id, feature)

    def test_auto_tick_only_once_per_feature_per_tick(self, admin_client, cadence_server, db):
        """A single (server,feature) gets exactly one preemption per tick."""
        _set_auto(admin_client, False, 10)
        time.sleep(0.5)
        feature = "Innovus"
        srv_id = cadence_server["id"]
        try:
            lopri = [f"TEST_lo{i}" for i in range(1, 9)]
            payload = {
                "server_id": srv_id, "feature": feature,
                "hipri_users": ["TEST_hi1"], "lopri_users": lopri,
            }
            admin_client.put(f"{BASE_URL}/api/feature-priorities", json=payload)
            _saturate(db, srv_id, feature, lopri)

            body = admin_client.post(
                f"{BASE_URL}/api/feature-priorities/auto-tick", json={}).json()
            ours = [x for x in body["results"]
                    if x.get("feature") == feature
                    and x.get("server") == cadence_server["name"]]
            assert len(ours) == 1, f"expected 1 preempt result, got {len(ours)}: {ours}"
        finally:
            _cleanup_feature(db, admin_client, srv_id, feature)


# ----- background loop --------------------------------------------------------

class TestBackgroundDaemon:
    def test_background_loop_preempts_when_enabled(self, admin_client, cadence_server, db):
        feature = "Innovus"
        srv_id = cadence_server["id"]
        try:
            # ensure disabled while we set up, so the loop doesn't race seeding
            _set_auto(admin_client, False, 10)
            time.sleep(0.5)
            lopri = [f"TEST_bg{i}" for i in range(1, 9)]
            admin_client.put(f"{BASE_URL}/api/feature-priorities", json={
                "server_id": srv_id, "feature": feature,
                "hipri_users": ["TEST_bghi1"], "lopri_users": lopri,
            })
            _saturate(db, srv_id, feature, lopri)
            before = list(db.checkouts.find(
                {"server_id": srv_id, "feature": feature}))
            assert len(before) == 8

            # now enable & wait for the loop (interval 10, sleep ~25s)
            _set_auto(admin_client, True, 10)
            deadline = time.time() + 30
            preempted = False
            while time.time() < deadline:
                count = db.checkouts.count_documents(
                    {"server_id": srv_id, "feature": feature})
                if count < 8:
                    preempted = True
                    break
                time.sleep(2)
            assert preempted, ("background loop did not preempt within 30s "
                               f"(still {count} holders)")
        finally:
            _cleanup_feature(db, admin_client, srv_id, feature)

    def test_background_loop_noop_when_disabled(self, admin_client, cadence_server, db):
        feature = "Innovus"
        srv_id = cadence_server["id"]
        try:
            _set_auto(admin_client, False, 10)
            time.sleep(0.5)
            lopri = [f"TEST_no{i}" for i in range(1, 9)]
            admin_client.put(f"{BASE_URL}/api/feature-priorities", json={
                "server_id": srv_id, "feature": feature,
                "hipri_users": ["TEST_nohi"], "lopri_users": lopri,
            })
            _saturate(db, srv_id, feature, lopri)
            # wait ~15s with the daemon disabled — nothing should change
            time.sleep(15)
            count = db.checkouts.count_documents(
                {"server_id": srv_id, "feature": feature})
            assert count == 8, f"daemon preempted while disabled: {count} holders left"
        finally:
            _cleanup_feature(db, admin_client, srv_id, feature)
            # restore enabled for downstream UI tests
            _set_auto(admin_client, True, 10)
