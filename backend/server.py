from fastapi import FastAPI, APIRouter, HTTPException, Request, Response, Depends
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


class FeatureModel(BaseModel):
    name: str
    version: str = "1.0"
    total: int = 1
    expires: str = "permanent"


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


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    daemon: Optional[str] = None
    status: Optional[Literal["up", "down", "stale"]] = None


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
    await db.audit.insert_one(entry.model_dump())


def _sample_users():
    return ["asingh", "jzhang", "kpatel", "mlopez", "rkumar", "tnguyen", "ehassan", "yliu"]


def _sample_hosts():
    return ["wks-bangalore-04", "wks-sjc-12", "build-farm-07", "tape-out-02",
            "verify-rig-09", "synth-node-11", "pnr-rack-03", "drc-node-15"]


def generate_checkouts(server: dict):
    """Generate plausible simulated checkouts for a server's features."""
    checkouts = []
    users = _sample_users()
    hosts = _sample_hosts()
    features = server.get("features", [])
    if not features:
        return checkouts
    for feat in features:
        # Random utilization 0..total+1 (allowing saturation/over occasionally)
        in_use = random.randint(0, feat.get("total", 1))
        for _ in range(in_use):
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
            ).model_dump())
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
async def get_alert_settings() -> dict:
    doc = await db.settings.find_one({"_key": "alerts"}, {"_id": 0})
    if not doc:
        return AlertSettings().model_dump()
    doc.pop("_key", None)
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
    ev = AlertEvent(
        kind=kind, server_id=server_id, server_name=server_name,
        feature=feature, detail=detail, delivered=delivered, error=err  # type: ignore
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
        return await asyncio.to_thread(_ssh_real_exec, ssh, command)
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
    r"\(v?(?P<ver>[^)]+)\)\s+\((?P<lic>\S+)\s+(?P<pid>\d+)\),\s+start\s+(?P<when>.+)$"
)
_MONTH_NAMES = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
                "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _parse_start_to_iso(when: str) -> str:
    """`Wed 5/14 9:42` or `5/14/2025 9:42` → ISO timestamp. Best-effort, falls back to now."""
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
        year = int(y[0]) if y else now.year
        month, day = int(m), int(d)
        hh, mm = (int(x) for x in time_str.split(":")[:2])
        return datetime(year, month, day, hh, mm, 0, tzinfo=timezone.utc).isoformat()
    except Exception:
        return now.isoformat()


def parse_lmstat_a(text: str, server_id: str) -> dict:
    """Return dict {features: [...], checkouts: [...]} parsed from `lmstat -a` output."""
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
                "in_use": int(m.group("inuse")),
                "version": "",
                "expires": "permanent",
            }
            # Sometimes the meta line follows after a blank line
            for j in range(i + 1, min(i + 4, len(lines))):
                mm = _RE_FEATURE_META.match(lines[j])
                if mm and mm.group("feature") == current_feature:
                    features[current_feature]["version"] = mm.group("version")
                    features[current_feature]["expires"] = mm.group("expires") or "permanent"
                    break
            continue
        mu = _RE_USER_LINE.match(line)
        if mu and current_feature:
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
            })
    return {
        "features": [
            {"name": f["name"], "version": f.get("version") or "1.0",
             "total": f["total"], "expires": f.get("expires") or "permanent"}
            for f in features.values()
        ],
        "checkouts": checkouts,
    }


async def _real_checkouts_via_ssh(server: dict) -> Optional[dict]:
    """Returns {features, checkouts} parsed from real lmstat output, or None on failure."""
    ssh = server.get("ssh", {}) or {}
    if not (ssh.get("enabled") and PARAMIKO_AVAILABLE):
        return None
    lmutil = ssh.get("lmutil_path") or "lmutil"
    cmd = f"{lmutil} lmstat -a -c {server['port']}@{server['host']}"
    res = await asyncio.to_thread(_ssh_real_exec, ssh, cmd)
    if res.get("exit") != 0 or not res.get("output"):
        logger.warning(f"lmstat ssh failed on {server['name']}: {res.get('output')[:200]}")
        return None
    return parse_lmstat_a(res["output"], server["id"])


