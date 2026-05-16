"""Iteration 7 — Bulk ops, options validator, CSV exports, webhook channel.

Tests use cookie-based JWT auth via /api/auth/login (admin@example.com / adminpass123).
Engineer-role tests create a fresh user via POST /api/users (admin) and re-login
as that user to verify 403 on admin-only endpoints.
"""
import os
import re
import time
import uuid
import requests
import pytest

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or "https://eda-license-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "adminpass123"


# ---------- Auth helpers ----------
@pytest.fixture(scope="module")
def admin_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    assert "access_token" in s.cookies, "access_token cookie missing"
    return s


@pytest.fixture(scope="module")
def engineer_client(admin_client):
    """Create + login as a temp engineer-role user."""
    email = f"TEST_eng_{uuid.uuid4().hex[:6]}@example.com"
    password = "engpass123"
    r = admin_client.post(f"{API}/users",
                          json={"email": email, "password": password,
                                "role": "engineer", "full_name": "Test Eng"})
    assert r.status_code in (200, 201), f"user create failed: {r.status_code} {r.text}"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/login",
               json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"engineer login failed: {r.text}"
    return s


# =====================================================================
# 1) Bulk ops: sync-all
# =====================================================================
class TestSyncAll:
    def test_sync_all_admin_returns_shape(self, admin_client):
        r = admin_client.post(f"{API}/servers/sync-all", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("ok", "count", "features_total", "checkouts_total", "results"):
            assert k in d, f"missing key {k}"
        assert isinstance(d["results"], list)
        assert isinstance(d["count"], int)
        # In sandbox seeded servers default to adapter_mode='mock' so count==0 is OK.

    def test_sync_all_engineer_forbidden(self, engineer_client):
        r = engineer_client.post(f"{API}/servers/sync-all", timeout=15)
        assert r.status_code == 403, f"engineer should be 403, got {r.status_code}"

    def test_sync_all_anonymous_unauthorized(self):
        r = requests.post(f"{API}/servers/sync-all", timeout=15)
        assert r.status_code in (401, 403)


# =====================================================================
# 2) Bulk ops: reread-all
# =====================================================================
class TestRereadAll:
    def test_reread_all_admin(self, admin_client):
        r = admin_client.post(f"{API}/servers/reread-all", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["count"] >= 1, "expected at least one seeded server"
        assert isinstance(d["results"], list)
        assert len(d["results"]) == d["count"]
        for row in d["results"]:
            assert "server_id" in row and "name" in row
            assert "ok" in row

    def test_reread_all_engineer_forbidden(self, engineer_client):
        r = engineer_client.post(f"{API}/servers/reread-all", timeout=15)
        assert r.status_code == 403


# =====================================================================
# 3) Options file validator
# =====================================================================
class TestOptionsValidator:
    @pytest.fixture(scope="class")
    def server_id(self, admin_client):
        rs = admin_client.get(f"{API}/servers").json()
        assert rs, "no servers seeded"
        return rs[0]["id"]

    def test_valid_options(self, admin_client, server_id):
        content = "\n".join([
            "# comment",
            "RESERVE 2 ace USER alice",
            "INCLUDE ace USER bob",
            "EXCLUDE ace HOST blade01",
            "GROUP designers alice bob carol",
            "MAX 4 ace USER alice",
            "TIMEOUT ace 7200",
        ])
        r = admin_client.post(f"{API}/servers/{server_id}/options/validate",
                              json={"content": content})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True, d
        assert d["errors"] == 0
        s = d["summary"]
        assert s["reserve"] >= 1
        assert s["include"] >= 1
        assert s["exclude"] >= 1
        assert s["group"] >= 1
        assert s["max"] >= 1
        assert s["timeout"] >= 1

    def test_invalid_directive(self, admin_client, server_id):
        r = admin_client.post(f"{API}/servers/{server_id}/options/validate",
                              json={"content": "FOO bar baz"})
        assert r.status_code == 200
        d = r.json()
        assert d["ok"] is False
        assert d["errors"] >= 1
        assert any(i["severity"] == "error" for i in d["issues"])

    def test_unknown_target_type_warning(self, admin_client, server_id):
        # EXCLUDE feat XYZ name where XYZ not a known target type
        r = admin_client.post(f"{API}/servers/{server_id}/options/validate",
                              json={"content": "EXCLUDE feat XYZ name"})
        assert r.status_code == 200
        d = r.json()
        # Should produce a 'warning' severity issue
        assert any(i["severity"] == "warning" for i in d["issues"]), d


# =====================================================================
# 4) CSV exports
# =====================================================================
class TestCSVExports:
    def test_expiry_export_csv(self, admin_client):
        r = admin_client.get(f"{API}/expiry/export", timeout=30)
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "text/csv" in ctype.lower(), ctype
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        first = r.text.splitlines()[0]
        for col in ("vendor", "server_name", "feature", "version", "total", "expires"):
            assert col in first, f"missing column {col} in: {first}"

    def test_audit_export_csv(self, admin_client):
        r = admin_client.get(f"{API}/audit/export?limit=5", timeout=30)
        assert r.status_code == 200
        ctype = r.headers.get("content-type", "")
        assert "text/csv" in ctype.lower()
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd.lower()
        first = r.text.splitlines()[0]
        for col in ("timestamp", "actor", "severity", "action"):
            assert col in first, f"missing column {col} in: {first}"


# =====================================================================
# 5) Webhook settings
# =====================================================================
class TestWebhookSettings:
    def test_get_settings_exposes_webhook_fields(self, admin_client):
        r = admin_client.get(f"{API}/settings")
        assert r.status_code == 200
        d = r.json()
        for k in ("webhook_url", "webhook_kind", "webhook_enabled"):
            assert k in d, f"webhook key {k} missing from /settings"

    def test_put_settings_persists_webhook(self, admin_client):
        # Read current then patch in webhook fields
        cur = admin_client.get(f"{API}/settings").json()
        payload = {**cur}
        # Strip non-payload helpers
        payload.pop("smtp_password_set", None)
        payload["smtp_password"] = ""  # masked → preserved
        payload["webhook_url"] = "https://hooks.slack.com/services/T000/B000/FAKE"
        payload["webhook_kind"] = "slack"
        payload["webhook_enabled"] = True
        r = admin_client.put(f"{API}/settings", json=payload)
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["webhook_url"] == payload["webhook_url"]
        assert out["webhook_kind"] == "slack"
        assert out["webhook_enabled"] is True
        # GET should also show it
        g = admin_client.get(f"{API}/settings").json()
        assert g["webhook_url"] == payload["webhook_url"]
        assert g["webhook_kind"] == "slack"
        assert g["webhook_enabled"] is True

    def test_test_webhook_400_when_url_unset(self, admin_client):
        cur = admin_client.get(f"{API}/settings").json()
        payload = {**cur}
        payload.pop("smtp_password_set", None)
        payload["smtp_password"] = ""
        payload["webhook_url"] = ""
        payload["webhook_enabled"] = False
        admin_client.put(f"{API}/settings", json=payload)
        r = admin_client.post(f"{API}/settings/test-webhook", timeout=15)
        assert r.status_code == 400, r.text

    def test_test_webhook_invalid_url_returns_200_with_error(self, admin_client):
        cur = admin_client.get(f"{API}/settings").json()
        payload = {**cur}
        payload.pop("smtp_password_set", None)
        payload["smtp_password"] = ""
        payload["webhook_url"] = "https://invalid-host.example.invalid/hook"
        payload["webhook_kind"] = "generic"
        payload["webhook_enabled"] = True
        admin_client.put(f"{API}/settings", json=payload)
        r = admin_client.post(f"{API}/settings/test-webhook", timeout=30)
        # Must be a graceful 200 (not a 500)
        assert r.status_code == 200, f"got {r.status_code}: {r.text}"
        d = r.json()
        assert d["ok"] is False
        assert d.get("error"), "expected non-empty error string"

    def test_test_webhook_admin_only(self, engineer_client):
        r = engineer_client.post(f"{API}/settings/test-webhook", timeout=15)
        assert r.status_code == 403


# =====================================================================
# 6) Auth regression
# =====================================================================
class TestAuthRegression:
    def test_setup_status_after_admin_exists(self):
        r = requests.get(f"{API}/setup-status", timeout=10)
        assert r.status_code == 200
        # admin already seeded; needs_setup must be False
        assert r.json().get("needs_setup") is False

    def test_login_sets_both_cookies(self):
        s = requests.Session()
        r = s.post(f"{API}/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        assert r.status_code == 200
        assert "access_token" in s.cookies
        assert "refresh_token" in s.cookies

    def test_me_endpoint(self, admin_client):
        r = admin_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        d = r.json()
        assert d["email"] == ADMIN_EMAIL
        assert d["role"] == "admin"

    def test_logout_clears_cookies(self):
        s = requests.Session()
        s.post(f"{API}/auth/login",
               json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
        r = s.post(f"{API}/auth/logout", timeout=10)
        assert r.status_code == 200
        # after logout, /me should be 401
        r2 = s.get(f"{API}/auth/me", timeout=10)
        assert r2.status_code in (401, 403)


# =====================================================================
# 7) SSH config encryption-at-rest round-trip
# =====================================================================
class TestSSHRoundTrip:
    def test_ssh_password_and_key_round_trip_masked(self, admin_client):
        sid = admin_client.get(f"{API}/servers").json()[0]["id"]
        # Write real values
        payload = {
            "enabled": True, "host": "10.0.0.42", "port": 22,
            "username": "licmgr", "auth_method": "password",
            "password": "SuperSecretP@ss!", "private_key": "-----BEGIN KEY-----\nABC\n-----END KEY-----",
            "lmutil_path": "/opt/flexlm/lmutil",
        }
        r = admin_client.put(f"{API}/servers/{sid}/ssh", json=payload)
        assert r.status_code == 200
        out = r.json()
        # Must be masked, not plaintext
        assert out["ssh"].get("password") in ("********", None)
        assert out["ssh"].get("private_key") in ("********", None)
        # GET round-trip
        g = admin_client.get(f"{API}/servers/{sid}").json()
        assert g["ssh"]["host"] == "10.0.0.42"
        assert g["ssh"].get("password") in ("********", None)
        # Now PUT again with masked value – should NOT lose the encrypted blob
        masked = {**payload, "password": "********", "private_key": "********"}
        r2 = admin_client.put(f"{API}/servers/{sid}/ssh", json=masked)
        assert r2.status_code == 200
        g2 = admin_client.get(f"{API}/servers/{sid}").json()
        # Indicator should still be set / mask still shows
        assert g2["ssh"].get("password") in ("********", None)


# =====================================================================
# 8) Sync 400 when adapter not ssh
# =====================================================================
class TestSyncSingleAdapterGuard:
    def test_sync_requires_ssh_adapter(self, admin_client):
        sid = admin_client.get(f"{API}/servers").json()[0]["id"]
        admin_client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "mock"})
        r = admin_client.post(f"{API}/servers/{sid}/sync")
        assert r.status_code == 400, r.text
