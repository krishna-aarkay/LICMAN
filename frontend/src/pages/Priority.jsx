import { useEffect, useMemo, useState } from "react";
import {
  Crown, Plus, Trash2, Save, Edit3, Zap, X, RefreshCw,
  AlertTriangle, CheckCircle2, ShieldAlert,
} from "lucide-react";
import { api } from "@/lib/api";
import Header from "@/components/Header";
import { toast } from "sonner";

/**
 * Priority Dashboard v2 — pure username-based.
 * One config row per (server, feature). Each row has two flat user lists:
 *   - HIGH-PRIORITY  → may trigger preemption
 *   - LOW-PRIORITY   → may be preempted
 * Preemption is on-demand: an admin enters a hipri user + feature and clicks
 * REQUEST. Backend kills the oldest lopri holder via lmremove and returns
 * the action taken. No background daemon, no SGE.
 */

const emptyForm = {
  id: null,
  server_id: "",
  feature: "",
  hipri_users: "",   // comma/newline-separated in the form, normalised on save
  lopri_users: "",
};

const parseUserList = (s) =>
  (s || "")
    .split(/[\s,]+/)
    .map((x) => x.trim())
    .filter(Boolean);

export default function Priority() {
  const [configs, setConfigs] = useState([]);
  const [servers, setServers] = useState([]);
  const [editing, setEditing] = useState(null); // null | "new" | row obj
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);

  // REQUEST panel state
  const [reqServer, setReqServer] = useState("");
  const [reqFeature, setReqFeature] = useState("");
  const [reqUser, setReqUser] = useState("");
  const [reqResult, setReqResult] = useState(null);
  const [requesting, setRequesting] = useState(false);

  const load = async () => {
    try {
      const [cfgs, srvs] = await Promise.all([
        api.listFeaturePriorities(),
        api.listServers(),
      ]);
      setConfigs(cfgs);
      setServers(srvs);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load priority configs");
    }
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 15000); // light polling so checkout counts stay live
    return () => clearInterval(t);
  }, []);

  // Lookup helpers
  const serverById = useMemo(
    () => Object.fromEntries(servers.map((s) => [s.id, s])),
    [servers],
  );
  const featuresForServer = (sid) =>
    serverById[sid]?.features?.map((f) => f.name) || [];

  // ----------------------------------------------------------------------
  // Edit / save / delete
  // ----------------------------------------------------------------------
  const startNew = () => {
    setEditing("new");
    setForm({ ...emptyForm, server_id: servers[0]?.id || "" });
  };

  const startEdit = (row) => {
    setEditing(row);
    setForm({
      id: row.id,
      server_id: row.server_id,
      feature: row.feature,
      hipri_users: (row.hipri_users || []).join(", "),
      lopri_users: (row.lopri_users || []).join(", "),
    });
  };

  const cancelEdit = () => {
    setEditing(null);
    setForm(emptyForm);
  };

  const save = async () => {
    if (!form.server_id) return toast.error("Pick a server");
    if (!form.feature?.trim()) return toast.error("Pick a feature");
    const hipri = parseUserList(form.hipri_users);
    const lopri = parseUserList(form.lopri_users);
    if (!hipri.length) {
      return toast.error(
        "HIGH-PRIORITY list cannot be empty. Add at least one user who may trigger preemption.",
      );
    }
    setSaving(true);
    try {
      await api.upsertFeaturePriority({
        server_id: form.server_id,
        feature: form.feature.trim(),
        hipri_users: hipri,
        lopri_users: lopri,
      });
      toast.success(`Saved priority for ${form.feature}`);
      cancelEdit();
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (row) => {
    if (!window.confirm(`Delete priority config for "${row.feature}"?`)) return;
    try {
      await api.deleteFeaturePriority(row.id);
      toast.success(`Deleted priority for ${row.feature}`);
      await load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  // ----------------------------------------------------------------------
  // REQUEST flow
  // ----------------------------------------------------------------------
  const submitRequest = async () => {
    if (!reqServer || !reqFeature || !reqUser.trim()) {
      return toast.error("Server, feature and user are required");
    }
    setRequesting(true);
    setReqResult(null);
    try {
      const r = await api.requestFeatureSeat({
        server_id: reqServer,
        feature: reqFeature,
        user: reqUser.trim(),
      });
      setReqResult(r);
      if (r.action === "preempted") {
        toast.success(`Preempted ${r.preempted_user}@${r.preempted_host}`);
      } else if (r.action === "available") {
        toast.success("Seat available — no preempt needed");
      } else if (r.action === "already_holding") {
        toast.info(`${reqUser} already holds a seat`);
      } else if (r.action === "no_victim") {
        toast.warning("Saturated — no low-priority holder to preempt");
      }
      await load();
    } catch (e) {
      const detail = e?.response?.data?.detail || "Request failed";
      setReqResult({ ok: false, action: "error", message: detail });
      toast.error(detail);
    } finally {
      setRequesting(false);
    }
  };

  // Pre-fill request feature dropdown when configs exist
  const reqFeatureOptions =
    configs
      .filter((c) => !reqServer || c.server_id === reqServer)
      .map((c) => ({
        server_id: c.server_id,
        server_name: serverById[c.server_id]?.name || "—",
        feature: c.feature,
      }));

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="priority-page">
      <Header />
      <main className="max-w-7xl mx-auto px-4 sm:px-6 py-6 space-y-6">
        {/* ─────────── Page title ─────────── */}
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.35em] text-[#6b7280]">
              /// PRIORITY
            </div>
            <h1
              className="text-3xl font-bold flex items-center gap-2 mt-1"
              data-testid="priority-title"
            >
              <Crown size={22} className="text-amber-400" />
              Per-Feature Priority Groups
            </h1>
            <p className="text-[#9ca3af] font-mono text-xs mt-1.5">
              Username-based. Two groups per feature: HIGH-PRIORITY (may
              preempt) and LOW-PRIORITY (may be preempted). Triggered on
              demand from the REQUEST panel — no background daemon, no SGE.
            </p>
          </div>
          <button
            onClick={startNew}
            className="btn-brutal primary flex items-center gap-1.5"
            data-testid="add-feature-priority-btn"
          >
            <Plus size={12} /> ADD FEATURE
          </button>
        </div>

        {/* ─────────── Design statement banner ─────────── */}
        <section
          className="bg-[#111] border border-[#222] rounded-sm px-4 py-3 font-mono text-[11px]"
          data-testid="design-statement-banner"
        >
          <div className="flex items-start gap-2">
            <Crown size={13} className="text-amber-400 mt-0.5 shrink-0" />
            <div className="text-[#9ca3af] leading-relaxed">
              <span className="text-amber-400 uppercase tracking-[0.2em] text-[10px]">
                REQUEST-DRIVEN
              </span>{" "}
              · Preemption fires ONLY when a HIGH-PRIORITY user clicks
              REQUEST below. There is no background daemon scanning
              saturated features — if no hipri user is asking, all current
              holders keep their seats untouched.
            </div>
          </div>
        </section>

        {/* ─────────── REQUEST LICENSE panel ─────────── */}
        <section
          className="bg-[#111] border border-[#222] rounded-sm"
          data-testid="request-license-panel"
        >
          <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2">
            <Zap size={14} className="text-emerald-400" />
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              REQUEST LICENSE
            </div>
            <span className="font-mono text-[11px] text-[#6b7280]">
              · enter a HIPRI user + feature · backend preempts a lopri holder
              and returns the action
            </span>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-5 gap-3 font-mono text-xs">
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
                Server *
              </div>
              <select
                value={reqServer}
                onChange={(e) => {
                  setReqServer(e.target.value);
                  setReqFeature("");
                }}
                className="inp"
                data-testid="req-server"
              >
                <option value="">— pick server —</option>
                {servers.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
                Feature *
              </div>
              <select
                value={reqFeature}
                onChange={(e) => setReqFeature(e.target.value)}
                className="inp"
                data-testid="req-feature"
              >
                <option value="">— pick feature —</option>
                {reqFeatureOptions.map((o) => (
                  <option key={`${o.server_id}:${o.feature}`} value={o.feature}>
                    {o.feature} {o.server_id !== reqServer ? `· ${o.server_name}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
                Requesting user *
              </div>
              <input
                value={reqUser}
                onChange={(e) => setReqUser(e.target.value)}
                placeholder="ramkella"
                className="inp"
                data-testid="req-user"
              />
            </div>
            <div className="md:col-span-2 flex items-end">
              <button
                onClick={submitRequest}
                disabled={requesting}
                className="btn-brutal primary flex items-center gap-1.5 w-full justify-center disabled:opacity-50"
                data-testid="submit-request-btn"
              >
                <Zap size={12} /> {requesting ? "REQUESTING…" : "REQUEST"}
              </button>
            </div>
          </div>
          {reqResult && (
            <div
              className="border-t border-[#222] p-4"
              data-testid="request-result-card"
            >
              <ResultCard r={reqResult} />
            </div>
          )}
          <div className="px-4 pb-3 text-[10px] font-mono text-[#6b7280]">
            <code className="text-emerald-400">available</code> · seats free, just check out.{" "}
            <code className="text-emerald-400">preempted</code> · we killed a lopri holder.{" "}
            <code className="text-amber-400">no_victim</code> · saturated but no lopri to kill.{" "}
            <code className="text-red-400">not in hipri</code> · 403 — requester isn&apos;t configured.
          </div>
        </section>

        {/* ─────────── CONFIG ROWS ─────────── */}
        <section
          className="bg-[#111] border border-[#222] rounded-sm"
          data-testid="priority-configs-section"
        >
          <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2">
            <Crown size={14} className="text-amber-400" />
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              FEATURE PRIORITY CONFIGS [{configs.length}]
            </div>
            <button
              onClick={load}
              className="ml-auto btn-brutal flex items-center gap-1"
              data-testid="reload-configs-btn"
              title="Reload"
            >
              <RefreshCw size={11} />
            </button>
          </div>

          {configs.length === 0 && !editing && (
            <div className="px-4 py-10 text-center text-[#6b7280] font-mono text-xs">
              {"// no per-feature priority configs yet — click ADD FEATURE to create one"}
            </div>
          )}

          <div className="divide-y divide-[#1a1a1a]">
            {configs.map((c) => (
              <ConfigRow
                key={c.id}
                row={c}
                server={serverById[c.server_id]}
                onEdit={() => startEdit(c)}
                onDelete={() => remove(c)}
                onQuickRequest={(user) => {
                  setReqServer(c.server_id);
                  setReqFeature(c.feature);
                  setReqUser(user);
                  // scroll to top
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            ))}
          </div>
        </section>

        {/* ─────────── EDITOR ─────────── */}
        {editing && (
          <section
            className="bg-[#111] border border-amber-700/40 rounded-sm"
            data-testid="priority-editor"
          >
            <div className="px-4 py-3 border-b border-amber-700/40 flex items-center gap-2">
              <Edit3 size={14} className="text-amber-400" />
              <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-amber-400">
                {editing === "new" ? "NEW FEATURE PRIORITY" : `EDIT · ${form.feature}`}
              </div>
              <button
                onClick={cancelEdit}
                className="ml-auto text-[#6b7280] hover:text-white"
                data-testid="close-editor"
                aria-label="Close editor"
              >
                <X size={14} />
              </button>
            </div>
            <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
                  Server
                </div>
                <select
                  value={form.server_id}
                  onChange={(e) =>
                    setForm({ ...form, server_id: e.target.value, feature: "" })
                  }
                  className="inp"
                  data-testid="edit-server"
                  disabled={editing !== "new"}
                >
                  <option value="">— pick server —</option>
                  {servers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
                  Feature (FlexLM name, case-sensitive)
                </div>
                <input
                  value={form.feature}
                  onChange={(e) => setForm({ ...form, feature: e.target.value })}
                  list={`feat-list-${form.server_id}`}
                  className="inp"
                  placeholder="Innovus"
                  data-testid="edit-feature"
                  disabled={editing !== "new"}
                />
                <datalist id={`feat-list-${form.server_id}`}>
                  {featuresForServer(form.server_id).map((f) => (
                    <option key={f} value={f} />
                  ))}
                </datalist>
              </div>
              <div className="md:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.2em] text-emerald-400 mb-1 flex items-center gap-1">
                  <Crown size={11} /> HIGH-PRIORITY users
                </div>
                <textarea
                  value={form.hipri_users}
                  onChange={(e) => setForm({ ...form, hipri_users: e.target.value })}
                  rows={3}
                  placeholder="ramkella, arya, sr_team1"
                  className="inp font-mono"
                  data-testid="edit-hipri"
                />
                <div className="text-[10px] text-[#6b7280] mt-1">
                  Comma- or whitespace-separated. These users may trigger
                  preemption of low-priority holders via the REQUEST panel.
                </div>
              </div>
              <div className="md:col-span-2">
                <div className="text-[10px] uppercase tracking-[0.2em] text-red-400 mb-1 flex items-center gap-1">
                  <ShieldAlert size={11} /> LOW-PRIORITY users
                </div>
                <textarea
                  value={form.lopri_users}
                  onChange={(e) => setForm({ ...form, lopri_users: e.target.value })}
                  rows={3}
                  placeholder="junior1, junior2, intern_b   (or leave EMPTY to mean: anyone not in HI-PRI)"
                  className="inp font-mono"
                  data-testid="edit-lopri"
                />
                <div className="text-[10px] text-[#6b7280] mt-1">
                  These users&apos; checkouts will be killed (via lmremove)
                  when a high-priority user requests this feature and seats
                  are full.{" "}
                  <span className="text-amber-400">
                    Leave EMPTY to implicitly treat every non-hipri holder as
                    a preempt candidate
                  </span>{" "}
                  — useful when you want hipri users to always win without
                  enumerating the whole rest of the org.
                </div>
              </div>
              <div className="md:col-span-2 flex justify-end gap-2 pt-1">
                <button
                  onClick={cancelEdit}
                  className="btn-brutal"
                  data-testid="cancel-edit-btn"
                >
                  CANCEL
                </button>
                <button
                  onClick={save}
                  disabled={saving}
                  className="btn-brutal primary flex items-center gap-1.5 disabled:opacity-50"
                  data-testid="save-edit-btn"
                >
                  <Save size={12} /> {saving ? "SAVING…" : "SAVE"}
                </button>
              </div>
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────
function ConfigRow({ row, server, onEdit, onDelete, onQuickRequest }) {
  const feat = server?.features?.find((f) => f.name === row.feature);
  const total = feat?.total ?? 0;
  const inUse = feat?.in_use_reported ?? 0;
  const free = Math.max(0, total - inUse);
  const isSat = total > 0 && inUse >= total;
  return (
    <div
      className="px-4 py-3 hover:bg-[#0e0e0e] grid grid-cols-1 md:grid-cols-12 gap-3 items-start"
      data-testid={`config-row-${row.id}`}
    >
      <div className="md:col-span-3">
        <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b7280]">
          {server?.name || "— unknown server —"}
        </div>
        <div className="font-mono text-white text-sm mt-0.5">{row.feature}</div>
        <div className="font-mono text-[10px] text-[#9ca3af] mt-1 space-y-0.5">
          <div>
            seats:{" "}
            <span className={`tabular-nums ${isSat ? "text-red-400" : "text-emerald-400"}`}>
              {inUse}/{total}
            </span>
            {isSat && (
              <span className="ml-1.5 text-red-400 text-[9px] uppercase">SAT</span>
            )}
          </div>
          <div>
            free: <span className="text-white tabular-nums">{free}</span>
            <span className="text-[#6b7280]"> · reported by lmstat (incl. RESERVE pools)</span>
          </div>
        </div>
      </div>
      <div className="md:col-span-4">
        <UserPills
          label="HI-PRI"
          color="emerald"
          users={row.hipri_users}
          onClick={onQuickRequest}
        />
      </div>
      <div className="md:col-span-4">
        <UserPills
          label="LO-PRI"
          color="red"
          users={row.lopri_users}
          emptyLabel="// empty → implicit: all users not in HI-PRI"
        />
      </div>
      <div className="md:col-span-1 flex md:justify-end gap-1.5">
        <button
          onClick={onEdit}
          className="btn-brutal flex items-center gap-1 text-[10px] py-1"
          data-testid={`edit-config-${row.id}`}
          title="Edit"
        >
          <Edit3 size={11} />
        </button>
        <button
          onClick={onDelete}
          className="btn-brutal flex items-center gap-1 text-[10px] py-1 hover:border-red-500 hover:text-red-400"
          data-testid={`delete-config-${row.id}`}
          title="Delete"
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
}

function UserPills({ label, color, users, onClick, emptyLabel }) {
  const palette = {
    emerald: { border: "border-emerald-700/40", text: "text-emerald-400", bg: "hover:bg-emerald-900/20" },
    red: { border: "border-red-700/40", text: "text-red-400", bg: "hover:bg-red-900/20" },
  }[color];
  return (
    <div>
      <div className={`font-mono text-[9px] uppercase tracking-[0.25em] ${palette.text} mb-1`}>
        {label} [{(users || []).length}]
      </div>
      {(users || []).length === 0 ? (
        <div className="font-mono text-[10px] text-[#6b7280] italic">
          {emptyLabel || "// empty"}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1">
          {users.map((u) => (
            <button
              key={u}
              onClick={() => onClick && onClick(u)}
              className={`font-mono text-[10px] px-2 py-0.5 border ${palette.border} ${palette.text} ${palette.bg} ${onClick ? "cursor-pointer" : "cursor-default"}`}
              data-testid={`pill-${label.toLowerCase()}-${u}`}
              title={onClick ? `Quick-fill REQUEST for ${u}` : ""}
              disabled={!onClick}
              type="button"
            >
              {u}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultCard({ r }) {
  if (!r) return null;
  const tone =
    r.action === "preempted" || r.action === "available" || r.action === "already_holding"
      ? "emerald"
      : r.action === "no_victim"
      ? "amber"
      : "red";
  const Icon =
    tone === "emerald" ? CheckCircle2 : tone === "amber" ? AlertTriangle : ShieldAlert;
  const palette = {
    emerald: { border: "border-emerald-700/40", text: "text-emerald-400", bg: "bg-emerald-900/10" },
    amber: { border: "border-amber-700/40", text: "text-amber-400", bg: "bg-amber-900/10" },
    red: { border: "border-red-700/40", text: "text-red-400", bg: "bg-red-900/10" },
  }[tone];
  return (
    <div className={`border ${palette.border} ${palette.bg} p-3 font-mono text-xs`}>
      <div className={`flex items-center gap-1.5 ${palette.text} text-[10px] uppercase tracking-[0.2em] mb-2`}>
        <Icon size={12} /> {r.action || "result"}
      </div>
      <div className="text-white">{r.message}</div>
      {r.action === "preempted" && r.exec && (
        <pre className="mt-2 text-[10px] text-[#9ca3af] whitespace-pre-wrap break-all">
          $ {r.exec.command}
          {"\n"}
          {r.exec.output}
        </pre>
      )}
      {r.action === "preempt_failed" && (
        <div className="mt-2 space-y-2">
          {r.attempts?.length > 0 && (
            <div className="text-[10px]">
              <div className="text-amber-400 uppercase tracking-[0.2em] mb-1">
                lmremove attempts ({r.attempts.length})
              </div>
              <div className="border border-[#1a1a1a] bg-[#0a0a0a]">
                <table className="w-full">
                  <thead>
                    <tr className="text-[#6b7280] text-[9px] uppercase">
                      <th className="text-left px-2 py-1">host tried</th>
                      <th className="text-left px-2 py-1">display</th>
                      <th className="text-right px-2 py-1">exit</th>
                      <th className="text-left px-2 py-1">output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {r.attempts.map((a, i) => (
                      <tr key={i} className="border-t border-[#1a1a1a]">
                        <td className="px-2 py-1 text-white">{a.host || "—"}</td>
                        <td className="px-2 py-1 text-[#9ca3af]">{a.display || "(none)"}</td>
                        <td className="px-2 py-1 text-right">
                          <span className={a.exit === 0 ? "text-emerald-400" : "text-red-400"}>
                            {a.exit}
                          </span>
                        </td>
                        <td className="px-2 py-1 text-[#9ca3af] break-all">{a.output}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <div className="text-[10px] text-amber-400 border-l-2 border-amber-700/60 pl-2">
            <div className="uppercase tracking-[0.2em] mb-1">What to try next</div>
            <ul className="list-disc list-inside text-[#d1d5db] space-y-0.5">
              <li>Run <code className="text-emerald-400">lmutil lmremove</code> manually from the license server itself — workstation lmutil is often blocked by FlexLM ACLs.</li>
              <li>Check the vendor daemon options file for <code className="text-emerald-400">INCLUDE_BORROW</code> / admin restrictions.</li>
              <li>If the user&apos;s tool client immediately reconnects (sticky), kill the process on their host (<code className="text-emerald-400">kill -9 &lt;pid&gt;</code>).</li>
              <li>Re-sync the server (Dashboard → SYNC ALL) — the stored hostname may be stale; FlexLM&apos;s internal host string may differ from what the parser captured.</li>
            </ul>
          </div>
        </div>
      )}
      {r.action === "no_victim" && r.current_holders?.length > 0 && (
        <div className="mt-2 text-[10px] text-[#9ca3af]">
          Current holders:{" "}
          {r.current_holders.map((h, i) => (
            <span key={i} className="mr-2">
              {h.user}@{h.host}
              {h.is_hipri ? " (hipri)" : ""}
              {h.is_lopri ? " (lopri)" : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
