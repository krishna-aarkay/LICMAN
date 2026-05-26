from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import PlainTextResponse
import csv as _csv
import io as _io
import json as _json
import urllib.request as _urlreq
import urllib.error as _urlerr
import shlex as _shlex
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
import re
import smtplib
import ssl
import asyncio
import secrets as _secrets
import bcrypt
import jwt as pyjwt
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from typing import List, Optional, Literal
import uuid
from datetime import datetime, timezone, timedelta, date


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="LICMAN — VLSI License Console")
async def _require_auth(request: Request):
    """Wrapper that defers to get_current_user (defined later in file)."""
    return await get_current_user(request)


api_router = APIRouter(prefix="/api", dependencies=[Depends(_require_auth)])
# Public sub-router (no auth) — carries /api/, /api/setup-status
public_router = APIRouter(prefix="/api")


# ------------------------- Models -------------------------

# Vendor is now a free-form string (cadence/synopsys/mentor/xilinx/defacto/ansys/...)
Vendor = str


class FeatureIncrement(BaseModel):
    """One INCREMENT/FEATURE line from the license file. A single feature can
    have several increments with different expiry dates and seat counts."""
    version: str = "1.0"
    expires: str = "permanent"
    count: int = 0


class FeatureModel(BaseModel):
    name: str
    version: str = "1.0"
    total: int = 1
    expires: str = "permanent"
    # Authoritative `in use` count reported by lmstat header ("Total of N licenses in use").
    # Some FlexLM checkout lines are folded into a single line per user, so the
    # user-line count alone undercounts the real seats held. We use this field
    # as the upper bound for utilization display.
    in_use_reported: int = 0
    increments: List[FeatureIncrement] = []


class SshConfig(BaseModel):
    enabled: bool = False
    host: str = ""
    port: int = 22
    username: str = ""
    auth_method: Literal["password", "key"] = "key"
    password: str = ""
    private_key: str = ""
    lmutil_path: str = "/usr/local/flexlm/lmutil"


class LicenseServer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    vendor: Vendor
    host: str
    port: int
    daemon: str
    status: Literal["up", "down", "stale"] = "up"
    license_file: str = ""
    options_file: str = ""
    license_file_path: str = ""  # Absolute path on the license host (e.g. /cadmgr/cadence/license.dat)
    options_file_path: str = ""  # Absolute path on the license host (e.g. /cadmgr/cadence/options.txt)
    features: List[FeatureModel] = []
    ssh: SshConfig = Field(default_factory=SshConfig)
    adapter_mode: Literal["mock", "ssh"] = "mock"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_action: str = ""


class ServerCreate(BaseModel):
    name: str
    vendor: Vendor
    host: str
    port: int
    daemon: str
    license_file_path: str = ""
    options_file_path: str = ""


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    daemon: Optional[str] = None
    status: Optional[Literal["up", "down", "stale"]] = None
    license_file_path: Optional[str] = None
    options_file_path: Optional[str] = None


class FileContent(BaseModel):
    content: str


class Checkout(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    server_id: str
    feature: str
    version: str
    user: str
    host: str
    display: str
    checkout_time: str
    pid: int
    count: int = 1  # Number of license seats held in this single session (lmstat "N licenses")


class Reservation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    server_id: str
    feature: str
    target_type: Literal["USER", "HOST", "GROUP", "INTERNET"]
    target: str
    count: int = 1
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ReservationCreate(BaseModel):
    server_id: str
    feature: str
    target_type: Literal["USER", "HOST", "GROUP", "INTERNET"]
    target: str
    count: int = 1


class AlertSettings(BaseModel):
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    from_address: str = ""
    to_addresses: List[str] = []
    enabled: bool = False
    starttls: bool = True
    alert_on_saturation: bool = True
    alert_on_expiry: bool = True
    expiry_warn_days: int = 30
    webhook_url: str = ""
    webhook_kind: Literal["slack", "teams", "generic", ""] = ""
    webhook_enabled: bool = False
    # Son of Grid Engine integration for graceful preemption
    sge_enabled: bool = False
    sge_qstat_path: str = "qstat"
    sge_qmod_path: str = "qmod"
    # Fully automatic background preemption loop
    auto_preempt_enabled: bool = False
    auto_preempt_interval_sec: int = 30


class AlertEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    kind: Literal["saturation", "expiry", "test"]
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    feature: Optional[str] = None
    detail: str
    delivered: bool = False
    error: Optional[str] = None


class AuditLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    server_id: Optional[str] = None
    server_name: Optional[str] = None
    action: str
    detail: str
    actor: str = "engineer"
    severity: Literal["info", "success", "warning", "error"] = "info"


# ------------------------- Helpers -------------------------

async def log_audit(action: str, detail: str, server_id: Optional[str] = None,
                    server_name: Optional[str] = None, severity: str = "info"):
    entry = AuditLog(
        action=action, detail=detail, server_id=server_id,
        server_name=server_name, severity=severity  # type: ignore
    )
    doc = entry.model_dump()
    # Add a real BSON Date for the TTL index
    doc["ts"] = datetime.now(timezone.utc)
    await db.audit.insert_one(doc)


def _sample_users():
    return ["asingh", "jzhang", "kpatel", "mlopez", "rkumar", "tnguyen", "ehassan", "yliu"]


def _sample_hosts():
    return ["wks-bangalore-04", "wks-sjc-12", "build-farm-07", "tape-out-02",
            "verify-rig-09", "synth-node-11", "pnr-rack-03", "drc-node-15"]


def generate_checkouts(server: dict):
    """Generate plausible simulated checkouts for a server's features.
    Occasionally produces multi-seat sessions (multi-CPU/multi-handle runs)
    so the parser & UI can demo the new `count` field."""
    checkouts = []
    users = _sample_users()
    hosts = _sample_hosts()
    features = server.get("features", [])
    if not features:
        return checkouts
    for feat in features:
        total = max(1, feat.get("total", 1))
        in_use = random.randint(0, total)
        seats_left = in_use
        while seats_left > 0:
            # 25% chance this session takes 2-4 seats (multi-CPU run)
            roll = random.random()
            if roll < 0.25 and seats_left >= 2:
                grab = random.randint(2, min(4, seats_left))
            else:
                grab = 1
            ago = random.randint(2, 480)
            ct = datetime.now(timezone.utc) - timedelta(minutes=ago)
            checkouts.append(Checkout(
                server_id=server["id"],
                feature=feat["name"],
                version=feat.get("version", "1.0"),
                user=random.choice(users),
                host=random.choice(hosts),
                display=f":{random.randint(0, 6)}.0",
                checkout_time=ct.isoformat(),
                pid=random.randint(1000, 65000),
                count=grab,
            ).model_dump())
            seats_left -= grab
    return checkouts


# ---------- Expiry parsing ----------
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
)}


def parse_expiry(expires_str: str) -> Optional[date]:
    """Parse FlexLM-style date like '31-dec-2026' or '2026-12-31'. None for 'permanent'."""
    if not expires_str:
        return None
    s = expires_str.strip().lower()
    if s in ("permanent", "0", "none"):
        return None
    # 31-dec-2026
    m = re.match(r"^(\d{1,2})-([a-z]{3})-(\d{4})$", s)
    if m:
        d, mon, y = int(m.group(1)), _MONTHS.get(m.group(2)), int(m.group(3))
        if mon:
            try:
                return date(y, mon, d)
            except ValueError:
                return None
    # 2026-12-31
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def days_until(d: Optional[date]) -> Optional[int]:
    if d is None:
        return None
    return (d - date.today()).days


# ---------- SMTP / Alerts ----------
async def get_alert_settings(*, decrypt_smtp: bool = True) -> dict:
    doc = await db.settings.find_one({"_key": "alerts"}, {"_id": 0})
    if not doc:
        return AlertSettings().model_dump()
    doc.pop("_key", None)
    # Backfill new fields so older DB records expose webhook_* keys to the UI
    defaults = AlertSettings().model_dump()
    for k, v in defaults.items():
        doc.setdefault(k, v)
    if decrypt_smtp and doc.get("smtp_password"):
        doc["smtp_password"] = decrypt_secret(doc["smtp_password"])
    return doc


def send_smtp_email(cfg: dict, subject: str, body: str) -> tuple[bool, Optional[str]]:
    """Send via Office 365 / generic SMTP. Returns (ok, error)."""
    if not cfg.get("enabled") or not cfg.get("smtp_host") or not cfg.get("to_addresses"):
        return False, "SMTP not configured"
    try:
        msg = MIMEMultipart()
        msg["From"] = cfg.get("from_address") or cfg.get("smtp_username")
        msg["To"] = ", ".join(cfg["to_addresses"])
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        host = cfg["smtp_host"]
        port = int(cfg.get("smtp_port", 587))
        with smtplib.SMTP(host, port, timeout=10) as s:
            s.ehlo()
            if cfg.get("starttls", True):
                ctx = ssl.create_default_context()
                s.starttls(context=ctx)
                s.ehlo()
            if cfg.get("smtp_username") and cfg.get("smtp_password"):
                s.login(cfg["smtp_username"], cfg["smtp_password"])
            s.sendmail(msg["From"], cfg["to_addresses"], msg.as_string())
        return True, None
    except Exception as e:
        return False, str(e)


