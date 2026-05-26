# INSTALL.md — flexlm-preempt deployment guide

This guide takes you from `tar xzf` to a fully working priority-preemption
setup in ~10 minutes. **Everything is offline / air-gap friendly** — no
packages downloaded, no internet calls.

---

## 0. Inventory before you start

Collect these from your existing FlexLM setup:

| Item | Example | How to find it |
|------|---------|----------------|
| License server | `5280@licsrv01` | Whatever you set in `LM_LICENSE_FILE` |
| Path to `lmutil` | `/usr/local/flexlm/lmutil` | `which lmutil` |
| Real binary path of each tool you'll wrap | `/opt/cadence/innovus/bin/innovus` | `which innovus` (BEFORE you install the wrapper) |
| Vendor daemon names | `cdslmd`, `snpslmd`, `mgcld` | `lmutil lmstat -a` |
| Feature names | `innovus`, `Genus`, `Virtuoso_L`, `VCS-RuntimeNetlist` | `lmutil lmstat -a` |
| Username of every high-priority user | `ramkella arya sr_team1` | your own org chart |

---

## 1. Extract the tarball

On any one host (e.g. your license server). The tarball is self-contained.

```bash
sudo mkdir -p /opt/flexlm-preempt
sudo tar xzf flexlm-preempt.tar.gz -C /opt/flexlm-preempt --strip-components=1
cd /opt/flexlm-preempt
```

---

## 2. Run the installer

The installer has two modes:

```bash
# On every engineering workstation (or once on the NFS-shared /usr/local/bin)
sudo ./install.sh --workstation

# On the license-server host(s) only
sudo ./install.sh --license-server
```

What `--workstation` does:
- Installs `/usr/local/bin/tool-wrapper` (the generic wrapper)
- Installs `/usr/local/sbin/licman-preempt` (the root sudo helper)
- Installs `/etc/sudoers.d/licman-preempt`
- Creates `/etc/licman/` with example `config.env` and `innovus.priority`
- Creates `/var/log/licman/` with sane perms
- Creates the `priority-users` POSIX group (empty — you add users later)

What `--license-server` does:
- All of the above, **plus** copies the example vendor options files into
  `/etc/licman/opt-examples/` so you can `diff` them against your own.

---

## 3. Customise `/etc/licman/config.env`

This is the ONLY file most sites will edit. It's the source of truth for the
wrapper.

```bash
sudo cp /etc/licman/config.env.example /etc/licman/config.env
sudo vi /etc/licman/config.env
```

Set these:

```bash
# Where lmutil lives
LMUTIL="/usr/local/flexlm/lmutil"

# Your license server (port@host)
LIC="5280@licsrv01"

# Per-tool config: WRAPPER_NAME : FEATURE : REAL_BINARY_PATH
# Add one line per tool you want preemption for. Empty entries are ignored.
declare -A TOOL_MAP=(
  [innovus]="innovus:/opt/cadence/innovus/bin/innovus.real"
  [virtuoso]="Virtuoso_L:/opt/cadence/virtuoso/bin/virtuoso.real"
  [genus]="Genus:/opt/cadence/genus/bin/genus.real"
  [vcs]="VCS-RuntimeNetlist:/opt/synopsys/vcs/bin/vcs.real"
  [calibre]="Calibre_DRC:/opt/mentor/calibre/bin/calibre.real"
)

# Settle time (sec) after lmremove before launching real binary
SETTLE_SEC=3

# Wrapper log
LOG="/var/log/licman/wrapper.log"
```

### What "REAL binary" means

You can't have `/usr/local/bin/innovus` (wrapper) AND `/opt/.../innovus` (real)
both in `PATH` — the wrapper would loop. So:

1. Rename the real binary once: `sudo mv /opt/cadence/innovus/bin/innovus /opt/cadence/innovus/bin/innovus.real`
2. Reference `innovus.real` in `config.env`
3. The wrapper at `/usr/local/bin/innovus` calls `/opt/cadence/innovus/bin/innovus.real`

This rename is a **one-time** step. Vendor patches usually preserve `.real`
suffixes; if you're nervous, use a symlink instead:
```bash
sudo ln -s /opt/cadence/innovus/bin/innovus /opt/cadence/innovus/bin/innovus.real
```
and then move the wrapper somewhere PATH-precedent (see Step 4).

---

## 4. Create the per-tool wrapper symlinks

The wrapper looks up its own name (`$0`) and finds the matching entry in
`TOOL_MAP`. So you just symlink:

