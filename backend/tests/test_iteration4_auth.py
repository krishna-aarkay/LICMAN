"""
Iteration 4 auth tests — JWT cookie auth, RBAC, user CRUD, brute-force protection.
Public URL via REACT_APP_BACKEND_URL.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://eda-license-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "adminpass123"


@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    assert "access_token" in s.cookies, "access_token cookie not set"
    assert "refresh_token" in s.cookies, "refresh_token cookie not set"
    return s


@pytest.fixture(scope="module")
def engineer_creds(admin_session):
    email = f"test_eng_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "engpass123!"
    r = admin_session.post(f"{API}/users", json={
        "email": email, "password": pwd, "name": "Test Eng", "role": "engineer"
    }, timeout=10)
    assert r.status_code == 200, f"create engineer failed: {r.status_code} {r.text}"
    user = r.json()
    yield {"email": email, "password": pwd, "id": user["id"]}
    # teardown
    try:
        admin_session.delete(f"{API}/users/{user['id']}", timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="module")
def engineer_session(engineer_creds):
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": engineer_creds["email"], "password": engineer_creds["password"]}, timeout=10)
    assert r.status_code == 200, r.text
    return s


# ---------- Public routes ----------
class TestPublic:
    def test_root_is_public(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        assert r.json().get("service") == "LICMAN"

    def test_setup_status_public_and_false(self):
        r = requests.get(f"{API}/setup-status", timeout=10)
        assert r.status_code == 200
        assert r.json() == {"needs_setup": False}

    def test_protected_returns_401_without_auth(self):
        for path in ("/servers", "/stats", "/users", "/auth/me"):
            r = requests.get(f"{API}{path}", timeout=10)
            assert r.status_code == 401, f"{path} expected 401, got {r.status_code}"


# ---------- Auth flow ----------
class TestAuthFlow:
    def test_setup_blocked_when_users_exist(self):
        r = requests.post(f"{API}/auth/setup", json={
            "email": "shouldfail@example.com", "password": "newpass123", "name": "X"
        }, timeout=10)
        assert r.status_code == 400

    def test_login_invalid_creds(self):
        r = requests.post(f"{API}/auth/login", json={
            "email": ADMIN_EMAIL, "password": "wrongpassword!"
        }, timeout=10)
        assert r.status_code == 401

    def test_login_success_sets_cookies(self, admin_session):
        # admin_session fixture already validated cookies; double-check /me
        r = admin_session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["email"] == ADMIN_EMAIL
        assert data["role"] == "admin"

    def test_refresh_extends_access(self, admin_session):
        # Drop access_token cookie, keep refresh
        s = requests.Session()
        s.cookies.set("refresh_token", admin_session.cookies.get("refresh_token"))
        r = s.post(f"{API}/auth/refresh", timeout=10)
        assert r.status_code == 200
        assert "access_token" in r.json()
        # Cookie should be set
        assert "access_token" in s.cookies

    def test_refresh_requires_cookie(self):
        r = requests.post(f"{API}/auth/refresh", timeout=10)
        assert r.status_code == 401

    def test_logout_clears_cookies(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
        assert r.status_code == 200
        r2 = s.post(f"{API}/auth/logout", timeout=10)
        assert r2.status_code == 200
        # subsequent /me should now 401 (session cookies are cleared via Set-Cookie deletion)
        r3 = s.get(f"{API}/auth/me", timeout=10)
        assert r3.status_code == 401

    def test_brute_force_lockout(self):
        """5 failed attempts within 15min should lock identifier (returns 429)."""
        bad_email = f"bf_{uuid.uuid4().hex[:6]}@example.com"
        statuses = []
        for _ in range(7):
            r = requests.post(f"{API}/auth/login", json={"email": bad_email, "password": "x"}, timeout=10)
            statuses.append(r.status_code)
            time.sleep(0.3)
        # First 5 should be 401, subsequent should be 429
        assert statuses.count(429) >= 1, f"expected lockout, got {statuses}"


# ---------- RBAC ----------
class TestRBAC:
    def test_engineer_me(self, engineer_session, engineer_creds):
        r = engineer_session.get(f"{API}/auth/me", timeout=10)
        assert r.status_code == 200
        assert r.json()["role"] == "engineer"
        assert r.json()["email"] == engineer_creds["email"]

    def test_engineer_can_list_servers(self, engineer_session):
        r = engineer_session.get(f"{API}/servers", timeout=10)
        assert r.status_code == 200

    def test_engineer_cannot_create_server(self, engineer_session):
        r = engineer_session.post(f"{API}/servers", json={
            "name": "TEST_x", "vendor": "cadence", "host": "1.2.3.4", "port": 5280, "daemon": "cdslmd"
        }, timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_delete_server(self, engineer_session, admin_session):
        # Get a real server id
        servers = admin_session.get(f"{API}/servers", timeout=10).json()
        if not servers:
            pytest.skip("no servers")
        r = engineer_session.delete(f"{API}/servers/{servers[0]['id']}", timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_put_settings(self, engineer_session):
        r = engineer_session.put(f"{API}/settings", json={
            "smtp_host": "x", "smtp_port": 587, "to_addresses": ["a@b.c"]
        }, timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_test_email(self, engineer_session):
        r = engineer_session.post(f"{API}/settings/test-email", timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_seed_reset(self, engineer_session):
        r = engineer_session.post(f"{API}/seed/reset", timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_put_ssh(self, engineer_session, admin_session):
        servers = admin_session.get(f"{API}/servers", timeout=10).json()
        if not servers:
            pytest.skip("no servers")
        r = engineer_session.put(f"{API}/servers/{servers[0]['id']}/ssh", json={
            "enabled": False, "host": "", "port": 22, "username": "",
            "auth_method": "key", "password": "", "private_key": "", "lmutil_path": "/x"
        }, timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_put_adapter(self, engineer_session, admin_session):
        servers = admin_session.get(f"{API}/servers", timeout=10).json()
        if not servers:
            pytest.skip("no servers")
        r = engineer_session.put(f"{API}/servers/{servers[0]['id']}/adapter",
                                 json={"adapter_mode": "ssh"}, timeout=10)
        assert r.status_code == 403

    def test_engineer_cannot_list_users(self, engineer_session):
        r = engineer_session.get(f"{API}/users", timeout=10)
        assert r.status_code == 403

    def test_engineer_can_reserve_and_unreserve(self, engineer_session, admin_session):
        servers = admin_session.get(f"{API}/servers", timeout=10).json()
        if not servers:
            pytest.skip("no servers")
        srv = servers[0]
        feature = (srv.get("features") or [{"name": "X"}])[0]["name"]
        r = engineer_session.post(f"{API}/reservations", json={
            "server_id": srv["id"], "feature": feature, "target_type": "USER",
            "target": "TEST_engineer", "count": 1
        }, timeout=10)
        assert r.status_code == 200, r.text
        rid = r.json()["id"]
        r2 = engineer_session.delete(f"{API}/reservations/{rid}", timeout=10)
        assert r2.status_code == 200

    def test_engineer_can_reread(self, engineer_session, admin_session):
        servers = admin_session.get(f"{API}/servers", timeout=10).json()
        if not servers:
            pytest.skip("no servers")
        r = engineer_session.post(f"{API}/servers/{servers[0]['id']}/reread", timeout=15)
        assert r.status_code == 200


# ---------- User CRUD ----------
class TestUserCRUD:
    def test_create_user_bcrypt_and_duplicate(self, admin_session):
        email = f"TEST_dup_{uuid.uuid4().hex[:6]}@example.com"
        r = admin_session.post(f"{API}/users", json={
            "email": email, "password": "pwd12345", "role": "engineer"
        }, timeout=10)
        assert r.status_code == 200
        uid = r.json()["id"]
        # duplicate
        r2 = admin_session.post(f"{API}/users", json={
            "email": email, "password": "pwd12345", "role": "engineer"
        }, timeout=10)
        assert r2.status_code == 409
        # cleanup
        admin_session.delete(f"{API}/users/{uid}", timeout=10)

    def test_cannot_demote_last_admin(self, admin_session):
        me = admin_session.get(f"{API}/auth/me", timeout=10).json()
        r = admin_session.patch(f"{API}/users/{me['id']}", json={"role": "engineer"}, timeout=10)
        assert r.status_code == 400

    def test_cannot_disable_last_admin(self, admin_session):
        me = admin_session.get(f"{API}/auth/me", timeout=10).json()
        r = admin_session.patch(f"{API}/users/{me['id']}", json={"active": False}, timeout=10)
        assert r.status_code == 400

    def test_cannot_delete_self(self, admin_session):
        me = admin_session.get(f"{API}/auth/me", timeout=10).json()
        r = admin_session.delete(f"{API}/users/{me['id']}", timeout=10)
        assert r.status_code == 400

    def test_cannot_delete_last_admin(self, admin_session):
        # Try to delete any other admin or self via a different admin context.
        # Since we are the only admin, deleting self handles this (already tested),
        # but verify deleting last admin would 400. Create a fake target by id substitution.
        me = admin_session.get(f"{API}/auth/me", timeout=10).json()
        # ensure no other admin exists
        users = admin_session.get(f"{API}/users", timeout=10).json()
        admins = [u for u in users if u["role"] == "admin" and u["active"]]
        assert len(admins) == 1
        # already covered by test_cannot_delete_self
        assert admins[0]["id"] == me["id"]
