# LICMAN — Production hardening checklist

Use this after the first successful run of `install-rhel9.sh`.

## ✅ Auto-done by the installer
- Docker + Compose plugin installed from Docker's official RHEL repo
- Firewall ports 80 / 443 opened
- SELinux booleans set for containers
- Self-signed TLS cert generated with `CN=<your-host-IP>`
- `JWT_SECRET` and `FERNET_KEY` generated and written to `.env` (mode 600)
- `licman.service` enabled (auto-start on boot)
- `licman-backup.timer` enabled (weekly Mongo backup → `/var/backups/licman`, 14-day rotation)
- Backend health/readiness probes wired into `docker-compose.yml`
- MongoDB indexes created on first startup (users, login_attempts, servers, checkouts, audit-TTL)

## 🔐 Secrets you should rotate before exposing to your team
| Secret | Where | Why |
|---|---|---|
| `MONGO_INITDB_ROOT_PASSWORD` | `/opt/licman/deploy/.env` | Default value is weak |
| `JWT_SECRET` | same | Auto-generated; if you ever shared `.env`, rotate it |
| `FERNET_KEY` | same | **Encrypts SSH keys & SMTP passwords at rest.** If you rotate it, re-paste SSH keys + SMTP password in the UI |

After rotating, run:
```bash
cd /opt/licman/deploy
chmod 600 .env
docker compose restart backend
```

## 🌐 Switch to HTTPS-only (recommended for prod)
```bash
cd /opt/licman/deploy
sed -i 's|^COOKIE_SECURE=.*|COOKIE_SECURE=true|' .env
docker compose restart backend

# Optionally redirect HTTP→HTTPS in nginx.conf:
#   Replace the `listen 80` server block's `location` with:
#     return 301 https://$host$request_uri;
```

## 🔑 Replace the self-signed cert with your internal CA
```bash
cd /opt/licman/deploy/nginx/ssl
cp /path/to/yourcompany.crt server.crt
cp /path/to/yourcompany.key server.key
chmod 600 server.key
docker compose restart nginx
```

## 👥 First-run user setup
1. Open `https://<host>/` (or `http://<host>/`)
2. Setup wizard appears → create your admin account (8+ char password)
3. Open the **USERS** page → add an `engineer` user for each member of your CAD team
4. Engineers can view, reserve/unreserve, reread/restart but cannot delete servers, change SSH config, or alter settings

## 🛰️ Wire real `lmstat` per license host
1. Copy `setup-license-host.sh` to each license host (192.168.200.51, .52, …)
2. As root: `bash setup-license-host.sh <YOUR-WEB-HOST-IP>`
3. Copy the printed private key into LICMAN → server → **Connection** tab
4. Toggle adapter to **SSH**, save, click **TEST**, then **SYNC NOW** (in server header)
5. After that, the background scheduler will sync every `SYNC_INTERVAL_SECONDS` seconds (default 60)

## 📈 Auto-sync tuning
| Env var | Default | What it does |
|---|---|---|
| `SYNC_INTERVAL_SECONDS` | `60` | Background loop runs lmstat on every SSH-enabled server every N seconds. `0` to disable. |
| `AUDIT_TTL_DAYS` | `90` | Audit log entries auto-deleted after N days (Mongo TTL index) |

```bash
# Change values then:
docker compose restart backend
```

## 📨 Office 365 SMTP setup (optional but useful)
1. Go to `/settings`
2. Click **USE O365 PRESET** → confirms host=smtp.office365.com, port=587, STARTTLS
3. Username = your O365 email; Password = **App Password** (not your login password — generate at https://account.microsoft.com/security)
4. Add recipient emails (comma-separated)
5. Toggle **Master Enable** → ON
6. Click **SEND TEST EMAIL**

The SMTP password is encrypted at rest with `FERNET_KEY` — never visible in the API or in the DB plaintext.

## 🧪 Validation commands

```bash
# Liveness (no DB)
curl -fsS http://localhost/api/health             # → {"status":"ok"}

# Readiness (DB ping)
curl -fsS http://localhost/api/ready              # → {"status":"ok"} or 503

# Auth-protected route should be 401 without cookie
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/api/servers   # → 401

# Stack status
docker compose -f /opt/licman/deploy/docker-compose.yml ps

# Manual backup
sudo bash /opt/licman/deploy/backup.sh

# Restore a backup
docker compose -f /opt/licman/deploy/docker-compose.yml exec -T mongo \
  mongorestore --uri="mongodb://licman:<PWD>@localhost:27017/?authSource=admin" \
  --gzip --archive < /var/backups/licman/licman-YYYY-MM-DD-HHMM.gz
```

## 🆘 Common ops
| Need | Command |
|---|---|
| Logs (all) | `docker compose -f /opt/licman/deploy/docker-compose.yml logs -f` |
| Restart | `systemctl restart licman.service` |
| Update code | `cd /opt/licman && git pull && cd deploy && docker compose up -d --build` |
| Wipe everything | `cd /opt/licman/deploy && docker compose down -v` ⚠ |

## 🧷 Disaster recovery
- Backups land in `/var/backups/licman/` (root-only, mode 600).
- Snapshot that directory off-host (`rsync`, S3-compatible store, NAS, etc.).
- To restore on a fresh box: install LICMAN, then `mongorestore` from the latest archive — all servers, users, audit history, SSH configs come back intact (FERNET_KEY must match the one that was used at backup time).

## 🎯 Operating envelope
| Scale point | Tested up to | Note |
|---|---|---|
| License servers registered | 50+ | Each adds ~1 lmstat call per `SYNC_INTERVAL_SECONDS` |
| Concurrent users (browsers) | 25-50 | Tested behind nginx; increase uvicorn workers in Dockerfile.backend if needed |
| Audit retention | 90 days default | Set `AUDIT_TTL_DAYS=365` for a full year |
| Backup retention | 14 weekly archives | Set `KEEP_DAYS` env in backup.sh |
