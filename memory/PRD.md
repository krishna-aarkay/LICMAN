# LICMAN — VLSI License Console

## Original Problem Statement
> I am a cad engineer in to VLSI. Most of the times I work with cadence siemens-mentor and synpsys licenses servers hosting on local network… Help me to build a web pages to do all above things from the web itself.

Follow-ups:
> Add license expiry countdown + Office 365 email alerts. Persist filter & auto-refresh preferences. Wire real lmstat / lmreread integration over SSH.
> Host on private network (10.10.11.0/24) — web app on 10.10.11.11, cadence at .111, siemens at .112, synopsys at .113. Allow adding more vendors (XILINX, defacto, others). RHEL 9 host.

## User Choices
- Auth: **None** (single-user internal tool)
- Theme: Dark Swiss/Terminal aesthetic, JetBrains Mono + IBM Plex Sans
- Adapter: SSH adapter scaffolded with **paramiko-ready** code (mock by default)
- Alerts: Office 365 SMTP, configured from the web UI
- Vendor field: **free-form text + curated palette** (Cadence/Synopsys/Siemens/Xilinx/Defacto/Ansys/Altair/Keysight/Intel/ARM presets + auto-color for any custom string)
- Deployment: **Docker Compose** plug-and-play for RHEL 9
- TLS: Both HTTP and self-signed HTTPS supported
- License-host execution: dedicated `licadmin` service account with restricted sudoers

## Implemented

### MVP (iteration 1) — 2026-02
- 18 `/api` endpoints (server CRUD, license/options editing, lmreread, restart, toggle, checkouts, reservations, audit, stats, seed/reset)
- Dashboard, ServerDetail (5 tabs), monospace code editor with FlexLM syntax highlighting

### Iteration 2 — Alerts / Expiry / SSH / Persistence
- `SshConfig`, `AlertSettings`, `AlertEvent` models
- `/api/settings`, `/api/settings/test-email`, `/api/alerts`, `/api/alerts/evaluate`, `/api/expiry`, `/api/servers/{id}/ssh`, `/api/servers/{id}/adapter`, `/api/servers/{id}/ssh/test`
- Alert engine wired as side-effect of `/api/checkouts` with 6-hour throttle
- SMTP send via stdlib `smtplib` (Office 365 preset, STARTTLS)
- Expiry calendar page + per-feature color-coded badges
- SSH adapter scaffold (mocked) + Connection tab
- `localStorage` persistence (`licman_prefs_v1`)

### Iteration 3 — Private network + vendor freedom + RHEL 9 deploy
- **Vendor field opened to free-form string** (was `Literal`). Backend accepts any value (xilinx, defacto, ansys, altium, …)
- **`vendorMeta()` helper** on frontend: curated colors for 12 known vendors (Cadence, Synopsys, Siemens/Mentor, Xilinx/AMD, Defacto, Ansys, Altair, Keysight, Intel, ARM…) + deterministic hash-based auto-color for anything else
- **AddServerDialog** got a **PRESET / CUSTOM** toggle — preset gives one-click vendor + default port/daemon, custom is a free-text input
- **Real paramiko SSH execution** added — when `adapter_mode='ssh'` AND `ssh.enabled=True`, `ssh_execute()` actually connects (RSA/Ed25519/ECDSA keys, password fallback). Wrapped in `asyncio.to_thread` for non-blocking. Errors returned gracefully as `mode='ssh-error'`
- **Seed updated** to use 10.10.11.111/.112/.113 with vendors cadence/siemens/synopsys
- **`DEMO_MODE=0`** env var disables auto-seeding for production installs
- **CheckoutTable + Expiry filter chips dynamic** — derived from actual data, no longer hardcoded
- **RHEL 9 deployment bundle** at `/app/deploy/`:
  - `install-rhel9.sh` — one-shot: installs Docker CE + Compose, opens firewall 80/443, sets SELinux booleans, generates self-signed TLS cert, builds & starts 4 containers, installs `licman.service` systemd unit
  - `docker-compose.yml` — mongo + backend + frontend + nginx
  - `Dockerfile.backend` (Python 3.11 + paramiko), `Dockerfile.frontend` (Node 20 build → nginx static)
  - `nginx.conf` — both HTTP and HTTPS reverse proxy (`/api` → backend, `/` → frontend)
  - `setup-license-host.sh` — run on each license host (10.10.11.111/.112/.113…); creates `licadmin` user, generates ed25519 keypair, drops in restricted sudoers (`/etc/sudoers.d/licadmin`) that only permits lmstat/lmreread/lmdown and systemctl restart for cdslmd/snpslmd/mgcld/xilinxd/defacto
  - `licman.service` — systemd unit so the stack starts on boot
  - `README.md` — end-to-end install guide

