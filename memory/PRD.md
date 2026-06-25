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

## Iteration 8 — UX polish + Usage telemetry — 2026-02
- **UTC ↔ IST clock toggle** in header (default IST), persisted in `prefs.tz`. All timestamps in the new Usage page and CheckoutTable use the chosen timezone.
- **Usage History page** (`/usage`) with:
  - Date-range presets (TODAY / 7D / 30D / 90D / 1Y / ALL) + custom from/to inputs
  - Filters: user (dropdown from `/api/usage/facets`), license/feature, vendor
  - Aggregation by user / feature / vendor / server (toggle)
  - Sortable column headers on the sessions table
  - One-click CSV export honouring all active filters
- **Backend tracking**: `usage_history` collection upserted on every sync tick (server-side scheduler + on-demand `/api/checkouts`). 365-day TTL (configurable via `USAGE_TTL_DAYS`). New endpoints: `GET /api/usage`, `/api/usage/export`, `/api/usage/summary`, `/api/usage/facets`.
- **Kill checkout** from the web: `POST /api/servers/{id}/checkouts/kill` runs `lmutil lmremove -h <feature> <vendor_daemon> <host> <user>` over SSH (or mock). Admin-only. All four user-supplied identifiers are validated against `^[A-Za-z0-9._@:/+-]+$` and shlex-quoted to block shell injection.
- **Feature drill-in**: ServerDetail feature boxes replaced with clickable rows. Clicking a row opens a Feature Detail modal listing active checkouts (with kill buttons) and reservations.
- **Kill buttons** added to Dashboard CheckoutTable rows + ServerDetail Checkouts tab + Feature Detail modal (all admin-gated).
- **Sortable column headers** on Dashboard CheckoutTable, Expiry table, and the new Usage detail/aggregate tables. Permanent expirations stay pinned at the bottom regardless of sort direction.

## Iteration 9 — Production correctness + SGE preemption — 2026-02
**4 bug fixes:**
- **RESET no longer wipes user-added servers**. `POST /api/seed/reset` now only clears transient history (checkouts, alerts, audit log, usage history) and reseeds demo servers ONLY when the servers collection is empty. The Dashboard button is renamed `CLEAR HIST` with a confirm modal explaining what's preserved.
- **lmreread fixed** — was emitting `lmreread -c @{port}@{host}` (stray `@`). Now emits proper `lmutil lmreread -c {port}@{host} -vendor {daemon}`.
- **fetch-license + ssh/test fixed** — both endpoints were passing *encrypted* SSH credentials to `_ssh_real_exec` ("authentication failed"). Now route through `_ssh_with_decrypted(ssh)` like `_real_checkouts_via_ssh` does.
- **kill-checkout fixed** — wrong lmremove argument order ("no such feature"). Now: `lmutil lmremove -c {port}@{host} {feature} {user} {host} [display]`. Removed mandatory vendor_daemon validation since it's not used in this form.

**NEW: Priority &amp; Preemption (SGE-aware):**
- New `priority_rules` collection + full CRUD at `/api/priority-rules` (admin only)
- Match by user_pattern / group_pattern / project_pattern (glob); scope by feature list (empty = all features)
- `POST /api/preempt/plan` — preview which lowest-priority holders would be released
- `POST /api/preempt/run` — execute via `qmod -d <jobid>` (SGE) → falls back to `lmremove`
- `GET /api/preempt/who-am-i` — convenience helper to look up an actor's priority
- Settings extended with `sge_enabled` / `sge_qstat_path` / `sge_qmod_path` (panel added)
- New `/priority` page (admin) with rules table, editor, and manual preemption tester
- All preempt endpoints gated behind `require_admin`

## Iteration 10 — UX gaps + SGE auto-discovery — 2026-02