def send_webhook(cfg: dict, kind: str, subject: str, body: str) -> tuple[bool, Optional[str]]:
    """POST a Slack/Teams/generic webhook message. Returns (ok, error).
    Keeps no external deps — uses urllib so the air-gapped wheelhouse stays small."""
    url = (cfg.get("webhook_url") or "").strip()
    if not (cfg.get("webhook_enabled") and url):
        return False, "webhook not configured"
    flavor = (cfg.get("webhook_kind") or "generic").lower()
    color = {"saturation": "#f59e0b", "expiry": "#ef4444", "test": "#3b82f6"}.get(kind, "#9ca3af")
    try:
        if flavor == "slack":
            payload = {
                "text": f"*{subject}*\n{body}",
                "attachments": [{"color": color, "text": body, "ts": int(datetime.now(timezone.utc).timestamp())}],
            }
        elif flavor == "teams":
            payload = {
                "@type": "MessageCard", "@context": "https://schema.org/extensions",
                "themeColor": color.lstrip("#"),
                "summary": subject, "title": subject, "text": body,
            }
        else:
            payload = {"kind": kind, "subject": subject, "body": body,
                       "timestamp": datetime.now(timezone.utc).isoformat()}
        data = _json.dumps(payload).encode("utf-8")
        req = _urlreq.Request(url, data=data, headers={"Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=8) as resp:  # nosec - operator-supplied URL
            code = resp.getcode()
            if 200 <= code < 300:
                return True, None
            return False, f"webhook HTTP {code}"
    except _urlerr.HTTPError as e:
        return False, f"webhook HTTP {e.code}"
    except Exception as e:
        return False, str(e)[:200]


async def _alert_throttled(kind: str, server_id: Optional[str], feature: Optional[str]) -> bool:
    """Return True if a similar alert was fired in last 6 hours."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    q = {"kind": kind, "server_id": server_id, "feature": feature, "timestamp": {"$gt": cutoff}}
    return (await db.alert_events.count_documents(q)) > 0


async def trigger_alert(kind: str, detail: str, server_id: Optional[str] = None,
                        server_name: Optional[str] = None, feature: Optional[str] = None):
    if await _alert_throttled(kind, server_id, feature):
        return
    cfg = await get_alert_settings()
    enable_flag = {
        "saturation": cfg.get("alert_on_saturation", True),
        "expiry": cfg.get("alert_on_expiry", True),
        "test": True,
    }.get(kind, True)
    delivered, err = False, None
    if cfg.get("enabled") and enable_flag:
        subject = f"[LICMAN] {kind.upper()} — {server_name or 'server'} · {feature or ''}".strip()
        delivered, err = send_smtp_email(cfg, subject, detail)
    # Webhook (Slack/Teams) — fired in addition to email, independent of SMTP enable flag
    webhook_delivered, webhook_err = False, None
    if enable_flag and cfg.get("webhook_enabled") and cfg.get("webhook_url"):
        subject = f"[LICMAN] {kind.upper()} — {server_name or 'server'} · {feature or ''}".strip()
        webhook_delivered, webhook_err = send_webhook(cfg, kind, subject, detail)
    # Merge delivery flags — at least one channel succeeded counts as delivered
    final_delivered = bool(delivered or webhook_delivered)
    final_err = err if err else webhook_err
    ev = AlertEvent(
        kind=kind, server_id=server_id, server_name=server_name,
        feature=feature, detail=detail, delivered=final_delivered, error=final_err  # type: ignore
    )
    await db.alert_events.insert_one(ev.model_dump())
    sev = "warning" if kind == "saturation" else ("error" if kind == "expiry" else "info")
    await log_audit(f"ALERT_{kind.upper()}", detail, server_id, server_name, sev)


async def evaluate_alerts():
    """Scan all servers for saturation and expiry conditions."""
    cfg = await get_alert_settings()
    warn_days = int(cfg.get("expiry_warn_days", 30))
    servers = await db.servers.find({"status": "up"}, {"_id": 0}).to_list(500)
    for srv in servers:
        in_use_by_feat = {}
        for c in generate_checkouts(srv):
            in_use_by_feat[c["feature"]] = in_use_by_feat.get(c["feature"], 0) + 1
        for feat in srv.get("features", []):
            total = feat.get("total", 0)
            used = in_use_by_feat.get(feat["name"], 0)
            if total > 0 and used >= total:
                await trigger_alert(
                    "saturation",
                    f"Feature {feat['name']} on {srv['name']} is SATURATED ({used}/{total} in use).",
                    srv["id"], srv["name"], feat["name"],
                )
            d = days_until(parse_expiry(feat.get("expires", "")))
            if d is not None and d <= warn_days:
                await trigger_alert(
                    "expiry",
                    f"Feature {feat['name']} on {srv['name']} expires in {d} day(s) ({feat.get('expires')}).",
                    srv["id"], srv["name"], feat["name"],
                )


# ---------- SSH adapter (paramiko-ready) ----------
try:
    import paramiko  # type: ignore
    PARAMIKO_AVAILABLE = True
except Exception:
    PARAMIKO_AVAILABLE = False


def _ssh_with_decrypted(ssh: dict) -> dict:
    """Return a copy of an ssh dict with password/private_key decrypted for paramiko use."""
    if not isinstance(ssh, dict):
        return ssh
    out = dict(ssh)
    out["password"] = decrypt_secret(out.get("password", ""))
    out["private_key"] = decrypt_secret(out.get("private_key", ""))
    return out


def _ssh_real_exec(ssh_cfg: dict, command: str) -> dict:
    """Execute a command on a remote host via paramiko. Returns dict with stdout/stderr/exit."""
    if not PARAMIKO_AVAILABLE:
        return {"mode": "ssh-error", "command": command,
                "output": "paramiko not installed on backend host", "exit": -1}
    host = ssh_cfg.get("host")
    port = int(ssh_cfg.get("port", 22))
    user = ssh_cfg.get("username")
    if not host or not user:
        return {"mode": "ssh-error", "command": command,
                "output": "missing host or username", "exit": -1}
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        connect_kwargs = {"hostname": host, "port": port, "username": user, "timeout": 10}
        if ssh_cfg.get("auth_method") == "password":
            connect_kwargs["password"] = ssh_cfg.get("password", "")
        else:
            key_str = ssh_cfg.get("private_key", "")
            if key_str:
                from io import StringIO
                pkey = None
                for KCls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                    try:
                        pkey = KCls.from_private_key(StringIO(key_str))
                        break
                    except Exception:
                        continue
                if pkey is None:
                    return {"mode": "ssh-error", "command": command,
                            "output": "could not parse private key", "exit": -1}
                connect_kwargs["pkey"] = pkey
        client.connect(**connect_kwargs)
        _stdin, stdout, stderr = client.exec_command(command, timeout=20)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        return {"mode": "ssh", "command": command,
                "output": (out + err).strip() or "(no output)", "exit": rc}
    except Exception as e:
        return {"mode": "ssh-error", "command": command, "output": str(e), "exit": -1}
    finally:
        try:
            client.close()
        except Exception:
            pass


async def ssh_execute(server: dict, command: str) -> dict:
    """Execute via real SSH when adapter_mode='ssh' and ssh.enabled. Otherwise mocked."""
    mode = server.get("adapter_mode", "mock")
    ssh = server.get("ssh", {}) or {}
    if mode == "ssh" and ssh.get("enabled"):
        return await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), command)
    return {"mode": "mock", "command": command, "output": f"[MOCK] {command} executed", "exit": 0}


# ---------- lmstat output parser ----------

# Parses standard FlexLM `lmstat -a` output produced by lmutil from any vendor.
_RE_USERS_OF = re.compile(
    r"^Users of\s+(?P<feature>\S+):\s+\(Total of (?P<total>\d+) license[s]? issued;"
    r"\s+Total of (?P<inuse>\d+) license[s]? in use\)",
    re.IGNORECASE,
)
_RE_FEATURE_META = re.compile(
    r'^\s*"(?P<feature>[^"]+)"\s+v(?P<version>\S+),\s+vendor:\s*(?P<vendor>[A-Za-z0-9_.-]+)'
    r'(?:,\s*expiry:\s*(?P<expires>\S+))?',
    re.IGNORECASE,
)
# Example:  ramak edaserver1 :0.0 (v17.1) (hostname/5280 102), start Wed 5/14 9:42
_RE_USER_LINE = re.compile(
    r"^\s+(?P<user>\S+)\s+(?P<host>\S+)\s+(?P<display>\S+)\s+"
    r"\(v?(?P<ver>[^)]+)\)\s+\((?P<lic>\S+)\s+(?P<pid>\d+)\),\s+start\s+(?P<when>.+?)"
    r"(?:,\s*(?P<count>\d+)\s+licenses?)?$"
)
_MONTH_NAMES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _parse_start_to_iso(when: str) -> str:
    """`Wed 5/14 9:42` or `5/14/2025 9:42` → ISO timestamp.
    lmstat reports times in the LICENSE SERVER's LOCAL timezone (not UTC). We
    therefore interpret the parsed components as local time using the backend
    host's timezone (which is typically the same as the license server's TZ
    on a private LAN), then convert to UTC for storage. Falls back to now on
    any parsing error.
    """
    s = when.strip()
    now = datetime.now(timezone.utc)
    try:
        parts = s.split()
        # Drop leading day name if present (Mon..Sun)
        if parts and parts[0][:3].title() in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"):
            parts = parts[1:]
        if not parts:
            return now.isoformat()
        date_str = parts[0]
        time_str = parts[1] if len(parts) > 1 else "0:00"
        m, d, *y = date_str.split("/")
        local_now = datetime.now().astimezone()
        local_tz = local_now.tzinfo
        year = int(y[0]) if y else local_now.year
        month, day = int(m), int(d)
        hh, mm = (int(x) for x in time_str.split(":")[:2])
        local_dt = datetime(year, month, day, hh, mm, 0, tzinfo=local_tz)
        # If lmstat omitted the year and our guess lands in the future
        # (e.g., logs from late December seen in early January), roll back.
        if not y and local_dt > local_now + timedelta(days=1):
            local_dt = local_dt.replace(year=year - 1)
        return local_dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return now.isoformat()


def parse_lmstat_a(text: str, server_id: str) -> dict:
    """Return dict {features: [...], checkouts: [...]} parsed from `lmstat -a` output.
    Captures both the server-reported `in use` count (authoritative) and individual
    user-line checkouts. Also gathers ALL increment expiry lines per feature."""
    features: dict = {}
    checkouts: list = []
    current_feature = None

    lines = (text or "").splitlines()
    for i, line in enumerate(lines):
        m = _RE_USERS_OF.match(line)
        if m:
            current_feature = m.group("feature")
            features[current_feature] = {
                "name": current_feature,
                "total": int(m.group("total")),
                "in_use_reported": int(m.group("inuse")),
                "version": "",
                "expires": "permanent",
                "increments": [],  # All INCREMENT/feature-meta lines for this feature
            }
            # Scan forward until the next `Users of` line, collecting every
            # FEATURE_META line that belongs to this feature.
            for j in range(i + 1, len(lines)):
                if _RE_USERS_OF.match(lines[j]):
                    break
                mm = _RE_FEATURE_META.match(lines[j])
                if mm and mm.group("feature") == current_feature:
                    if not features[current_feature]["version"]:
                        features[current_feature]["version"] = mm.group("version")
                    if not features[current_feature]["expires"] or \
                            features[current_feature]["expires"] == "permanent":
                        features[current_feature]["expires"] = mm.group("expires") or "permanent"
                    features[current_feature]["increments"].append({
                        "version": mm.group("version"),
                        "expires": mm.group("expires") or "permanent",
                        "count": 0,  # filled by license-file parser if available
                    })
            continue
        mu = _RE_USER_LINE.match(line)
        if mu and current_feature:
            try:
                count = int(mu.group("count")) if mu.group("count") else 1
            except Exception:
                count = 1
            checkouts.append({
                "id": str(uuid.uuid4()),
                "server_id": server_id,
                "feature": current_feature,
                "version": mu.group("ver"),
                "user": mu.group("user"),
                "host": mu.group("host"),
                "display": mu.group("display"),
                "pid": int(mu.group("pid")),
                "checkout_time": _parse_start_to_iso(mu.group("when")),
                "count": count,
            })
    return {
        "features": [
            {
                "name": f["name"],
                "version": f.get("version") or "1.0",
                "total": f["total"],
                "in_use_reported": f.get("in_use_reported", 0),
                "expires": f.get("expires") or "permanent",
                "increments": f.get("increments") or [],
            }
            for f in features.values()
        ],
        "checkouts": checkouts,
    }


# ---------- License-file INCREMENT parser ----------

# INCREMENT <feature> <daemon> <version> <date> <count> [...]
_RE_INCREMENT = re.compile(
    r"^\s*(?:INCREMENT|FEATURE)\s+(?P<feature>\S+)\s+(?P<daemon>\S+)\s+"
    r"(?P<version>\S+)\s+(?P<expires>\S+)\s+(?P<count>uncounted|\d+)",
    re.IGNORECASE,
)


def parse_license_file_increments(content: str) -> dict:
    """Walk every INCREMENT/FEATURE line in a .lic/.dat file and return
    {feature_name: [{version, expires, count}, ...]}. Multiple increments per
    feature (different expiry dates with separate seat counts) are preserved
    so the Expiry calendar shows each tranche separately."""
    out: dict = {}
    for raw in (content or "").splitlines():
        line = raw.rstrip("\\").strip()  # FlexLM may use \ for line continuation
        m = _RE_INCREMENT.match(line)
        if not m:
            continue
        feat = m.group("feature")
        count_raw = m.group("count")
        try:
            count = 0 if count_raw.lower() == "uncounted" else int(count_raw)
        except Exception:
            count = 0
        out.setdefault(feat, []).append({
            "version": m.group("version"),
            "expires": m.group("expires"),
            "count": count,
        })
    return out


async def _real_checkouts_via_ssh(server: dict) -> Optional[dict]:
    """Returns {features, checkouts} parsed from real lmstat output, or None on failure."""
    ssh = server.get("ssh", {}) or {}
    if not (ssh.get("enabled") and PARAMIKO_AVAILABLE):
        return None
    decrypted = _ssh_with_decrypted(ssh)
    lmutil = ssh.get("lmutil_path") or "lmutil"
    cmd = f"{lmutil} lmstat -a -c {server['port']}@{server['host']}"
    res = await asyncio.to_thread(_ssh_real_exec, decrypted, cmd)
    if res.get("exit") != 0 or not res.get("output"):
        logger.warning(f"lmstat ssh failed on {server['name']}: {res.get('output', '')[:200]}")
        return None
    return parse_lmstat_a(res["output"], server["id"])


async def gather_checkouts(server: dict) -> list:
    """Return checkouts. Use real lmstat when adapter_mode='ssh', else simulate."""
    mode = server.get("adapter_mode", "mock")
    if mode == "ssh":
        parsed = await _real_checkouts_via_ssh(server)
        if parsed is not None:
            # Merge license-file INCREMENT counts into each feature so the
            # Expiry calendar shows separate rows per tranche.
            lic_content = server.get("license_file") or ""
            inc_map = parse_license_file_increments(lic_content) if lic_content else {}
            for feat in parsed["features"]:
                inc_from_file = inc_map.get(feat["name"]) or []
                if inc_from_file:
                    # Prefer file data — it's the source of truth for per-tranche counts
                    feat["increments"] = inc_from_file
            if parsed["features"]:
                await db.servers.update_one(
                    {"id": server["id"]}, {"$set": {"features": parsed["features"]}}
                )
            return parsed["checkouts"]
        # SSH failed → fall back to empty (do NOT lie with simulated data)
        return []
    return generate_checkouts(server)


async def record_usage_history(server: dict, checkouts: list):
    """Upsert a usage_history entry per active checkout.
    Key: (server_id, feature, user, host, pid, checkout_time). We track first_seen
    and last_seen so the same checkout session counted across multiple sync ticks
    yields a single row whose duration_seconds = last_seen - first_seen.
    """
    if not checkouts:
        return
    now = datetime.now(timezone.utc)
    server_name = server.get("name", "")
    vendor = server.get("vendor", "")
    server_id = server.get("id", "")
    for c in checkouts:
        key = {
            "server_id": server_id,
            "feature": c.get("feature", ""),
            "user": c.get("user", ""),
            "host": c.get("host", ""),
            "pid": c.get("pid", 0),
            "checkout_time": c.get("checkout_time", ""),
        }
        update = {
            "$setOnInsert": {
                **key,
                "id": str(uuid.uuid4()),
                "server_name": server_name,
                "vendor": vendor,
                "version": c.get("version", ""),
                "display": c.get("display", ""),
                "first_seen": now,
                "first_seen_iso": now.isoformat(),
            },
            "$set": {
                "last_seen": now,
                "last_seen_iso": now.isoformat(),
            },
        }
        try:
            await db.usage_history.update_one(key, update, upsert=True)
        except Exception as e:
            logger.warning(f"usage_history upsert failed: {e}")



def default_license_text(vendor: str, name: str, port: int, daemon: str):
    """Build a plausible-looking license file."""
    today = datetime.now().strftime("%d-%b-%Y").lower()
    return (
        f"# {name} — {vendor.upper()} license file (generated)\n"
        f"SERVER lic-{vendor}-01 ANY {port}\n"
        f"VENDOR {daemon}\n"
        f"USE_SERVER\n"
        f"#\n"
        f"FEATURE example_feature {daemon} 1.0 permanent 10 \\\n"
        f"\tSIGN=\"00AB CD12 34EF 5678 9012 ABCD EF12 3456\" \\\n"
        f"\tISSUED={today}\n"
    )


def default_options_text(vendor: str):
    return (
        f"# Options file for {vendor.upper()}\n"
        f"# Lines beginning with '#' are comments.\n\n"
        f"REPORTLOG +/var/flexlm/{vendor}.report.log\n"
        f"TIMEOUTALL 7200\n"
        f"# RESERVE 1 example_feature USER alice\n"
        f"# EXCLUDE example_feature HOST untrusted-host\n"
        f"# GROUP design_team alice bob carol\n"
        f"# INCLUDE example_feature GROUP design_team\n"
    )


SEED_SERVERS = [
    {
        "name": "cadence-prod-01",
        "vendor": "cadence",
        "host": "10.10.11.111",
        "port": 5280,
        "daemon": "cdslmd",
        "features": [
            {"name": "Innovus", "version": "21.10", "total": 8, "expires": "31-dec-2026"},
            {"name": "Genus", "version": "21.10", "total": 6, "expires": "31-dec-2026"},
            {"name": "Virtuoso_L", "version": "ICADV12.3", "total": 12, "expires": "31-dec-2026"},
            {"name": "Spectre", "version": "21.1", "total": 16, "expires": "31-dec-2026"},
            {"name": "Tempus", "version": "21.10", "total": 4, "expires": "31-dec-2026"},
        ],
    },
    {
        "name": "siemens-mentor-prod-01",
        "vendor": "siemens",
        "host": "10.10.11.112",
        "port": 1717,
        "daemon": "mgcld",
        "features": [
            {"name": "Calibre_DRC", "version": "2023.4", "total": 12, "expires": "30-sep-2026"},
            {"name": "Calibre_LVS", "version": "2023.4", "total": 12, "expires": "30-sep-2026"},
            {"name": "Questa_Sim", "version": "2023.3", "total": 24, "expires": "30-sep-2026"},
            {"name": "Tessent_Shell", "version": "2023.3", "total": 4, "expires": "30-sep-2026"},
        ],
    },
    {
        "name": "synopsys-prod-01",
        "vendor": "synopsys",
        "host": "10.10.11.113",
        "port": 27020,
        "daemon": "snpslmd",
        "features": [
            {"name": "VCS-RuntimeNetlist", "version": "2023.06", "total": 32, "expires": "30-jun-2026"},
            {"name": "DesignCompiler", "version": "2023.06", "total": 8, "expires": "30-jun-2026"},
            {"name": "PrimeTime", "version": "2023.06", "total": 10, "expires": "30-jun-2026"},
            {"name": "ICCompiler2", "version": "2023.06", "total": 6, "expires": "30-jun-2026"},
            {"name": "Verdi", "version": "2023.06", "total": 20, "expires": "30-jun-2026"},
        ],
    },
]


async def seed_if_empty():
    # Skip seeding entirely when DEMO_MODE=0 (production install)
    if os.environ.get("DEMO_MODE", "1") == "0":
        return
    count = await db.servers.count_documents({})
    if count > 0:
        return
    for s in SEED_SERVERS:
        server = LicenseServer(
            name=s["name"], vendor=s["vendor"], host=s["host"],
            port=s["port"], daemon=s["daemon"], status="up",
            features=[FeatureModel(**f) for f in s["features"]],
            license_file=default_license_text(s["vendor"], s["name"], s["port"], s["daemon"]),
            options_file=default_options_text(s["vendor"]),
        )
        await db.servers.insert_one(server.model_dump())
        await log_audit("SEED", f"Seeded server {s['name']}", server.id, s["name"], "info")


# ---------- Secret encryption at rest (Fernet) ----------
from cryptography.fernet import Fernet, InvalidToken
import base64 as _b64
import hashlib as _hashlib

_ENC_PREFIX = "enc::v1::"


def _fernet() -> Optional[Fernet]:
    key = os.environ.get("FERNET_KEY", "").strip()
    if not key:
        return None
    # Accept either a real Fernet urlsafe-b64 key or a long passphrase (derive).
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        derived = _b64.urlsafe_b64encode(_hashlib.sha256(key.encode("utf-8")).digest())
        return Fernet(derived)


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    if value.startswith(_ENC_PREFIX):
        return value
    f = _fernet()
    if f is None:
        return value
    return _ENC_PREFIX + f.encrypt(value.encode("utf-8")).decode("utf-8")


def decrypt_secret(value: str) -> str:
    if not value or not isinstance(value, str):
        return value or ""
    if not value.startswith(_ENC_PREFIX):
        return value
    f = _fernet()
    if f is None:
        logger.warning("FERNET_KEY missing — cannot decrypt secret; returning empty")
        return ""
    try:
        return f.decrypt(value[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.warning("Fernet InvalidToken — FERNET_KEY likely changed since encryption")
        return ""


def _redact_ssh_for_client(ssh: dict) -> dict:
    """Return a copy of an ssh config dict with secret fields masked for API responses."""
    if not isinstance(ssh, dict):
        return ssh
    out = dict(ssh)
    if out.get("password"):
        out["password"] = "" if not out["password"] else "********"
    if out.get("private_key"):
        out["private_key"] = "********"
    return out


def _redact_smtp_for_client(cfg: dict) -> dict:
    out = dict(cfg)
    if out.get("smtp_password"):
        out["smtp_password"] = "********"
        out["smtp_password_set"] = True
    else:
        out["smtp_password_set"] = False
    return out


# ---------- end Fernet ----------


# ------------------------- AUTH (JWT + bcrypt) -------------------------

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 15
REFRESH_TOKEN_DAYS = 7
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 15


def _jwt_secret() -> str:
    sec = os.environ.get("JWT_SECRET")
    if not sec or len(sec) < 16:
        raise RuntimeError(
            "JWT_SECRET environment variable is missing or too short. "
            "Generate one with:  python -c \"import secrets; print(secrets.token_hex(64))\""
        )
    return sec


Role = Literal["admin", "engineer"]


class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: EmailStr
    name: str = ""
    role: Role
    active: bool = True
    created_at: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""
    role: Role = "engineer"


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Role] = None
    active: Optional[bool] = None
    password: Optional[str] = Field(default=None, min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SetupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = "Administrator"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def _create_token(payload: dict, minutes: int = ACCESS_TOKEN_MINUTES, kind: str = "access") -> str:
    now = datetime.now(timezone.utc)
    body = {
        **payload,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
        "type": kind,
    }
    return pyjwt.encode(body, _jwt_secret(), algorithm=JWT_ALGORITHM)


def create_access_token(user: dict) -> str:
    return _create_token(
        {"sub": user["id"], "email": user["email"], "role": user["role"]},
        minutes=ACCESS_TOKEN_MINUTES, kind="access",
    )


def create_refresh_token(user: dict) -> str:
    return _create_token(
        {"sub": user["id"]},
        minutes=REFRESH_TOKEN_DAYS * 24 * 60, kind="refresh",
    )


def _cookie_secure_flag() -> bool:
    return os.environ.get("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")


def _set_auth_cookies(response: Response, access: str, refresh: str):
    common = dict(httponly=True, samesite="lax", secure=_cookie_secure_flag(), path="/")
    response.set_cookie("access_token",  access,  max_age=ACCESS_TOKEN_MINUTES * 60, **common)
    response.set_cookie("refresh_token", refresh, max_age=REFRESH_TOKEN_DAYS * 86400, **common)


def _clear_auth_cookies(response: Response):
    response.delete_cookie("access_token",  path="/")
    response.delete_cookie("refresh_token", path="/")


def _user_public(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "email": doc["email"],
        "name": doc.get("name", ""),
        "role": doc.get("role", "engineer"),
        "active": doc.get("active", True),
        "created_at": doc.get("created_at"),
    }


def _read_token(request: Request) -> Optional[str]:
    tok = request.cookies.get("access_token")
    if tok:
        return tok
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


async def get_current_user(request: Request) -> dict:
    token = _read_token(request)
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(401, "Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
        if not user or not user.get("active", True):
            raise HTTPException(401, "User not found or disabled")
        return user
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin role required")
    return user


# ----- Brute-force protection -----

async def _is_locked_out(identifier: str) -> bool:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
    n = await db.login_attempts.count_documents({
        "identifier": identifier, "ts": {"$gt": cutoff}
    })
    return n >= LOCKOUT_THRESHOLD


async def _record_failed_login(identifier: str):
    await db.login_attempts.insert_one({
        "identifier": identifier, "ts": datetime.now(timezone.utc).isoformat()
    })


async def _clear_failed_logins(identifier: str):
    await db.login_attempts.delete_many({"identifier": identifier})


# ----- Auth routes -----

auth_router = APIRouter(prefix="/api/auth")


@auth_router.post("/setup")
async def auth_setup(payload: SetupRequest, response: Response):
    if (await db.users.count_documents({})) > 0:
        raise HTTPException(400, "Setup already complete")
    email = payload.email.lower()
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name or "Administrator",
        "role": "admin",
        "active": True,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    await log_audit("AUTH_SETUP", f"First-run admin created: {email}", None, None, "success")
    access  = create_access_token(user_doc)
    refresh = create_refresh_token(user_doc)
    _set_auth_cookies(response, access, refresh)
    return {"user": _user_public(user_doc), "access_token": access}


def _client_ip(request: Request) -> str:
    """Resolve the real client IP behind a reverse-proxy / k8s ingress."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip", "")
    if xri:
        return xri.strip()
    return request.client.host if request.client else "na"