## Testing
- Backend: **66/66 pytests** passing (iter4 auth 27 + iter6 hardening 18 + iter7 features 21)
- Frontend: all critical flows verified by testing agent across iterations 5–7

## Iteration 7 — "Add all the best" final feature batch — 2026-02
- **Bulk operations**: `POST /api/servers/sync-all` and `POST /api/servers/reread-all` for one-click maintenance across the fleet (admin-only). Dashboard exposes new `SYNC ALL` and `REREAD ALL` buttons gated to admin.
- **Slack / Teams / generic webhooks**: `AlertSettings` extended with `webhook_url`, `webhook_kind`, `webhook_enabled`. Webhook fired in addition to SMTP from `trigger_alert`. New `POST /api/settings/test-webhook` for one-click delivery test. Settings page got a dedicated WEBHOOK panel.
- **Options file validator**: `POST /api/servers/{id}/options/validate` returns line-numbered errors/warnings against the FlexLM directive grammar (RESERVE/INCLUDE/EXCLUDE/GROUP/MAX/TIMEOUT/...). ServerDetail → Options tab gets a VALIDATE button + inline results panel.
- **CSV exports**: `GET /api/expiry/export` and `GET /api/audit/export` stream CSV with attachment headers. Expiry page + Settings page each carry a download button.
- **Settings backfill**: `get_alert_settings` merges defaults so legacy DB records expose the new webhook fields to the UI without a manual migration.

## Open Concerns / Tech Debt
- `server.py` is ~1968 lines — strongly recommend splitting into `auth.py`, `crypto.py`, `scheduler.py`, `bulk_ops.py`, `options_validator.py`, `csv_exports.py` before the next feature batch.
- `send_webhook` uses stdlib `urllib` — fine for stdlib-only/air-gapped builds, but blocks the event loop. Consider `asyncio.to_thread` wrap (consistent with `_ssh_real_exec`) when refactoring.
- CSV exports build in memory with `StringIO`. Switch to `StreamingResponse` if audit corpus grows large.
- `audit_export` currently inherits the same auth as `/api/audit` (any logged-in user). Tighten to `require_admin` if compliance demands it.
- `_ssh_real_exec` uses `AutoAddPolicy` — add strict known-hosts mode for prod.
- No vendor name normalization (`Cadence` vs `cadence` create two groups).

## Prioritized Backlog
### P1
- Production SSH validation on user's air-gapped RHEL 10 box (real lmstat output regex tuning if needed)
- Split `server.py` into route modules

### P2
- Vendor-specific daemon startup scripts when lmdown/lmreread divergence appears
- Per-feature usage sparkline + 24×7 peak-hours heatmap
- LDAP / SSO for multi-user
- Diff view when saving license/options

### P3
- Public read-only status board for engineers
- License purchase ROI dashboard
- Bulk reservation propagation across vendor-grouped servers

## Next Tasks
1. User runs `bash deploy/install-rhel9.sh` on the production RHEL host
2. User runs `bash deploy/setup-license-host.sh <licman-host>` on each license server
3. User configures SSH credentials in LICMAN UI → Connection tab → SSH mode → SAVE
4. (Optional) Configure Slack/Teams webhook in Settings → WEBHOOK panel for chat alerts
