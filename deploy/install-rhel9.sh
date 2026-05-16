#!/usr/bin/env bash
# install-rhel9.sh — one-shot installer for LICMAN on RHEL 9
# Run as root from the deploy/ directory.

set -euo pipefail

NEED_SUDO() {
    if [[ $EUID -ne 0 ]]; then
        echo "[!] please run as root:  sudo bash $0"
        exit 1
    fi
}
NEED_SUDO

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DEPLOY_DIR"

echo
echo "============================================================"
echo " LICMAN installer — target $(hostname -I | awk '{print $1}')"
echo "============================================================"
echo

# --------------- 1. Docker + Compose plugin ---------------
if ! command -v docker >/dev/null 2>&1; then
    echo "[*] Installing Docker CE from Docker official repo..."
    dnf -y install dnf-plugins-core
    dnf config-manager --add-repo=https://download.docker.com/linux/rhel/docker-ce.repo
    dnf -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
else
    echo "[=] Docker already installed: $(docker --version)"
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "[*] Installing docker compose plugin..."
    dnf -y install docker-compose-plugin
fi

# --------------- 2. .env file ---------------
if [[ ! -f .env ]]; then
    echo "[*] Creating .env from template (edit later if you wish)..."
    cp .env.example .env
fi

# --------------- 3. Self-signed cert ---------------
mkdir -p nginx/ssl ssh_keys
if [[ ! -f nginx/ssl/server.crt || ! -f nginx/ssl/server.key ]]; then
    HOST_IP="$(hostname -I | awk '{print $1}')"
    echo "[*] Generating self-signed TLS cert (CN=${HOST_IP}) valid 10 years..."
    openssl req -x509 -nodes -newkey rsa:4096 \
        -keyout nginx/ssl/server.key \
        -out    nginx/ssl/server.crt \
        -days 3650 \
        -subj "/CN=${HOST_IP}/O=LICMAN/C=IN" \
        -addext "subjectAltName=IP:${HOST_IP},DNS:licman.local" 2>/dev/null
    chmod 600 nginx/ssl/server.key
else
    echo "[=] TLS cert already present"
fi

# --------------- 4. Firewall ---------------
if systemctl is-active --quiet firewalld; then
    echo "[*] Opening firewall ports 80/443..."
    firewall-cmd --add-service=http  --permanent >/dev/null
    firewall-cmd --add-service=https --permanent >/dev/null
    firewall-cmd --reload >/dev/null
else
    echo "[i] firewalld not running — skipping firewall step"
fi

# --------------- 5. SELinux ---------------
if command -v getenforce >/dev/null 2>&1 && [[ "$(getenforce)" != "Disabled" ]]; then
    echo "[*] Setting SELinux booleans for container connectivity..."
    setsebool -P container_manage_cgroup 1 2>/dev/null || true
    setsebool -P httpd_can_network_connect 1 2>/dev/null || true
fi

# --------------- 6. Build & start ---------------
echo "[*] Building images (first run takes ~3-5 min)..."
docker compose --env-file .env build --pull

echo "[*] Starting containers..."
docker compose --env-file .env up -d

# --------------- 7. systemd unit (auto-start on boot) ---------------
if [[ ! -f /etc/systemd/system/licman.service ]]; then
    echo "[*] Installing systemd unit so LICMAN starts on boot..."
    cp licman.service /etc/systemd/system/licman.service
    sed -i "s|/opt/licman/deploy|$DEPLOY_DIR|g" /etc/systemd/system/licman.service
    systemctl daemon-reload
    systemctl enable licman.service >/dev/null
fi

# --------------- 8. Smoke test ---------------
echo
echo "[*] Waiting for backend health (max 60s)..."
for i in $(seq 1 30); do
    if curl -fsS http://localhost/api/ >/dev/null 2>&1; then
        echo "[OK] Backend is responding."
        break
    fi
    sleep 2
done

IP="$(hostname -I | awk '{print $1}')"
echo
echo "============================================================"
echo " [OK] LICMAN is running."
echo "       HTTP  ->  http://${IP}/"
echo "       HTTPS ->  https://${IP}/   (self-signed cert)"
echo "============================================================"
echo " Useful commands:"
echo "   logs:        docker compose -f $DEPLOY_DIR/docker-compose.yml logs -f"
echo "   restart:     systemctl restart licman.service"
echo "   stop:        systemctl stop licman.service"
echo "   update code: cd $DEPLOY_DIR && docker compose down && git pull && docker compose up -d --build"
echo "============================================================"
