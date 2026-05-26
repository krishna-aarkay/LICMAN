# ARCHITECTURE.md — why this bundle looks the way it does

## The fundamental FlexLM constraint

FlexLM checkouts are **stateful and sticky**. When a client process opens a
TCP connection to the vendor daemon and successfully checks out a feature,
the daemon writes the (feature, user, host, display, pid-like handle) tuple
into its in-memory table. That table is the **only** source of truth — any
"priority" you imagine layering on top must, in the end, mutate that table.

The vendor options file (`*.opt`) is consulted **only at checkout time**.
Once a seat is granted, no rule in any options file can take it back. This
is why every directive in the table below is static:

| Directive | Evaluated when | Can revoke after grant? |
|---|---|---|
| `INCLUDE` / `EXCLUDE` | Checkout attempt | No |
| `RESERVE` | Checkout attempt | No |
| `MAX` | Checkout attempt | No |
| `GROUP` / `HOST_GROUP` | Reference resolution | No |
| `TIMEOUTALL` | Idle-detection loop (passive) | Only after N sec of inactivity |
| `BORROW_LOWWATER` | Checkout attempt | No |

The **only** vendor-supplied way to mutate the table at runtime is:
```
lmutil lmremove [-c port@host] feature user host [display]
```

Therefore on-demand preemption = wrapper script + lmremove. There is no
way around this short of paying Flexera for FNE / Flex Enterprise.

## Why lmremove needs root (or admin context)

`lmremove` is gated by the vendor daemon, which checks the request against:

1. Is the caller the seat owner? → allow self-remove
2. Is the caller in `EXCLUDE` for `lmremove`? → deny
3. Is the caller running on the host listed as `SERVER`/`DAEMON` admin? → allow
4. Otherwise → deny

Regular engineers fall through to case 4. Three workable patterns:

| Pattern | Pros | Cons |
|---|---|---|
| **sudo helper on workstation** | Simple, no SSH | Only works if license server treats workstations as admin (uncommon) |
| **SSH to license server** | Always works | Need key auth, group-readable private key |
| **Daemon on license server** | Most robust | Adds a service to manage |

This bundle ships **sudo helper + optional SSH fallback**. Pick the one that
matches your FlexLM ACL.

## Why a single wrapper script with symlinks

Every Cadence/Synopsys/Mentor tool needs the same logic:
1. Look up the feature name
2. Run `lmstat -f <feature>`
3. If saturated and I'm priority, preempt a non-priority holder
4. `exec` the real binary

Duplicating that script per tool means every bug-fix touches 8 files.
Instead, `tool-wrapper` reads `$0` (basename) and resolves the feature +
real-binary path from `/etc/licman/config.env`. One file to audit, one
file to patch.

## Why `exec` (not `&` or `nohup`)

`exec` replaces the wrapper process with the real binary. This gives you:

- Correct signal propagation (Ctrl-C kills the tool, not just the wrapper)
- Correct `getppid()` for tools that introspect their parent
- Correct exit code (the user sees the tool's exit code, not the wrapper's)
- Wrapper does not appear in `ps` after launch

The only thing the wrapper does AFTER it would `exec` is clean up the wait
flag — but that's done via `trap EXIT` registered before `exec`, which bash
fires *before* the exec actually happens.

## Why `lmstat -f <feature>` not `lmstat -a`

`lmstat -a` parses thousands of lines for vendors with large feature sets.
`lmstat -f <feature>` is 10-50× faster and atomic (no risk of seeing a
partial picture during another checkout). On a saturated daemon this matters
— the wrapper must complete in <1s to feel snappy to engineers.

## Why one priority list per feature

Real EDA shops have feature-specific priorities. `ramkella` may be priority
for `Innovus` (tape-out work) but NOT for `Virtuoso_L` (interactive schematic
editing — first come, first served). Storing one list per feature lets you
express this without inventing a tag system:

```
/etc/licman/innovus.priority    → ramkella arya
/etc/licman/Virtuoso_L.priority → arya
/etc/licman/Genus.priority      → arya sr_team1
```

## Why no daemon

A daemon would buy you:
- Centralised audit log
- Cross-host coordination (e.g. avoid double-preempt)
- Web UI

It would cost you:
- A service to monitor
- A failure mode where the daemon dies and preemption silently stops
- A network dependency on the daemon's listener

Engineers running tools is already a "polling" event — the wrapper IS the
trigger. There's nothing for a daemon to wait on. Skip the daemon.

## What about race conditions?

Yes, two priority users launching the same tool simultaneously can both
decide to preempt. In the worst case both call `lmremove` on the same
victim — the second call gets *"no such checkout"* from FlexLM, which the
helper exits non-zero on, the wrapper logs *"sudo-preempt failed"* and
falls through. The real binary then competes for the freed seat normally.
Net effect: one preempt, one priority user wins, the other queues. The
victim is fired regardless. This is the correct behaviour.

If you need tighter coordination, switch to the `PREEMPT_VIA_SSH` mode and
have the SSH target serialize calls with `flock /var/lock/licman.preempt`.
