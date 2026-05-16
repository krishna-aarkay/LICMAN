"""Iteration 3 tests: free-form vendor, new seed (10.10.11.x), real paramiko SSH, DEMO_MODE."""
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


# ---------- Free-form vendor ----------
@pytest.mark.parametrize("vendor", ["xilinx", "defacto", "custom-anything", "altium", "TEST_vendor_NEW"])
def test_create_server_accepts_arbitrary_vendor(client, vendor):
    payload = {
        "name": f"TEST_{vendor}_srv",
        "vendor": vendor,
        "host": "10.10.11.200",
        "port": 27000,
        "daemon": "lmgrd",
    }
    r = client.post(f"{API}/servers", json=payload)
    assert r.status_code == 200, f"Expected 200 for vendor={vendor}, got {r.status_code}: {r.text}"
    data = r.json()
    # Backend lowercases vendor? Check create_server flow - it preserves payload.vendor as-is
    assert data["vendor"] == vendor
    assert data["name"] == payload["name"]
    assert "id" in data
    # Verify persistence
    g = client.get(f"{API}/servers/{data['id']}")
    assert g.status_code == 200
    assert g.json()["vendor"] == vendor
    # Cleanup
    client.delete(f"{API}/servers/{data['id']}")


# ---------- New seed: 10.10.11.x ----------
def test_seed_reset_creates_new_hosts(client):
    r = client.post(f"{API}/seed/reset", timeout=30)
    assert r.status_code == 200
    servers = client.get(f"{API}/servers").json()
    assert len(servers) == 3
    by_vendor = {s["vendor"]: s for s in servers}
    assert "cadence" in by_vendor
    assert "siemens" in by_vendor, "Iteration 3 expects 'siemens' (replacing 'mentor')"
    assert "synopsys" in by_vendor
    # 'mentor' should NOT be in the seed anymore
    assert "mentor" not in by_vendor

    # Verify host/port/daemon mapping per spec
    assert by_vendor["cadence"]["host"] == "10.10.11.111"
    assert by_vendor["cadence"]["port"] == 5280
    assert by_vendor["cadence"]["daemon"] == "cdslmd"

    assert by_vendor["siemens"]["host"] == "10.10.11.112"
    assert by_vendor["siemens"]["port"] == 1717
    assert by_vendor["siemens"]["daemon"] == "mgcld"

    assert by_vendor["synopsys"]["host"] == "10.10.11.113"
    assert by_vendor["synopsys"]["port"] == 27020
    assert by_vendor["synopsys"]["daemon"] == "snpslmd"


# ---------- SSH test endpoint with free-form vendor ----------
def test_ssh_test_returns_mocked_flag(client):
    # Add a xilinx server
    r = client.post(f"{API}/servers", json={
        "name": "TEST_xilinx_ssh", "vendor": "xilinx", "host": "10.10.11.114",
        "port": 2100, "daemon": "xilinxd",
    })
    sid = r.json()["id"]
    try:
        # Without ssh config -> should return ok=False, mocked=True (graceful)
        rr = client.post(f"{API}/servers/{sid}/ssh/test", timeout=20)
        assert rr.status_code == 200
        body = rr.json()
        assert "ok" in body and "mocked" in body
        assert body["mocked"] is True

        # Configure ssh + enabled=True; in sandbox host is unreachable —
        # endpoint should still return 200 with mocked=True per backend stub
        client.put(f"{API}/servers/{sid}/ssh", json={
            "enabled": True, "host": "10.10.11.114", "port": 22,
            "username": "licmgr", "auth_method": "key",
            "password": "", "private_key": "K",
            "lmutil_path": "/usr/local/flexlm/lmutil",
        })
        rr = client.post(f"{API}/servers/{sid}/ssh/test", timeout=30)
        assert rr.status_code == 200, f"ssh/test should not 500 on unreachable host: {rr.text}"
        b = rr.json()
        # Either the stub form (mocked=True) or a graceful failure
        assert "ok" in b
        assert "mocked" in b
    finally:
        client.delete(f"{API}/servers/{sid}")


# ---------- PUT adapter works for non-Literal vendors ----------
def test_put_adapter_for_custom_vendor(client):
    r = client.post(f"{API}/servers", json={
        "name": "TEST_defacto_adapter", "vendor": "defacto",
        "host": "10.10.11.150", "port": 27000, "daemon": "defacto",
    })
    sid = r.json()["id"]
    try:
        # adapter=ssh
        a = client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "ssh"})
        assert a.status_code == 200
        assert a.json()["adapter_mode"] == "ssh"
        g = client.get(f"{API}/servers/{sid}").json()
        assert g["adapter_mode"] == "ssh"

        # adapter=mock back
        a = client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "mock"})
        assert a.status_code == 200
        assert a.json()["adapter_mode"] == "mock"
    finally:
        client.delete(f"{API}/servers/{sid}")


# ---------- Expiry handles custom vendors ----------
def test_expiry_includes_custom_vendors(client):
    # Create a xilinx server with a feature
    r = client.post(f"{API}/servers", json={
        "name": "TEST_xilinx_expiry", "vendor": "xilinx",
        "host": "10.10.11.115", "port": 2100, "daemon": "xilinxd",
    })
    sid = r.json()["id"]
    try:
        # Inject features by saving a license file with FEATURE line
        lic = ("SERVER lic-xilinx-01 ANY 2100\nVENDOR xilinxd\nUSE_SERVER\n"
               "FEATURE Vivado xilinxd 1.0 31-dec-2026 4 SIGN=abc\n")
        s = client.put(f"{API}/servers/{sid}/license", json={"content": lic})
        assert s.status_code == 200

        rows = client.get(f"{API}/expiry").json()
        assert isinstance(rows, list)
        xrows = [r for r in rows if r["vendor"] == "xilinx"]
        assert len(xrows) >= 1, f"Expected xilinx row in expiry; got vendors: {set(r['vendor'] for r in rows)}"
        assert xrows[0]["feature"] == "Vivado"
        assert xrows[0]["status"] in ("ok", "warning", "critical", "expired", "permanent")
    finally:
        client.delete(f"{API}/servers/{sid}")


# ---------- /api/checkouts side-effect ----------
def test_checkouts_endpoint_works_with_seeded_vendors(client):
    client.post(f"{API}/seed/reset")
    r = client.get(f"{API}/checkouts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- Real paramiko import check ----------
def test_paramiko_path_does_not_500(client):
    """When adapter=ssh + ssh.enabled=True with bogus host, reread should NOT 500."""
    r = client.post(f"{API}/servers", json={
        "name": "TEST_paramiko_real", "vendor": "cadence",
        "host": "10.10.11.111", "port": 5280, "daemon": "cdslmd",
    })
    sid = r.json()["id"]
    try:
        client.put(f"{API}/servers/{sid}/ssh", json={
            "enabled": True, "host": "10.99.99.99", "port": 22,
            "username": "nobody", "auth_method": "password",
            "password": "x", "private_key": "",
            "lmutil_path": "/usr/local/flexlm/lmutil",
        })
        client.put(f"{API}/servers/{sid}/adapter", json={"adapter_mode": "ssh"})
        rr = client.post(f"{API}/servers/{sid}/reread", timeout=60)
        assert rr.status_code == 200, f"reread should be graceful: {rr.text}"
        ex = rr.json()["exec"]
        # Real paramiko path used — mode should be "ssh" (success) or "ssh-error" (graceful failure)
        assert ex["mode"] in ("ssh", "ssh-error"), f"Expected real paramiko mode, got {ex['mode']}"
    finally:
        client.delete(f"{API}/servers/{sid}")
