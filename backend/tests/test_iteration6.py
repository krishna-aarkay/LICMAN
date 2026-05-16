"""Iteration 6 backend tests: encryption at rest, redaction, health/ready, indexes, COOKIE_SECURE.

Verifies:
- /api/health (public, no DB)
- /api/ready (public, DB ping)
- SSH password/private_key never returned in plaintext
- PUT /servers/{id}/ssh persists 'enc::v1::' prefix in DB; masked roundtrip preserves
- /api/settings smtp_password redaction + smtp_password_set flag
- PUT /api/settings encrypts smtp_password at rest; masked roundtrip preserves
- /api/audit does not leak BSON 'ts' field
- MongoDB indexes (servers.id unique, vendor; audit TTL on 'ts')
"""
import os
import uuid
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://eda-license-portal.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@example.com"
ADMIN_PASS = "adminpass123"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")


# --------------------- fixtures ---------------------

@pytest.fixture(scope="module")
def admin_session():
    s = requests.Session()
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    if r.status_code != 200:
        # try first-run setup
        s.post(f"{API}/auth/setup", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS, "name": "Admin"}, timeout=15)
        r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


@pytest.fixture(scope="module")
def created_server_id(admin_session):
    """Pick an existing server or create a fresh one for SSH tests."""
    r = admin_session.get(f"{API}/servers", timeout=15)
    assert r.status_code == 200
    servers = r.json()
    if servers:
        return servers[0]["id"]
    # create one
    r = admin_session.post(f"{API}/servers", json={
        "name": f"TEST_iter6_{uuid.uuid4().hex[:6]}",
        "vendor": "synopsys", "host": "10.0.0.10", "port": 27000, "daemon": "snpslmd",
    }, timeout=15)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --------------------- public endpoints ---------------------

