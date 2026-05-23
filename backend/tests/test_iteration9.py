"""
Iteration 9 — Bug fixes (reset/reread/kill/fetch-license/ssh-test) + Priority/Preemption + SGE settings.
Verifies command strings via exec.command, role-gating, and CRUD/state correctness.
"""
import os
import re
import uuid
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"


def _admin_session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login",
               json={"email": "admin@example.com", "password": "adminpass123"})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return s


def _engineer_session(admin):
    """Create an engineer-role user and return a logged-in session for it."""
    email = f"TEST_eng_{uuid.uuid4().hex[:8]}@example.com"
    pwd = "EngPass!2345"
    r = admin.post(f"{BASE_URL}/api/users",
                   json={"email": email, "password": pwd, "role": "engineer"})
    assert r.status_code in (200, 201), f"create engineer failed: {r.status_code} {r.text}"
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": email, "password": pwd})
    assert r.status_code == 200, f"engineer login failed: {r.text}"
    return s, email


@pytest.fixture(scope="module")
def admin():
    s = _admin_session()
    # Clean up any leftover TEST_ priority rules from previous runs
    for r in s.get(f"{BASE_URL}/api/priority-rules").json():
        if r.get("name", "").startswith("TEST_") or r.get("user_pattern", "") in ("*", "nobody*"):
            s.delete(f"{BASE_URL}/api/priority-rules/{r['id']}")
    return s


@pytest.fixture(scope="module")
def engineer(admin):
    s, _ = _engineer_session(admin)
    return s


@pytest.fixture(scope="module")
def first_server(admin):
    r = admin.get(f"{BASE_URL}/api/servers")
    assert r.status_code == 200
    servers = r.json()
    assert len(servers) > 0, "Need at least one seeded server"
    # Prefer a mock-mode server
    mock = [s for s in servers if s.get("adapter_mode", "mock") == "mock"]
    return (mock or servers)[0]


# ============================= BUG FIXES =============================

class TestBugFixSeedReset:
    def test_reset_preserves_servers_clears_history(self, admin):
        # Touch checkouts so usage_history has rows
        admin.get(f"{BASE_URL}/api/checkouts")
        before = admin.get(f"{BASE_URL}/api/servers").json()
        before_count = len(before)
        assert before_count > 0

        r = admin.post(f"{BASE_URL}/api/seed/reset")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        assert "Transient history cleared" in body.get("message", "")

        after = admin.get(f"{BASE_URL}/api/servers").json()
        assert len(after) == before_count, "servers count must be UNCHANGED"

        # audit cleared then 1 entry was added by reset itself — allow <= 1
        audit = admin.get(f"{BASE_URL}/api/audit").json()
        assert len(audit) <= 2, f"audit should be near-empty after reset, got {len(audit)}"