async def gather_checkouts(server: dict) -> list:
    """Return checkouts. Use real lmstat when adapter_mode='ssh', else simulate."""
    mode = server.get("adapter_mode", "mock")
    if mode == "ssh":
        parsed = await _real_checkouts_via_ssh(server)
        if parsed is not None:
            # Persist parsed features if any new ones discovered
            if parsed["features"]:
                await db.servers.update_one(
                    {"id": server["id"]}, {"$set": {"features": parsed["features"]}}
                )
            return parsed["checkouts"]
        # SSH failed → fall back to empty (do NOT lie with simulated data)
        return []
    return generate_checkouts(server)



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


def _set_auth_cookies(response: Response, access: str, refresh: str):
    common = dict(httponly=True, samesite="lax", secure=False, path="/")
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
                        httponly=True, samesite="lax", secure=False, path="/")
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


@public_router.get("/setup-status")
async def setup_status():
    count = await db.users.count_documents({})
    return {"needs_setup": count == 0}


@api_router.get("/servers", response_model=List[LicenseServer])
async def list_servers():
    docs = await db.servers.find({}, {"_id": 0}).to_list(500)
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
async def save_license_file(server_id: str, payload: FileContent):
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"license_file": payload.content}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")

    # Try to parse FEATURE lines and update features list
    features = []
    for line in payload.content.splitlines():
        m = re.match(r"^\s*(?:FEATURE|INCREMENT)\s+(\S+)\s+\S+\s+(\S+)\s+(\S+)\s+(\d+)", line)
        if m:
            features.append({
                "name": m.group(1), "version": m.group(2),
                "expires": m.group(3), "total": int(m.group(4)),
            })
    if features:
        await db.servers.update_one({"id": server_id}, {"$set": {"features": features}})

    await log_audit("LICENSE_SAVE", f"License file updated for {res['name']} ({len(features)} features parsed)",
                    server_id, res["name"], "success")
    return {"ok": True, "features_parsed": len(features)}


@api_router.put("/servers/{server_id}/options")
async def save_options_file(server_id: str, payload: FileContent):
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"options_file": payload.content}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    await log_audit("OPTIONS_SAVE", f"Options file saved for {res['name']}",
                    server_id, res["name"], "success")
    return {"ok": True}


@api_router.post("/servers/{server_id}/reread")
async def reread(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    exec_log = await ssh_execute(doc, f"lmreread -c @{doc['port']}@{doc['host']}")
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"status": "up", "last_action": f"lmreread [{exec_log['mode']}] @ {datetime.now(timezone.utc).isoformat()}"}}
    )
    await log_audit("LMREREAD", f"lmreread issued to {doc['name']} · {exec_log['output']}",
                    server_id, doc["name"], "info")
    return {"ok": True, "message": f"lmreread executed on {doc['name']}", "exec": exec_log}


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
    return fresh


@api_router.get("/checkouts", response_model=List[Checkout])
async def all_checkouts():
    servers = await db.servers.find({"status": "up"}, {"_id": 0}).to_list(500)
    all_co = []
    for srv in servers:
        fresh = await gather_checkouts(srv)
        all_co.extend(fresh)
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
    res = await db.servers.find_one_and_update(
        {"id": server_id}, {"$set": {"ssh": payload.model_dump()}},
        return_document=True, projection={"_id": 0}
    )
    if not res:
        raise HTTPException(404, "Server not found")
    await log_audit("SSH_CONFIG", f"SSH config updated for {res['name']} (host={payload.host})",
                    server_id, res["name"], "info")
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
            _ssh_real_exec, ssh, f"echo licman-ok && which {ssh.get('lmutil_path','lmutil')} || true"
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
    await log_audit("SYNC_OK",
                    f"Synced {doc['name']}: {len(parsed['features'])} features, {len(parsed['checkouts'])} checkouts",
                    server_id, doc["name"], "success")
    return {
        "ok": True,
        "features_parsed": len(parsed["features"]),
        "checkouts_parsed": len(parsed["checkouts"]),
    }