@auth_router.post("/login")
async def auth_login(payload: LoginRequest, request: Request, response: Response):
    email = payload.email.lower()
    # Brute-force protection keys on email (and best-effort IP) so that k8s ingress
    # proxy-IP rotation doesn't split the counter across replicas.
    ident_email = f"email:{email}"
    ident_ip = f"ip:{_client_ip(request)}:{email}"
    if (await _is_locked_out(ident_email)) or (await _is_locked_out(ident_ip)):
        raise HTTPException(429, f"Too many failed attempts — locked for {LOCKOUT_MINUTES} minutes")
    user = await db.users.find_one({"email": email})
    if not user or not user.get("active", True) or not verify_password(payload.password, user.get("password_hash", "")):
        await _record_failed_login(ident_email)
        await _record_failed_login(ident_ip)
        raise HTTPException(401, "Invalid credentials")
    await _clear_failed_logins(ident_email)
    await _clear_failed_logins(ident_ip)
    access  = create_access_token(user)
    refresh = create_refresh_token(user)
    _set_auth_cookies(response, access, refresh)
    await log_audit("AUTH_LOGIN", f"{email} logged in", None, None, "info")
    return {"user": _user_public(user), "access_token": access}


@auth_router.get("/me")
async def auth_me(user: dict = Depends(get_current_user)):
    return _user_public(user)


@auth_router.post("/refresh")
async def auth_refresh(request: Request, response: Response):
    rtok = request.cookies.get("refresh_token") or ""
    if not rtok:
        raise HTTPException(401, "No refresh token")
    try:
        payload = pyjwt.decode(rtok, _jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid token type")
        user = await db.users.find_one({"id": payload["sub"]})
        if not user or not user.get("active", True):
            raise HTTPException(401, "User not found")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Refresh token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(401, "Invalid refresh token")
    access = create_access_token(user)
    response.set_cookie("access_token", access, max_age=ACCESS_TOKEN_MINUTES * 60,
                        httponly=True, samesite="lax", secure=_cookie_secure_flag(), path="/")
    return {"access_token": access, "user": _user_public(user)}


@auth_router.post("/logout")
async def auth_logout(response: Response, user: dict = Depends(get_current_user)):
    _clear_auth_cookies(response)
    await log_audit("AUTH_LOGOUT", f"{user['email']} logged out", None, None, "info")
    return {"ok": True}


# ----- User management (admin) -----

@api_router.get("/users", response_model=List[UserPublic])
async def list_users(_: dict = Depends(require_admin)):
    docs = await db.users.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(500)
    return [_user_public(d) for d in docs]


@api_router.post("/users", response_model=UserPublic)
async def create_user(payload: UserCreate, admin: dict = Depends(require_admin)):
    email = payload.email.lower()
    if await db.users.find_one({"email": email}):
        raise HTTPException(409, "Email already exists")
    user_doc = {
        "id": str(uuid.uuid4()),
        "email": email,
        "name": payload.name,
        "role": payload.role,
        "active": True,
        "password_hash": hash_password(payload.password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(user_doc)
    await log_audit("USER_CREATE", f"{admin['email']} created {email} ({payload.role})",
                    None, None, "success")
    return _user_public(user_doc)


@api_router.patch("/users/{user_id}", response_model=UserPublic)
async def update_user(user_id: str, payload: UserUpdate, admin: dict = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(404, "User not found")
    update: dict = {}
    if payload.name is not None:
        update["name"] = payload.name
    if payload.role is not None:
        update["role"] = payload.role
    if payload.active is not None:
        update["active"] = payload.active
    if payload.password is not None:
        update["password_hash"] = hash_password(payload.password)
    # Guard: don't lock the last admin out of admin role / deactivate them
    if (payload.role == "engineer" or payload.active is False) and target.get("role") == "admin":
        admins_left = await db.users.count_documents({"role": "admin", "active": True})
        if admins_left <= 1:
            raise HTTPException(400, "Cannot demote/disable the last active admin")
    if not update:
        raise HTTPException(400, "No fields to update")
    await db.users.update_one({"id": user_id}, {"$set": update})
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    await log_audit("USER_UPDATE", f"{admin['email']} updated {target['email']}: {list(update.keys())}",
                    None, None, "info")
    return _user_public(doc)


@api_router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(require_admin)):
    target = await db.users.find_one({"id": user_id})
    if not target:
        raise HTTPException(404, "User not found")
    if target["id"] == admin["id"]:
        raise HTTPException(400, "Cannot delete yourself")
    if target.get("role") == "admin":
        admins_left = await db.users.count_documents({"role": "admin", "active": True})
        if admins_left <= 1:
            raise HTTPException(400, "Cannot delete the last active admin")
    await db.users.delete_one({"id": user_id})
    await log_audit("USER_DELETE", f"{admin['email']} deleted {target['email']}",
                    None, None, "warning")
    return {"ok": True}


# ------------------------- end AUTH -------------------------


# ------------------------- Routes -------------------------

@public_router.get("/")
async def root():
    return {"service": "LICMAN", "status": "ok"}


@public_router.get("/health")
async def health():
    """Liveness — process responds, doesn't touch the database."""
    return {"status": "ok"}


@public_router.get("/ready")
async def ready():
    """Readiness — verifies the DB is reachable."""
    try:
        await db.command("ping")
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(503, f"db unreachable: {e}")


@public_router.get("/setup-status")
async def setup_status():
    count = await db.users.count_documents({})
    return {"needs_setup": count == 0}


@api_router.get("/servers", response_model=List[LicenseServer])
async def list_servers():
    docs = await db.servers.find({}, {"_id": 0}).to_list(500)
    for d in docs:
        d["ssh"] = _redact_ssh_for_client(d.get("ssh", {}))
    return docs


@api_router.post("/servers", response_model=LicenseServer)
async def create_server(payload: ServerCreate, _: dict = Depends(require_admin)):
    srv = LicenseServer(
        name=payload.name, vendor=payload.vendor, host=payload.host,
        port=payload.port, daemon=payload.daemon, status="up",
        license_file=default_license_text(payload.vendor, payload.name, payload.port, payload.daemon),
        options_file=default_options_text(payload.vendor),
        features=[],
    )
    await db.servers.insert_one(srv.model_dump())
    await log_audit("SERVER_CREATE", f"Created server {payload.name} ({payload.vendor})",
                    srv.id, payload.name, "success")
    return srv


@api_router.get("/servers/{server_id}", response_model=LicenseServer)
async def get_server(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    doc["ssh"] = _redact_ssh_for_client(doc.get("ssh", {}))
    return doc


@api_router.patch("/servers/{server_id}", response_model=LicenseServer)
async def update_server(server_id: str, payload: ServerUpdate):
    update = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(400, "No fields to update")
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": update},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    await log_audit("SERVER_UPDATE", f"Updated {res['name']}: {update}",
                    server_id, res["name"], "info")
    return res


@api_router.delete("/servers/{server_id}")
async def delete_server(server_id: str, _: dict = Depends(require_admin)):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0, "name": 1})
    if not doc:
        raise HTTPException(404, "Server not found")
    await db.servers.delete_one({"id": server_id})
    await db.checkouts.delete_many({"server_id": server_id})
    await db.reservations.delete_many({"server_id": server_id})
    await log_audit("SERVER_DELETE", f"Deleted {doc['name']}", server_id, doc["name"], "warning")
    return {"ok": True}


@api_router.put("/servers/{server_id}/license")
async def save_license_file(server_id: str, payload: FileContent,
                             push_to_disk: bool = True, reread: bool = True):
    """Save license file. If license_file_path is set + SSH enabled, also write
    the content to that path on the remote host (atomic via .new + mv) and
    optionally fire lmreread so the daemon picks up the new entitlements."""
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"license_file": payload.content}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")

    # Parse INCREMENT/FEATURE lines into the feature list + per-increment tranches
    inc_map = parse_license_file_increments(payload.content)
    features = []
    for fname, increments in inc_map.items():
        total = sum(int(i.get("count") or 0) for i in increments)
        # Pick the EARLIEST expiry as the feature's nominal expiry (so dashboard
        # surfaces the nearest renewal date). Per-tranche detail is in increments[].
        earliest = ""
        try:
            from datetime import datetime as _dt
            dts = []
            for i in increments:
                exp = (i.get("expires") or "").strip()
                if not exp or exp.lower() in ("permanent", "1-jan-0000"):
                    continue
                try:
                    dts.append((_dt.strptime(exp, "%d-%b-%Y"), exp))
                except Exception:
                    pass
            if dts:
                dts.sort(key=lambda x: x[0])
                earliest = dts[0][1]
        except Exception:
            pass
        features.append({
            "name": fname,
            "version": increments[0].get("version") or "1.0",
            "expires": earliest or "permanent",
            "total": total or 1,
            "in_use_reported": 0,
            "increments": increments,
        })
    if features:
        await db.servers.update_one({"id": server_id}, {"$set": {"features": features}})

    pushed, push_err, rereaded = False, None, False
    ssh = res.get("ssh", {}) or {}
    lic_path = (res.get("license_file_path") or "").strip()
    is_ssh = res.get("adapter_mode") == "ssh" and ssh.get("enabled") and PARAMIKO_AVAILABLE
    if push_to_disk and is_ssh and lic_path:
        import base64
        b64 = base64.b64encode(payload.content.encode("utf-8")).decode("ascii")
        # Atomic write: stage to .new, mv into place. Preserves existing perms via cp --preserve.
        cmd = (
            f"echo {_shlex.quote(b64)} | base64 -d > {_shlex.quote(lic_path + '.new')} "
            f"&& (cp --preserve=mode {_shlex.quote(lic_path)} {_shlex.quote(lic_path + '.bak')} 2>/dev/null || true) "
            f"&& mv {_shlex.quote(lic_path + '.new')} {_shlex.quote(lic_path)} "
            f"&& echo PUSHED_OK || echo PUSH_FAILED"
        )
        pr = await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), cmd)
        pushed = "PUSHED_OK" in (pr.get("output") or "")
        if not pushed:
            push_err = (pr.get("output") or "")[:300] or "unknown error"
        if pushed and reread:
            lmutil = (ssh.get("lmutil_path") or "lmutil").strip()
            target = f"{res['port']}@{res['host']}"
            daemon = (res.get("daemon") or "").strip()
            r_cmd = f"{_shlex.quote(lmutil)} lmreread -c {_shlex.quote(target)}"
            if daemon:
                r_cmd += f" -vendor {_shlex.quote(daemon)}"
            rr = await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), r_cmd)
            rereaded = rr.get("exit") == 0

    await log_audit(
        "LICENSE_SAVE",
        f"License file updated for {res['name']} · features={len(features)} "
        f"pushed={pushed} reread={rereaded} path={lic_path or '(db only)'}"
        f"{' · ERR:' + push_err if push_err else ''}",
        server_id, res["name"], "warning" if push_err else "success",
    )
    return {
        "ok": True, "features_parsed": len(features),
        "pushed_to_disk": pushed, "lmreread": rereaded,
        "license_path": lic_path, "push_error": push_err,
        "stored_in_db": True,
    }


@api_router.put("/servers/{server_id}/options")
async def save_options_file(server_id: str, payload: FileContent,
                             push_to_disk: bool = True, reread: bool = True):
    """Save options file. If the server has options_file_path set and SSH enabled,
    also push the content to that path on the remote host and trigger lmreread so
    the running daemon picks up the changes."""
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"options_file": payload.content}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    pushed = False
    push_error = None
    rereaded = False
    opts_path = (res.get("options_file_path") or "").strip()
    ssh = res.get("ssh", {}) or {}
    is_ssh = res.get("adapter_mode") == "ssh" and ssh.get("enabled") and PARAMIKO_AVAILABLE
    if push_to_disk and is_ssh and opts_path:
        # Stream the content via stdin to avoid escaping nightmares; use cat > path
        import base64
        b64 = base64.b64encode(payload.content.encode("utf-8")).decode("ascii")
        cmd = (
            f"echo {_shlex.quote(b64)} | base64 -d > {_shlex.quote(opts_path)} "
            f"&& echo PUSHED_OK || echo PUSH_FAILED"
        )
        push_res = await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), cmd)
        pushed = "PUSHED_OK" in (push_res.get("output") or "")
        if not pushed:
            push_error = (push_res.get("output") or "")[:300] or "unknown error"
        if pushed and reread:
            lmutil = (ssh.get("lmutil_path") or "lmutil").strip()
            target = f"{res['port']}@{res['host']}"
            daemon = (res.get("daemon") or "").strip()
            r_cmd = f"{_shlex.quote(lmutil)} lmreread -c {_shlex.quote(target)}"
            if daemon:
                r_cmd += f" -vendor {_shlex.quote(daemon)}"
            rr = await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), r_cmd)
            rereaded = rr.get("exit") == 0
    await log_audit(
        "OPTIONS_SAVE",
        f"Options saved for {res['name']} · pushed={pushed} reread={rereaded} "
        f"path={opts_path or '(db only)'}{' · ERR:' + push_error if push_error else ''}",
        server_id, res["name"], "warning" if push_error else "success",
    )
    return {
        "ok": True, "pushed_to_disk": pushed, "lmreread": rereaded,
        "options_path": opts_path, "push_error": push_error,
        "stored_in_db": True,
    }