class TestBugFixReread:
    def test_reread_command_format(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/servers/{first_server['id']}/reread")
        assert r.status_code == 200, r.text
        body = r.json()
        cmd = (body.get("exec") or {}).get("command", "")
        assert "lmreread" in cmd
        # Correct: lmreread -c <port>@<host>   NOT lmreread -c @<port>@<host>
        assert "-c @" not in cmd, f"stray '@' before port — {cmd}"
        target = f"{first_server['port']}@{first_server['host']}"
        assert target in cmd, f"missing port@host target in {cmd}"
        # Verify -vendor flag if daemon present
        if first_server.get("daemon"):
            assert "-vendor" in cmd


class TestBugFixKillCheckout:
    def test_kill_command_format(self, admin, first_server):
        payload = {
            "feature": "Innovus", "user": "rakella",
            "host": "ws-01", "display": ":0.0",
        }
        r = admin.post(f"{BASE_URL}/api/servers/{first_server['id']}/checkouts/kill",
                       json=payload)
        assert r.status_code == 200, r.text
        cmd = (r.json().get("exec") or {}).get("command", "")
        # Expected: lmutil lmremove -c <port>@<host> <feature> <user> <host> [display]
        assert "lmremove" in cmd
        assert f"-c {first_server['port']}@{first_server['host']}" in cmd or \
               f"-c '{first_server['port']}@{first_server['host']}'" in cmd
        # Order check: feature, user, host, display appear in order after -c arg
        m = re.search(r"lmremove\s+-c\s+\S+\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?", cmd)
        assert m, f"could not parse kill cmd: {cmd}"
        # strip possible shell quoting
        def unq(s): return s.strip("'\"") if s else s
        assert unq(m.group(1)) == "Innovus"
        assert unq(m.group(2)) == "rakella"
        assert unq(m.group(3)) == "ws-01"
        assert unq(m.group(4)) == ":0.0"

    def test_kill_rejects_injection(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/servers/{first_server['id']}/checkouts/kill",
                       json={"feature": "X;rm -rf /", "user": "u", "host": "h"})
        assert r.status_code == 400, f"expected 400 for injection, got {r.status_code}"


class TestBugFixSshAndFetch:
    def test_ssh_test_no_decrypt_crash(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/servers/{first_server['id']}/ssh/test")
        assert r.status_code == 200, r.text
        body = r.json()
        # Critical: must NOT crash with 'decrypt' anywhere — bug fix verification.
        # The body may show ok=True (stub) OR ok=False with a network/timeout error
        # (when the seeded server has ssh.enabled=True pointing to an unreachable host).
        # Either is acceptable as long as no decrypt crash occurred.
        assert "decrypt" not in str(body).lower(), f"decrypt crash: {body}"
        # The endpoint returned 200, not 500 → ssh.test no longer crashes

    def test_fetch_license_no_decrypt_crash(self, admin, first_server):
        # mock-mode server returns 400 ("SSH adapter not enabled") which is fine —
        # but it must NOT 500 with a decrypt error.
        r = admin.post(f"{BASE_URL}/api/servers/{first_server['id']}/fetch-license")
        assert r.status_code in (200, 400, 404, 502), r.text
        assert "decrypt" not in r.text.lower(), f"decrypt crash: {r.text}"


# ============================= PRIORITY RULES CRUD =============================

class TestPriorityRules:
    def test_initial_list(self, admin):
        r = admin.get(f"{BASE_URL}/api/priority-rules")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_full_crud(self, admin):
        # CREATE
        payload = {"name": "TEST_A_team", "priority": 900,
                   "user_pattern": "rakella*", "features": ["Innovus"]}
        r = admin.post(f"{BASE_URL}/api/priority-rules", json=payload)
        assert r.status_code in (200, 201), r.text
        rule = r.json()
        assert rule["id"]
        assert rule["priority"] == 900
        assert rule["name"] == "TEST_A_team"
        rid = rule["id"]

        # GET-verify
        lst = admin.get(f"{BASE_URL}/api/priority-rules").json()
        assert any(x["id"] == rid for x in lst)

        # PATCH
        r = admin.patch(f"{BASE_URL}/api/priority-rules/{rid}",
                        json={**payload, "priority": 950})
        assert r.status_code == 200, r.text
        assert r.json()["priority"] == 950

        # DELETE
        r = admin.delete(f"{BASE_URL}/api/priority-rules/{rid}")
        assert r.status_code == 200
        # confirm gone
        lst = admin.get(f"{BASE_URL}/api/priority-rules").json()
        assert not any(x["id"] == rid for x in lst)

    def test_engineer_forbidden(self, engineer):
        r = engineer.post(f"{BASE_URL}/api/priority-rules",
                          json={"name": "TEST_blocked", "priority": 100})
        assert r.status_code == 403, r.text
        # Patch / Delete on a fake id — must still 403, NOT 404
        r = engineer.patch(f"{BASE_URL}/api/priority-rules/fake",
                           json={"name": "X", "priority": 1})
        assert r.status_code == 403
        r = engineer.delete(f"{BASE_URL}/api/priority-rules/fake")
        assert r.status_code == 403


# ============================= PREEMPTION =============================

class TestPreempt:
    @pytest.fixture(autouse=True)
    def _seed_rule(self, admin):
        # Insert an admin-priority rule for rakella so requester gets a positive prio
        r = admin.post(f"{BASE_URL}/api/priority-rules",
                       json={"name": "TEST_rakella_high", "priority": 900,
                             "user_pattern": "rakella*", "features": ["Innovus"]})
        rid = r.json()["id"]
        # ensure some checkouts exist
        admin.get(f"{BASE_URL}/api/checkouts")
        yield rid
        admin.delete(f"{BASE_URL}/api/priority-rules/{rid}")

    def test_plan_structure(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/preempt/plan",
                       json={"server_id": first_server["id"],
                             "feature": "Innovus",
                             "requester_user": "rakella",
                             "seats_needed": 1})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["requester_priority"] == 900
        assert "current_holders" in body
        assert "releasable_holders" in body
        assert "can_satisfy" in body
        assert "targets" in body
        # targets sorted ascending priority
        prios = [t["holder_priority"] for t in body["targets"]]
        assert prios == sorted(prios)

    def test_plan_no_rule_requester(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/preempt/plan",
                       json={"server_id": first_server["id"],
                             "feature": "Innovus",
                             "requester_user": "nobody_x",
                             "seats_needed": 1})
        assert r.status_code == 200
        body = r.json()
        assert body["requester_priority"] == 0
        # Since holders all default to 0, releasable (strictly lower) should be 0
        assert body["releasable_holders"] == 0

    def test_run_dry_run(self, admin, first_server):
        r = admin.post(f"{BASE_URL}/api/preempt/run",
                       json={"server_id": first_server["id"],
                             "feature": "Innovus",
                             "requester_user": "rakella",
                             "seats_needed": 1,
                             "dry_run": True})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("dry_run") is True
        assert "plan" in body
        # No actions[] on dry-run
        assert "actions" not in body or body.get("actions") in (None, [])

    def test_run_executes_lmremove(self, admin, first_server):
        # ensure holders exist
        admin.get(f"{BASE_URL}/api/checkouts")
        r = admin.post(f"{BASE_URL}/api/preempt/run",
                       json={"server_id": first_server["id"],
                             "feature": "Innovus",
                             "requester_user": "rakella",
                             "seats_needed": 1,
                             "dry_run": False})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("ok") is True
        if body.get("plan", {}).get("can_satisfy"):
            actions = body.get("actions", [])
            assert len(actions) >= 1
            # SGE disabled by default → method must be 'lmremove'
            for a in actions:
                assert a["method"] == "lmremove", f"unexpected method {a['method']}"
            # PREEMPT audit entry should exist
            audit = admin.get(f"{BASE_URL}/api/audit").json()
            assert any(a.get("action") == "PREEMPT" for a in audit), "no PREEMPT audit entry"

    def test_who_am_i(self, admin):
        r = admin.get(f"{BASE_URL}/api/preempt/who-am-i",
                      params={"user": "rakella", "feature": "Innovus"})
        assert r.status_code == 200
        assert r.json()["priority"] == 900
        # Unmatched user
        r = admin.get(f"{BASE_URL}/api/preempt/who-am-i",
                      params={"user": "nobody_x", "feature": "Innovus"})
        assert r.json()["priority"] == 0


# ============================= SGE SETTINGS =============================

class TestSgeSettings:
    def test_settings_has_sge_fields(self, admin):
        r = admin.get(f"{BASE_URL}/api/settings")
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("sge_enabled", "sge_qstat_path", "sge_qmod_path"):
            assert k in body, f"missing SGE setting {k}"

    def test_sge_persistence(self, admin):
        cur = admin.get(f"{BASE_URL}/api/settings").json()
        payload = {**cur, "sge_enabled": True,
                   "sge_qstat_path": "/opt/sge/bin/qstat",
                   "sge_qmod_path": "/opt/sge/bin/qmod"}
        r = admin.put(f"{BASE_URL}/api/settings", json=payload)
        assert r.status_code == 200, r.text
        # Re-fetch
        after = admin.get(f"{BASE_URL}/api/settings").json()
        assert after["sge_enabled"] is True
        assert after["sge_qstat_path"] == "/opt/sge/bin/qstat"
        assert after["sge_qmod_path"] == "/opt/sge/bin/qmod"
        # Restore default (disabled)
        admin.put(f"{BASE_URL}/api/settings",
                  json={**after, "sge_enabled": False})