```bash
sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/innovus
sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/virtuoso
sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/genus
sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/vcs
sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/calibre
```

Make sure `/usr/local/bin` comes **before** the vendor's bin dir in every
engineer's `PATH`:
```bash
echo 'export PATH=/usr/local/bin:$PATH' | sudo tee /etc/profile.d/licman.sh
```

---

## 5. List your high-priority users

One file per feature. Username per line. No commas, no quotes.

```bash
sudo tee /etc/licman/innovus.priority <<EOF
ramkella
arya
sr_team1
EOF

sudo tee /etc/licman/Virtuoso_L.priority <<EOF
ramkella
arya
EOF

sudo tee /etc/licman/Genus.priority <<EOF
arya
sr_team1
EOF
```

> **Note** — the filename is the **FEATURE** name (case-sensitive, matching
> `lmutil lmstat -a`), not the wrapper name. So Cadence `Virtuoso_L` →
> `/etc/licman/Virtuoso_L.priority`.

---

## 6. Add users to the `priority-users` POSIX group

This unlocks `sudo /usr/local/sbin/licman-preempt` for them without a
password. Sudoers config is already installed by `install.sh`.

```bash
sudo usermod -aG priority-users ramkella
sudo usermod -aG priority-users arya
sudo usermod -aG priority-users sr_team1
```

Users must log out / log back in for the group to take effect.

---

## 7. (Recommended) Drop a vendor options file in place

The wrapper does NOT require this — `MAX` and `TIMEOUTALL` are belt-and-braces.

### Cadence
```bash
sudo cp /etc/licman/opt-examples/cdslmd.opt /opt/cadence/lic/cdslmd.opt
sudo vi /opt/cadence/lic/cdslmd.opt   # edit GROUP memberships
```
Reference it in your `license.dat`:
```
VENDOR cdslmd OPTIONS=/opt/cadence/lic/cdslmd.opt
```
Reread without restart:
```bash
sudo -u licadmin /usr/local/flexlm/lmutil lmreread -c 5280@licsrv01 -vendor cdslmd
```

### Synopsys
```bash
sudo cp /etc/licman/opt-examples/snpslmd.opt /opt/synopsys/lic/snpslmd.opt
# reference in license.dat:  VENDOR snpslmd OPTIONS=/opt/synopsys/lic/snpslmd.opt
sudo -u licadmin /usr/local/flexlm/lmutil lmreread -c 27000@licsrv02 -vendor snpslmd
```

### Mentor / Siemens
```bash
sudo cp /etc/licman/opt-examples/mgcld.opt /opt/mentor/lic/mgcld.opt
# reference in license.dat:  VENDOR mgcld OPTIONS=/opt/mentor/lic/mgcld.opt
sudo -u licadmin /usr/local/flexlm/lmutil lmreread -c 1717@licsrv03 -vendor mgcld
```

---

## 8. Smoke test

```bash
# 1. As a low-priority user, take the seat
sudo -u junior_b -i innovus &
sleep 5
lmutil lmstat -c 5280@licsrv01 -f innovus
#   → "1 license in use" by junior_b

# 2. As a priority user, try to launch innovus
sudo -u ramkella -i innovus
#   → wrapper log shows "preempting junior_b@<host>"
#   → junior_b's Innovus dies within seconds
#   → ramkella's Innovus starts normally

# 3. Confirm
tail -n 10 /var/log/licman/wrapper.log
lmutil lmstat -c 5280@licsrv01 -f innovus
#   → now held by ramkella
```

If step 2 fails with *"sudo: a password is required"*, the user isn't in the
`priority-users` group yet — see Step 6.

If step 2 logs *"lmremove: permission denied"*, your FlexLM admin is locked
down to a specific host. Move the `licman-preempt` invocation to the license
server via passwordless SSH — see **Gotcha #2** below.

---

## Customisation cheatsheet

| You want to… | Change |
|---|---|
| Add a new tool | 1) Add a line to `TOOL_MAP` in `/etc/licman/config.env`. 2) `sudo ln -sf /usr/local/bin/tool-wrapper /usr/local/bin/<toolname>`. 3) Create `/etc/licman/<feature>.priority`. |
| Promote a user | `sudo usermod -aG priority-users alice` AND add `alice` to `/etc/licman/<feature>.priority` for every feature they need preemption on. |
| Demote a user | Remove from `/etc/licman/<feature>.priority`. Their wrapper still works, just won't preempt. |
| Change license server | Edit `LIC=` in `/etc/licman/config.env`. No restart needed. |
| Disable preemption for a feature | `sudo mv /etc/licman/innovus.priority /etc/licman/innovus.priority.disabled`. Wrapper still launches the tool, just never preempts. |
| Have B refuse to launch when A is waiting | Set `BACK_OFF_FOR_PRIORITY=1` in `config.env`. Wrapper for non-priority users will check `/var/lib/licman/<feature>.waiting` and exit with code 2 if a priority user is currently waiting. |
| Use SSH-to-license-server instead of local sudo | Edit `PREEMPT_VIA_SSH=licadmin@licsrv01` in `config.env`. Wrapper will run the helper over SSH instead of `sudo` locally. Key-based auth required. |

