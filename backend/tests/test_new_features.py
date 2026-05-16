"""Tests for LICMAN new features: SSH adapter, SMTP alerts, Expiry."""
import os
import pytest
import requests

BASE_URL = (os.environ.get('REACT_APP_BACKEND_URL') or 'https://eda-license-portal.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module", autouse=True)
def reset_seed(client):
    r = client.post(f"{API}/seed/reset", timeout=30)
    assert r.status_code == 200
    yield


# ---------- Settings ----------
def test_get_settings_defaults(client):
    r = client.get(f"{API}/settings")
    assert r.status_code == 200
    d = r.json()
    for k in ["smtp_host", "smtp_port", "smtp_username", "from_address",
              "to_addresses", "enabled", "starttls", "alert_on_saturation",
              "alert_on_expiry", "expiry_warn_days"]:
        assert k in d, f"missing {k}"


def test_put_settings_persists(client):
    payload = {
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_username": "alerts@example.com",
        "smtp_password": "secret123",
        "from_address": "alerts@example.com",
        "to_addresses": ["ops@example.com", "team@example.com"],
        "enabled": True,
        "starttls": True,
        "alert_on_saturation": True,
        "alert_on_expiry": True,
        "expiry_warn_days": 45,
    }
    r = client.put(f"{API}/settings", json=payload)
    assert r.status_code == 200
    out = r.json()
    # Password masked, indicator set
    assert "smtp_password" not in out
    assert out.get("smtp_password_set") is True
    assert out["smtp_host"] == "smtp.office365.com"
    assert out["expiry_warn_days"] == 45
    assert out["to_addresses"] == ["ops@example.com", "team@example.com"]

    # Verify GET returns persisted values
    g = client.get(f"{API}/settings").json()
    assert g["smtp_host"] == "smtp.office365.com"
    assert g["expiry_warn_days"] == 45
    assert g["enabled"] is True


# ---------- Test email ----------
def test_test_email_400_when_no_smtp_host(client):
    # First reset settings to empty (no host)
    client.put(f"{API}/settings", json={
        "smtp_host": "", "smtp_port": 587, "smtp_username": "", "smtp_password": "",
        "from_address": "", "to_addresses": [],
        "enabled": False, "starttls": True,
        "alert_on_saturation": True, "alert_on_expiry": True, "expiry_warn_days": 30,
    })
    r = client.post(f"{API}/settings/test-email")
    assert r.status_code == 400


def test_test_email_400_when_no_recipients(client):
    client.put(f"{API}/settings", json={
        "smtp_host": "smtp.office365.com", "smtp_port": 587,
        "smtp_username": "u", "smtp_password": "p",
        "from_address": "u@example.com", "to_addresses": [],
        "enabled": False, "starttls": True,
        "alert_on_saturation": True, "alert_on_expiry": True, "expiry_warn_days": 30,
    })
    r = client.post(f"{API}/settings/test-email")
    assert r.status_code == 400


def test_test_email_attempts_and_logs(client):
    # Configure with host + recipients; SMTP is unreachable but endpoint must not crash
    client.put(f"{API}/settings", json={
        "smtp_host": "smtp.invalid-host.example.com", "smtp_port": 587,
        "smtp_username": "u", "smtp_password": "p",
        "from_address": "u@example.com", "to_addresses": ["ops@example.com"],
        "enabled": True, "starttls": True,
        "alert_on_saturation": True, "alert_on_expiry": True, "expiry_warn_days": 30,
    })
    r = client.post(f"{API}/settings/test-email", timeout=30)
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body and "error" in body
    # delivery is expected to fail (no real SMTP) but it should not crash
    assert body["ok"] is False
    assert body["error"]

    # Alert event of kind=test must be logged
    alerts = client.get(f"{API}/alerts?limit=50").json()
    assert any(a["kind"] == "test" for a in alerts)


# ---------- Alerts ----------
def test_alerts_sorted_desc(client):
    r = client.get(f"{API}/alerts?limit=20")
    assert r.status_code == 200
    data = r.json()
    ts = [d["timestamp"] for d in data]
    assert ts == sorted(ts, reverse=True)


def test_alerts_evaluate_endpoint(client):
    # Reset to clear prior alerts
    client.post(f"{API}/seed/reset")
    before = client.get(f"{API}/alerts").json()
    assert before == []
    # Force evaluate up to 10 times (random saturation odds)
    for _ in range(10):
        r = client.post(f"{API}/alerts/evaluate")
        assert r.status_code == 200
        after = client.get(f"{API}/alerts").json()
        if any(a["kind"] == "saturation" for a in after):
            return
    pytest.fail("No saturation alerts created after 10 evaluations")


def test_checkouts_triggers_alert_evaluation(client):
    client.post(f"{API}/seed/reset")
    fired = False
    for _ in range(15):
        client.get(f"{API}/checkouts")
        alerts = client.get(f"{API}/alerts").json()
        if any(a["kind"] in ("saturation", "expiry") for a in alerts):
            fired = True
            break
    assert fired, "GET /api/checkouts did not trigger alert evaluation side-effect"


def test_seed_reset_clears_alert_events(client):
    # ensure some alert exists
    for _ in range(10):
        client.post(f"{API}/alerts/evaluate")
        if client.get(f"{API}/alerts").json():
            break
    r = client.post(f"{API}/seed/reset")
    assert r.status_code == 200
    assert client.get(f"{API}/alerts").json() == []


# ---------- Expiry ----------
def test_expiry_rows_and_sorting(client):
    r = client.get(f"{API}/expiry")
    assert r.status_code == 200
    rows = r.json()
    assert isinstance(rows, list) and len(rows) > 0
    needed = {"server_id", "server_name", "vendor", "feature",
              "expires", "days_remaining", "status"}
    for row in rows:
        assert needed.issubset(row.keys())
        assert row["status"] in ("expired", "critical", "warning", "ok", "permanent")
    # Sort assertion: expired(0) -> by days asc; future(1) -> by days asc; permanent(2) last
    def sk(r):
        d = r["days_remaining"]
        if d is None:
            return (2, 0)
        if d < 0:
            return (0, d)
        return (1, d)
    keys = [sk(r) for r in rows]
    assert keys == sorted(keys)


# ---------- SSH config ----------
def test_put_ssh_config_persists(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    payload = {
        "enabled": True, "host": "10.0.0.5", "port": 2222,
        "username": "licmgr", "auth_method": "key",
        "password": "", "private_key": "-----BEGIN KEY-----\nXXX\n-----END KEY-----",
        "lmutil_path": "/opt/flexlm/lmutil",
    }
    r = client.put(f"{API}/servers/{sid}/ssh", json=payload)
    assert r.status_code == 200
    out = r.json()
    assert out["ssh"]["host"] == "10.0.0.5"
    assert out["ssh"]["port"] == 2222
    assert out["ssh"]["username"] == "licmgr"
    assert out["ssh"]["auth_method"] == "key"
    assert out["ssh"]["enabled"] is True

    g = client.get(f"{API}/servers/{sid}").json()
    assert g["ssh"]["host"] == "10.0.0.5"


def test_put_adapter_mode(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    r = client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "ssh"})
    assert r.status_code == 200
    assert r.json()["adapter_mode"] == "ssh"
    g = client.get(f"{API}/servers/{sid}").json()
    assert g["adapter_mode"] == "ssh"

    r = client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "mock"})
    assert r.status_code == 200
    assert r.json()["adapter_mode"] == "mock"


