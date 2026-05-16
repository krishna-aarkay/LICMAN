# LICMAN — RHEL 9 plug-and-play deployment

Target server: **`10.10.11.11`** (RHEL 9)
Talks to license hosts: `10.10.11.111` (Cadence) · `10.10.11.112` (Siemens/Mentor) · `10.10.11.113` (Synopsys) · …add as many as you want.

This bundle gives you **one-shot install** with Docker Compose. No Node, Python, or MongoDB to set up by hand.

---

## TL;DR (10-minute install on 10.10.11.11)

```bash
# 1. Become root on your RHEL 9 box (10.10.11.11)
sudo -i

# 2. Drop this folder anywhere, e.g. /opt/licman/
cd /opt && git clone <your-repo> licman   # OR scp the /app/deploy folder here
cd /opt/licman/deploy

# 3. Run the installer (idempotent — safe to re-run)
bash install-rhel9.sh

# Done. Open http://10.10.11.11/  (or https://10.10.11.11/  if you chose TLS)
```

The installer:
* Installs Docker + Compose plugin from Docker's official repo
* Opens firewall ports 80, 443
* Sets SELinux booleans for container access
* Generates a self-signed TLS cert (10-year, CN=10.10.11.11) if missing
* Builds & starts the four containers (`mongo`, `backend`, `frontend`, `nginx`)
* Enables `licman.service` so it auto-starts on boot

---

## What's inside

| File | Purpose |
|------|---------|
| `install-rhel9.sh` | One-shot installer for RHEL 9 |
| `docker-compose.yml` | mongo + backend + frontend + nginx |
| `Dockerfile.backend` | Python 3.11 + FastAPI + paramiko |
| `Dockerfile.frontend` | Multi-stage React build → nginx-served static bundle |
| `nginx.conf` | Reverse proxy: `/api` → backend, `/` → frontend, HTTP + HTTPS |
| `.env.example` | Copy to `.env` and tweak |
| `licman.service` | systemd unit so the stack starts on boot |
| `setup-license-host.sh` | Run **on each license host** (10.10.11.111/112/113…) to create the `licadmin` service account |
| `licadmin.sudoers` | Restricted sudoers template installed by the script above |

---

## Step-by-step

### A) On the web-app host (`10.10.11.11`)

```bash
sudo -i
mkdir -p /opt/licman && cd /opt/licman
# Copy the repo (or this `deploy/` folder + backend/ + frontend/) here
# Example: scp from your dev machine
#   scp -r ./deploy ./backend ./frontend root@10.10.11.11:/opt/licman/

cd /opt/licman/deploy
cp .env.example .env
$EDITOR .env       # adjust MONGO password / hostnames if you wish

bash install-rhel9.sh
```

After it finishes you should see:
```
[OK] LICMAN is running. Open http://10.10.11.11/
```

### B) On every license host (`10.10.11.111`, `10.10.11.112`, `10.10.11.113`, …)

Copy `setup-license-host.sh` + `licadmin.sudoers` to each host **once** and run as root:

```bash
sudo bash setup-license-host.sh
```

This creates a `licadmin` user, drops your LICMAN public key into `~licadmin/.ssh/authorized_keys`, and installs a **restricted sudoers rule** that only allows:
* `/usr/local/flexlm/lmutil lmstat *`
* `/usr/local/flexlm/lmutil lmreread *`
* `/usr/local/flexlm/lmutil lmdown *`
* `/usr/bin/systemctl restart cdslmd|snpslmd|mgcld|xilinxd|defacto`

→ Then in the LICMAN web UI: open each server → **Connection** tab → paste the matching private key, toggle adapter to **SSH**, click TEST.

### C) Adding more license servers

In the UI click **+ ADD SERVER**. Switch the vendor selector to **CUSTOM** and type any name (xilinx, defacto, ansys, altium, internal-tool, …). Colors are auto-assigned for unknown vendors; the well-known ones have curated palettes.

---

## Common ops

```bash
# View logs
cd /opt/licman/deploy && docker compose logs -f backend frontend nginx mongo

# Restart everything
systemctl restart licman.service        # OR: docker compose restart

# Update to a new code drop
cd /opt/licman/deploy
docker compose down
git pull           # or refresh files
docker compose up -d --build

# Reset demo data (only relevant if DEMO_MODE=1 in .env)
curl -X POST http://10.10.11.11/api/seed/reset

# Backup MongoDB
docker compose exec mongo mongodump --archive=/data/db/licman-backup-$(date +%F).gz --gzip
```

---

## Firewall / network notes

* Ports opened on `10.10.11.11`: **80** (HTTP), **443** (HTTPS).
* The web-app host needs **outbound SSH (22)** to each license host (10.10.11.111/.112/.113…).
* The web-app host needs **outbound 587** (SMTP/STARTTLS) to `smtp.office365.com` for alerts.
* License hosts only need to accept SSH from `10.10.11.11`.

---

## Switching from MOCK to real SSH

1. Run `setup-license-host.sh` on each license host (only once per host).
2. In the LICMAN UI → server → **Connection** tab:
   * Paste the LICMAN private key (the script printed the matching public key to add to authorized_keys, but for the private side use the key you control).
   * Adapter Mode → **SSH**
   * Click **TEST** — should return `licman-ok` and the path to `lmutil`.
3. Click **SAVE**. From now on REREAD/RESTART will execute over real SSH.

Until you do step 2 the app continues to simulate with the built-in mock generator.

---

## Production hardening (recommended later)

* Replace the auto-generated self-signed cert with one from your internal CA → drop into `nginx/ssl/server.crt` & `server.key` and restart.
* Encrypt MongoDB-at-rest (RHEL FIPS or LUKS volume).
* Move `SMTP_PASSWORD` / SSH keys to Vault or Ansible-vault-encrypted secrets.
* Put LICMAN behind your internal SSO (we can swap in JWT or LDAP later).