**3 issues addressed:**
- **Delete server** — added trash button on every ServerCard (Dashboard) + REMOVE button on ServerDetail header. Both admin-only with confirm() dialog. Backend `DELETE /api/servers/{id}` already existed.
- **RAW LMSTAT diagnostic** — new admin button on ServerDetail → `POST /api/servers/{id}/diagnose` runs `lmutil lmstat -a -c port@host` over the user's SSH connection and returns the unparsed output, the parser's interpretation (features/checkouts counts), and a `command -v lmutil` resolved path. UI surfaces the raw text plus actionable diagnosis ("parser is healthy" vs "parser saw 0 of N lines"). This is the single most valuable button when integrating with real Cadence/Synopsys/Siemens output.
- **SGE auto-discovery** — new endpoints `GET /api/sge/users`, `/sge/groups`, `/sge/projects`, `/sge/test` shell out to `qconf -suserl / -shgrpl / -sprjl` over the same SSH connection as lmstat. Priority page has a `PULL FROM SGE` button that loads all three lists; each editor input gets HTML `<datalist>` autocomplete so admins type-ahead from real SGE catalog instead of guessing patterns. Settings page got a `TEST SGE` button for one-click smoke check.

## Testing
- Backend: **151/151 pytests** still passing + new endpoints smoke-tested via curl
- Frontend: delete button verified live on 5 server cards, Priority PULL FROM SGE button visible

## Iteration 7 — "Add all the best" final feature batch — 2026-02
- **Bulk operations**: `POST /api/servers/sync-all` and `POST /api/servers/reread-all` for one-click maintenance across the fleet (admin-only). Dashboard exposes new `SYNC ALL` and `REREAD ALL` buttons gated to admin.
- **Slack / Teams / generic webhooks**: `AlertSettings` extended with `webhook_url`, `webhook_kind`, `webhook_enabled`. Webhook fired in addition to SMTP from `trigger_alert`. New `POST /api/settings/test-webhook` for one-click delivery test. Settings page got a dedicated WEBHOOK panel.
- **Options file validator**: `POST /api/servers/{id}/options/validate` returns line-numbered errors/warnings against the FlexLM directive grammar (RESERVE/INCLUDE/EXCLUDE/GROUP/MAX/TIMEOUT/...). ServerDetail → Options tab gets a VALIDATE button + inline results panel.
- **CSV exports**: `GET /api/expiry/export` and `GET /api/audit/export` stream CSV with attachment headers. Expiry page + Settings page each carry a download button.
- **Settings backfill**: `get_alert_settings` merges defaults so legacy DB records expose the new webhook fields to the UI without a manual migration.

## Iteration 14 — Wildcard auto-preempt fix — 2026-02

**Issue (recurring)**: Automatic preemption never triggered even with auto-toggle ON
and a priority rule configured. Manual preempt worked.

**Root cause**: `_heuristic_preempt_candidates` skipped every rule whose
`user_pattern` contained a wildcard (line `if not pat or any(ch in pat for ch
in "*?["): continue`). The user's rules use wildcards (`rakella*`,
`cad_team_*`), so no candidates were ever generated → loop no-op every tick.

**Fix**: Replaced the synthetic-user heuristic with a new
`_rule_driven_preempt_pass` invoked from every `_auto_preempt_tick`:
- For each ENABLED rule, for each feature in the rule (or all features
  fleet-wide if `features=[]`), if the feature is fully saturated AND at
  least one current holder has STRICTLY lower priority than the rule,
  the lowest-priority holder is preempted via `lmremove`.