---

## Gotchas (read before you ship)

### #1  Vendor patches replace the real binary

When Cadence/Synopsys ship a tool update, their installer overwrites
`/opt/cadence/innovus/bin/innovus`. If you renamed it to `innovus.real`,
the patch will recreate the un-suffixed file. Two safe patterns:

**Pattern A — Symlink instead of rename**
```bash
sudo ln -s /opt/cadence/innovus/bin/innovus /opt/cadence/innovus/bin/innovus.real
```
Patches preserve the symlink target.

**Pattern B — Drop wrapper in a dir that vendors don't touch**
Leave `/opt/cadence/...` alone. Put wrappers in `/opt/licman-wrappers/bin/`
and prepend it to PATH. Less invasive but every engineer needs the PATH change.

### #2  `lmremove` from non-admin host

By default, `lmutil lmremove` will be rejected when invoked from a workstation
unless the workstation user is the seat owner OR is listed in vendor
`EXCLUDE`/`INCLUDE_BORROW` ACLs. The safest fix: **run the helper on the
license server itself** via passwordless SSH.

```bash
# In /etc/licman/config.env
PREEMPT_VIA_SSH="licadmin@licsrv01"

# On the license server, install the helper too:
sudo ./install.sh --license-server

# Set up key auth from every workstation → licsrv01 as licadmin
# (one ed25519 key in /etc/licman/preempt.key, mode 0600, deployed via your
#  config-mgmt tool of choice)
```

The wrapper then runs:
```bash
ssh -i /etc/licman/preempt.key licadmin@licsrv01 \
    sudo /usr/local/sbin/licman-preempt innovus junior_b wks-jdev2
```

### #3  `TIMEOUTALL` cannot be smaller than 7200 sec (2 h) for some vendors

Cadence honours `TIMEOUTALL 3600` (1 h). Synopsys silently caps it at 7200.
Mentor sometimes ignores it entirely. **Don't rely on `TIMEOUTALL` for
preemption** — it's only a safety net for forgotten interactive sessions.

### #4  Wrapper detects saturation; queueing is your problem

If A launches innovus while B has it AND there's no lower-priority victim
(e.g. another priority user owns the seat), the wrapper logs
*"no low-priority victim available"* and `exec`s the real binary anyway.
The real binary will then fail with FlexLM error -4 (licensed number of
users already reached). That's correct behaviour — FlexLM tells A to retry,
which preserves first-come ordering among equal-priority users.

If you want A to wait/retry instead of erroring, wrap the wrapper:
```bash
while ! innovus_wrapper_check; do
  sleep 10
done
exec innovus "$@"
```

### #5  X11 display column in `lmstat`

Some FlexLM versions emit the user's `:0.0` display in the 3rd column instead
of the hostname. The wrapper handles both. If your lmstat output is weirder
than usual (e.g. IPv6 brackets, FQDNs with dots in the hostname), run
`lmutil lmstat -c $LIC -f $FEATURE` and paste the output — you may need to
tweak the parser regex at the top of `tool-wrapper`.

### #6  Wrapper as setuid root — DO NOT

It's tempting to skip the sudo helper by making the wrapper setuid root.
Don't. The wrapper inherits user environment ($DISPLAY, $LD_LIBRARY_PATH,
$CDSROOT etc.) and a setuid bash is a known privilege-escalation vector.
Keep the privileged surface to the 30-line `licman-preempt` helper.

---

## Uninstall

```bash
sudo rm -f /usr/local/bin/{tool-wrapper,innovus,virtuoso,genus,vcs,calibre}
sudo rm -f /usr/local/sbin/licman-preempt
sudo rm -f /etc/sudoers.d/licman-preempt
sudo rm -rf /etc/licman /var/log/licman
sudo groupdel priority-users 2>/dev/null || true
# rename the real binaries back if you used the .real pattern
sudo mv /opt/cadence/innovus/bin/innovus.real /opt/cadence/innovus/bin/innovus
```
