#!/usr/bin/env bash
# setup-license-host.sh — run ONCE on each license host (10.10.11.111 / .112 / .113 / …)
# Creates a restricted service account `licadmin` for LICMAN to manage daemons.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "[!] please run as root:  sudo bash $0"
    exit 1
fi

USER_NAME="licadmin"
HOME_DIR="/home/${USER_NAME}"
WEB_HOST="${1:-10.10.11.11}"     # IP of the LICMAN host. Pass as first arg to override.

echo
echo "============================================================"
echo " License-host bootstrap on $(hostname) — for LICMAN @ ${WEB_HOST}"
echo "============================================================"
echo

# 1. Create user
if ! id -u "$USER_NAME" >/dev/null 2>&1; then
    echo "[*] Creating user '${USER_NAME}'..."
    useradd -m -s /bin/bash "$USER_NAME"
else
    echo "[=] User '${USER_NAME}' already exists"
fi

# 2. SSH dir
install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "${HOME_DIR}/.ssh"
touch "${HOME_DIR}/.ssh/authorized_keys"
chmod 600 "${HOME_DIR}/.ssh/authorized_keys"
chown "${USER_NAME}:${USER_NAME}" "${HOME_DIR}/.ssh/authorized_keys"

# 3. Generate an SSH keypair if you don't already manage one centrally.
KEY_DIR="${HOME_DIR}/.ssh"
PRIV="${KEY_DIR}/licman_ed25519"
if [[ ! -f "$PRIV" ]]; then
    echo "[*] Generating Ed25519 keypair for LICMAN..."
    sudo -u "$USER_NAME" ssh-keygen -t ed25519 -N "" -f "$PRIV" -C "licman@${WEB_HOST}"
fi

# 4. Authorize that key for incoming connections from the web host
PUB="$(cat "${PRIV}.pub")"
grep -qxF "$PUB" "${HOME_DIR}/.ssh/authorized_keys" || \
    printf 'from="%s" %s\n' "$WEB_HOST" "$PUB" >> "${HOME_DIR}/.ssh/authorized_keys"

# 5. Restricted sudoers — only allows the FlexLM/daemon commands we need
SUDOERS_FILE="/etc/sudoers.d/licadmin"
echo "[*] Installing restricted sudoers (${SUDOERS_FILE})..."
cat > "${SUDOERS_FILE}" <<'EOF'
# /etc/sudoers.d/licadmin — restricted privileges for LICMAN service account
# Adjust paths to where YOUR lmutil/daemons actually live.

Cmnd_Alias LIC_FLEXLM = \
    /usr/local/flexlm/lmutil lmstat *, \
    /usr/local/flexlm/lmutil lmreread *, \
    /usr/local/flexlm/lmutil lmdown *, \
    /usr/local/flexlm/lmutil lmremove *, \
    /opt/flexlm/lmutil lmstat *, \
    /opt/flexlm/lmutil lmreread *, \
    /opt/flexlm/lmutil lmdown *

Cmnd_Alias LIC_DAEMONS = \
    /usr/bin/systemctl start cdslmd, \
    /usr/bin/systemctl stop cdslmd, \
    /usr/bin/systemctl restart cdslmd, \
    /usr/bin/systemctl start snpslmd, \
    /usr/bin/systemctl stop snpslmd, \
    /usr/bin/systemctl restart snpslmd, \
    /usr/bin/systemctl start mgcld, \
    /usr/bin/systemctl stop mgcld, \
    /usr/bin/systemctl restart mgcld, \
    /usr/bin/systemctl start xilinxd, \
    /usr/bin/systemctl stop xilinxd, \
    /usr/bin/systemctl restart xilinxd, \
    /usr/bin/systemctl start defacto, \
    /usr/bin/systemctl stop defacto, \
    /usr/bin/systemctl restart defacto

Defaults:licadmin !requiretty
licadmin ALL=(root) NOPASSWD: LIC_FLEXLM, LIC_DAEMONS
EOF
chmod 440 "${SUDOERS_FILE}"
visudo -cf "${SUDOERS_FILE}" >/dev/null

# 6. Firewall — allow SSH from web host
if systemctl is-active --quiet firewalld; then
    firewall-cmd --add-rich-rule="rule family='ipv4' source address='${WEB_HOST}/32' service name='ssh' accept" --permanent >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
fi

echo
echo "============================================================"
echo " [OK] License-host bootstrap complete."
echo "------------------------------------------------------------"
echo " Private key (paste into LICMAN  > server > Connection tab):"
echo "------------------------------------------------------------"
cat "$PRIV"
echo "------------------------------------------------------------"
echo "  Username : ${USER_NAME}"
echo "  Host     : $(hostname -I | awk '{print $1}')"
echo "  Auth     : key"
echo "  lmutil   : (whichever path FlexLM is installed at — usually /usr/local/flexlm/lmutil)"
echo "============================================================"
echo
echo "NOTE: This is the *private* key — keep it secret. After pasting it into"
echo "      LICMAN and clicking SAVE, you can delete /home/${USER_NAME}/.ssh/licman_ed25519"
echo "      from this host if you don't want a copy lying around."