@api_router.post("/servers/{server_id}/options/sync-reservations")
async def sync_reservations_to_options(server_id: str, _: dict = Depends(require_admin)):
    """Merge all reservations stored in MongoDB into the options file content
    as `RESERVE <count> <feature> <TYPE> <target>` directives, then push to disk
    and lmreread. This is what makes the Reservations tab actually take effect
    on the running daemon."""
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    reservations = await db.reservations.find(
        {"server_id": server_id}, {"_id": 0}
    ).to_list(500)
    existing = doc.get("options_file", "") or ""
    # Strip out previously-generated RESERVE block (marked by sentinel) so we don't duplicate
    SENTINEL_START = "# --- LICMAN MANAGED RESERVATIONS START ---"
    SENTINEL_END = "# --- LICMAN MANAGED RESERVATIONS END ---"
    lines = existing.splitlines()
    kept = []
    skipping = False
    for ln in lines:
        if ln.strip() == SENTINEL_START:
            skipping = True
            continue
        if ln.strip() == SENTINEL_END:
            skipping = False
            continue
        if not skipping:
            kept.append(ln)
    # Trim trailing blank lines
    while kept and not kept[-1].strip():
        kept.pop()
    # Append fresh RESERVE block
    new_block = [SENTINEL_START]
    new_block.append(f"# {len(reservations)} reservation(s) — auto-generated by LICMAN")
    new_block.append(f"# Last sync: {datetime.now(timezone.utc).isoformat()}")
    for r in reservations:
        new_block.append(
            f"RESERVE {r.get('count', 1)} {r['feature']} {r['target_type']} {r['target']}"
        )
    new_block.append(SENTINEL_END)
    new_content = "\n".join(kept + [""] + new_block) + "\n"
    # Reuse save endpoint logic
    save_res = await save_options_file(
        server_id, FileContent(content=new_content), push_to_disk=True, reread=True
    )
    return {
        **save_res,
        "reservations_merged": len(reservations),
        "options_content_preview": new_content[-800:],
    }


@api_router.post("/servers/{server_id}/reread")
async def reread(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    # Correct lmutil syntax:  lmutil lmreread -c <port>@<host> [-vendor <daemon>]
    lmutil = ((doc.get("ssh") or {}).get("lmutil_path") or "lmutil").strip()
    target = f"{doc['port']}@{doc['host']}"
    daemon = (doc.get("daemon") or "").strip()
    cmd = f"{_shlex.quote(lmutil)} lmreread -c {_shlex.quote(target)}"
    if daemon:
        cmd += f" -vendor {_shlex.quote(daemon)}"
    exec_log = await ssh_execute(doc, cmd)
    ok = exec_log.get("exit") == 0 or exec_log.get("mode") == "mock"
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"status": "up", "last_action": f"lmreread [{exec_log['mode']}] @ {datetime.now(timezone.utc).isoformat()}"}}
    )
    await log_audit("LMREREAD",
                    f"lmreread issued to {doc['name']} · exit={exec_log.get('exit')} · {(exec_log.get('output') or '')[:200]}",
                    server_id, doc["name"], "success" if ok else "error")
    return {"ok": ok, "message": f"lmreread executed on {doc['name']}", "exec": exec_log}


@api_router.post("/servers/{server_id}/restart")
async def restart(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    exec_log = await ssh_execute(doc, f"systemctl restart {doc['daemon']}")
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"status": "up", "last_action": f"restart [{exec_log['mode']}] @ {datetime.now(timezone.utc).isoformat()}"}}
    )
    await log_audit("DAEMON_RESTART", f"Daemon restart on {doc['name']} · {exec_log['output']}",
                    server_id, doc["name"], "warning")
    return {"ok": True, "message": f"{doc['daemon']} restarted on {doc['name']}", "exec": exec_log}


class KillCheckoutPayload(BaseModel):
    feature: str
    user: str
    host: str
    display: str = ""
    vendor_daemon: str = ""  # e.g. "snpslmd", "cdslmd". If empty, uses server.daemon


@api_router.post("/servers/{server_id}/diagnose")
async def diagnose_server(server_id: str, _: dict = Depends(require_admin)):
    """RAW lmstat output for debugging. Runs the same lmstat command we'd use
    for sync but returns the unparsed output so you can verify what your real
    server is reporting and tune the regex if anything is missed.
    """
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    ssh = doc.get("ssh", {}) or {}
    is_ssh = doc.get("adapter_mode") == "ssh" and ssh.get("enabled") and PARAMIKO_AVAILABLE
    lmutil = (ssh.get("lmutil_path") or "lmutil").strip()
    target = f"{doc['port']}@{doc['host']}"
    cmd_stat = f"{_shlex.quote(lmutil)} lmstat -a -c {_shlex.quote(target)}"
    cmd_diag = f"{_shlex.quote(lmutil)} lmdiag -c {_shlex.quote(target)} -n 2>&1 | head -200"
    cmd_which = f"command -v {_shlex.quote(lmutil)} || echo 'NOT FOUND'"
    if is_ssh:
        ssh_dec = _ssh_with_decrypted(ssh)
        which_r = await asyncio.to_thread(_ssh_real_exec, ssh_dec, cmd_which)
        stat_r = await asyncio.to_thread(_ssh_real_exec, ssh_dec, cmd_stat)
        diag_r = await asyncio.to_thread(_ssh_real_exec, ssh_dec, cmd_diag)
    else:
        which_r = {"output": f"[mock] {lmutil} → /opt/flexlm/lmutil", "exit": 0, "mode": "mock"}
        stat_r = {"output": "[mock] lmstat not run — switch adapter_mode='ssh' to see real output",
                  "exit": -1, "mode": "mock"}
        diag_r = {"output": "[mock]", "exit": -1, "mode": "mock"}
    # Re-run the parser on the captured stat output so we can show "parsed N / raw M lines"
    parsed_features, parsed_checkouts = 0, 0
    try:
        if stat_r.get("output"):
            p = parse_lmstat_a(stat_r["output"], server_id)
            parsed_features = len(p.get("features", []))
            parsed_checkouts = len(p.get("checkouts", []))
    except Exception as e:
        logger.warning(f"diagnose parser failed: {e}")
    return {
        "server": doc["name"],
        "mode": "ssh" if is_ssh else "mock",
        "lmutil_resolved": (which_r.get("output") or "").strip(),
        "lmstat": {
            "command": cmd_stat,
            "exit": stat_r.get("exit"),
            "output": stat_r.get("output", ""),
            "lines": len((stat_r.get("output") or "").splitlines()),
            "parsed_features": parsed_features,
            "parsed_checkouts": parsed_checkouts,
        },
        "lmdiag": {
            "command": cmd_diag,
            "exit": diag_r.get("exit"),
            "output": (diag_r.get("output") or "")[:8000],
        },
    }


@api_router.post("/servers/{server_id}/checkouts/kill")
async def kill_checkout(server_id: str, payload: KillCheckoutPayload, admin: dict = Depends(require_admin)):
    """Forcibly release a checked-out license via `lmremove`.
    Real SSH path uses:  lmremove -h <feature> <vendor_daemon> <host> <user>
    Mock mode logs the intent + audit entry without contacting any server.
    """
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    # Validate every user-supplied identifier against a tight regex BEFORE composing
    # the shell command — prevents injection via spaces, semicolons, backticks, $()
    _SAFE = re.compile(r"^[A-Za-z0-9._@:/+\-]+$")
    for label, value in (
        ("feature", payload.feature),
        ("user", payload.user),
        ("host", payload.host),
    ):
        if not value or not _SAFE.match(value):
            raise HTTPException(
                400,
                f"Invalid {label!r}: must match ^[A-Za-z0-9._@:/+-]+$ (got {value!r})",
            )
    # display is optional, but if given must also be safe (allow colon for X11 ':0.0')
    if payload.display and not _SAFE.match(payload.display):
        raise HTTPException(400, f"Invalid display: {payload.display!r}")
    lmutil = ((doc.get("ssh") or {}).get("lmutil_path") or "lmutil").strip()
    # Correct FlexLM lmremove syntax (via lmutil):
    #   lmutil lmremove [-c port@host] feature user host [display]
    # All identifiers are pre-validated above; quote defensively anyway.
    target = f"{doc['port']}@{doc['host']}"
    display = payload.display.strip() if payload.display else ""
    cmd = (
        f"{_shlex.quote(lmutil)} lmremove "
        f"-c {_shlex.quote(target)} "
        f"{_shlex.quote(payload.feature)} "
        f"{_shlex.quote(payload.user)} "
        f"{_shlex.quote(payload.host)}"
    )
    if display:
        cmd += f" {_shlex.quote(display)}"
    exec_log = await ssh_execute(doc, cmd)
    ok = exec_log.get("exit") == 0 or exec_log.get("mode") == "mock"
    severity = "success" if ok else "error"
    await log_audit(
        "CHECKOUT_KILL",
        f"kill {payload.feature} for {payload.user}@{payload.host} on {doc['name']} "
        f"[{exec_log.get('mode')}] · {(exec_log.get('output') or '')[:200]}",
        server_id, doc["name"], severity,
    )
    if ok:
        await db.checkouts.delete_many({
            "server_id": server_id,
            "feature": payload.feature,
            "user": payload.user,
            "host": payload.host,
        })
    return {"ok": ok, "message": f"lmremove issued for {payload.feature}", "exec": exec_log}


@api_router.post("/servers/{server_id}/toggle")
async def toggle_status(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    new_status = "down" if doc["status"] == "up" else "up"
    await db.servers.update_one({"id": server_id}, {"$set": {"status": new_status}})
    await log_audit("STATUS_TOGGLE", f"{doc['name']} -> {new_status}",
                    server_id, doc["name"], "warning" if new_status == "down" else "success")
    return {"ok": True, "status": new_status}


@api_router.get("/servers/{server_id}/checkouts", response_model=List[Checkout])
async def server_checkouts(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc or doc.get("status") != "up":
        return []
    fresh = await gather_checkouts(doc)
    await db.checkouts.delete_many({"server_id": server_id})
    if fresh:
        await db.checkouts.insert_many([{**c} for c in fresh])
        await record_usage_history(doc, fresh)
    return fresh


@api_router.get("/checkouts", response_model=List[Checkout])
async def all_checkouts():
    servers = await db.servers.find({"status": "up"}, {"_id": 0}).to_list(500)
    all_co = []
    for srv in servers:
        fresh = await gather_checkouts(srv)
        all_co.extend(fresh)
        await record_usage_history(srv, fresh)
    await db.checkouts.delete_many({})
    if all_co:
        await db.checkouts.insert_many([{**c} for c in all_co])
    try:
        await evaluate_alerts()
    except Exception as e:
        logger.warning(f"alert evaluation failed: {e}")
    return all_co


# ---------- SSH config ----------

@api_router.put("/servers/{server_id}/ssh", response_model=LicenseServer)
async def save_ssh_config(server_id: str, payload: SshConfig, _: dict = Depends(require_admin)):
    cfg = payload.model_dump()
    # If client sends masked secrets, preserve existing stored values
    existing = await db.servers.find_one({"id": server_id}, {"_id": 0, "ssh": 1})
    if existing and existing.get("ssh"):
        old = existing["ssh"]
        if cfg.get("password") in ("", "********"):
            cfg["password"] = old.get("password", "")
        else:
            cfg["password"] = encrypt_secret(cfg["password"])
        if cfg.get("private_key") in ("", "********"):
            cfg["private_key"] = old.get("private_key", "")
        else:
            cfg["private_key"] = encrypt_secret(cfg["private_key"])
    else:
        if cfg.get("password"):
            cfg["password"] = encrypt_secret(cfg["password"])
        if cfg.get("private_key"):
            cfg["private_key"] = encrypt_secret(cfg["private_key"])
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"ssh": cfg}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    await log_audit("SSH_CONFIG", f"SSH config updated for {res['name']} (host={payload.host})",
                    server_id, res["name"], "info")
    # Redact for response
    res["ssh"] = _redact_ssh_for_client(res.get("ssh", {}))
    return res


class AdapterPayload(BaseModel):
    adapter_mode: Literal["mock", "ssh"]


@api_router.put("/servers/{server_id}/adapter")
async def set_adapter(server_id: str, payload: AdapterPayload, _: dict = Depends(require_admin)):
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"adapter_mode": payload.adapter_mode}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    await log_audit("ADAPTER_MODE", f"{res['name']} adapter -> {payload.adapter_mode}",
                    server_id, res["name"], "warning")
    return {"ok": True, "adapter_mode": payload.adapter_mode}


@api_router.post("/servers/{server_id}/ssh/test")
async def test_ssh(server_id: str, _: dict = Depends(require_admin)):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    ssh = doc.get("ssh", {}) or {}
    if not (ssh.get("host") and ssh.get("username")):
        return {"ok": False, "message": "Missing host or username", "mocked": True}
    if ssh.get("enabled") and PARAMIKO_AVAILABLE:
        res = await asyncio.to_thread(
            _ssh_real_exec, _ssh_with_decrypted(ssh),
            f"echo licman-ok && which {ssh.get('lmutil_path','lmutil')} || true"
        )
        ok = res.get("exit") == 0
        await log_audit("SSH_TEST", f"SSH test {ssh['username']}@{ssh['host']} -> {res.get('output')[:200]}",
                        server_id, doc["name"], "success" if ok else "error")
        return {"ok": ok, "message": res.get("output", "")[:500], "mocked": False, "exit": res.get("exit")}
    msg = f"[STUB] would connect to {ssh.get('username')}@{ssh.get('host')}:{ssh.get('port', 22)}"
    await log_audit("SSH_TEST", msg, server_id, doc["name"], "info")
    return {"ok": True, "message": msg, "mocked": True}


@api_router.post("/servers/{server_id}/sync")
async def sync_server(server_id: str, _: dict = Depends(require_admin)):
    """Run lmstat -a over SSH, parse, persist features + checkouts."""
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    if doc.get("adapter_mode") != "ssh":
        raise HTTPException(400, "Sync requires adapter_mode='ssh' on this server")
    parsed = await _real_checkouts_via_ssh(doc)
    if parsed is None:
        await log_audit("SYNC_FAIL", f"lmstat sync failed for {doc['name']}",
                        server_id, doc["name"], "error")
        raise HTTPException(502, "lmstat command failed — check SSH config and lmutil_path")
    update = {}
    if parsed["features"]:
        update["features"] = parsed["features"]
    update["last_action"] = f"lmstat sync @ {datetime.now(timezone.utc).isoformat()}"
    await db.servers.update_one({"id": server_id}, {"$set": update})
    await db.checkouts.delete_many({"server_id": server_id})
    if parsed["checkouts"]:
        await db.checkouts.insert_many([{**c} for c in parsed["checkouts"]])
        await record_usage_history(doc, parsed["checkouts"])
    await log_audit("SYNC_OK",
                    f"Synced {doc['name']}: {len(parsed['features'])} features, {len(parsed['checkouts'])} checkouts",
                    server_id, doc["name"], "success")
    return {
        "ok": True,
        "features_parsed": len(parsed["features"]),
        "checkouts_parsed": len(parsed["checkouts"]),
    }


@api_router.post("/servers/{server_id}/fetch-license")
async def fetch_license(server_id: str, path: Optional[str] = None, _: dict = Depends(require_admin)):
    """Pull the actual .lic file from the license host over SSH (cat).
    If ?path= is provided, skip auto-discovery and cat that exact path.
    """
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    ssh = doc.get("ssh", {}) or {}
    if doc.get("adapter_mode") != "ssh" or not ssh.get("enabled"):
        raise HTTPException(400, "SSH adapter not enabled on this server")
    ssh_decrypted = _ssh_with_decrypted(ssh)
    lmutil = (ssh.get("lmutil_path") or "lmutil").strip()
    # Priority: explicit ?path= → server.license_file_path → auto-discover via lmdiag
    lic_path = (path or doc.get("license_file_path") or "").strip()
    if not lic_path:
        target = f"{doc['port']}@{doc['host']}"
        discover_cmd = (
            f"{_shlex.quote(lmutil)} lmdiag -c {_shlex.quote(target)} 2>/dev/null "
            f"| grep -m1 -oE '/[^ ]+\\.(lic|dat)' || true"
        )
        disc = await asyncio.to_thread(_ssh_real_exec, ssh_decrypted, discover_cmd)
        lic_path = (disc.get("output") or "").strip().splitlines()[0] if disc.get("output") else ""
        if not lic_path:
            raise HTTPException(
                404,
                "Could not auto-discover the license file path. "
                "Set 'license_file_path' on this server (Dashboard → server card → edit), "
                "or call this endpoint with ?path=/full/path/to/license.dat",
            )
    res = await asyncio.to_thread(
        _ssh_real_exec, ssh_decrypted, f"cat {_shlex.quote(lic_path)}"
    )
    if res.get("exit") != 0 or not res.get("output"):
        raise HTTPException(502, f"Failed to read remote license file: {(res.get('output') or '')[:300]}")
    content = res["output"]
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"license_file": content, "license_file_path": lic_path}},
    )
    # Also pre-populate per-increment expiry data so the calendar is correct
    # immediately, without waiting for the next sync.
    inc_map = parse_license_file_increments(content)
    if inc_map:
        cur_features = (await db.servers.find_one({"id": server_id}, {"_id": 0})).get("features", []) or []
        idx = {f["name"]: f for f in cur_features}
        for fname, incs in inc_map.items():
            f = idx.setdefault(fname, {
                "name": fname,
                "version": incs[0].get("version") or "1.0",
                "expires": incs[0].get("expires") or "permanent",
                "total": sum(int(i.get("count") or 0) for i in incs),
                "in_use_reported": 0,
            })
            f["increments"] = incs
            f["total"] = sum(int(i.get("count") or 0) for i in incs) or f.get("total") or 1
        await db.servers.update_one(
            {"id": server_id}, {"$set": {"features": list(idx.values())}}
        )
    await log_audit("LICENSE_FETCH",
                    f"Fetched license from {ssh.get('host')}:{lic_path} ({len(content)} bytes)",
                    server_id, doc["name"], "success")
    return {"ok": True, "path": lic_path, "bytes": len(content)}


