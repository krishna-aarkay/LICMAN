# LICMAN — VLSI License Console

## Original Problem Statement
> I am a cad engineer in to VLSI. Most of the times I work with cadence siemens-mentor and synpsys licenses servers hosting on local network. My daily routine is to install the licenses files apply options files and save changes, monitoring licenses checkouts reserve and unreserves changes and saves. it is too bored and repeated for me. Help me to build a web pages to do all above things from the web itself.

## User Choices
- Auth: **None** (single-user internal tool)
- Theme: User said "you decide" → Dark Swiss/Terminal aesthetic, JetBrains Mono + IBM Plex Sans
- Mode: Fully mocked demo (simulated `lmstat`/`lmreread` — safe iteration)

## Personas
- **CAD Engineer**: power user; manages 3+ vendors of FlexLM-style servers; lives in terminal; values density & speed over decoration.

## Core Requirements (Static)
1. Multi-vendor license server registry (Cadence, Synopsys, Siemens-Mentor)
2. Install / edit license files (`.lic`) per server, parse FEATURE lines
3. Edit options files with directives: RESERVE / INCLUDE / EXCLUDE / GROUP / MAX / TIMEOUT
4. Live monitoring of feature checkouts (user, host, feature, version, PID, since)
5. Reserve / Unreserve features for users/hosts/groups
6. Daemon control: lmreread / restart / stop
7. Audit log of every action
8. Aggregate stats: servers up, features total, active checkouts, reservations

## Implemented (2026-02)
### Backend (`/app/backend/server.py`)
- MongoDB collections: `servers`, `checkouts`, `reservations`, `audit`
- 18 `/api/*` endpoints (CRUD + actions + stats + seed reset)
- Auto-seed 3 servers on startup: lic-cadence-prod-01 (Innovus, Genus, Virtuoso, Spectre, Tempus), lic-synopsys-prod-01 (VCS, DC, PrimeTime, ICC2, Verdi), lic-mentor-prod-01 (Calibre DRC/LVS, Questa, Tessent)
- License file FEATURE-line regex parser updates server.features on save
- Simulated checkouts generated per call using realistic user/host pools

### Frontend (React + Tailwind + shadcn)
- Dark "Control Room" UI — JetBrains Mono / IBM Plex Sans, no rounded corners, semantic colors (emerald=up, amber=warn, red=down)
- `/` Dashboard: live header stats + UTC clock + auto-refresh, 3 vendor server cards with per-card REREAD/RESTART/STOP, live checkouts table (vendor filter + search), audit timeline
- `/servers/:id`: feature-usage bars, 5 tabs (Checkouts / License File / Options File / Reservations / Audit), monospace code editor with line numbers + syntax highlighting, reservation dialog
- ADD SERVER and RESET demo data buttons

## Testing
- Backend: **13/13 pytest cases PASSED** (`/app/backend/tests/backend_test.py`)
- Frontend: core flows render & API-integrated; testid coverage extended in iteration 1

## Prioritized Backlog
### P1 (next)
- Real `lmstat` / `lmreread` integration via SSH or local shell command runner (currently mocked)
- Per-feature checkout *deltas* over time (sparkline chart)
- CSV export of checkouts & audit log

### P2
- Multi-user auth (JWT or Google) — currently single-user
- Email/Slack alerts when a feature is fully checked out
- License expiry calendar / countdown widget
- Diff view when saving license/options files

### P3
- Multi-server bulk actions
- License usage analytics over weeks/months
- Public read-only status dashboard for end-engineers

## Next Tasks
1. Wire real `lmstat`/`lmutil` integration when user grants SSH access to license hosts
2. Add expiry warnings to license file editor
3. Persist auto-refresh & filter preferences in localStorage
