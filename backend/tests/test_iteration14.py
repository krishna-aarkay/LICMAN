"""
Iteration 14 — Backend tests for the NEW Feature-Priority (clean v2) endpoints.

Scope:
  - PUT  /api/feature-priorities      (upsert + idempotency + overlap + unknown server/feature)
  - GET  /api/feature-priorities      (sorted list)
  - DELETE /api/feature-priorities/{id}
  - POST /api/feature-priorities/request
        action ∈ {available, already_holding, preempted, no_victim}
        plus 403 not-hipri and 404 no-config
  - Role gating: engineer-role users receive 403 on PUT/DELETE/POST.
  - Startup invariant: auto-preempt background loop is OFF (no log line on startup).

Auth: admin@example.com / adminpass123  (creds from /app/memory/test_credentials.md)
"""
import os
import uuid
import time
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://eda-license-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "adminpass123"

CADENCE_ID = "48ca082c-f9a3-46a9-8b83-6423d43cdf59"
FEATURE_GENUS = "Genus"
FEATURE_INNOVUS = "Innovus"   # total=8 (we'll use this for clean scenarios)
FEATURE_TEMPUS = "Tempus"     # total=3 (small, easy to saturate)


# -------------------- shared session helpers --------------------

@pytest.fixture(scope="session")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="session")
def engineer_session(admin_session):
    """Create (or reuse) an engineer-role user and return a logged-in session."""
    email = f"TEST_eng_iter14@example.com"
    pw = "EngPass!2026"
    # try to create; if exists, ignore
    admin_session.post(f"{API}/users", json={
        "email": email, "password": pw, "name": "Iter14 Engineer", "role": "engineer"
    }, timeout=10)
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": email, "password": pw}, timeout=10)
    if r.status_code != 200:
        pytest.skip(f"engineer login failed: {r.status_code} {r.text}")
    return s


@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient("mongodb://localhost:27017")
    return client["test_database"]


# -------------------- helpers --------------------

def _delete_fp(session, fp_id):
    try:
        session.delete(f"{API}/feature-priorities/{fp_id}", timeout=10)
    except Exception:
        pass


# ============================================================
# 1. CRUD on /api/feature-priorities
# ============================================================

class TestFeaturePriorityCRUD:

    def test_put_creates_config(self, admin_session):
        # Use Innovus to avoid colliding with the pre-existing Genus config
        payload = {
            "server_id": CADENCE_ID,
            "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_hi1", "TEST_hi2"],
            "lopri_users": ["TEST_lo1", "TEST_lo2"],
        }
        r = admin_session.put(f"{API}/feature-priorities", json=payload, timeout=10)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["server_id"] == CADENCE_ID
        assert data["feature"] == FEATURE_INNOVUS
        assert set(data["hipri_users"]) == {"TEST_hi1", "TEST_hi2"}
        assert set(data["lopri_users"]) == {"TEST_lo1", "TEST_lo2"}
        assert "id" in data and isinstance(data["id"], str)

    def test_put_is_idempotent(self, admin_session):
        # Second PUT on same (server_id, feature) must reuse the same id (no duplicate)
        payload = {
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_hi1"], "lopri_users": ["TEST_lo1", "TEST_lo3"],
        }
        r1 = admin_session.put(f"{API}/feature-priorities", json=payload, timeout=10)
        assert r1.status_code == 200, r1.text
        id1 = r1.json()["id"]
        r2 = admin_session.put(f"{API}/feature-priorities", json=payload, timeout=10)
        assert r2.status_code == 200
        id2 = r2.json()["id"]
        assert id1 == id2, "PUT must be idempotent (same id on second call)"
        # And the list endpoint must contain only one entry for that (server, feature)
        all_fps = admin_session.get(f"{API}/feature-priorities", timeout=10).json()
        matches = [f for f in all_fps if f["server_id"] == CADENCE_ID and f["feature"] == FEATURE_INNOVUS]
        assert len(matches) == 1, f"expected exactly 1 Innovus config, got {len(matches)}"

    def test_put_rejects_overlap(self, admin_session):
        r = admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["alice", "bob"], "lopri_users": ["bob", "carol"],
        }, timeout=10)
        assert r.status_code == 400, r.text
        assert "bob" in r.text.lower()

    def test_put_unknown_server(self, admin_session):
        r = admin_session.put(f"{API}/feature-priorities", json={
            "server_id": "no-such-server-id", "feature": FEATURE_INNOVUS,
            "hipri_users": ["x"], "lopri_users": ["y"],
        }, timeout=10)
        assert r.status_code == 404, r.text

    def test_put_unknown_feature(self, admin_session):
        r = admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": "NoSuchFeature",
            "hipri_users": ["x"], "lopri_users": ["y"],
        }, timeout=10)
        assert r.status_code == 404, r.text

    def test_list_sorted_by_feature(self, admin_session):
        # Create Tempus config to ensure at least 2 in the list (Genus already exists)
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_TEMPUS,
            "hipri_users": ["TEST_thi"], "lopri_users": ["TEST_tlo"],
        }, timeout=10)
        r = admin_session.get(f"{API}/feature-priorities", timeout=10)
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list) and len(items) >= 2
        names = [i["feature"] for i in items]
        assert names == sorted(names), f"not sorted by feature: {names}"

    def test_delete_and_re_delete(self, admin_session):
        # Create a throwaway config on Tempus then delete it twice
        r = admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_TEMPUS,
            "hipri_users": ["TEST_del_hi"], "lopri_users": ["TEST_del_lo"],
        }, timeout=10)
        assert r.status_code == 200
        fp_id = r.json()["id"]
        d1 = admin_session.delete(f"{API}/feature-priorities/{fp_id}", timeout=10)
        assert d1.status_code == 200, d1.text
        d2 = admin_session.delete(f"{API}/feature-priorities/{fp_id}", timeout=10)
        assert d2.status_code == 404, d2.text