@api_router.post("/servers/{server_id}/fetch-options")
async def fetch_options(server_id: str, path: Optional[str] = None,
                         _: dict = Depends(require_admin)):
    """Pull the actual options file from the license host via SSH.
    Mirrors fetch_license — uses options_file_path if set, else ?path= override.
    """
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    ssh = doc.get("ssh", {}) or {}
    if doc.get("adapter_mode") != "ssh" or not ssh.get("enabled"):
        raise HTTPException(400, "SSH adapter not enabled on this server")
    opts_path = (path or doc.get("options_file_path") or "").strip()
    if not opts_path:
        raise HTTPException(
            400,
            "options_file_path is not set on this server. Click 'edit paths' "
            "on the server detail page and point to your options file (e.g. "
            "/cadmgr/cadence/options.txt) — then click FETCH again. "
            "Alternatively pass ?path=/full/path/to/options.txt",
        )
    ssh_decrypted = _ssh_with_decrypted(ssh)
    res = await asyncio.to_thread(
        _ssh_real_exec, ssh_decrypted, f"cat {_shlex.quote(opts_path)}"
    )
    if res.get("exit") != 0:
        raise HTTPException(
            502,
            f"Failed to read remote options file at {opts_path}: "
            f"{(res.get('output') or 'no output')[:300]}",
        )
    content = res.get("output") or ""
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"options_file": content, "options_file_path": opts_path}},
    )
    # Materialize RESERVE directives from the fetched file back into LICMAN's
    # reservations collection so the Reservations tab matches what's actually
    # running on the daemon. We REPLACE LICMAN-managed reservations and SKIP
    # the ones inside the LICMAN-managed sentinel block (those came from us).
    SENT_START = "# --- LICMAN MANAGED RESERVATIONS START ---"
    SENT_END = "# --- LICMAN MANAGED RESERVATIONS END ---"
    in_managed = False
    discovered = []
    for raw in content.splitlines():
        line = raw.strip()
        if line == SENT_START:
            in_managed = True
            continue
        if line == SENT_END:
            in_managed = False
            continue
        if in_managed or not line or line.startswith("#"):
            continue
        # RESERVE <count> <feature> <TYPE> <target>
        m = re.match(
            r"^RESERVE\s+(\d+)\s+(\S+)\s+(USER|HOST|GROUP|HOST_GROUP|PROJECT|DISPLAY|INTERNET)\s+(\S+)",
            line, re.IGNORECASE,
        )
        if m:
            discovered.append({
                "id": str(uuid.uuid4()),
                "server_id": server_id,
                "feature": m.group(2),
                "target_type": m.group(3).upper(),
                "target": m.group(4),
                "count": int(m.group(1)),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": "options-file",
            })
    if discovered:
        # Replace only options-file-sourced reservations (preserve UI-added ones)
        await db.reservations.delete_many({
            "server_id": server_id, "source": "options-file"
        })
        await db.reservations.insert_many(discovered)
    await log_audit(
        "OPTIONS_FETCH",
        f"Fetched options from {ssh.get('host')}:{opts_path} "
        f"({len(content)} bytes, {len(discovered)} RESERVE entries imported)",
        server_id, doc["name"], "success",
    )
    return {
        "ok": True, "path": opts_path, "bytes": len(content),
        "reservations_imported": len(discovered),
    }


# ---------- Bulk operations ----------

@api_router.post("/servers/sync-all")
async def sync_all_servers(_: dict = Depends(require_admin)):
    """Run lmstat sync over SSH for every adapter_mode='ssh' & ssh.enabled server."""
    servers = await db.servers.find(
        {"adapter_mode": "ssh", "ssh.enabled": True}, {"_id": 0}
    ).to_list(500)
    results = []
    total_feats = 0
    total_co = 0
    for srv in servers:
        try:
            parsed = await _real_checkouts_via_ssh(srv)
            if parsed is None:
                results.append({"server_id": srv["id"], "name": srv["name"],
                                "ok": False, "error": "lmstat failed"})
                continue
            update = {"last_sync": datetime.now(timezone.utc).isoformat()}
            if parsed["features"]:
                update["features"] = parsed["features"]
            await db.servers.update_one({"id": srv["id"]}, {"$set": update})
            await db.checkouts.delete_many({"server_id": srv["id"]})
            if parsed["checkouts"]:
                await db.checkouts.insert_many([{**c} for c in parsed["checkouts"]])
                await record_usage_history(srv, parsed["checkouts"])
            total_feats += len(parsed["features"])
            total_co += len(parsed["checkouts"])
            results.append({
                "server_id": srv["id"], "name": srv["name"], "ok": True,
                "features": len(parsed["features"]),
                "checkouts": len(parsed["checkouts"]),
            })
        except Exception as e:
            results.append({"server_id": srv["id"], "name": srv["name"],
                            "ok": False, "error": str(e)[:200]})
    await log_audit("SYNC_ALL",
                    f"Bulk sync: {len(servers)} server(s), {total_feats} features, {total_co} checkouts",
                    None, None, "success")
    return {"ok": True, "count": len(servers), "features_total": total_feats,
            "checkouts_total": total_co, "results": results}


@api_router.post("/servers/reread-all")
async def reread_all_servers(_: dict = Depends(require_admin)):
    """Issue lmreread to every server. Uses SSH if enabled, otherwise mock."""
    servers = await db.servers.find({}, {"_id": 0}).to_list(500)
    results = []
    for srv in servers:
        try:
            exec_log = await ssh_execute(srv, f"lmreread -c @{srv['port']}@{srv['host']}")
            await db.servers.update_one(
                {"id": srv["id"]},
                {"$set": {"status": "up",
                          "last_action": f"lmreread [{exec_log['mode']}] @ {datetime.now(timezone.utc).isoformat()}"}}
            )
            results.append({"server_id": srv["id"], "name": srv["name"], "ok": True,
                            "mode": exec_log.get("mode")})
        except Exception as e:
            results.append({"server_id": srv["id"], "name": srv["name"],
                            "ok": False, "error": str(e)[:200]})
    await log_audit("REREAD_ALL", f"Bulk lmreread: {len(servers)} server(s)", None, None, "info")
    return {"ok": True, "count": len(servers), "results": results}


# ---------- Options file validator ----------

class OptionsValidatePayload(BaseModel):
    content: str


_OPT_KEYWORDS = {
    "RESERVE", "INCLUDE", "EXCLUDE", "INCLUDEALL", "EXCLUDEALL",
    "INCLUDE_BORROW", "EXCLUDE_BORROW",
    "MAX", "MAX_BORROW_HOURS", "MAX_OVERDRAFT",
    "TIMEOUT", "TIMEOUTALL", "LINGER", "REPORTLOG", "DEBUGLOG",
    "GROUP", "HOST_GROUP", "NOLOG", "GROUPCASEINSENSITIVE",
}
_OPT_TARGETS = {"USER", "HOST", "GROUP", "HOST_GROUP", "INTERNET", "PROJECT", "DISPLAY"}


@api_router.post("/servers/{server_id}/options/validate")
async def validate_options(server_id: str, payload: OptionsValidatePayload):
    """Light syntax check for FlexLM options files. Returns warnings/errors with line numbers."""
    srv = await db.servers.find_one({"id": server_id}, {"_id": 0, "name": 1})
    if not srv:
        raise HTTPException(404, "Server not found")
    issues = []
    summary = {"reserve": 0, "include": 0, "exclude": 0, "group": 0, "max": 0, "timeout": 0}
    for ln, raw in enumerate(payload.content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        kw = parts[0].upper()
        if kw not in _OPT_KEYWORDS:
            issues.append({"line": ln, "severity": "error",
                           "message": f"Unknown directive: {parts[0]}"})
            continue
        # Bucket counts
        if kw == "RESERVE":
            summary["reserve"] += 1
        elif kw.startswith("INCLUDE"):
            summary["include"] += 1
        elif kw.startswith("EXCLUDE"):
            summary["exclude"] += 1
        elif kw in ("GROUP", "HOST_GROUP"):
            summary["group"] += 1
        elif kw.startswith("MAX"):
            summary["max"] += 1
        elif kw.startswith("TIMEOUT"):
            summary["timeout"] += 1
        # Per-keyword arg validation
        if kw == "RESERVE":
            if len(parts) < 4:
                issues.append({"line": ln, "severity": "error",
                               "message": "RESERVE requires: count feature TYPE name"})
            else:
                if not parts[1].isdigit():
                    issues.append({"line": ln, "severity": "error",
                                   "message": "RESERVE count must be an integer"})
                if parts[3].upper() not in _OPT_TARGETS:
                    issues.append({"line": ln, "severity": "warning",
                                   "message": f"Unknown RESERVE target type: {parts[3]}"})
        elif kw in ("INCLUDE", "EXCLUDE", "INCLUDE_BORROW", "EXCLUDE_BORROW"):
            if len(parts) < 4:
                issues.append({"line": ln, "severity": "error",
                               "message": f"{kw} requires: feature TYPE name"})
            elif parts[2].upper() not in _OPT_TARGETS:
                issues.append({"line": ln, "severity": "warning",
                               "message": f"Unknown {kw} target type: {parts[2]}"})
        elif kw in ("INCLUDEALL", "EXCLUDEALL"):
            if len(parts) < 3:
                issues.append({"line": ln, "severity": "error",
                               "message": f"{kw} requires: TYPE name"})
            elif parts[1].upper() not in _OPT_TARGETS:
                issues.append({"line": ln, "severity": "warning",
                               "message": f"Unknown {kw} target type: {parts[1]}"})
        elif kw == "GROUP" or kw == "HOST_GROUP":
            if len(parts) < 3:
                issues.append({"line": ln, "severity": "error",
                               "message": f"{kw} requires: name member1 [member2 ...]"})
        elif kw == "TIMEOUT":
            if len(parts) < 3 or not parts[2].isdigit():
                issues.append({"line": ln, "severity": "error",
                               "message": "TIMEOUT requires: feature seconds"})
        elif kw == "TIMEOUTALL":
            if len(parts) < 2 or not parts[1].isdigit():
                issues.append({"line": ln, "severity": "error",
                               "message": "TIMEOUTALL requires: seconds"})
        elif kw == "MAX":
            if len(parts) < 4:
                issues.append({"line": ln, "severity": "error",
                               "message": "MAX requires: count feature TYPE name"})
    error_count = sum(1 for i in issues if i["severity"] == "error")
    return {"ok": error_count == 0, "issues": issues, "summary": summary,
            "errors": error_count, "warnings": len(issues) - error_count}


# ---------- Expiry ----------

@api_router.get("/expiry")
async def expiry_calendar(warn_days: int = 90):
    """One row per INCREMENT tranche. A feature with seats split across multiple
    INCREMENT lines (e.g. 1 seat exp 26-may + 2 seats exp 29-may) emits TWO
    rows so the calendar reflects the staggered renewal schedule, not just the
    last expiry date."""
    servers = await db.servers.find({}, {"_id": 0}).to_list(500)
    rows = []
    for s in servers:
        for f in s.get("features", []):
            increments = f.get("increments") or []
            # Backfill from `expires` so legacy features (no increments parsed) still
            # produce exactly one row.
            if not increments:
                increments = [{
                    "version": f.get("version"),
                    "expires": f.get("expires", ""),
                    "count": f.get("total") or 0,
                }]
            for inc in increments:
                expires_str = inc.get("expires") or ""
                d = parse_expiry(expires_str)
                days = days_until(d)
                rows.append({
                    "server_id": s["id"],
                    "server_name": s["name"],
                    "vendor": s["vendor"],
                    "feature": f["name"],
                    "version": inc.get("version") or f.get("version"),
                    "total": inc.get("count") or f.get("total"),
                    "expires": expires_str or "permanent",
                    "expires_iso": d.isoformat() if d else None,
                    "days_remaining": days,
                    "status": (
                        "permanent" if days is None
                        else "expired" if days < 0
                        else "critical" if days <= 30
                        else "warning" if days <= warn_days
                        else "ok"
                    ),
                })
    # Sort: expired first, then nearest expiry, permanent at end
    def sk(r):
        if r["days_remaining"] is None:
            return (2, 0)
        if r["days_remaining"] < 0:
            return (0, r["days_remaining"])
        return (1, r["days_remaining"])
    rows.sort(key=sk)
    return rows


@api_router.get("/expiry/export")
async def expiry_export(warn_days: int = 90):
    """Stream the expiry calendar as CSV for spreadsheet/ticketing workflows."""
    rows = await expiry_calendar(warn_days=warn_days)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["vendor", "server_name", "feature", "version", "total",
                "expires", "expires_iso", "days_remaining", "status"])
    for r in rows:
        w.writerow([r.get("vendor", ""), r.get("server_name", ""), r.get("feature", ""),
                    r.get("version", ""), r.get("total", ""), r.get("expires", ""),
                    r.get("expires_iso", "") or "", r.get("days_remaining") if r.get("days_remaining") is not None else "",
                    r.get("status", "")])
    filename = f"licman-expiry-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/audit/export")
async def audit_export(limit: int = 1000):
    """Stream recent audit log entries as CSV for compliance / change-control reviews."""
    docs = await db.audit.find({}, {"_id": 0, "ts": 0}).sort("timestamp", -1).to_list(limit)
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["timestamp", "actor", "severity", "action", "server_name", "server_id", "detail"])
    for d in docs:
        w.writerow([d.get("timestamp", ""), d.get("actor", ""), d.get("severity", ""),
                    d.get("action", ""), d.get("server_name", "") or "",
                    d.get("server_id", "") or "", d.get("detail", "")])
    filename = f"licman-audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Settings / Alerts ----------

@api_router.get("/settings")
async def get_settings():
    cfg = await get_alert_settings(decrypt_smtp=False)
    return _redact_smtp_for_client(cfg)


@api_router.put("/settings")
async def put_settings(payload: AlertSettings, _: dict = Depends(require_admin)):
    data = payload.model_dump()
    existing = await db.settings.find_one({"_key": "alerts"}, {"_id": 0}) or {}
    # Preserve existing encrypted password if client sent masked value
    if data.get("smtp_password") in ("", "********"):
        data["smtp_password"] = existing.get("smtp_password", "")
    else:
        data["smtp_password"] = encrypt_secret(data["smtp_password"])
    data["_key"] = "alerts"
    await db.settings.update_one({"_key": "alerts"}, {"$set": data}, upsert=True)
    await log_audit(
        "SETTINGS_SAVE",
        f"Alert settings updated (enabled={payload.enabled}, recipients={len(payload.to_addresses)})",
        None, None, "info",
    )
    out = dict(data)
    out.pop("_key", None)
    return _redact_smtp_for_client(out)


@api_router.post("/settings/test-email")
async def test_email(_: dict = Depends(require_admin)):
    cfg = await get_alert_settings()
    if not cfg.get("smtp_host"):
        raise HTTPException(400, "SMTP host not configured")
    if not cfg.get("to_addresses"):
        raise HTTPException(400, "No recipient addresses configured")
    # Force enabled=True for the test send
    cfg2 = {**cfg, "enabled": True}
    ok, err = send_smtp_email(
        cfg2, "[LICMAN] Test email", "This is a test alert from LICMAN. If you receive this, SMTP works."
    )
    ev = AlertEvent(
        kind="test", detail=f"Test email -> {', '.join(cfg['to_addresses'])}",
        delivered=ok, error=err  # type: ignore
    )
    await db.alert_events.insert_one(ev.model_dump())
    await log_audit("ALERT_TEST", f"Test email: delivered={ok} err={err}", None, None,
                    "success" if ok else "error")
    return {"ok": ok, "error": err}


@api_router.post("/settings/test-webhook")
async def test_webhook(_: dict = Depends(require_admin)):
    cfg = await get_alert_settings()
    if not cfg.get("webhook_url"):
        raise HTTPException(400, "Webhook URL not configured")
    cfg2 = {**cfg, "webhook_enabled": True}
    ok, err = send_webhook(
        cfg2, "test", "[LICMAN] Test webhook",
        "This is a test alert from LICMAN. If you receive this, the webhook works.",
    )
    ev = AlertEvent(
        kind="test", detail=f"Test webhook -> {cfg.get('webhook_kind') or 'generic'}",
        delivered=ok, error=err  # type: ignore
    )
    await db.alert_events.insert_one(ev.model_dump())
    await log_audit("ALERT_WEBHOOK_TEST", f"Webhook test delivered={ok} err={err}", None, None,
                    "success" if ok else "error")
    return {"ok": ok, "error": err}


