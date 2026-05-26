# flexlm-preempt — pure-FlexLM priority preemption

**Zero web app. Zero SGE. Zero external network.** Just a vendor options file
+ one wrapper script that any user runs in place of their EDA tool. When a
high-priority user launches a tool whose feature is saturated, the wrapper
yanks the lowest-priority holder's seat via `lmutil lmremove` and then
launches the real binary.

This is what FlexLM cannot do natively — every options-file directive
(`RESERVE`, `INCLUDE`, `MAX`, `TIMEOUTALL`) is *static*. Real on-demand
preemption requires `lmremove` triggered by a script. This bundle is that
script, productionised.

## Why this works

| Layer | What it does |
|---|---|
| **Vendor options file** | Defines `GROUP hipri / lopri`, optional `MAX` cap, `TIMEOUTALL` safety net |
| **Wrapper (`tool-wrapper`)** | Drop-in replacement for `innovus`, `virtuoso`, `vcs`, etc. Detects saturation, kicks a low-priority holder, then `exec`s the real binary |
| **sudo helper (`licman-preempt`)** | Only piece that runs as root — validates args and calls `lmutil lmremove`. Required because regular users can't remove other users' seats |
| **Priority list (`/etc/licman/<feature>.priority`)** | One username per line. Edit anytime, no daemon restart |

## How preemption fires (example)

1. user `junior_b` runs `innovus` → wrapper sees feature free → `exec` real innovus → 1/1 seat in use
2. user `ramkella` (in `/etc/licman/innovus.priority`) runs `innovus` 5 minutes later
3. wrapper runs `lmstat -f innovus` → sees `used=1 total=1` (saturated)
4. wrapper finds `junior_b` is **not** in the priority file → calls `sudo /usr/local/sbin/licman-preempt innovus junior_b wks-jdev2`
5. helper runs `lmutil lmremove -c 5280@licsrv01 innovus junior_b wks-jdev2` → seat is freed
6. wrapper sleeps 3 s (FlexLM settle) → `exec` real innovus → `ramkella` is now holder
7. `junior_b`'s Innovus dies with *"Lost license"* within ~30 s and can be relaunched (it'll queue / fail until a seat is free)

## What's in the box

```
flexlm-preempt/
├── README.md              ← this file
├── INSTALL.md             ← step-by-step deployment + customisation
├── install.sh             ← one-shot installer (run as root)
├── config.env.example     ← central config (copy → /etc/licman/config.env, edit)
├── bin/
│   └── tool-wrapper       ← the generic wrapper (one script, many symlinks)
├── sbin/
│   └── licman-preempt     ← root-only lmremove helper
├── etc/
│   ├── licman/
│   │   ├── config.env.example
│   │   └── innovus.priority.example
│   └── sudoers.d/
│       └── licman-preempt
├── opt/lic-examples/
│   ├── cdslmd.opt         ← Cadence vendor options
│   ├── snpslmd.opt        ← Synopsys vendor options
│   └── mgcld.opt          ← Mentor/Siemens vendor options
└── docs/
    └── ARCHITECTURE.md    ← FlexLM internals, why we need lmremove, sudo
```

## Requirements

- RHEL 9 / 10 (or any glibc Linux with bash 4+, awk, grep)
- `lmutil` from the vendor FlexLM bundle, reachable at the path you set
- Passwordless `sudo` for priority users → see `etc/sudoers.d/licman-preempt`
- Wrapper installed on every workstation (NFS-shared `/usr/local/bin` is easiest)

## Quick start

```bash
tar xzf flexlm-preempt.tar.gz
cd flexlm-preempt
sudo ./install.sh --workstation        # on every engineer's box
sudo ./install.sh --license-server     # on the license host(s) only
```

Then edit `/etc/licman/config.env` and `/etc/licman/innovus.priority` and you're done.

See **INSTALL.md** for the full walk-through, including how to wire the
wrapper for `virtuoso`, `genus`, `vcs`, `calibre`, and how to test it.