# ============================================================
# 2. Role gating
# ============================================================

class TestRoleGating:

    def test_engineer_cannot_put(self, engineer_session):
        r = engineer_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["x"], "lopri_users": ["y"],
        }, timeout=10)
        assert r.status_code == 403, r.text

    def test_engineer_cannot_delete(self, engineer_session):
        # Try to delete some random uuid; admin gate should fire before lookup
        r = engineer_session.delete(f"{API}/feature-priorities/{uuid.uuid4()}", timeout=10)
        assert r.status_code == 403, r.text

    def test_engineer_cannot_request(self, engineer_session):
        r = engineer_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_GENUS, "user": "ramkella",
        }, timeout=10)
        assert r.status_code == 403, r.text

    def test_engineer_can_list(self, engineer_session):
        # GET is not admin-gated in the new code
        r = engineer_session.get(f"{API}/feature-priorities", timeout=10)
        assert r.status_code == 200


# ============================================================
# 3. POST /api/feature-priorities/request — all branches
# ============================================================

class TestRequestSeat:

    def test_no_priority_config_404(self, admin_session):
        # Spectre has no config (we never created one and seeded data doesn't include it)
        # First make sure none exists; if any, delete.
        all_fps = admin_session.get(f"{API}/feature-priorities", timeout=10).json()
        for fp in all_fps:
            if fp["server_id"] == CADENCE_ID and fp["feature"] == "Spectre":
                admin_session.delete(f"{API}/feature-priorities/{fp['id']}", timeout=10)
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": "Spectre", "user": "anyone",
        }, timeout=10)
        assert r.status_code == 404, r.text

    def test_not_in_hipri_403(self, admin_session):
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_GENUS, "user": "no_such_user_xyz",
        }, timeout=10)
        assert r.status_code == 403, r.text
        assert "high-priority" in r.text.lower() or "hipri" in r.text.lower()

    def test_available_seats(self, admin_session, mongo_db):
        # Configure Innovus with seed users; Innovus total=8, no checkouts seeded → free
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_avail_hi"], "lopri_users": ["TEST_avail_lo"],
        }, timeout=10)
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS, "user": "TEST_avail_hi",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["action"] == "available"
        assert d["seats_free"] == 8

    def test_already_holding(self, admin_session, mongo_db):
        # Seed a single checkout for TEST_hold_hi on Innovus, then request → already_holding
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_hold_hi"], "lopri_users": [],
        }, timeout=10)
        mongo_db.checkouts.insert_one({
            "id": str(uuid.uuid4()),
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": "TEST_hold_hi", "host": "wks-test-1",
            "count": 1, "checkout_time": "2026-01-01T00:00:00+00:00",
        })
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS, "user": "TEST_hold_hi",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["action"] == "already_holding"
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})

    def test_no_victim_when_holders_neutral(self, admin_session, mongo_db):
        # Saturate Innovus with 8 neutral holders (in neither hipri nor lopri).
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_nv_hi"], "lopri_users": ["TEST_nv_lo"],   # lopri user does not currently hold
        }, timeout=10)
        docs = [{
            "id": str(uuid.uuid4()),
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": f"neutral_{i}", "host": f"wks-{i}",
            "count": 1, "checkout_time": f"2026-01-01T0{i}:00:00+00:00",
        } for i in range(8)]
        mongo_db.checkouts.insert_many(docs)
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS, "user": "TEST_nv_hi",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is False, d
        assert d["action"] == "no_victim", d
        assert isinstance(d.get("current_holders"), list)
        assert len(d["current_holders"]) == 8
        # All marked neutral
        assert all(h["is_lopri"] is False and h["is_hipri"] is False for h in d["current_holders"])
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})

    def test_no_victim_when_all_holders_hipri(self, admin_session, mongo_db):
        # Saturate Innovus with 8 holders, ALL of whom are in hipri → still no_victim
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_hi_a", "TEST_hi_b", "TEST_hi_c", "TEST_hi_d",
                            "TEST_hi_e", "TEST_hi_f", "TEST_hi_g", "TEST_hi_h",
                            "TEST_hi_new"],
            "lopri_users": [],
        }, timeout=10)
        docs = [{
            "id": str(uuid.uuid4()),
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": f"TEST_hi_{c}", "host": f"wks-h-{c}",
            "count": 1, "checkout_time": f"2026-01-01T0{i}:00:00+00:00",
        } for i, c in enumerate("abcdefgh")]
        mongo_db.checkouts.insert_many(docs)
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS, "user": "TEST_hi_new",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["action"] == "no_victim"
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})

    def test_preempted_happy_path(self, admin_session, mongo_db):
        # Saturate Innovus with mix of hipri + lopri holders. Requester is hipri.
        # Expect: oldest lopri removed; response action='preempted'; row deleted from db.checkouts.
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})
        admin_session.put(f"{API}/feature-priorities", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "hipri_users": ["TEST_pre_hi"],
            "lopri_users": ["TEST_pre_lo_old", "TEST_pre_lo_new"],
        }, timeout=10)
        # 6 neutral + 2 lopri = 8 (saturate); oldest is TEST_pre_lo_old
        docs = [{
            "id": str(uuid.uuid4()),
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": "TEST_pre_lo_old", "host": "wks-old",
            "count": 1, "checkout_time": "2026-01-01T00:00:00+00:00",
        }, {
            "id": str(uuid.uuid4()),
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": "TEST_pre_lo_new", "host": "wks-new",
            "count": 1, "checkout_time": "2026-06-01T00:00:00+00:00",
        }]
        for i in range(6):
            docs.append({
                "id": str(uuid.uuid4()),
                "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
                "user": f"neutral_p_{i}", "host": f"wks-np-{i}",
                "count": 1, "checkout_time": f"2026-03-01T0{i}:00:00+00:00",
            })
        mongo_db.checkouts.insert_many(docs)
        r = admin_session.post(f"{API}/feature-priorities/request", json={
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS, "user": "TEST_pre_hi",
        }, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True, d
        assert d["action"] == "preempted", d
        assert d["preempted_user"] == "TEST_pre_lo_old"
        assert d["preempted_host"] == "wks-old"
        # Verify removal from db
        leftover = mongo_db.checkouts.count_documents({
            "server_id": CADENCE_ID, "feature": FEATURE_INNOVUS,
            "user": "TEST_pre_lo_old",
        })
        assert leftover == 0, "preempted holder should be removed from db.checkouts"
        mongo_db.checkouts.delete_many({"server_id": CADENCE_ID, "feature": FEATURE_INNOVUS})


# ============================================================
# 4. Startup invariant: auto-preempt loop must be OFF
# ============================================================

class TestAutoPreemptOff:

    def test_no_auto_preempt_in_recent_logs(self):
        """Inspect the latest backend startup block in the supervisor log.
        The most recent 'Auto-sync loop started' marker should NOT be followed
        (within the same startup window) by an 'Auto-preempt loop started' line.
        """
        path = "/var/log/supervisor/backend.err.log"
        if not os.path.exists(path):
            pytest.skip("backend log not present")
        # Read last 200 KB
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 200_000))
            tail = f.read().decode("utf-8", errors="ignore")
        lines = tail.splitlines()
        # Find the LAST 'Auto-sync loop started' line
        idx = None
        for i in range(len(lines) - 1, -1, -1):
            if "Auto-sync loop started" in lines[i]:
                idx = i
                break
        assert idx is not None, "expected at least one 'Auto-sync loop started' line"
        # Look at the next 5 lines after the most recent sync-start marker;
        # in v2 the auto-preempt line must NOT appear here.
        window = "\n".join(lines[idx: idx + 5])
        assert "Auto-preempt loop started" not in window, (
            f"auto-preempt loop should be OFF in v2; found it in startup window:\n{window}"
        )