# Health endpoint
def test_health_public_no_auth():
    r = requests.get(f"{API}/health", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"


# Readiness endpoint
def test_ready_public_db_ping():
    r = requests.get(f"{API}/ready", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# --------------------- COOKIE_SECURE ---------------------

# Check Set-Cookie flag honors COOKIE_SECURE env var
def test_login_set_cookie_secure_flag():
    # Just verify response headers contain Set-Cookie and behavior is consistent with env var
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=15)
    assert r.status_code == 200
    cookies_header = r.headers.get("set-cookie", "") or ""
    # Multiple Set-Cookie headers may exist; requests collapses
    raw = "\n".join(v for k, v in r.raw.headers.items() if k.lower() == "set-cookie") or cookies_header
    secure_env = os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
    has_secure = "Secure" in raw
    # When env is true, both access+refresh cookies should include Secure
    if secure_env:
        assert has_secure, f"COOKIE_SECURE=true but Secure flag missing in Set-Cookie: {raw}"
    # When env is false, we still expect HttpOnly + SameSite
    assert "HttpOnly" in raw
    assert "SameSite" in raw or "samesite" in raw.lower()


# --------------------- SSH redaction + encryption ---------------------

# GET /api/servers must never return ssh.password / private_key plaintext
def test_list_servers_ssh_redacted(admin_session):
    r = admin_session.get(f"{API}/servers", timeout=15)
    assert r.status_code == 200
    for s in r.json():
        ssh = s.get("ssh", {}) or {}
        pw = ssh.get("password", "")
        pk = ssh.get("private_key", "")
        assert pw in ("", "********"), f"plaintext password leaked in /servers: {pw!r}"
        assert pk in ("", "********"), f"plaintext private_key leaked: {pk!r}"


# PUT /servers/{id}/ssh encrypts password at rest (DB value starts with enc::v1::)
@pytest.mark.asyncio
async def test_ssh_password_encrypted_at_rest(admin_session, created_server_id):
    secret = f"PlainPassword_{uuid.uuid4().hex[:8]}"
    r = admin_session.put(
        f"{API}/servers/{created_server_id}/ssh",
        json={"enabled": True, "host": "10.0.0.50", "port": 22,
              "username": "lmadmin", "password": secret, "private_key": "",
              "lmstat_path": "/usr/local/bin/lmstat", "lmutil_path": "/usr/local/bin/lmutil",
              "lmreread_path": "/usr/local/bin/lmreread"},
        timeout=15,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Response is redacted
    assert body["ssh"]["password"] == "********"
    # Raw DB doc has enc::v1:: prefix
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        doc = await client[DB_NAME].servers.find_one({"id": created_server_id}, {"_id": 0, "ssh": 1})
        assert doc and doc.get("ssh", {}).get("password", "").startswith("enc::v1::"), \
            f"password not encrypted: {doc!r}"
    finally:
        client.close()


# PUT with masked password preserves encrypted DB value (no overwrite)
@pytest.mark.asyncio
async def test_ssh_masked_password_preserves(admin_session, created_server_id):
    # First ensure password is set
    initial_secret = f"OrigSecret_{uuid.uuid4().hex[:8]}"
    admin_session.put(
        f"{API}/servers/{created_server_id}/ssh",
        json={"enabled": True, "host": "10.0.0.50", "port": 22, "username": "lmadmin",
              "password": initial_secret, "private_key": "",
              "lmstat_path": "/usr/local/bin/lmstat", "lmutil_path": "/usr/local/bin/lmutil",
              "lmreread_path": "/usr/local/bin/lmreread"},
        timeout=15,
    )
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        before = await client[DB_NAME].servers.find_one({"id": created_server_id}, {"_id": 0, "ssh": 1})
        before_enc = before["ssh"]["password"]
        assert before_enc.startswith("enc::v1::")
        # Now PUT with masked
        r = admin_session.put(
            f"{API}/servers/{created_server_id}/ssh",
            json={"enabled": True, "host": "10.0.0.50", "port": 22, "username": "lmadmin",
                  "password": "********", "private_key": "",
                  "lmstat_path": "/usr/local/bin/lmstat", "lmutil_path": "/usr/local/bin/lmutil",
                  "lmreread_path": "/usr/local/bin/lmreread"},
            timeout=15,
        )
        assert r.status_code == 200
        after = await client[DB_NAME].servers.find_one({"id": created_server_id}, {"_id": 0, "ssh": 1})
        assert after["ssh"]["password"] == before_enc, "masked PUT must preserve existing encrypted password"
    finally:
        client.close()


# Empty-string password also preserves (per requirement)
@pytest.mark.asyncio
async def test_ssh_empty_password_preserves(admin_session, created_server_id):
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        # ensure encrypted password exists
        admin_session.put(
            f"{API}/servers/{created_server_id}/ssh",
            json={"enabled": True, "host": "10.0.0.50", "port": 22, "username": "lmadmin",
                  "password": f"S_{uuid.uuid4().hex[:6]}", "private_key": "",
                  "lmstat_path": "/usr/local/bin/lmstat", "lmutil_path": "/usr/local/bin/lmutil",
                  "lmreread_path": "/usr/local/bin/lmreread"},
            timeout=15,
        )
        before = await client[DB_NAME].servers.find_one({"id": created_server_id}, {"_id": 0, "ssh": 1})
        before_enc = before["ssh"]["password"]
        # now PUT with empty
        r = admin_session.put(
            f"{API}/servers/{created_server_id}/ssh",
            json={"enabled": True, "host": "10.0.0.50", "port": 22, "username": "lmadmin",
                  "password": "", "private_key": "",
                  "lmstat_path": "/usr/local/bin/lmstat", "lmutil_path": "/usr/local/bin/lmutil",
                  "lmreread_path": "/usr/local/bin/lmreread"},
            timeout=15,
        )
        assert r.status_code == 200
        after = await client[DB_NAME].servers.find_one({"id": created_server_id}, {"_id": 0, "ssh": 1})
        assert after["ssh"]["password"] == before_enc, "empty-string PUT must preserve existing encrypted password"
    finally:
        client.close()


# SSH test endpoint uses decrypted creds and does NOT crash
def test_ssh_test_endpoint_decrypts_path(admin_session, created_server_id):
    # SSH test will fail because host unreachable, but must NOT 500 from decrypt error
    r = admin_session.post(f"{API}/servers/{created_server_id}/ssh/test", timeout=20)
    # Expect either 200 with ok=False, or specific error code, but NOT 500 from crypto failure
    assert r.status_code in (200, 400, 502, 504), f"unexpected status {r.status_code}: {r.text}"
    if r.status_code == 200:
        body = r.json()
        # 'output' should not contain Fernet/Invalid token traceback signature
        out = str(body)
        assert "InvalidToken" not in out, "decrypt path crashed: InvalidToken leaked"


# --------------------- SMTP redaction + encryption ---------------------

# GET /settings redacts smtp_password and exposes smtp_password_set
def test_settings_smtp_redacted(admin_session):
    r = admin_session.get(f"{API}/settings", timeout=15)
    assert r.status_code == 200
    body = r.json()
    pw = body.get("smtp_password", "")
    assert pw in ("", "********"), f"plaintext smtp_password leaked: {pw!r}"
    assert "smtp_password_set" in body
    assert isinstance(body["smtp_password_set"], bool)


# PUT /settings encrypts smtp_password at rest
@pytest.mark.asyncio
async def test_settings_smtp_encrypted_at_rest(admin_session):
    secret = f"SmtpSecret_{uuid.uuid4().hex[:6]}"
    payload = {
        "enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 587,
        "smtp_user": "alerts@example.com", "smtp_password": secret,
        "smtp_use_tls": True, "from_address": "alerts@example.com",
        "to_addresses": ["ops@example.com"], "expiry_warn_days": 30,
    }
    r = admin_session.put(f"{API}/settings", json=payload, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["smtp_password"] == "********"
    assert body.get("smtp_password_set") is True
    # Verify DB
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        doc = await client[DB_NAME].settings.find_one({"_key": "alerts"}, {"_id": 0})
        assert doc and doc.get("smtp_password", "").startswith("enc::v1::"), \
            f"smtp_password not encrypted in DB: {doc!r}"
    finally:
        client.close()


# PUT /settings with masked smtp_password preserves existing encrypted
@pytest.mark.asyncio
async def test_settings_smtp_masked_preserves(admin_session):
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        before = await client[DB_NAME].settings.find_one({"_key": "alerts"}, {"_id": 0})
        before_enc = before.get("smtp_password", "")
        assert before_enc.startswith("enc::v1::"), "precondition: smtp_password must already be encrypted"
        payload = {
            "enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 587,
            "smtp_user": "alerts@example.com", "smtp_password": "********",
            "smtp_use_tls": True, "from_address": "alerts@example.com",
            "to_addresses": ["ops@example.com"], "expiry_warn_days": 30,
        }
        r = admin_session.put(f"{API}/settings", json=payload, timeout=15)
        assert r.status_code == 200
        after = await client[DB_NAME].settings.find_one({"_key": "alerts"}, {"_id": 0})
        assert after.get("smtp_password") == before_enc, "masked PUT must preserve smtp_password"
    finally:
        client.close()


# --------------------- audit log ---------------------

# /api/audit must not leak BSON 'ts' field
def test_audit_no_ts_field(admin_session):
    r = admin_session.get(f"{API}/audit?limit=20", timeout=15)
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list)
    for row in rows:
        assert "ts" not in row, f"audit row leaks internal 'ts' field: {row}"
        # 'timestamp' ISO string field present
        assert "timestamp" in row
        assert isinstance(row["timestamp"], str)


# --------------------- MongoDB indexes ---------------------

@pytest.mark.asyncio
async def test_mongo_indexes_present():
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        # servers.id unique + vendor
        srv_idx = await client[DB_NAME].servers.index_information()
        # Find an index keyed on id with unique
        id_unique = any(
            v.get("key") == [("id", 1)] and v.get("unique") for v in srv_idx.values()
        )
        vendor_idx = any(v.get("key") == [("vendor", 1)] for v in srv_idx.values())
        assert id_unique, f"servers.id unique index missing: {srv_idx}"
        assert vendor_idx, f"servers.vendor index missing: {srv_idx}"
        # audit TTL on 'ts'
        audit_idx = await client[DB_NAME].audit.index_information()
        ttl_idx = any(
            v.get("key") == [("ts", 1)] and "expireAfterSeconds" in v
            for v in audit_idx.values()
        )
        assert ttl_idx, f"audit TTL index on 'ts' missing: {audit_idx}"
        # checkouts.server_id, reservations.server_id
        co_idx = await client[DB_NAME].checkouts.index_information()
        assert any(v.get("key") == [("server_id", 1)] for v in co_idx.values()), \
            f"checkouts.server_id index missing: {co_idx}"
        rsv_idx = await client[DB_NAME].reservations.index_information()
        assert any(v.get("key") == [("server_id", 1)] for v in rsv_idx.values()), \
            f"reservations.server_id index missing: {rsv_idx}"
    finally:
        client.close()


# --------------------- regression: prior iteration core flows ---------------------

def test_setup_status_public():
    r = requests.get(f"{API}/setup-status", timeout=10)
    assert r.status_code == 200
    assert "needs_setup" in r.json()


def test_servers_requires_auth():
    r = requests.get(f"{API}/servers", timeout=10)
    assert r.status_code == 401


def test_auth_me(admin_session):
    r = admin_session.get(f"{API}/auth/me", timeout=10)
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["role"] == "admin"


def test_stats_endpoint(admin_session):
    r = admin_session.get(f"{API}/stats", timeout=15)
    assert r.status_code == 200
    body = r.json()
    for k in ("servers_total", "servers_up", "features_total", "checkouts_active", "reservations"):
        assert k in body


def test_test_email_requires_admin(admin_session):
    # admin should not 403 (might 400 SMTP not configured but that's fine)
    r = admin_session.post(f"{API}/settings/test-email", timeout=15)
    assert r.status_code != 403, f"admin got 403 on test-email: {r.text}"
