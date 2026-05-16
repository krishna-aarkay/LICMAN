# LICMAN — End-to-end Install Guide for RHEL 9

This is the **only** document you need to take LICMAN from a fresh RHEL 9 box to a running web UI on your private network.

Throughout this guide:
- `<WEB_HOST_IP>` = the IP of the RHEL 9 box hosting the web app (e.g. `192.168.200.11`)
- `<LIC_HOST_IP>` = the IP of any FlexLM license host (e.g. `192.168.200.51` for Cadence, `.52` for Siemens, `.53` for Synopsys, `.71` for Xilinx, …)

> **Time estimate:** 15-20 minutes for the web host, ~5 minutes per license host.

---

## ⓪ Prerequisites checklist

You need:
1. A RHEL 9 (or RHEL 9-clone: Rocky 9, Alma 9) machine on your network — call it the **web host**.
   - Minimum: 2 vCPU, 4 GB RAM, 20 GB disk.
   - Root access (or a sudoer).
   - Outbound internet **once** (to pull Docker, base images, and OS packages). After that it can run fully air-gapped except for SMTP and SSH to license hosts.
2. The LICMAN source tree on a USB / dev box (the folder containing `backend/`, `frontend/`, `deploy/`).
3. SSH access (port 22) **from the web host to each license host**.
4. (Optional, for email alerts) Office 365 mailbox with an **App Password** (MFA users only).

---

## ① Prepare the RHEL 9 web host

### 1.1 Log in as root and update

```bash
sudo -i
dnf -y update
```

If `dnf update` upgraded the kernel, **reboot once** (`reboot`) and log back in.

### 1.2 Set a static IP (optional but recommended)

```bash
# Replace eth0 with your interface (check via `nmcli device status`)
nmcli con mod eth0 ipv4.addresses <WEB_HOST_IP>/24 \
                   ipv4.gateway 192.168.200.1 \
                   ipv4.dns "192.168.200.1 8.8.8.8" \
                   ipv4.method manual
nmcli con up eth0
```

### 1.3 Set hostname (optional)

```bash
hostnamectl set-hostname licman.corp.local
```

### 1.4 Install basics

```bash
dnf -y install git curl tar unzip openssl
```

That's everything — Docker and the rest will be installed by the LICMAN script.

---

## ② Get the LICMAN code onto the web host

Pick **one** of these:

### Option A — Internal Git
```bash
mkdir -p /opt && cd /opt
git clone <your-internal-git-url> licman
cd licman/deploy
```

### Option B — SCP from your dev box
On your laptop / dev box:
```bash
scp -r ./licman root@<WEB_HOST_IP>:/opt/
```
Then on the web host:
```bash
cd /opt/licman/deploy
```

### Option C — Tar from a USB / share
```bash
mkdir -p /opt && cd /opt
tar -xzf /mnt/usb/licman.tar.gz   # contains backend/ frontend/ deploy/
cd /opt/licman/deploy
```

Either way, when you're done you should see:
```bash
ls /opt/licman
# backend/  deploy/  frontend/  (and others)
ls /opt/licman/deploy
# Dockerfile.backend  Dockerfile.frontend  docker-compose.yml
# install-rhel9.sh    nginx.conf           setup-license-host.sh
# README.md           .env.example         licman.service
```

---

## ③ Configure for production (1 minute)

```bash
cd /opt/licman/deploy
cp .env.example .env
$EDITOR .env
```

In `.env` change **only these** for a production install:

```bash
MONGO_INITDB_ROOT_PASSWORD=<pick-a-strong-password>
DEMO_MODE=0               # skip the demo 10.10.11.x seed servers
TZ=Asia/Kolkata           # or your timezone
```

Save and exit.

---

## ④ Run the one-shot installer

```bash
bash install-rhel9.sh
```

This **automatically**:
- Installs Docker CE + Compose plugin from Docker's official RHEL repo
- Enables and starts the Docker daemon
- Opens firewall ports 80 and 443
- Sets the two SELinux booleans that containers need
- Generates a 10-year self-signed TLS cert with `CN=<WEB_HOST_IP>` (auto-detected)
- Builds the 4 container images (`mongo`, `backend`, `frontend`, `nginx`) — first build takes 3-5 min
- Starts everything with `docker compose up -d`
- Installs `licman.service` so the stack auto-starts on every reboot