@api_router.post("/servers/{server_id}/fetch-license")
async def fetch_license(server_id: str, _: dict = Depends(require_admin)):
    """Pull the actual .lic file from the license host over SSH (cat)."""
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    ssh = doc.get("ssh", {}) or {}
    if doc.get("adapter_mode") != "ssh" or not ssh.get("enabled"):
        raise HTTPException(400, "SSH adapter not enabled on this server")
    lmutil = ssh.get("lmutil_path") or "lmutil"
    discover_cmd = (
        f"{lmutil} lmdiag -c {doc['port']}@{doc['host']} 2>/dev/null "
        f"| grep -m1 -oE '/[^ ]+\\.(lic|dat)' || true"
    )
    disc = await asyncio.to_thread(_ssh_real_exec, ssh, discover_cmd)
    lic_path = (disc.get("output") or "").strip().splitlines()[0] if disc.get("output") else ""
    if not lic_path:
        raise HTTPException(404, "Could not auto-discover license file path on remote host. "
                                 "Pass ?path=/full/path/to/license.dat manually.")
    res = await asyncio.to_thread(_ssh_real_exec, ssh, f"cat {lic_path}")
    if res.get("exit") != 0 or not res.get("output"):
        raise HTTPException(502, f"Failed to read remote license file: {res.get('output','')[:300]}")
    content = res["output"]
    await db.servers.update_one({"id": server_id}, {"$set": {"license_file": content}})
    await log_audit("LICENSE_FETCH",
                    f"Fetched license from {ssh.get('host')}:{lic_path} ({len(content)} bytes)",
                    server_id, doc["name"], "success")
    return {"ok": True, "path": lic_path, "bytes": len(content)}


# ---------- Expiry ----------

@api_router.get("/expiry")
async def expiry_calendar(warn_days: int = 90):
    servers = await db.servers.find({}, {"_id": 0}).to_list(500)
    rows = []
    for s in servers:
        for f in s.get("features", []):
            d = parse_expiry(f.get("expires", ""))
            days = days_until(d)
            rows.append({
                "server_id": s["id"],
                "server_name": s["name"],
                "vendor": s["vendor"],
                "feature": f["name"],
                "version": f.get("version"),
                "total": f.get("total"),
                "expires": f.get("expires"),
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


# ---------- Settings / Alerts ----------

@api_router.get("/settings")
async def get_settings():
    return await get_alert_settings()


@api_router.put("/settings")
async def put_settings(payload: AlertSettings, _: dict = Depends(require_admin)):
    data = payload.model_dump()
    data["_key"] = "alerts"
    await db.settings.update_one({"_key": "alerts"}, {"$set": data}, upsert=True)
    await log_audit("SETTINGS_SAVE", f"Alert settings updated (enabled={payload.enabled}, recipients={len(payload.to_addresses)})",
                    None, None, "info")
    out = data.copy()
    out.pop("_key", None)
    out.pop("smtp_password", None)
    out["smtp_password_set"] = bool(payload.smtp_password)
    return out


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
async def create_reservation(payload: ReservationCreate):
    srv = await db.servers.find_one({"id": payload.server_id}, {"_id": 0})
    if not srv:
        raise HTTPException(404, "Server not found")
    r = Reservation(**payload.model_dump())
    await db.reservations.insert_one(r.model_dump())
    await log_audit(
        "RESERVE",
        f"RESERVE {r.count} {r.feature} {r.target_type} {r.target} on {srv['name']}",
        srv["id"], srv["name"], "info",
    )
    return r


@api_router.delete("/reservations/{rid}")
async def delete_reservation(rid: str):
    doc = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Reservation not found")
    await db.reservations.delete_one({"id": rid})
    srv = await db.servers.find_one({"id": doc["server_id"]}, {"_id": 0, "name": 1})
    await log_audit(
        "UNRESERVE",
        f"Removed RESERVE {doc['feature']} {doc['target_type']} {doc['target']}",
        doc["server_id"], srv["name"] if srv else None, "info",
    )
    return {"ok": True}


@api_router.get("/audit", response_model=List[AuditLog])
async def audit(limit: int = 50):
    docs = await db.audit.find({}, {"_id": 0}).sort("timestamp", -1).to_list(limit)
    return docs


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
    await db.servers.delete_many({})
    await db.checkouts.delete_many({})
    await db.reservations.delete_many({})
    await db.audit.delete_many({})
    await db.alert_events.delete_many({})
    await seed_if_empty()
    return {"ok": True}


app.include_router(public_router)
app.include_router(api_router)
app.include_router(auth_router)

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


@app.on_event("startup")
async def startup_event():
    # Indexes for auth
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.login_attempts.create_index("identifier")
    await seed_if_empty()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
