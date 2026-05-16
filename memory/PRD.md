# LICMAN — VLSI License Console

## Original Problem Statement
> I am a cad engineer in to VLSI. Most of the times I work with cadence siemens-mentor and synpsys licenses servers hosting on local network. My daily routine is to install the licenses files apply options files and save changes, monitoring licenses checkouts reserve and unreserves changes and saves. it is too bored and repeated for me. Help me to build a web pages to do all above things from the web itself.

## User Choices
- Auth: **None** (single-user internal tool)
- Theme: Dark Swiss/Terminal aesthetic, JetBrains Mono + IBM Plex Sans
- License-server adapter: **MOCKED + SSH adapter layer scaffolded** (paramiko swap-in later)
- Alert channel: **Office 365 SMTP** (configured via web UI)

## Personas
- **CAD Engineer**: power user; manages 3+ vendors of FlexLM-style servers; lives in terminal; values density & speed over decoration.

## Core Requirements (Static)
1. Multi-vendor license server registry (Cadence, Synopsys, Siemens-Mentor)
2. Install / edit license files (`.lic`) per server, parse FEATURE lines
3. Edit options files with directives: RESERVE / INCLUDE / EXCLUDE / GROUP / MAX / TIMEOUT
4. Live monitoring of feature checkouts
5. Reserve / Unreserve features for users/hosts/groups
6. Daemon control: lmreread / restart / stop
7. Audit log of every action
8. **License expiry tracking** + alerts when nearing expiration
9. **Saturation alerts** when a feature hits 100% checked-out
10. **SSH connection adapter** for remote license-host execution (mock-only today)
11. **Office 365 / SMTP alerts** with master + per-trigger toggles
12. **Persistent UI preferences** via localStorage

## Implemented

### 2026-02 — MVP (iteration 1)
- 18 `/api` endpoints (server CRUD, license/options editing with FEATURE parsing, lmreread, restart, toggle, checkouts, reservations, audit, stats, seed/reset)
- 3-server auto-seed (Innovus/VCS/Calibre…)
- Dashboard with live stats, vendor cards, checkouts table, audit timeline
- ServerDetail with 5 tabs (Checkouts, License File, Options, Reservations, Audit) + monospace code editor with syntax highlighting

### 2026-02 — iteration 2 (alerts + SSH + expiry + prefs)
- **New Models**: `SshConfig`, `AlertSettings`, `AlertEvent`
- **New endpoints**: `/api/settings` GET/PUT, `/api/settings/test-email`, `/api/alerts`, `/api/alerts/evaluate`, `/api/expiry`, `/api/servers/{id}/ssh`, `/api/servers/{id}/adapter`, `/api/servers/{id}/ssh/test`
- **Alert engine**: Saturation + expiry detection wired as side-effect of `GET /api/checkouts`; 6-hour throttle per (kind, server, feature); SMTP delivery via stdlib `smtplib` with STARTTLS (Office 365 ready)
- **Expiry parser**: `31-dec-2026` / `2026-12-31` / `permanent` formats; computes `days_remaining` and severity (expired/critical/warning/ok/permanent)
- **SSH adapter (mocked)**: `ssh_execute` records "would-have-executed" commands; switching `adapter_mode='ssh'` is the only line to swap with real paramiko later
- **Frontend pages added**: `/expiry` (color-coded calendar), `/settings` (SMTP form + O365 preset + alert toggles + recent alerts column)
- **Frontend components added**: `ExpiryBadge`, `SshConfigPanel`
- **ServerDetail**: new "Connection" tab with full SSH config form + adapter mode toggle + test button
- **Feature bars**: now show ExpiryBadge with color-coded days remaining
- **Header**: 3 nav links (Control Room / Expiry / Settings)
- **localStorage `licman_prefs_v1`**: persists `autoRefresh`, `vendorFilter`, `searchQuery`, `lastServerId`

## Testing
- Backend: **29/29 pytests passing** (13 from iteration 1 + 16 new for iteration 2)
- All new endpoints verified end-to-end; alert engine confirmed triggering automatically

## Open Concerns / Tech Debt
- `server.py` is ~860 lines — consider splitting into modules
- `send_smtp_email` runs synchronously in async endpoint — wrap with `asyncio.to_thread` under load
- SMTP password stored in plaintext — encrypt-at-rest for prod
- SSH credentials stored in plaintext — same caveat
- `adapter_mode='ssh'` doesn't enforce `ssh.enabled=True`

## Prioritized Backlog
### P1
- Real paramiko SSH execution (swap-in for `ssh_execute` mock)
- Live `lmstat -a` parsing into checkouts (replace random generator)
- Encrypt SMTP & SSH credentials at rest

### P2
- Slack webhook channel alongside SMTP
- CSV export of checkouts / audit / expiry
- Per-feature usage sparkline + peak-hour heatmap (helps justify budget)
- Bulk lmreread across all servers

### P3
- Multi-user JWT auth (deferred per user choice)
- Public read-only status board for end-engineers
- Diff view when saving license/options files
- Multi-server bulk actions

## Next Tasks
1. When user grants SSH access, swap `ssh_execute` mock with paramiko 1-liner
2. Refactor `server.py` into modules (`models/`, `routes/`, `services/`)
3. Add encryption for stored secrets (Fernet keyed by env var)
