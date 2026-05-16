from fastapi import FastAPI, APIRouter, HTTPException
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import random
import re
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
import uuid
from datetime import datetime, timezone, timedelta


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="LICMAN — VLSI License Console")
api_router = APIRouter(prefix="/api")


# ------------------------- Models -------------------------

Vendor = Literal["cadence", "synopsys", "mentor"]


class FeatureModel(BaseModel):
    name: str
    version: str = "1.0"
    total: int = 1
    expires: str = "permanent"


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
        in_use = random.randint(0, min(feat.get("total", 1), 4))
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
        "name": "lic-cadence-prod-01",
        "vendor": "cadence",
        "host": "lic-cadence-01.eda.local",
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
        "name": "lic-synopsys-prod-01",
        "vendor": "synopsys",
        "host": "lic-syn-01.eda.local",
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
    {
        "name": "lic-mentor-prod-01",
        "vendor": "mentor",
        "host": "lic-mgc-01.eda.local",
        "port": 1717,
        "daemon": "mgcld",
        "features": [
            {"name": "Calibre_DRC", "version": "2023.4", "total": 12, "expires": "30-sep-2026"},
            {"name": "Calibre_LVS", "version": "2023.4", "total": 12, "expires": "30-sep-2026"},
            {"name": "Questa_Sim", "version": "2023.3", "total": 24, "expires": "30-sep-2026"},
            {"name": "Tessent_Shell", "version": "2023.3", "total": 4, "expires": "30-sep-2026"},
        ],
    },
]


async def seed_if_empty():
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


# ------------------------- Routes -------------------------

@api_router.get("/")
async def root():
    return {"service": "LICMAN", "status": "ok"}


@api_router.get("/servers", response_model=List[LicenseServer])
async def list_servers():
    docs = await db.servers.find({}, {"_id": 0}).to_list(500)
    return docs


@api_router.post("/servers", response_model=LicenseServer)
async def create_server(payload: ServerCreate):
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
async def delete_server(server_id: str):
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
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"status": "up", "last_action": f"lmreread @ {datetime.now(timezone.utc).isoformat()}"}}
    )
    await log_audit("LMREREAD", f"lmreread issued to {doc['name']}", server_id, doc["name"], "info")
    return {"ok": True, "message": f"lmreread executed on {doc['name']}"}


@api_router.post("/servers/{server_id}/restart")
async def restart(server_id: str):
    doc = await db.servers.find_one({"id": server_id}, {"_id": 0})
    if not doc:
        raise HTTPException(404, "Server not found")
    await db.servers.update_one(
        {"id": server_id},
        {"$set": {"status": "up", "last_action": f"restart @ {datetime.now(timezone.utc).isoformat()}"}}
    )
    await log_audit("DAEMON_RESTART", f"Daemon restart issued on {doc['name']}",
                    server_id, doc["name"], "warning")
    return {"ok": True, "message": f"{doc['daemon']} restarted on {doc['name']}"}


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
    # Regenerate simulated checkouts each call to feel live
    fresh = generate_checkouts(doc)
    await db.checkouts.delete_many({"server_id": server_id})
    if fresh:
        await db.checkouts.insert_many([{**c} for c in fresh])
    return fresh


@api_router.get("/checkouts", response_model=List[Checkout])
async def all_checkouts():
    servers = await db.servers.find({"status": "up"}, {"_id": 0}).to_list(500)
    all_co = []
    for srv in servers:
        fresh = generate_checkouts(srv)
        all_co.extend(fresh)
    await db.checkouts.delete_many({})
    if all_co:
        await db.checkouts.insert_many([{**c} for c in all_co])
    return all_co


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
async def seed_reset():
    await db.servers.delete_many({})
    await db.checkouts.delete_many({})
    await db.reservations.delete_many({})
    await db.audit.delete_many({})
    await seed_if_empty()
    return {"ok": True}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
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
    await seed_if_empty()


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
