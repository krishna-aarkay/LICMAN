#!/usr/bin/env bash
# install.sh — one-shot installer for flexlm-preempt.
# Run as root from inside the extracted tarball directory.
#
# Modes:
#   --workstation     install wrapper + helper + config + sudoers
#   --license-server  same as --workstation PLUS copy options-file examples
#   --uninstall       remove everything (keeps /etc/licman/*.priority)
#
# Idempotent: re-running upgrades files but never clobbers existing
# /etc/licman/config.env or /etc/licman/*.priority.

set -euo pipefail

MODE="${1:-}"
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
    cat <<EOF
Usage:
  sudo $0 --workstation
  sudo $0 --license-server
  sudo $0 --uninstall
EOF
    exit 1
}

require_root() {
    if [[ "$EUID" -ne 0 ]]; then
        echo "install.sh: must run as root (use sudo)" >&2
        exit 1
    fi
}

install_common() {
    echo "==> Installing wrapper to /usr/local/bin/tool-wrapper"
    install -m 0755 -o root -g root "$SRC_DIR/bin/tool-wrapper" /usr/local/bin/tool-wrapper

    echo "==> Installing privileged helper to /usr/local/sbin/licman-preempt"
    install -m 0750 -o root -g root "$SRC_DIR/sbin/licman-preempt" /usr/local/sbin/licman-preempt

    echo "==> Installing sudoers fragment"
    install -m 0440 -o root -g root "$SRC_DIR/etc/sudoers.d/licman-preempt" /etc/sudoers.d/licman-preempt
    # Validate sudoers — fail loudly so we don't lock the system out
    if ! visudo -cf /etc/sudoers.d/licman-preempt >/dev/null; then
        echo "ERROR: sudoers fragment failed validation. Reverting." >&2
        rm -f /etc/sudoers.d/licman-preempt
        exit 2
    fi

    echo "==> Ensuring /etc/licman and /var/log/licman and /var/lib/licman exist"
    install -d -m 0755 -o root -g root /etc/licman
    install -d -m 0775 -o root -g root /var/log/licman
    install -d -m 0775 -o root -g root /var/lib/licman

    echo "==> Creating priority-users POSIX group (if missing)"
    if ! getent group priority-users >/dev/null; then
        groupadd --system priority-users
        echo "    created group 'priority-users' — add members with: usermod -aG priority-users <user>"
    fi
    chgrp priority-users /var/log/licman /var/lib/licman || true
    chmod g+w /var/log/licman /var/lib/licman || true

    echo "==> Installing config.env.example (NOT overwriting your existing config.env)"
    install -m 0644 -o root -g root "$SRC_DIR/etc/licman/config.env.example" /etc/licman/config.env.example
    if [[ ! -f /etc/licman/config.env ]]; then
        cp /etc/licman/config.env.example /etc/licman/config.env
        echo "    seeded /etc/licman/config.env — EDIT THIS FILE NOW (LIC=, TOOL_MAP=...)"
    else
        echo "    /etc/licman/config.env already exists — left untouched"
    fi

    echo "==> Installing innovus.priority.example (NOT overwriting any *.priority you already have)"
    install -m 0644 -o root -g root "$SRC_DIR/etc/licman/innovus.priority.example" /etc/licman/innovus.priority.example
    if [[ ! -f /etc/licman/innovus.priority ]]; then
        cp /etc/licman/innovus.priority.example /etc/licman/innovus.priority
        echo "    seeded /etc/licman/innovus.priority — EDIT IT or create per-feature lists"
    fi
}

install_symlinks() {
    echo "==> Creating wrapper symlinks for every tool in TOOL_MAP"
    # shellcheck disable=SC1091
    source /etc/licman/config.env
    for tool in "${!TOOL_MAP[@]}"; do
        entry="${TOOL_MAP[$tool]}"
        feature="${entry%%:*}"
        real="${entry#*:}"
        if [[ ! -x "$real" ]]; then
            echo "    SKIP $tool: real binary '$real' not executable (edit config.env or rename your binary to .real)"
            continue
        fi
        ln -sf /usr/local/bin/tool-wrapper "/usr/local/bin/$tool"
        echo "    linked /usr/local/bin/$tool -> tool-wrapper  (feature=$feature)"
    done
    cat <<EOF

NOTE — PATH ordering matters. Make sure /usr/local/bin is BEFORE the vendor's
bin dirs in every engineer's \$PATH. The installer wrote a profile snippet:
    /etc/profile.d/licman-path.sh
EOF
    cat >/etc/profile.d/licman-path.sh <<'EOF'
# flexlm-preempt: ensure wrapper takes precedence
case ":$PATH:" in
    *":/usr/local/bin:"*) ;;
    *) export PATH="/usr/local/bin:$PATH" ;;
esac
EOF
    chmod 0644 /etc/profile.d/licman-path.sh
}

install_license_server_extras() {
    echo "==> Copying vendor options-file examples to /etc/licman/opt-examples/"
    install -d -m 0755 /etc/licman/opt-examples
    install -m 0644 "$SRC_DIR/opt/lic-examples/cdslmd.opt"  /etc/licman/opt-examples/
    install -m 0644 "$SRC_DIR/opt/lic-examples/snpslmd.opt" /etc/licman/opt-examples/
    install -m 0644 "$SRC_DIR/opt/lic-examples/mgcld.opt"   /etc/licman/opt-examples/
    cat <<EOF

Next steps on the license server:
  1) Edit each .opt file in /etc/licman/opt-examples/ — set GROUP memberships
  2) Copy each one to its real path (see header comment in each file)
  3) Reference it from your license.dat: VENDOR <daemon> OPTIONS=/path/to/.opt
  4) Reread without restart:
       lmutil lmreread -c <port@host> -vendor <daemon>
EOF
}

uninstall() {
    echo "==> Removing wrapper, helper, sudoers, and PATH snippet"
    rm -f /usr/local/sbin/licman-preempt
    rm -f /etc/sudoers.d/licman-preempt
    rm -f /etc/profile.d/licman-path.sh
    # Remove every wrapper symlink that points at tool-wrapper
    for f in /usr/local/bin/*; do
        [[ -L "$f" && "$(readlink "$f")" == "/usr/local/bin/tool-wrapper" ]] && rm -f "$f"
    done
    rm -f /usr/local/bin/tool-wrapper
    echo "    config.env and *.priority left in /etc/licman/ for safety."
    echo "    rm -rf /etc/licman /var/log/licman /var/lib/licman   # to fully purge"
}

case "$MODE" in
    --workstation)
        require_root
        install_common
        install_symlinks
        echo
        echo "DONE (workstation). See INSTALL.md sections 3-6 for what to edit next."
        ;;
    --license-server)
        require_root
        install_common
        install_symlinks
        install_license_server_extras
        echo
        echo "DONE (license server). See INSTALL.md section 7."
        ;;
    --uninstall)
        require_root
        uninstall
        ;;
    *)
        usage
        ;;
esac