def test_put_adapter_invalid(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    r = client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "invalid"})
    assert r.status_code == 422


def test_ssh_test_success(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    # Configure host + user
    client.put(f"{API}/servers/{sid}/ssh", json={
        "enabled": True, "host": "10.0.0.5", "port": 22, "username": "licmgr",
        "auth_method": "key", "password": "", "private_key": "K",
        "lmutil_path": "/usr/local/flexlm/lmutil",
    })
    r = client.post(f"{API}/servers/{sid}/ssh/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["mocked"] is True


def test_ssh_test_fails_when_missing(client):
    sid = client.get(f"{API}/servers").json()[1]["id"]
    # Clear ssh config
    client.put(f"{API}/servers/{sid}/ssh", json={
        "enabled": False, "host": "", "port": 22, "username": "",
        "auth_method": "key", "password": "", "private_key": "",
        "lmutil_path": "/usr/local/flexlm/lmutil",
    })
    r = client.post(f"{API}/servers/{sid}/ssh/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["mocked"] is True


# ---------- exec mode logged ----------
def test_reread_records_mode(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    # mock mode
    client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "mock"})
    r = client.post(f"{API}/servers/{sid}/reread")
    assert r.status_code == 200
    assert r.json()["exec"]["mode"] == "mock"
    g = client.get(f"{API}/servers/{sid}").json()
    assert "mock" in g["last_action"]

    # ssh mode (stub)
    client.put(f"{API}/servers/{sid}/ssh", json={
        "enabled": True, "host": "h", "port": 22, "username": "u",
        "auth_method": "key", "password": "", "private_key": "K",
        "lmutil_path": "/usr/local/flexlm/lmutil",
    })
    client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "ssh"})
    r = client.post(f"{API}/servers/{sid}/restart")
    assert r.status_code == 200
    # Iteration 3: real paramiko is invoked when adapter='ssh' and ssh.enabled.
    # Host is unreachable in sandbox => mode is "ssh-error" (graceful), not "ssh-stub".
    mode = r.json()["exec"]["mode"]
    assert mode in ("ssh", "ssh-error", "ssh-stub")
    g = client.get(f"{API}/servers/{sid}").json()
    assert any(m in g["last_action"] for m in ("ssh", "ssh-error", "ssh-stub"))