@api_router.get("/alerts")
async def list_alerts(limit: int = 50):
    docs = await db.alert_events.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return docs


@api_router.post("/alerts/evaluate")
async def force_evaluate_alerts():
    await evaluate_alerts()
    return {"ok": True}


@api_router.get("/reservations", response_model=List[Reservation])
async def list_reservations(server_id: Optional[str] = None):
    q = {"server_id": server_id} if server_id else {}
    return await db.reservations.find(q, {"_id": 0}).to_list(500)


@api_router.post("/reservations", response_model=Reservation)
async def create_reservation(payload: ReservationCreate, auto_apply: bool = True):
    srv = await db.servers.find_one({"id": payload.server_id}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    r = Reservation(**payload.model_dump())
    await db.reservations.insert_one(r.model_dump())
    applied = False
    if auto_apply and (srv.get("options_file_path") or "").strip() \
            and srv.get("adapter_mode") == "ssh" \
            and (srv.get("ssh") or {}).get("enabled"):
        try:
            await sync_reservations_to_options(payload.server_id, {"role": "admin"})  # type: ignore
            applied = True
        except Exception as e:
            logger.warning(f"reservation auto-apply failed: {e}")
    await log_audit(
        "RESERVE",
        f"RESERVE {r.count} {r.feature} {r.target_type} {r.target} on {srv['name']} "
        f"(applied={applied})",
        srv["id"], srv["name"], "info",
    )
    return r


@api_router.delete("/reservations/{rid}")
async def delete_reservation(rid: str, auto_apply: bool = True):
    doc = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Reservation not found")
    await db.reservations.delete_one({"id": rid})
    srv = await db.servers.find_one({"id": doc["server_id"]}, {"_id": 0})
    applied = False
    if (
        auto_apply and srv
        and (srv.get("options_file_path") or "").strip()
        and srv.get("adapter_mode") == "ssh"
        and (srv.get("ssh") or {}).get("enabled")
    ):
        try:
            await sync_reservations_to_options(doc["server_id"], {"role": "admin"})  # type: ignore
            applied = True
        except Exception as e:
            logger.warning(f"reservation auto-apply failed: {e}")
    await log_audit(
        "UNRESERVE",
        f"Removed RESERVE {doc['feature']} {doc['target_type']} {doc['target']} "
        f"(applied={applied})",
        doc["server_id"], srv["name"] if srv else None, "info",
    )
    return {"ok": True, "applied_to_options": applied}


@api_router.get("/audit", response_model=List[AuditLog])
async def audit(limit: int = 50):
    docs = await db.audit.find({}, {"_id": 0, "ts": 0}).sort("timestamp", -1).to_list(limit)
    return docs


# ---------- Usage history ----------

def _parse_iso_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # Accept 'YYYY-MM-DD' or full ISO. Treat naive as UTC.
        if len(s) == 10 and s.count("-") == 2:
            dt = datetime.fromisoformat(s + "T00:00:00+00:00")
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _build_usage_query(*, from_dt: Optional[datetime], to_dt: Optional[datetime],
                      user: Optional[str], feature: Optional[str],
                      server_id: Optional[str], vendor: Optional[str]) -> dict:
    q: dict = {}
    if from_dt or to_dt:
        # We consider a session "in range" if its [first_seen, last_seen] overlaps [from, to]
        range_clauses = []
        if from_dt:
            range_clauses.append({"last_seen": {"$gte": from_dt}})
        if to_dt:
            range_clauses.append({"first_seen": {"$lte": to_dt}})
        if range_clauses:
            q["$and"] = range_clauses
    if user:
        q["user"] = {"$regex": f"^{re.escape(user)}$", "$options": "i"}
    if feature:
        q["feature"] = {"$regex": f"^{re.escape(feature)}$", "$options": "i"}
    if server_id:
        q["server_id"] = server_id
    if vendor:
        q["vendor"] = vendor
    return q


@api_router.get("/usage")
async def usage_history_list(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Optional[str] = None,
    feature: Optional[str] = None,
    server_id: Optional[str] = None,
    vendor: Optional[str] = None,
    limit: int = 1000,
):
    """List historical license usage sessions. Times are UTC ISO strings.
    Supports date_from/date_to (YYYY-MM-DD or full ISO), user, feature, server_id, vendor filters.
    """
    q = _build_usage_query(
        from_dt=_parse_iso_to_dt(date_from),
        to_dt=_parse_iso_to_dt(date_to),
        user=user, feature=feature, server_id=server_id, vendor=vendor,
    )
    docs = await db.usage_history.find(
        q, {"_id": 0, "first_seen": 0, "last_seen": 0}
    ).sort("last_seen_iso", -1).to_list(min(max(limit, 1), 5000))
    return docs


@api_router.get("/usage/export")
async def usage_history_export(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Optional[str] = None,
    feature: Optional[str] = None,
    server_id: Optional[str] = None,
    vendor: Optional[str] = None,
    limit: int = 10000,
):
    """Stream the same filtered usage history as CSV."""
    q = _build_usage_query(
        from_dt=_parse_iso_to_dt(date_from),
        to_dt=_parse_iso_to_dt(date_to),
        user=user, feature=feature, server_id=server_id, vendor=vendor,
    )
    docs = await db.usage_history.find(
        q, {"_id": 0, "first_seen": 0, "last_seen": 0}
    ).sort("last_seen_iso", -1).to_list(min(max(limit, 1), 100000))
    buf = _io.StringIO()
    w = _csv.writer(buf)
    w.writerow([
        "first_seen", "last_seen", "duration_seconds",
        "vendor", "server_name", "feature", "version",
        "user", "host", "display", "pid", "checkout_time",
    ])
    for d in docs:
        try:
            f = _parse_iso_to_dt(d.get("first_seen_iso"))
            l_ = _parse_iso_to_dt(d.get("last_seen_iso"))
            dur = int((l_ - f).total_seconds()) if (f and l_) else ""
        except Exception:
            dur = ""
        w.writerow([
            d.get("first_seen_iso", ""), d.get("last_seen_iso", ""), dur,
            d.get("vendor", ""), d.get("server_name", ""), d.get("feature", ""),
            d.get("version", ""), d.get("user", ""), d.get("host", ""),
            d.get("display", ""), d.get("pid", ""), d.get("checkout_time", ""),
        ])
    filename = f"licman-usage-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_router.get("/usage/summary")
async def usage_history_summary(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: Optional[str] = None,
    feature: Optional[str] = None,
    server_id: Optional[str] = None,
    vendor: Optional[str] = None,
    group_by: Literal["user", "feature", "vendor", "server_name"] = "feature",
):
    """Aggregate usage history by user/feature/vendor/server. Returns sorted by total sessions desc."""
    q = _build_usage_query(
        from_dt=_parse_iso_to_dt(date_from),
        to_dt=_parse_iso_to_dt(date_to),
        user=user, feature=feature, server_id=server_id, vendor=vendor,
    )
    pipeline = [
        {"$match": q},
        {"$group": {
            "_id": f"${group_by}",
            "sessions": {"$sum": 1},
            "unique_users": {"$addToSet": "$user"},
            "unique_features": {"$addToSet": "$feature"},
            "first_seen_min": {"$min": "$first_seen_iso"},
            "last_seen_max": {"$max": "$last_seen_iso"},
        }},
        {"$project": {
            "_id": 0,
            "key": "$_id",
            "sessions": 1,
            "user_count": {"$size": "$unique_users"},
            "feature_count": {"$size": "$unique_features"},
            "first_seen": "$first_seen_min",
            "last_seen": "$last_seen_max",
        }},
        {"$sort": {"sessions": -1}},
        {"$limit": 1000},
    ]
    rows = await db.usage_history.aggregate(pipeline).to_list(1000)
    return {"group_by": group_by, "rows": rows}


@api_router.get("/usage/facets")
async def usage_history_facets():
    """Distinct users / features / vendors / servers for filter dropdowns."""
    users = await db.usage_history.distinct("user")
    features = await db.usage_history.distinct("feature")
    vendors = await db.usage_history.distinct("vendor")
    servers = await db.usage_history.distinct("server_name")
    return {
        "users": sorted([u for u in users if u]),
        "features": sorted([f for f in features if f]),
        "vendors": sorted([v for v in vendors if v]),
        "servers": sorted([s for s in servers if s]),
        "total_rows": await db.usage_history.count_documents({}),
    }


# ---------- Preemption ( SGE / FlexLM priority-based release ) ----------
# A `priority_rule` describes WHO has what priority on WHICH feature(s).
# Higher `priority` wins. When a higher-priority requester needs a feature
# that is fully checked out, we find the lowest-priority current holder
# and release them via lmremove (or SGE `qmod -d <jobid>` if SGE integration
# is configured under /api/settings).
#
# Matching:
#   - user_pattern   — exact user name OR glob like "rakella*"
#   - group_pattern  — group name (resolved via SGE `qconf -shgrp` if enabled)
#   - project_pattern— SGE project (`qstat -ext` shows project per job)
#   - features       — list of feature names; empty list = applies to ALL features
# Evaluation order: highest priority first; first match wins.

class PriorityRule(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    priority: int = Field(ge=0, le=1000)
    user_pattern: str = ""
    group_pattern: str = ""
    project_pattern: str = ""
    features: List[str] = []
    description: str = ""
    enabled: bool = True
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PriorityRuleCreate(BaseModel):
    name: str
    priority: int = Field(ge=0, le=1000)
    user_pattern: str = ""
    group_pattern: str = ""
    project_pattern: str = ""
    features: List[str] = []
    description: str = ""
    enabled: bool = True


class PreemptPayload(BaseModel):
    server_id: str
    feature: str
    requester_user: str = ""
    requester_group: str = ""
    requester_project: str = ""
    seats_needed: int = 1
    dry_run: bool = False


def _match_pattern(pat: str, value: str) -> bool:
    """Glob-style match. Empty pattern never matches."""
    if not pat:
        return False
    import fnmatch
    return fnmatch.fnmatch(value or "", pat)


async def _resolve_priority(user: str, group: str = "", project: str = "",
                            feature: str = "") -> int:
    """Return the priority an actor has for a given feature (0 = no rule matched)."""
    rules = await db.priority_rules.find(
        {"enabled": True}, {"_id": 0}
    ).sort("priority", -1).to_list(500)
    best = 0
    for r in rules:
        feats = r.get("features") or []
        if feats and feature and feature not in feats:
            continue
        if _match_pattern(r.get("user_pattern", ""), user):
            best = max(best, int(r.get("priority", 0)))
        if group and _match_pattern(r.get("group_pattern", ""), group):
            best = max(best, int(r.get("priority", 0)))
        if project and _match_pattern(r.get("project_pattern", ""), project):
            best = max(best, int(r.get("priority", 0)))
    return best


@api_router.get("/priority-rules", response_model=List[PriorityRule])
async def list_priority_rules():
    return await db.priority_rules.find({}, {"_id": 0}).sort("priority", -1).to_list(500)


@api_router.post("/priority-rules", response_model=PriorityRule)
async def create_priority_rule(payload: PriorityRuleCreate, _: dict = Depends(require_admin)):
    rule = PriorityRule(**payload.model_dump())
    await db.priority_rules.insert_one(rule.model_dump())
    await log_audit("PRIORITY_ADD",
                    f"Added priority rule '{rule.name}' (prio={rule.priority})",
                    None, None, "info")
    return rule


@api_router.patch("/priority-rules/{rule_id}", response_model=PriorityRule)
async def update_priority_rule(rule_id: str, payload: PriorityRuleCreate,
                                _: dict = Depends(require_admin)):
    data = payload.model_dump()
    res = await db.priority_rules.find_one_and_update(
        {"id": rule_id}, {"$set": data},
        return_document=True, projection={"_id": 0},
    )
    if not res:
        raise HTTPException(404, "Rule not found")
    await log_audit("PRIORITY_UPDATE", f"Updated priority rule '{res['name']}'",
                    None, None, "info")
    return res


@api_router.delete("/priority-rules/{rule_id}")
async def delete_priority_rule(rule_id: str, _: dict = Depends(require_admin)):
    res = await db.priority_rules.find_one_and_delete({"id": rule_id}, projection={"_id": 0})
    if not res:
        raise HTTPException(404, "Rule not found")
    await log_audit("PRIORITY_DELETE", f"Deleted priority rule '{res['name']}'",
                    None, None, "warning")
    return {"ok": True}


@api_router.post("/preempt/plan")
async def preempt_plan(payload: PreemptPayload, _: dict = Depends(require_admin)):
    """Compute (but do NOT execute) which checkouts would be released to satisfy
    the requester. Useful for previewing a preemption before clicking the
    destructive button. Returns the holders sorted by ascending priority
    (lowest priority first → first to release).
    """
    srv = await db.servers.find_one({"id": payload.server_id}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    holders = await db.checkouts.find(
        {"server_id": payload.server_id, "feature": payload.feature}, {"_id": 0}
    ).to_list(500)
    requester_prio = await _resolve_priority(
        payload.requester_user, payload.requester_group,
        payload.requester_project, payload.feature,
    )
    enriched = []
    for h in holders:
        hp = await _resolve_priority(h.get("user", ""), "", "", payload.feature)
        enriched.append({**h, "holder_priority": hp})
    # Releasable holders = those strictly lower priority than the requester
    releasable = [h for h in enriched if h["holder_priority"] < requester_prio]
    releasable.sort(key=lambda x: (x["holder_priority"], x.get("checkout_time", "")))
    return {
        "feature": payload.feature,
        "server": srv["name"],
        "requester_priority": requester_prio,
        "current_holders": len(holders),
        "releasable_holders": len(releasable),
        "seats_needed": payload.seats_needed,
        "can_satisfy": len(releasable) >= payload.seats_needed,
        "targets": releasable[: payload.seats_needed],
    }


async def _sge_kill_job(ssh_decrypted: dict, user: str, host: str) -> Optional[dict]:
    """Try to find the SGE job_id running on (user, host) and `qmod -d` it.
    Falls back to None if no SGE integration configured or no matching job."""
    cfg = await get_alert_settings()  # alerts collection also holds SGE keys
    if not cfg.get("sge_enabled"):
        return None
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    qmod = (cfg.get("sge_qmod_path") or "qmod").strip()
    # qstat -u <user> -s r -F  →  one line per running job; we grep host.
    list_cmd = (
        f"{_shlex.quote(qstat)} -u {_shlex.quote(user)} -s r 2>/dev/null "
        f"| awk -v h={_shlex.quote(host)} '$0 ~ h {{print $1; exit}}'"
    )
    r = await asyncio.to_thread(_ssh_real_exec, ssh_decrypted, list_cmd)
    jid = (r.get("output") or "").strip().splitlines()[0] if r.get("output") else ""
    if not jid or not jid.isdigit():
        return None
    kill_cmd = f"{_shlex.quote(qmod)} -d {_shlex.quote(jid)}"
    k = await asyncio.to_thread(_ssh_real_exec, ssh_decrypted, kill_cmd)
    return {"job_id": jid, "exit": k.get("exit"), "output": (k.get("output") or "")[:300]}


@api_router.post("/preempt/run")
async def preempt_run(payload: PreemptPayload, admin: dict = Depends(require_admin)):
    """Execute the preemption plan. For each target holder:
      1. Try SGE  qmod -d <job_id>  (graceful, cleans up the user's job)
      2. Fallback to lmutil lmremove (force-yank the license seat)
    Records every action in the audit log.
    """
    plan = await preempt_plan(payload, admin)
    if not plan["can_satisfy"]:
        return {
            "ok": False,
            "plan": plan,
            "message": (
                f"Cannot preempt — requester priority {plan['requester_priority']} "
                f"has only {plan['releasable_holders']} releasable holder(s) "
                f"but needs {payload.seats_needed}."
            ),
        }
    if payload.dry_run:
        return {"ok": True, "dry_run": True, "plan": plan}

    srv = await db.servers.find_one({"id": payload.server_id}, {"_id": 0})
    ssh = srv.get("ssh", {}) or {}
    ssh_decrypted = _ssh_with_decrypted(ssh) if ssh else {}
    actions = []
    for target in plan["targets"]:
        method, result = None, None
        # 1) try SGE qmod -d first (only if real SSH + sge enabled)
        if srv.get("adapter_mode") == "ssh" and ssh.get("enabled"):
            sge_res = await _sge_kill_job(ssh_decrypted, target["user"], target["host"])
            if sge_res:
                method = "sge"
                result = sge_res
        # 2) fallback to lmutil lmremove
        if result is None:
            kill_payload = KillCheckoutPayload(
                feature=target["feature"], user=target["user"],
                host=target["host"], display=target.get("display", "") or "",
            )
            try:
                kr = await kill_checkout(payload.server_id, kill_payload, admin)
                method = "lmremove"
                result = kr.get("exec")
            except HTTPException as e:
                method = "error"
                result = {"output": e.detail, "exit": -1}
        actions.append({
            "user": target["user"], "host": target["host"],
            "feature": target["feature"], "holder_priority": target["holder_priority"],
            "method": method, "result": result,
        })
    await log_audit(
        "PREEMPT",
        f"Preempted {len(actions)} holder(s) of {payload.feature} on {srv['name']} "
        f"for requester={payload.requester_user or payload.requester_group or payload.requester_project} "
        f"(prio={plan['requester_priority']})",
        payload.server_id, srv["name"], "warning",
    )
    return {"ok": True, "plan": plan, "actions": actions}


@api_router.get("/preempt/who-am-i")
async def preempt_who_am_i(user: str = "", group: str = "", project: str = "",
                           feature: str = ""):
    """Convenience helper for the UI — returns the priority an actor currently has."""
    prio = await _resolve_priority(user, group, project, feature)
    return {"user": user, "group": group, "project": project,
            "feature": feature, "priority": prio}


class RequestLicensePayload(BaseModel):
    server_id: str
    feature: str
    requester_user: str = ""
    requester_group: str = ""
    requester_project: str = ""
    seats_needed: int = 1
    auto_preempt: bool = True


@api_router.post("/license/request")
async def request_license(payload: RequestLicensePayload, _: dict = Depends(require_admin)):
    """Workflow when a high-priority user wants a license:
      1. If feature is available → return ok=true, suggestion="check it out normally"
      2. If saturated and the requester's priority > some current holder's priority →
         auto-preempt the lowest holder(s) and return ok=true, preempted=N
      3. If saturated and requester is NOT high enough → return ok=false, reason
    """
    srv = await db.servers.find_one({"id": payload.server_id}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    feat = next((f for f in (srv.get("features") or []) if f["name"] == payload.feature), None)
    if not feat:
        raise HTTPException(404, f"Feature '{payload.feature}' not found on {srv['name']}")
    holders = await db.checkouts.find(
        {"server_id": payload.server_id, "feature": payload.feature}, {"_id": 0}
    ).to_list(500)
    seats_used = sum(int(h.get("count") or 1) for h in holders)
    seats_total = int(feat.get("total") or 0)
    seats_free = max(0, seats_total - seats_used)
    if seats_free >= payload.seats_needed:
        return {
            "ok": True, "action": "available",
            "seats_free": seats_free,
            "message": f"{seats_free} seat(s) free — '{payload.requester_user or 'requester'}' can check out normally.",
        }
    # Saturated → try preemption
    if not payload.auto_preempt:
        return {
            "ok": False, "action": "blocked",
            "seats_free": seats_free,
            "message": "Feature saturated and auto_preempt=false. Run /api/preempt/plan to preview.",
        }
    pp = PreemptPayload(
        server_id=payload.server_id, feature=payload.feature,
        requester_user=payload.requester_user,
        requester_group=payload.requester_group,
        requester_project=payload.requester_project,
        seats_needed=payload.seats_needed - seats_free,
    )
    plan = await preempt_plan(pp, _)
    if not plan["can_satisfy"]:
        return {
            "ok": False, "action": "denied_low_priority",
            "seats_free": seats_free,
            "requester_priority": plan["requester_priority"],
            "message": (
                f"Saturated and requester priority {plan['requester_priority']} is not high enough "
                f"to displace any current holder. Try increasing the rule priority."
            ),
        }
    run_res = await preempt_run(pp, _)
    return {
        "ok": True, "action": "preempted",
        "seats_freed": len(run_res.get("actions") or []),
        "requester_priority": plan["requester_priority"],
        "preempt_result": run_res,
        "message": (
            f"Preempted {len(run_res.get('actions') or [])} holder(s) — "
            f"'{payload.requester_user or 'requester'}' can now check out."
        ),
    }


# ---------- SGE auto-discovery ----------
# When sge_enabled is true, these endpoints SSH into the first ssh-enabled server
# (assumed to share the SGE qmaster's $SGE_ROOT) and run qconf to enumerate
# real users / groups / projects so the admin doesn't have to type them by hand.

async def _pick_sge_ssh_server() -> Optional[dict]:
    """Pick any ssh-enabled server as the SGE control host. Caller can override
    via the alert settings doc later if their qmaster lives elsewhere."""
    return await db.servers.find_one(
        {"adapter_mode": "ssh", "ssh.enabled": True}, {"_id": 0}
    )


async def _sge_run(cmd: str) -> dict:
    """Run an SGE command (qconf/qstat) over SSH on the picked host."""
    cfg = await get_alert_settings()
    if not cfg.get("sge_enabled"):
        raise HTTPException(400, "SGE integration is disabled in Settings")
    srv = await _pick_sge_ssh_server()
    if not srv:
        raise HTTPException(400, "No SSH-enabled server available to reach SGE. "
                                  "Configure SSH on at least one license host first.")
    ssh = srv.get("ssh", {}) or {}
    res = await asyncio.to_thread(_ssh_real_exec, _ssh_with_decrypted(ssh), cmd)
    return {"server": srv["name"], "host": ssh.get("host"), **res}


def _qconf_path(cfg: dict) -> str:
    # Reuse qstat dir if user supplied an absolute path; otherwise rely on $PATH
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    if "/" in qstat:
        from os.path import dirname, join
        return join(dirname(qstat), "qconf")
    return "qconf"


@api_router.get("/sge/users")
async def sge_users(_: dict = Depends(require_admin)):
    """List active SGE submit-users (`qconf -suserl` + any usernames seen in
    currently running jobs via `qstat -u '*' -s r`).
    """
    cfg = await get_alert_settings()
    qconf = _qconf_path(cfg)
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    out_users = await _sge_run(f"{_shlex.quote(qconf)} -suserl 2>/dev/null || true")
    seen = {u.strip() for u in (out_users.get("output") or "").splitlines() if u.strip()}
    # also union users currently running jobs
    out_running = await _sge_run(
        f"{_shlex.quote(qstat)} -u '*' -s r 2>/dev/null | awk 'NR>2 {{print $4}}' | sort -u || true"
    )
    for u in (out_running.get("output") or "").splitlines():
        u = u.strip()
        if u and not u.startswith("queuename") and not u.startswith("---"):
            seen.add(u)
    return {"users": sorted(seen), "source": out_users.get("server")}


@api_router.get("/sge/groups")
async def sge_groups(_: dict = Depends(require_admin)):
    """List SGE host & user-set groups (`qconf -shgrpl` and per-group resolve)."""
    cfg = await get_alert_settings()
    qconf = _qconf_path(cfg)
    out = await _sge_run(f"{_shlex.quote(qconf)} -shgrpl 2>/dev/null || true")
    groups = [g.strip() for g in (out.get("output") or "").splitlines() if g.strip()]
    # Also try `qconf -sul` for user-set lists (ACL-style groups)
    out_acl = await _sge_run(f"{_shlex.quote(qconf)} -sul 2>/dev/null || true")
    acls = [g.strip() for g in (out_acl.get("output") or "").splitlines() if g.strip()]
    return {"groups": sorted(set(groups) | set(acls)), "source": out.get("server")}


@api_router.get("/sge/projects")
async def sge_projects(_: dict = Depends(require_admin)):
    """List SGE projects (`qconf -sprjl`)."""
    cfg = await get_alert_settings()
    qconf = _qconf_path(cfg)
    out = await _sge_run(f"{_shlex.quote(qconf)} -sprjl 2>/dev/null || true")
    projects = [p.strip() for p in (out.get("output") or "").splitlines() if p.strip()]
    return {"projects": sorted(projects), "source": out.get("server")}


@api_router.get("/sge/test")
async def sge_test(_: dict = Depends(require_admin)):
    """Smoke-test: confirm we can reach SGE (`qstat -help` should always work)."""
    cfg = await get_alert_settings()
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    try:
        out = await _sge_run(f"{_shlex.quote(qstat)} -help 2>&1 | head -3")
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    ok = out.get("exit") == 0
    return {
        "ok": ok,
        "exit": out.get("exit"),
        "command": f"{qstat} -help",
        "output": (out.get("output") or "")[:500],
        "server": out.get("server"),
        "host": out.get("host"),
    }


@api_router.get("/stats")
async def stats():
    servers = await db.servers.find({}, {"_id": 0}).to_list(500)
    total = len(servers)
    up = sum(1 for s in servers if s["status"] == "up")
    feat_total = sum(sum(f["total"] for f in s.get("features", [])) for s in servers)
    co_count = 0
    for s in servers:
        if s["status"] == "up":
            co_count += len(generate_checkouts(s))
    resv = await db.reservations.count_documents({})
    return {
        "servers_total": total,
        "servers_up": up,
        "features_total": feat_total,
        "checkouts_active": co_count,
        "reservations": resv,
    }


@api_router.post("/seed/reset")
async def seed_reset(_: dict = Depends(require_admin)):
    """Clear transient history (checkouts, alerts, audit, usage) WITHOUT
    deleting user-defined servers, reservations or SSH credentials. Demo
    seed data is recreated ONLY if the servers collection is already empty
    (fresh install). Safe to call against a production deployment.
    """
    await db.checkouts.delete_many({})
    await db.alert_events.delete_many({})
    await db.audit.delete_many({})
    await db.usage_history.delete_many({})
    # Only seed demo servers if there are NO servers yet — never overwrite
    # user-added production servers.
    if (await db.servers.count_documents({})) == 0:
        await seed_if_empty()
    await log_audit("MAINT_CLEAR", "Cleared transient history (checkouts/alerts/audit/usage)",
                    None, None, "warning")
    return {"ok": True, "message": "Transient history cleared — user servers preserved"}


# (Routers are included near the bottom, after the auto-preempt scheduler is
#  defined, so newly-added @api_router decorated endpoints are picked up.)

# CORS: in private-LAN deploys we serve via nginx proxy on the same origin,
# so a wildcard is fine. If you split origins, set CORS_ORIGINS=https://your.host
# (comma-separated). When credentials are used, '*' becomes a regex match.
_origins_env = os.environ.get('CORS_ORIGINS', '*').strip()
if _origins_env == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _origins_env.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ---------- Background auto-sync scheduler ----------

_sync_task: Optional[asyncio.Task] = None


async def _periodic_sync_loop():
    """Periodically run lmstat sync for every server with adapter_mode='ssh' and ssh.enabled."""
    interval = int(os.environ.get("SYNC_INTERVAL_SECONDS", "60"))
    if interval <= 0:
        logger.info("Auto-sync disabled (SYNC_INTERVAL_SECONDS=0)")
        return
    logger.info(f"Auto-sync loop started — interval {interval}s")
    while True:
        try:
            servers = await db.servers.find(
                {"adapter_mode": "ssh", "ssh.enabled": True}, {"_id": 0}
            ).to_list(500)
            for srv in servers:
                try:
                    parsed = await _real_checkouts_via_ssh(srv)
                    if parsed is None:
                        continue
                    update: dict = {"last_sync": datetime.now(timezone.utc).isoformat()}
                    if parsed["features"]:
                        update["features"] = parsed["features"]
                    await db.servers.update_one({"id": srv["id"]}, {"$set": update})
                    await db.checkouts.delete_many({"server_id": srv["id"]})
                    if parsed["checkouts"]:
                        await db.checkouts.insert_many([{**c} for c in parsed["checkouts"]])
                        await record_usage_history(srv, parsed["checkouts"])
                except Exception as e:
                    logger.warning(f"auto-sync failed for {srv.get('name')}: {e}")
            try:
                await evaluate_alerts()
            except Exception as e:
                logger.warning(f"auto-sync alerts pass failed: {e}")
        except Exception as e:
            logger.warning(f"auto-sync iteration error: {e}")
        await asyncio.sleep(interval)


# ---------- Auto-preemption background loop ----------

_preempt_task: Optional[asyncio.Task] = None


async def _sge_get_pending_license_requests() -> List[dict]:
    """Query SGE for jobs in `qw` (queued waiting) state, parse their hard
    resource_list to extract requested license features. Returns one entry per
    (job, feature) pair.

    Expected resource format from `qsub -l <feature>=<count>`:
        hard resource_list: innovus=1,calibre=2
    """
    cfg = await get_alert_settings()
    if not cfg.get("sge_enabled"):
        return []
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    # Pull pending jobs in XML for stable parsing (every SGE flavour supports -xml)
    cmd_list = f"{_shlex.quote(qstat)} -s p -u '*' -xml 2>/dev/null || true"
    try:
        out = await _sge_run(cmd_list)
    except HTTPException:
        return []
    raw = out.get("output") or ""
    if not raw.strip():
        return []
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # qstat -xml not supported on some old SGE forks. Fall back to plain.
        return await _sge_get_pending_legacy()
    requests: List[dict] = []
    for job in root.iter("job_list"):
        jid = (job.findtext("JB_job_number") or "").strip()
        user = (job.findtext("JB_owner") or "").strip()
        project = (job.findtext("JB_project") or "").strip()
        if not jid or not user:
            continue
        # Fetch hard resources for this job
        det_cmd = (
            f"{_shlex.quote(qstat)} -j {_shlex.quote(jid)} 2>/dev/null "
            f"| awk -F: '/^hard resource_list/ {{sub(/^[^:]*:[[:space:]]*/, \"\"); print; exit}}'"
        )
        try:
            det = await _sge_run(det_cmd)
        except HTTPException:
            continue
        line = (det.get("output") or "").strip()
        if not line:
            continue
        # Parse "feat1=1,feat2=2"
        for part in line.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            feat, seats_s = part.split("=", 1)
            feat = feat.strip()
            try:
                seats = max(1, int(seats_s.strip()))
            except Exception:
                seats = 1
            if not feat:
                continue
            requests.append({
                "jobid": jid, "user": user, "project": project,
                "feature": feat, "seats": seats,
            })
    return requests


async def _sge_get_pending_legacy() -> List[dict]:
    """Fallback parser for SGE forks that don't speak XML. Best-effort."""
    cfg = await get_alert_settings()
    qstat = (cfg.get("sge_qstat_path") or "qstat").strip()
    out = await _sge_run(
        f"{_shlex.quote(qstat)} -s p -u '*' 2>/dev/null | awk 'NR>2 {{print $1\"|\"$4}}'"
    )
    pairs = [
        ln.split("|", 1) for ln in (out.get("output") or "").splitlines()
        if "|" in ln and ln.strip()
    ]
    requests: List[dict] = []
    for jid, user in pairs:
        det = await _sge_run(
            f"{_shlex.quote(qstat)} -j {_shlex.quote(jid)} 2>/dev/null "
            f"| awk -F: '/^hard resource_list/ {{sub(/^[^:]*:[[:space:]]*/, \"\"); print; exit}}'"
        )
        line = (det.get("output") or "").strip()
        if not line:
            continue
        for part in line.split(","):
            if "=" not in part:
                continue
            feat, seats_s = part.split("=", 1)
            try:
                seats = max(1, int(seats_s.strip()))
            except Exception:
                seats = 1
            requests.append({
                "jobid": jid.strip(), "user": user.strip(), "project": "",
                "feature": feat.strip(), "seats": seats,
            })
    return requests


async def _find_server_for_feature(feature: str) -> Optional[dict]:
    """Locate the server whose features include this name (case-insensitive)."""
    cur = db.servers.find({"status": "up"}, {"_id": 0})
    async for s in cur:
        for f in s.get("features") or []:
            if (f.get("name") or "").lower() == feature.lower():
                return s
    return None


async def _heuristic_preempt_candidates() -> List[dict]:
    """SGE-free fallback. Explicit signal source only — the pending_requests
    queue (admins/engineers explicitly ask "ramkella needs Innovus").

    The rule-driven proactive preemption is handled separately by
    `_rule_driven_preempt_pass` because rules can use wildcards / groups /
    projects and don't need a synthesized requester user.
    """
    pending = await db.pending_requests.find(
        {"state": "open"}, {"_id": 0}
    ).sort("created_at", 1).to_list(500)
    out: List[dict] = []
    for p in pending:
        # Skip aged-out requests (> 1h) — they probably gave up
        try:
            ts = datetime.fromisoformat((p.get("created_at") or "").replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - ts).total_seconds() > 3600:
                await db.pending_requests.update_one(
                    {"id": p["id"]}, {"$set": {"state": "expired"}}
                )
                continue
        except Exception:
            pass
        out.append({
            "jobid": f"req:{p['id']}",
            "user": p["user"], "project": "",
            "feature": p["feature"], "seats": int(p.get("seats") or 1),
            "_request_id": p["id"],
        })
    return out


async def _rule_driven_preempt_pass(fake_admin: dict) -> dict:
    """Proactive preemption driven by priority rules alone — no SGE, no UI
    click required. For each enabled rule, for each saturated feature in
    the rule (or all features if rule.features is empty), preempt the
    lowest-priority holder if at least one holder has strictly lower
    priority than the rule. Works with wildcard / group / project patterns
    because no synthetic requester user is needed — the rule's own
    priority is the requester-priority.

    Idempotency:
    - Skips the feature if a holder already matches the rule's pattern
      (high-priority user already has a seat → nothing to free for them)
    - Skips if all holders are at or above the rule's priority
    - Frees AT MOST ONE seat per (rule, feature) per tick to avoid runaway
      kills when many low-priority holders exist
    """
    rules = await db.priority_rules.find(
        {"enabled": True}, {"_id": 0}
    ).sort("priority", -1).to_list(500)
    if not rules:
        return {"scanned_rules": 0, "actioned": 0, "results": [], "reasons": []}

    actioned = 0
    results: List[dict] = []
    reasons: List[dict] = []
    # Track (server_id, feature) we already freed this tick so two rules
    # don't double-preempt the same feature in one sweep.
    freed_this_tick: set = set()

    for r in rules:
        rule_name = r.get("name") or r.get("id")
        rule_prio = int(r.get("priority", 0))
        u_pat = (r.get("user_pattern") or "").strip()
        g_pat = (r.get("group_pattern") or "").strip()
        p_pat = (r.get("project_pattern") or "").strip()
        feats = r.get("features") or []

        # Build the target (server, feature) list
        target_features: List[tuple] = []
        if feats:
            for fname in feats:
                srv = await _find_server_for_feature(fname)
                if srv:
                    target_features.append((srv, fname))
                else:
                    reasons.append({"rule": rule_name, "feature": fname,
                                    "skip": "no_server_hosts_feature"})
        else:
            # Empty features list = rule applies to ALL features fleet-wide
            servers = await db.servers.find({}, {"_id": 0}).to_list(200)
            for srv in servers:
                for ft in (srv.get("features") or []):
                    target_features.append((srv, ft["name"]))

        for srv, fname in target_features:
            if (srv["id"], fname) in freed_this_tick:
                continue
            feat = next((f for f in (srv.get("features") or [])
                         if f["name"] == fname), None)
            if not feat:
                continue
            holders = await db.checkouts.find(
                {"server_id": srv["id"], "feature": fname}, {"_id": 0}
            ).to_list(500)
            seats_used = sum(int(h.get("count") or 1) for h in holders)
            seats_total = int(feat.get("total") or 0)
            if seats_total <= 0:
                continue
            if seats_used < seats_total:
                reasons.append({"rule": rule_name, "feature": fname,
                                "server": srv["name"], "skip": "not_saturated",
                                "used": seats_used, "total": seats_total})
                continue
            # If a holder already matches the rule's pattern, the rule is
            # already "satisfied" — no need to free another seat.
            already_holding = any(
                (u_pat and _match_pattern(u_pat, h.get("user", ""))) or
                (g_pat and _match_pattern(g_pat, h.get("group", ""))) or
                (p_pat and _match_pattern(p_pat, h.get("project", "")))
                for h in holders
            )
            if already_holding:
                reasons.append({"rule": rule_name, "feature": fname,
                                "server": srv["name"],
                                "skip": "matching_user_already_holds_seat"})
                continue

            # Find the lowest-priority preemptible holder
            enriched = []
            for h in holders:
                hp = await _resolve_priority(h.get("user", ""), "", "", fname)
                enriched.append((hp, h))
            enriched.sort(key=lambda x: (x[0], x[1].get("checkout_time", "")))
            target = next(((hp, h) for (hp, h) in enriched if hp < rule_prio), None)
            if not target:
                reasons.append({"rule": rule_name, "feature": fname,
                                "server": srv["name"],
                                "skip": "all_holders_>=_rule_priority",
                                "rule_priority": rule_prio,
                                "holder_priorities": [hp for hp, _ in enriched]})
                continue

            holder_prio, h = target
            kill_payload = KillCheckoutPayload(
                feature=fname, user=h.get("user", ""),
                host=h.get("host", ""), display=h.get("display", "") or "",
            )
            try:
                kr = await kill_checkout(srv["id"], kill_payload, fake_admin)
                actioned += 1
                freed_this_tick.add((srv["id"], fname))
                results.append({
                    "rule": rule_name, "rule_priority": rule_prio,
                    "pattern": u_pat or g_pat or p_pat or "(all)",
                    "server": srv["name"], "feature": fname,
                    "preempted_user": h.get("user"),
                    "preempted_host": h.get("host"),
                    "preempted_priority": holder_prio,
                    "outcome": "preempted",
                    "method": "lmremove",
                    "exec": kr.get("exec"),
                })
                await log_audit(
                    "AUTO_PREEMPT",
                    f"Auto-released '{h.get('user')}@{h.get('host')}' "
                    f"(prio={holder_prio}) on '{fname}' to free a seat for "
                    f"priority rule '{rule_name}' "
                    f"(prio={rule_prio}, pattern={u_pat or g_pat or p_pat or '*'}, "
                    f"server={srv['name']})",
                    srv["id"], srv["name"], "warning",
                )
            except HTTPException as e:
                results.append({"rule": rule_name, "feature": fname,
                                "server": srv["name"],
                                "outcome": f"error: {e.detail}"})
            except Exception as e:
                results.append({"rule": rule_name, "feature": fname,
                                "server": srv["name"],
                                "outcome": f"error: {str(e)[:120]}"})

    return {"scanned_rules": len(rules), "actioned": actioned,
            "results": results, "reasons": reasons}


async def _auto_preempt_tick() -> dict:
    """One iteration of the auto-preemption loop. Returns a summary dict so the
    on-demand admin endpoint can show what just happened.

    Two passes run on every tick:
      A) **Rule-driven proactive pass** — for every enabled priority rule,
         free a seat on any saturated feature where a lower-priority holder
         exists. Works with wildcard / group / project patterns and does NOT
         require a real user to be waiting (suits CAD shops where users run
         `lmutil` from the terminal and don't visit the web UI).
      B) **Explicit request pass** — drain `pending_requests` and SGE qw jobs
         (if SGE enabled) using the existing `request_license` pipeline.
    """
    cfg = await get_alert_settings()
    fake_admin = {"role": "admin", "email": "auto-preempt@licman"}

    # --- Pass A: rule-driven proactive preemption (wildcard-friendly) ---
    rule_pass = await _rule_driven_preempt_pass(fake_admin)

    # --- Pass B: explicit pending_requests + SGE waiters ---
    requests: List[dict] = []
    if cfg.get("sge_enabled"):
        try:
            requests = await _sge_get_pending_license_requests()
        except Exception as e:
            logger.warning(f"auto-preempt: SGE query failed: {e}")
    if not requests:
        requests = await _heuristic_preempt_candidates()

    actioned = int(rule_pass.get("actioned") or 0)
    results: List[dict] = list(rule_pass.get("results") or [])
    reasons: List[dict] = list(rule_pass.get("reasons") or [])

    for req in requests:
        srv = await _find_server_for_feature(req["feature"])
        if not srv:
            results.append({**req, "outcome": "no_server"})
            continue
        # Skip if the user already holds a seat (avoid runaway loops)
        existing = await db.checkouts.find_one({
            "server_id": srv["id"], "feature": req["feature"], "user": req["user"],
        })
        if existing:
            results.append({**req, "outcome": "user_already_holds"})
            continue
        payload = RequestLicensePayload(
            server_id=srv["id"], feature=req["feature"],
            requester_user=req["user"], requester_project=req.get("project", ""),
            seats_needed=req["seats"],
        )
        try:
            res = await request_license(payload, fake_admin)  # type: ignore
            outcome = res.get("action") or "unknown"
            req_id = req.get("_request_id")
            if outcome in ("preempted", "available"):
                actioned += 1 if outcome == "preempted" else 0
                if req_id:
                    await db.pending_requests.update_one(
                        {"id": req_id},
                        {"$set": {
                            "state": "satisfied",
                            "resolved_at": datetime.now(timezone.utc).isoformat(),
                            "resolution": outcome,
                        }},
                    )
                if outcome == "preempted":
                    await log_audit(
                        "AUTO_PREEMPT",
                        f"Auto-released seat for '{req['user']}' on '{req['feature']}' "
                        f"(source={req['jobid']}, server={srv['name']}, "
                        f"seats_freed={res.get('seats_freed')})",
                        srv["id"], srv["name"], "warning",
                    )
            elif outcome == "denied_low_priority" and req_id:
                # Keep the request open but log the denial so the admin sees it
                await db.pending_requests.update_one(
                    {"id": req_id},
                    {"$set": {"last_attempt": datetime.now(timezone.utc).isoformat(),
                              "last_outcome": outcome}},
                )
            results.append({**req, "outcome": outcome,
                            "seats_freed": res.get("seats_freed")})
        except HTTPException as e:
            results.append({**req, "outcome": f"error: {e.detail}"})
        except Exception as e:
            results.append({**req, "outcome": f"error: {str(e)[:120]}"})
    return {
        "scanned": len(requests) + int(rule_pass.get("scanned_rules") or 0),
        "scanned_rules": int(rule_pass.get("scanned_rules") or 0),
        "scanned_requests": len(requests),
        "actioned": actioned,
        "results": results,
        "reasons": reasons,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


async def _auto_preempt_loop():
    """Daemon: tick every AUTO_PREEMPT_INTERVAL_SECONDS, no-op when disabled."""
    interval_env = int(os.environ.get("AUTO_PREEMPT_INTERVAL_SECONDS", "30"))
    if interval_env <= 0:
        logger.info("Auto-preempt loop disabled (AUTO_PREEMPT_INTERVAL_SECONDS=0)")
        return
    logger.info(f"Auto-preempt loop started — interval {interval_env}s")
    while True:
        try:
            cfg = await get_alert_settings()
            if cfg.get("auto_preempt_enabled"):
                summary = await _auto_preempt_tick()
                if summary["actioned"]:
                    logger.info(
                        f"auto-preempt: actioned {summary['actioned']} of "
                        f"{summary['scanned']} request(s)"
                    )
        except Exception as e:
            logger.warning(f"auto-preempt loop error: {e}")
        # Settings can override env-derived interval at runtime
        cfg = await get_alert_settings()
        rt_interval = int(cfg.get("auto_preempt_interval_sec") or interval_env)
        await asyncio.sleep(max(10, rt_interval))


@api_router.post("/preempt/auto-tick")
async def preempt_auto_tick_now(_: dict = Depends(require_admin)):
    """Trigger one auto-preempt iteration on demand. Useful for testing without
    waiting for the next scheduled tick."""
    summary = await _auto_preempt_tick()
    return summary


@api_router.get("/preempt/auto-status")
async def preempt_auto_status():
    """Report whether the loop is running + last run summary."""
    cfg = await get_alert_settings()
    running = bool(_preempt_task and not _preempt_task.done())
    return {
        "running": running,
        "enabled_in_settings": bool(cfg.get("auto_preempt_enabled")),
        "interval_sec": int(cfg.get("auto_preempt_interval_sec") or
                            os.environ.get("AUTO_PREEMPT_INTERVAL_SECONDS", "30")),
        "sge_enabled": bool(cfg.get("sge_enabled")),
        "mode": "sge+heuristic" if cfg.get("sge_enabled") else "heuristic-only",
    }


# ---------- Pending requests queue (SGE-free preemption workflow) ----------

class PendingRequestCreate(BaseModel):
    user: str
    feature: str
    seats: int = 1
    server_id: Optional[str] = None
    note: str = ""


@api_router.post("/pending-requests")
async def create_pending_request(payload: PendingRequestCreate, _: dict = Depends(require_admin)):
    """Queue a license request. The auto-preempt loop will action it on its
    next tick — preempting the lowest-priority holder if the requester
    outranks them via the configured priority rules. Pure username-based,
    no SGE / job scheduler required."""
    if not payload.user.strip():
        raise HTTPException(400, "user is required")
    if not payload.feature.strip():
        raise HTTPException(400, "feature is required")
    doc = {
        "id": str(uuid.uuid4()),
        "user": payload.user.strip(),
        "feature": payload.feature.strip(),
        "seats": max(1, int(payload.seats or 1)),
        "server_id": payload.server_id,
        "note": payload.note,
        "state": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.pending_requests.insert_one(doc)
    await log_audit(
        "PENDING_REQUEST",
        f"Queued request: {doc['user']} wants {doc['seats']}× {doc['feature']}",
        payload.server_id, None, "info",
    )
    # Best-effort: trigger an immediate tick so the user sees fast results
    try:
        cfg = await get_alert_settings()
        if cfg.get("auto_preempt_enabled"):
            asyncio.create_task(_auto_preempt_tick())
    except Exception:
        pass
    return {"ok": True, "request": {k: v for k, v in doc.items() if k != "_id"}}


@api_router.get("/pending-requests")
async def list_pending_requests(state: str = "open", limit: int = 200):
    q: dict = {} if state == "all" else {"state": state}
    docs = await db.pending_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return docs


@api_router.delete("/pending-requests/{rid}")
async def cancel_pending_request(rid: str, _: dict = Depends(require_admin)):
    res = await db.pending_requests.find_one_and_update(
        {"id": rid, "state": "open"},
        {"$set": {"state": "cancelled",
                  "resolved_at": datetime.now(timezone.utc).isoformat()}},
        projection={"_id": 0},
    )
    if not res:
        raise HTTPException(404, "Request not found or already resolved")
    await log_audit("PENDING_CANCEL", f"Cancelled request: {res['user']} ↔ {res['feature']}",
                    None, None, "info")
    return {"ok": True}


# ---------- end auto-preempt scheduler ----------
# ---------- end scheduler ----------


# Register routers AFTER all @api_router decorators are defined, otherwise
# FastAPI snapshots the route list at include time and misses later additions.
app.include_router(public_router)
app.include_router(api_router)
app.include_router(auth_router)


@app.on_event("startup")
async def startup_event():
    global _sync_task
    # Indexes: auth (wrapped in try/except so old DBs with dup entries don't block startup)
    for idx in [
        (db.users, [("email", 1)], {"unique": True}),
        (db.users, [("id", 1)], {"unique": True}),
        (db.login_attempts, [("identifier", 1)], {}),
        (db.servers, [("id", 1)], {"unique": True}),
        (db.servers, [("vendor", 1)], {}),
        (db.checkouts, [("server_id", 1)], {}),
        (db.reservations, [("server_id", 1)], {}),
        (db.alert_events, [("timestamp", -1)], {}),
        (db.usage_history, [("server_id", 1), ("feature", 1), ("user", 1), ("host", 1), ("pid", 1), ("checkout_time", 1)], {"unique": True}),
        (db.usage_history, [("last_seen_iso", -1)], {}),
        (db.usage_history, [("user", 1)], {}),
        (db.usage_history, [("feature", 1)], {}),
        (db.usage_history, [("vendor", 1)], {}),
    ]:
        try:
            await idx[0].create_index(idx[1], **idx[2])
        except Exception as e:
            logger.warning(f"index create skipped on {idx[0].name}: {e}")
    # Audit TTL — auto-delete entries older than AUDIT_TTL_DAYS (default 90 days)
    ttl_days = int(os.environ.get("AUDIT_TTL_DAYS", "90"))
    try:
        await db.audit.drop_indexes()
    except Exception:
        pass
    # Note: TTL needs a real BSON Date, not a string. We add a `ts` field on inserts via a wrapper.
    await db.audit.create_index([("timestamp", -1)])
    await db.audit.create_index("ts", expireAfterSeconds=ttl_days * 86400)
    # Usage history TTL — keep last USAGE_TTL_DAYS (default 365 days)
    usage_ttl_days = int(os.environ.get("USAGE_TTL_DAYS", "365"))
    try:
        await db.usage_history.create_index("last_seen", expireAfterSeconds=usage_ttl_days * 86400)
    except Exception as e:
        logger.warning(f"usage_history TTL index skipped: {e}")
    # Seed if applicable
    await seed_if_empty()
    # Start auto-sync loop
    if os.environ.get("SYNC_INTERVAL_SECONDS", "60") != "0":
        _sync_task = asyncio.create_task(_periodic_sync_loop())
    # Start auto-preempt loop (no-op until enabled in Settings)
    global _preempt_task
    if os.environ.get("AUTO_PREEMPT_INTERVAL_SECONDS", "30") != "0":
        _preempt_task = asyncio.create_task(_auto_preempt_loop())


@app.on_event("shutdown")
async def shutdown_db_client():
    global _sync_task, _preempt_task
    for t in (_sync_task, _preempt_task):
        if t and not t.done():
            t.cancel()
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    client.close()