- Works with wildcard / group / project patterns (no synthetic requester
  user required — rule's own priority is the comparison anchor).
- Skipped silently with structured `reasons` when:
  - Feature not saturated (`used < total`)
  - A holder already matches the rule pattern (rule is "already satisfied")
  - All holders are at or above the rule's priority
  - No server hosts the feature
- Frees AT MOST ONE seat per `(rule, feature)` per tick (`freed_this_tick`
  guard) so a single tick never kills more than necessary.

**Frontend**: New AUTO-PREEMPT MONITOR panel on `/priority`:
- Shows daemon running/stopped, settings toggle on/off, interval, mode
- "RUN TICK NOW" button → calls `/api/preempt/auto-tick` and renders
  RESULTS (green) + SKIP REASONS (amber) cards for self-diagnosis
- Verified: wildcard `rakella*` rule preempted `jzhang@synth-node-11` on
  saturated Calibre_DRC; 19 skip reasons surfaced for other rule/feature
  pairs that were not saturated.

## Iteration 15 — Clean Priority Dashboard v2 (per-feature hipri/lopri) — 2026-06

**User request** (verbatim):
> Remove existing priority complete dashboard. Start a clean dashboard.
> My requirement is to build priority based on username (No SGE dependent).
> Where high priority group of users and low priority group of users
> to added on the dashboard. For every feature there should be these two
> groups. When user from high priority group request a license then only
> it should kill the license from low priority group and assign to the user.

**Implementation**:

### New backend collection `feature_priorities` + endpoints
- `GET  /api/feature-priorities` — list configs
- `PUT  /api/feature-priorities` — upsert by (server_id, feature). Validates
  server + feature exist, rejects user-overlap between hipri/lopri groups.
- `DELETE /api/feature-priorities/{id}` — admin only
- `POST /api/feature-priorities/request` — body `{server_id, feature, user}`.
  Returns one of six outcomes:
    - `available` — seats free, no preempt needed
    - `already_holding` — requester already owns a seat
    - `preempted` — killed oldest lopri holder via lmremove, requester can
      now check out
    - `no_victim` (ok=false) — saturated but no lopri holder to kill
    - 403 `not_in_hipri` — requester not in the hipri group
    - 404 `no_priority_config` — no config exists for that feature

### Frontend rewrite — `/app/frontend/src/pages/Priority.jsx`
Completely rebuilt from scratch. Three sections:
1. **REQUEST LICENSE panel** — server + feature + user inputs, big REQUEST
   button, result card with `available` / `preempted` / `no_victim` /
   `error` tones and audit detail (`exec.command`, `exec.output`).
2. **FEATURE PRIORITY CONFIGS list** — one row per (server, feature):
   server name, feature name, total seats, HI-PRI pills (emerald,
   click-to-quickfill-request), LO-PRI pills (red), edit/delete buttons.
3. **Editor** — server dropdown + feature input (with datalist autocomplete
   from the server's actual features) + hipri textarea + lopri textarea.

### Removed / disabled
- Auto-preempt background loop **no longer starts** at boot (was
  `_auto_preempt_loop`). Preemption is strictly on-demand via REQUEST.
- Settings page lost the "SGE" and "AUTO-PREEMPTION DAEMON" panels — only
  a `DEPRECATED` placeholder remains for the SGE section.
- `api.js` cleared the obsolete helpers (`listPriorityRules`,
  `preemptPlan`, `preemptRun`, `listPendingRequests`, `preemptAutoTick`,
  etc.) and added `listFeaturePriorities`, `upsertFeaturePriority`,
  `deleteFeaturePriority`, `requestFeatureSeat`.

### Testing
- 19/19 backend pytest (new `/app/backend/tests/test_iteration14.py`)
- 7/7 frontend Playwright flows
- Auto-preempt loop confirmed OFF in startup logs
- See `/app/test_reports/iteration_14.json`

### Tech debt deliberately deferred
- The old `/api/priority-rules`, `/api/preempt/*`, `/api/pending-requests/*`,
  `/api/license/request` endpoints are dead code but still in `server.py`.
  Removing them is a separate cleanup PR (no UI consumers remain).
- `server.py` is now 3944 lines. Splitting into `routes/` is overdue.

## Iteration 16 — Input-visibility CSS fix + auto-preempt v2 daemon — 2026-06

**User bug**: Typed text in Priority page inputs (feature, hipri/lopri textareas, request user) was INVISIBLE — `.inp` className referenced by Login/Priority/Settings/etc. was **never defined** in `/app/frontend/src/index.css`, so inputs inherited default browser text color on the dark `#0a0a0a` backgrounds.

**Fix**: Added `.inp` rule + `:focus`, `:disabled`, `::placeholder`, textarea, and select variants in `index.css`. Text now renders in `rgb(243,244,246)` on `rgb(10,10,10)` across the entire app. Latent bug — silently affected Login screen as well.

**User feature request**: Re-enable AUTOMATIC preemption based on the hipri/lopri lists.

**Implementation** — fresh v2 daemon, NO SGE, NO old priority_rules:
- New helpers `_auto_preempt_tick_v2()` + `_auto_preempt_loop_v2()` in `server.py`.
- Walks every `feature_priorities` config every N seconds (settings-driven).
  For each saturated feature where no hipri user holds a seat AND at least
  one lopri user holds → kill the oldest lopri holder via `lmremove`.
- New endpoints:
  - `POST /api/feature-priorities/auto-tick` (admin) — force one iteration on demand
  - `GET  /api/feature-priorities/auto-status` — running/enabled/interval
- Reason codes for skipped (feature, server) pairs: `empty_hipri_or_lopri`,
  `server_missing`, `feature_missing_on_server`, `not_saturated`,
  `hipri_already_holds_seat`, `no_lopri_victim`.
- Frontend:
  - New AUTO-PREEMPT status banner on `/priority` (Activity icon + running/toggle/interval + TICK NOW button)
  - Optional LAST-TICK DIAGNOSTIC card showing RESULTS + SKIP REASONS for self-debugging
  - AUTO-PREEMPT DAEMON panel restored to `/settings` (interval input + toggle + RUN TICK NOW)
- The old SGE / priority_rules / pending_requests endpoints remain dead code (no UI consumers); kept in-file for the cleanup PR.

**Testing**: 12/12 backend + 7/7 frontend in `/app/test_reports/iteration_15.json`. Validated `.inp` color values directly via `page.evaluate(window.getComputedStyle)` and the background loop preempted a freshly-saturated all-lopri config in ~10-30s with interval=10s.

## Iteration 17 — Reservation-aware saturation — 2026-06

**User bug** (real Conformal_Asic case, screenshot attached):
- Feature: `Conformal_Asic`, total=75, lmstat reports 75 IN USE (100%)
- Detail modal: 24 ACTIVE checkouts, 0 RESERVED, 75 REPORTED
- Reality: 51 seats held by FlexLM RESERVE pool for other team(s)
- Auto-preempt panel said "NOT_SATURATED used=24/total=75" → never fired

**Root cause**: both `request_feature_seat()` and `_auto_preempt_tick_v2()`
computed `used` as `sum(count) from db.checkouts` only — they ignored
`feat.in_use_reported` (the authoritative number from `Total of N licenses
in use` in lmstat header) and the `db.reservations` pool.

**Fix** (both `request_feature_seat` and `_auto_preempt_tick_v2`):
```python
used_active   = sum(count for h in db.checkouts)
used_reported = feat.in_use_reported              # from lmstat header
reserved      = sum(count for r in db.reservations)
used          = max(used_active, used_reported, used_active + reserved)
```
This treats the feature as saturated whenever **any** of the three signals
says so. Preempt still targets the oldest visible LOPRI holder (we never
try to kill a RESERVE pool seat because there's no specific user to fire).

**UI surface**:
- Each config row now shows `seats: in_use/total [SAT]` + `free: N · reported
  by lmstat (incl. RESERVE pools)` so admins can see the true utilisation.
- SKIP REASONS panel adds `(active=…, reported=…, reserved=…)` breakdown
  on every `NOT_SATURATED` line so it's obvious which signal triggered.

**Verified**: seeded Conformal_Asic with 23 unknown holders + anushama (lopri)
+ 51 RESERVE pool. Auto-tick now detects saturation and preempts anushama.
After her preempt, /request from a hipri user correctly returns `no_victim`
with full breakdown `seats_active=23, seats_reserved=51, seats_reported=75`.

## Iteration 18 — FALSE-SUCCESS bug fix for lmremove — 2026-06

**User bug (real prod, screenshots attached)**: Priority page said
"PREEMPTED · CADENCE-105 → Conformal_Asic · preempted anushama@…" but the
Control Room live checkouts still showed anushama holding the seat 3
minutes later. ramkella's terminal was looping "Waiting for
Conformal_Asic…". Audit log alternated `WARN AUTO_PREEMPT_V2 · Auto-
released anushama@…` immediately followed by `ERR CHECKOUT_KILL · kill
Conformal_Asic for anushama@… (exit != 0)`.

**Root cause #1 — false-success reporting**: `kill_checkout()` returned
`{"ok": False, ...}` when `lmremove` exited non-zero, **but never raised**.
Both `_auto_preempt_tick_v2` and `request_feature_seat` blindly logged
"PREEMPTED" / "AUTO_PREEMPT_V2" audit lines + appended a success result
**before** inspecting `kr["ok"]`. So the UI claimed victory on every
failed `lmremove`.

**Root cause #2 — hostname mismatch killing lmremove**: the parser
captured FQDNs (`mctl-scs26.moschiptech.com`) but FlexLM's internal
checkout table records the short form (`mctl-scs26`) or vice-versa.
`lmremove` requires exact equality on `feature user host [display]` —
one mismatched field and the daemon rejects with non-zero exit.

**Fixes**:
1. **`kill_checkout` now tries up to 4 variants** per call: each
   permutation of `host_variants = [as-given, short]` × `display_variants
   = ["", as-given]`. Stops at the first exit==0. Returns full
   `attempts[]` trace.
2. **`request_feature_seat`** now checks `kr["ok"]`. On failure:
   - Returns new action `preempt_failed` (HTTP 200, ok=false) with the
     real `exec` output + `attempts[]` array + `message` containing the
     exact lmremove error
   - Logs `PRIORITY_PREEMPT_FAILED` audit (not the success line)
   - Does NOT mark the (server, feature) as actioned
3. **`_auto_preempt_tick_v2`** same change — on failure it now appends an
   `outcome: "preempt_failed"` row (red card in UI, NOT counted toward
   `actioned`) and logs `AUTO_PREEMPT_V2_FAILED` with severity=error. The
   `freed` guard is NOT updated, so the next tick will retry naturally.
4. **Frontend ResultCard** now renders a full failure panel:
   - lmremove attempts table (host tried | display | exit | output)
   - "What to try next" checklist: run lmremove manually from license
     server, check INCLUDE_BORROW, kill the user's process on their host
     (sticky-client case), re-sync the server
5. **Frontend last-tick diag** now styles `preempt_failed` rows in red
   with the lmremove error inline.

**Verified**: forced an SSH failure mode → POST /request returned
`action=preempt_failed, ok=false, attempts=4` with full trace; DB
checkouts NOT deleted (3 holders preserved). Switched back to mock
adapter → success path returned `action=preempted, ok=true` as before.

## Iteration 19 — Implicit LO-PRI (empty list = "everyone not in HI-PRI") — 2026-06

**User request** (after the false-success fix worked, screenshot showed
`SKIP_REASONS · EMPTY_HIPRI_OR_LOPRI` because user wanted to leave lopri
empty): "make sure if low priority is empty then assume it all the users
other then the list from high priority."

**Implementation**:

### Backend
- `_auto_preempt_tick_v2` & `request_feature_seat`:
  - Skip code changed from `not hipri_set or not lopri_set` → `not hipri_set`
    (hipri is the only required list)
  - Victim selection:
    ```python
    if implicit_lopri:                          # lopri_set is empty
        candidates = [h for h in holders
                      if h.user.lower() not in hipri_set]
    else:
        candidates = [h for h in holders
                      if h.user.lower() in lopri_set]
    ```
  - The `hipri_already_holds_seat` guard still wins — if a hipri user
    holds a seat, we never preempt anyone (no friendly fire).
- `upsert_feature_priority` now requires `hipri_users` to be non-empty
  (was: either list could be empty). `lopri_users=[]` is the documented
  "implicit lopri" sentinel.
- New diagnostic fields in `no_victim` / `no_lopri_victim` reasons:
  `implicit_lopri: bool` so the UI can colour the message correctly.

### Frontend
- `UserPills` now accepts an `emptyLabel` prop. The LO-PRI render shows
  `"// empty → implicit: all users not in HI-PRI"` instead of the bare
  `// empty`, so admins know the empty list is meaningful.
- Editor textarea placeholder + help text updated to explain the implicit
  behaviour. Yellow "Leave EMPTY to implicitly treat every non-hipri
  holder as a preempt candidate" callout.
- Save validation tightened to mirror backend: hipri required, lopri optional.

### Verified
- Seeded Conformal_Asic 5/5, hipri=[ramkella], lopri=EMPTY, all holders
  are NOT ramkella → auto-tick correctly preempted oldest non-hipri
  holder (`divakar_ac`); subsequent REQUEST by ramkella preempted next
  (`reshma_mc`); only 3 holders remained.
- Edge case: all 5 seats held by ramkella (hipri) → auto-tick safely
  skipped with `hipri_already_holds_seat`.

## Iteration 20 — Stale-DB double-kill bug (manikant + adityaa) — 2026-06

**User bug** (FlexLM log attached): after `ramkella` (hipri) got the
freed seat by preempting `anushama` at 20:04:09, the loop fired AGAIN
at 20:04:40 and 20:05:11 and killed `manikant` + `adityaa` without
ramkella ever asking for them.

**Root cause** — staleness window between auto-preempt (30s) and
auto-sync (60s): when the loop kills holder X:
1. lmremove succeeds → FlexLM frees the seat → ramkella's queued tool
   immediately claims it (FlexLM side)
2. LICMAN deletes X from db.checkouts but does NOT see ramkella's new
   checkout until the next periodic sync (could be ~50s later)
3. Next loop tick (30s later) → db.checkouts shows 4 stale non-hipri
   holders, no hipri user → `hipri_already_holds_seat` guard misses →
   loop kills ANOTHER non-hipri holder
4. Cycle repeats every interval until enough seats are freed that some
   really do go un-claimed

**Fix** (3 layers of defence):
1. **Per-(server, feature) cooldown** (default 180s, configurable via
   `PREEMPT_COOLDOWN_SECONDS` env var). After a successful preempt,
   the loop and on-demand REQUEST flow block further preempts on that
   `(server, feature)` until the cooldown expires. New skip reason
   `preempt_cooldown` with `cooldown_remaining_sec` field.
2. **Live post-preempt refresh** (`_refresh_checkouts_after_preempt`):
   fire-and-forget task that re-runs `_real_checkouts_via_ssh` for the
   affected server immediately after a successful kill, replacing the
   stale db.checkouts with live FlexLM state. The next tick now sees
   ramkella holding, hits `hipri_already_holds_seat`, and stays put.
3. **Status visibility**: `GET /api/feature-priorities/auto-status`
   now includes `cooldown_sec` and `active_cooldowns[]` so admins can
   see which (server, feature) is on hold and for how long. Status
   banner on the Priority page shows `Cooldown: 180s (N active)`.

**Verified**: re-seeded user's exact scenario (5/5 saturated, hipri=
[ramkella], lopri=[], all holders non-hipri). Tick 1 preempted
anushama (oldest). Tick 2 (immediately) returned actioned=0 with skip
`preempt_cooldown · 179s remaining`. manikant + adityaa untouched. ✓

## Iteration 21 — Stale-DB FALSE PREEMPT (manikant) + ghost-holder cleanup — 2026-06

**User bug** (screenshots show `PREEMPT_FAILED · lmremove: feature/user/host/display not found` for manikant@mctl-scsr23, while the FlexLM log shows ramkella was already holding the seat from 20:47:17):

The iteration-20 cooldown only triggered AFTER a successful preempt. But this scenario has no successful preempt — the loop tried to kill manikant based on stale `db.checkouts` (auto-sync runs every 60s, auto-preempt every 30s), got "not found" because manikant had probably already released and FlexLM had moved on.

**Root cause**: every decision was made on data up to ~60s stale.

**Fix** (three changes, on top of iteration 20 cooldown):

1. **Pre-flight live refresh** for every (unique) server BEFORE the loop scans its configs:
   ```python
   unique_servers = sorted({cfg["server_id"] for cfg in configs})
   await asyncio.gather(
       *[_refresh_server_state(sid) for sid in unique_servers],
       return_exceptions=True,
   )
   ```
   Now the `hipri_already_holds_seat` guard sees ramkella's seat the moment FlexLM does. Auto-loop is never more than ~1 tick stale.

2. **Same pre-flight refresh in the on-demand REQUEST flow** (`request_feature_seat`) — admins clicking REQUEST never get a false-preempt on stale data either.

3. **Ghost-holder cleanup on `lmremove ... not found`**: when lmremove fails because FlexLM doesn't know the (feature, user, host, display) tuple anymore (= the holder already released), the loop now:
   - Deletes the stale row from `db.checkouts` so it doesn't try the same ghost forever
   - Fires a `_refresh_server_state(server_id)` to repopulate with truth
   - Applies a 60s cooldown so the next tick doesn't immediately try ANOTHER ghost on the same feature

**Helper renamed**: `_refresh_checkouts_after_preempt` → `_refresh_server_state` (it's now called BOTH before decisions AND after preempts).

**Verified**:
- Seeded 5/5 saturated, ramkella IS one of the 5 holders → auto-tick skipped with `hipri_already_holds_seat`, manual REQUEST returned `already_holding`. manikant/adityaa SAFE.
- Seeded 5/5 saturated, ramkella NOT in DB → auto-tick preempted oldest (mock mode); second tick immediately → cooldown reason `cadence-prod-01 → Conformal_Asic · 175s remaining`.
- Refresh helper is best-effort; failures are silent (periodic sync catches up).

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