When it finishes you'll see:

```
============================================================
 [OK] LICMAN is running.
       HTTP  ->  http://<WEB_HOST_IP>/
       HTTPS ->  https://<WEB_HOST_IP>/   (self-signed cert)
============================================================
```

### 4.1 Smoke test from the web host
```bash
curl -fsS http://localhost/api/
# expected: {"service":"LICMAN","status":"ok"}
```

### 4.2 Open in your browser
On any laptop on the same LAN:
- `http://<WEB_HOST_IP>/`  (e.g. `http://192.168.200.11/`)
- or `https://<WEB_HOST_IP>/` (your browser will warn about the self-signed cert — that's expected; click "Advanced → Proceed").

You should see the LICMAN **Control Room**. With `DEMO_MODE=0` it'll be empty and ready for your real servers.

---

## ⑤ Add your license servers in the UI

In the web UI:

1. Click **+ ADD SERVER** (top-right of the Control Room)
2. Pick a vendor (PRESET button — Cadence/Synopsys/Siemens/Xilinx/Defacto/Ansys/Altair/Keysight/Intel/ARM **— or click `CUSTOM` to type any vendor name**).
3. Fill the form:
   - **Name**: anything human-readable (e.g. `cadence-prod-01`)
   - **Host / IP**: your real license host (e.g. `192.168.200.51`)
   - **Port**: FlexLM port (defaults filled per vendor)
   - **Daemon**: the daemon binary name (`cdslmd`, `snpslmd`, `mgcld`, `xilinxd`, …)
4. **REGISTER**.

Repeat for every license server in your fleet. Add as many as you want — and any vendor name (XILINX, defacto, ansys, altium, custom in-house, …).

> At this point everything works in **MOCK mode**: dashboard, license editing, options editing, expiry calendar, alerts, audit — all functional but checkouts/lmstat are simulated. Step ⑥ flips it to real.

---

## ⑥ (Optional but recommended) Wire real SSH on each license host

Do this **once on every license host** (192.168.200.51, .52, .53, …).

### 6.1 Copy the bootstrap script to each license host
On your web host:
```bash
scp /opt/licman/deploy/setup-license-host.sh root@<LIC_HOST_IP>:/tmp/
```

### 6.2 Run it as root on the license host
SSH into the license host:
```bash
ssh root@<LIC_HOST_IP>
bash /tmp/setup-license-host.sh <WEB_HOST_IP>
# e.g. bash /tmp/setup-license-host.sh 192.168.200.11
```

The script creates a `licadmin` user, generates an Ed25519 keypair, installs the **restricted sudoers** file `/etc/sudoers.d/licadmin` (only allows `lmstat / lmreread / lmdown` and `systemctl restart` of the well-known EDA daemons), and prints the **private key** to stdout.

**Copy the printed private key.** You'll paste it into LICMAN in step 6.4.

### 6.3 Adjust the sudoers paths (only if your FlexLM lives elsewhere)
If your `lmutil` is **not** at `/usr/local/flexlm/lmutil` or `/opt/flexlm/lmutil`:
```bash
sudo $EDITOR /etc/sudoers.d/licadmin
# add the actual path to LIC_FLEXLM
```

### 6.4 Plug the key into LICMAN
1. Open `http://<WEB_HOST_IP>/`
2. Click the server card → **CONNECTION** tab
3. **Enabled** → ON
4. **Auth Method** → KEY
5. **SSH Host** → `<LIC_HOST_IP>`
6. **SSH Port** → `22`
7. **Username** → `licadmin`
8. **lmutil path** → wherever your FlexLM lives (e.g. `/usr/local/flexlm/lmutil`)
9. **Private Key (PEM)** → paste the key from step 6.2
10. Adapter mode toggle → **SSH**
11. Click **SAVE**, then **TEST**

If you see `licman-ok` in the toast → real SSH is live. From now on REREAD/RESTART buttons run actual commands on the license host. Repeat for each server.

---

## ⑦ (Optional) Office 365 email alerts

In the UI go to **SETTINGS** (top-right).

1. Click **USE O365 PRESET** — fills `smtp.office365.com:587` + STARTTLS on.
2. **Username (email)** → your Office 365 mailbox (e.g. `alerts@yourcompany.com`).
3. **Password / App Password** → an **App Password** from `https://account.microsoft.com/security` (required if you have MFA, which you should).
4. **From Address** → same mailbox or a configured alias.
5. **Recipients** → comma-separated list (`cad-team@corp, you@corp`).
6. **Master Enable** → ON, **Saturation Alerts** → ON, **Expiry Alerts** → ON.
7. **Expiry warn threshold (days)** → 30 (or whatever).
8. Click **SAVE** → then **SEND TEST EMAIL**.

If you receive the test mail, you're done. Alerts will fire automatically when a feature saturates or expiry approaches (throttled to 1 per 6 hours per feature).

---

## ⑧ Day-2 operations

```bash
# All commands run from /opt/licman/deploy on the web host

# Status / logs
docker compose ps
docker compose logs -f backend
docker compose logs -f nginx

# Restart everything
systemctl restart licman.service     # OR: docker compose restart

# Stop / start
systemctl stop  licman.service
systemctl start licman.service

# Upgrade to new code drop
cd /opt/licman
git pull                              # OR: re-extract a new tarball
cd deploy
docker compose down
docker compose up -d --build

# Backup MongoDB (run weekly via cron)
docker compose exec -T mongo \
  mongodump --uri="mongodb://licman:<PASSWORD>@localhost:27017/?authSource=admin" \
  --archive=/data/db/backup-$(date +%F).gz --gzip

# Restore MongoDB
docker compose exec -T mongo \
  mongorestore --uri="mongodb://licman:<PASSWORD>@localhost:27017/?authSource=admin" \
  --gzip --archive=/data/db/backup-YYYY-MM-DD.gz
```

---

## ⑨ Replace the self-signed cert with your internal CA (optional)

```bash
cd /opt/licman/deploy/nginx/ssl
# Drop your two files here (overwrite the auto-generated ones)
cp /path/to/yourcompany.crt server.crt
cp /path/to/yourcompany.key server.key
chmod 600 server.key
docker compose restart nginx
```

Browsers on machines that trust your internal CA will now get a green padlock at `https://<WEB_HOST_IP>/`.

---

## 🆘 Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `bash install-rhel9.sh` fails on Docker repo | Behind a proxy → `export http_proxy=http://proxy.corp:8080 https_proxy=…` before running. |
| `http://<WEB_HOST_IP>/` times out from your laptop | Firewall outside the box (corporate firewall blocks 80/443). Test from the web host itself first: `curl http://localhost/`. |
| `curl http://localhost/api/` returns 502 from nginx | Backend hasn't finished startup → `docker compose logs backend` and look for the FastAPI banner. Wait 30s. |
| LICMAN UI loads but every API returns 500 | Mongo password mismatch — re-check `MONGO_INITDB_ROOT_PASSWORD` in `.env`. If you changed it after first install: `docker compose down -v` (⚠ wipes data) then `docker compose up -d`. |
| TEST button on Connection tab fails | (a) `licadmin` user not created on that license host → re-run `setup-license-host.sh`. (b) Wrong key — make sure you pasted the **private** key (begins `-----BEGIN OPENSSH PRIVATE KEY-----`), not the `.pub` one. (c) SSH from web host blocked → on web host: `ssh -i /tmp/k licadmin@<LIC_HOST_IP> echo ok`. |
| SEND TEST EMAIL → "STARTTLS extension not supported" | Wrong port (use 587, not 25 / 465) or your Office 365 tenant disables SMTP AUTH → an admin must enable it for the mailbox. |
| Alerts never fire | Check `Master Enable` toggle is ON in Settings, and at least one feature has hit 100% utilization (visible in audit log). |
| After reboot the app doesn't come back | `systemctl status licman.service` — if disabled: `systemctl enable --now licman.service`. |

---

## ⓪ Uninstall (just in case)

```bash
systemctl stop licman.service
systemctl disable licman.service
rm /etc/systemd/system/licman.service
systemctl daemon-reload
cd /opt/licman/deploy
docker compose down -v        # ⚠ deletes the Mongo volume
rm -rf /opt/licman
```

---

That's it. Welcome to LICMAN.
