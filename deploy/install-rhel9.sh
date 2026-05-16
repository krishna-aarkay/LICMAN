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
    if   [[ -f env.example ]];   then cp env.example   .env
    elif [[ -f .env.example ]];  then cp .env.example  .env
    else
        cat > .env <<'EOF'
MONGO_INITDB_ROOT_USERNAME=licman
MONGO_INITDB_ROOT_PASSWORD=change-me-please
MONGO_DB_NAME=licman
DEMO_MODE=0
CORS_ORIGINS=*
JWT_SECRET=
REACT_APP_BACKEND_URL=
TZ=UTC
EOF
        echo "[!] env.example missing — wrote a default .env. EDIT IT BEFORE PRODUCTION USE."
    fi
fi

# Auto-generate JWT_SECRET if absent or empty
if ! grep -E '^JWT_SECRET=.+' .env >/dev/null 2>&1; then
    NEW_JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(64))" 2>/dev/null || openssl rand -hex 64)
    if grep -q '^JWT_SECRET=' .env; then
        sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${NEW_JWT_SECRET}|" .env
    else
        echo "JWT_SECRET=${NEW_JWT_SECRET}" >> .env
    fi
    echo "[*] Generated random JWT_SECRET (stored in .env)"
fi

# Auto-generate FERNET_KEY for at-rest encryption of SSH keys & SMTP passwords
if ! grep -E '^FERNET_KEY=.+' .env >/dev/null 2>&1; then
    NEW_FERNET=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null \
                 || (openssl rand -base64 32 | tr -d '=' | tr '+/' '-_'))
    if grep -q '^FERNET_KEY=' .env; then
        sed -i "s|^FERNET_KEY=.*|FERNET_KEY=${NEW_FERNET}|" .env
    else
        echo "FERNET_KEY=${NEW_FERNET}" >> .env
    fi
    echo "[*] Generated random FERNET_KEY (stored in .env)"
fi

# Make .env readable only by root — it now contains secrets
chmod 600 .env

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

# --------------- 7b. Weekly backup timer ---------------
if [[ -f licman-backup.service && -f licman-backup.timer ]]; then
    install -d -m 700 /var/backups/licman
    cp licman-backup.service /etc/systemd/system/licman-backup.service
    cp licman-backup.timer   /etc/systemd/system/licman-backup.timer
    sed -i "s|/opt/licman/deploy|$DEPLOY_DIR|g" /etc/systemd/system/licman-backup.service
    systemctl daemon-reload
    systemctl enable --now licman-backup.timer >/dev/null 2>&1 || true
    echo "[*] Weekly backup timer enabled → /var/backups/licman"
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
