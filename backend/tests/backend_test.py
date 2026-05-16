"""Backend tests for LICMAN VLSI License Console."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://eda-license-portal.preview.emergentagent.com').rstrip('/')
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


# ---------- health ----------
def test_root(client):
    r = client.get(f"{API}/", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


# ---------- servers list / seed ----------
def test_list_seed_servers(client):
    r = client.get(f"{API}/servers", timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 3
    vendors = sorted([s["vendor"] for s in data])
    assert vendors == ["cadence", "mentor", "synopsys"]
    for s in data:
        assert len(s["features"]) > 0


def test_get_server_single(client):
    servers = client.get(f"{API}/servers").json()
    sid = servers[0]["id"]
    r = client.get(f"{API}/servers/{sid}")
    assert r.status_code == 200
    d = r.json()
    assert d["license_file"]
    assert d["options_file"]


def test_get_server_404(client):
    r = client.get(f"{API}/servers/nonexistent-id")
    assert r.status_code == 404


# ---------- CRUD ----------
def test_create_update_delete_server(client):
    payload = {
        "name": "TEST_lic-x-01", "vendor": "cadence",
        "host": "x.local", "port": 5999, "daemon": "cdslmd",
    }
    cr = client.post(f"{API}/servers", json=payload)
    assert cr.status_code == 200
    srv = cr.json()
    sid = srv["id"]
    assert srv["name"] == payload["name"]
    assert srv["license_file"]

    pr = client.patch(f"{API}/servers/{sid}", json={"port": 6001})
    assert pr.status_code == 200
    assert pr.json()["port"] == 6001

    gr = client.get(f"{API}/servers/{sid}")
    assert gr.json()["port"] == 6001

    dr = client.delete(f"{API}/servers/{sid}")
    assert dr.status_code == 200
    assert client.get(f"{API}/servers/{sid}").status_code == 404


# ---------- license / options ----------
def test_save_license_parses_features(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    content = (
        "SERVER lic ANY 5280\nVENDOR cdslmd\n"
        "FEATURE Innovus cdslmd 21.10 31-dec-2026 8 SIGN=AB\n"
        "FEATURE Spectre cdslmd 21.1 31-dec-2026 16 SIGN=CD\n"
    )
    r = client.put(f"{API}/servers/{sid}/license", json={"content": content})
    assert r.status_code == 200
    assert r.json()["features_parsed"] == 2
    d = client.get(f"{API}/servers/{sid}").json()
    names = sorted([f["name"] for f in d["features"]])
    assert names == ["Innovus", "Spectre"]
    assert d["license_file"] == content


def test_save_options(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    r = client.put(f"{API}/servers/{sid}/options", json={"content": "TIMEOUTALL 3600\n"})
    assert r.status_code == 200
    d = client.get(f"{API}/servers/{sid}").json()
    assert "TIMEOUTALL 3600" in d["options_file"]


# ---------- daemon control ----------
def test_reread_restart_toggle(client):
    sid = client.get(f"{API}/servers").json()[1]["id"]
    assert client.post(f"{API}/servers/{sid}/reread").status_code == 200
    assert client.post(f"{API}/servers/{sid}/restart").status_code == 200

    t1 = client.post(f"{API}/servers/{sid}/toggle").json()
    assert t1["status"] == "down"
    # checkouts should be empty when down
    co = client.get(f"{API}/servers/{sid}/checkouts").json()
    assert co == []
    t2 = client.post(f"{API}/servers/{sid}/toggle").json()
    assert t2["status"] == "up"


def test_checkouts_when_up(client):
    sid = client.get(f"{API}/servers").json()[2]["id"]
    # ensure up - reseed parsed features so checkouts can be generated
    r = client.get(f"{API}/servers/{sid}/checkouts")
    assert r.status_code == 200
    # could be 0..n, just check shape if any
    co = r.json()
    for c in co:
        assert "feature" in c and "user" in c and "pid" in c


def test_all_checkouts(client):
    r = client.get(f"{API}/checkouts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ---------- reservations ----------
def test_reservation_crud(client):
    sid = client.get(f"{API}/servers").json()[0]["id"]
    feat = client.get(f"{API}/servers/{sid}").json()["features"][0]["name"]
    cr = client.post(f"{API}/reservations", json={
        "server_id": sid, "feature": feat,
        "target_type": "USER", "target": "TEST_alice", "count": 1,
    })
    assert cr.status_code == 200
    rid = cr.json()["id"]

    lr = client.get(f"{API}/reservations")
    assert any(r["id"] == rid for r in lr.json())

    dr = client.delete(f"{API}/reservations/{rid}")
    assert dr.status_code == 200
    assert not any(r["id"] == rid for r in client.get(f"{API}/reservations").json())


# ---------- audit / stats ----------
def test_audit_sorted(client):
    r = client.get(f"{API}/audit?limit=20")
    assert r.status_code == 200
    data = r.json()
    assert len(data) > 0
    ts = [d["timestamp"] for d in data]
    assert ts == sorted(ts, reverse=True)


def test_stats(client):
    r = client.get(f"{API}/stats")
    assert r.status_code == 200
    d = r.json()
    for k in ["servers_total", "servers_up", "features_total", "checkouts_active", "reservations"]:
        assert k in d
