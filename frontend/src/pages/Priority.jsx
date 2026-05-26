import { useEffect, useState } from "react";
import { Zap, Plus, Trash2, Save, AlertTriangle, Crown, Edit3, Database, RefreshCw, Hourglass, X } from "lucide-react";
import { api } from "@/lib/api";
import Header from "@/components/Header";
import { toast } from "sonner";

const emptyRule = {
  name: "",
  priority: 500,
  user_pattern: "",
  group_pattern: "",
  project_pattern: "",
  features: "",
  description: "",
  enabled: true,
};

export default function Priority() {
  const [stats, setStats] = useState(null);
  const [rules, setRules] = useState([]);
  const [servers, setServers] = useState([]);
  const [editing, setEditing] = useState(null); // null | "new" | {id, ...rule}
  const [form, setForm] = useState(emptyRule);
  const [saving, setSaving] = useState(false);

  // Preemption tester state
  const [pServer, setPServer] = useState("");
  const [pFeature, setPFeature] = useState("");
  const [pUser, setPUser] = useState("");
  const [pGroup, setPGroup] = useState("");
  const [pProject, setPProject] = useState("");
  const [pSeats, setPSeats] = useState(1);
  const [plan, setPlan] = useState(null);
  const [runResult, setRunResult] = useState(null);
  const [planning, setPlanning] = useState(false);
  const [running, setRunning] = useState(false);

  // SGE auto-discovery
  const [sge, setSge] = useState({ users: [], groups: [], projects: [], loaded: false });
  const [sgeLoading, setSgeLoading] = useState(false);

  // Pending requests queue (SGE-free preemption workflow)
  const [pending, setPending] = useState([]);
  const [reqUser, setReqUser] = useState("");
  const [reqFeature, setReqFeature] = useState("");
  const [reqSeats, setReqSeats] = useState(1);
  const [reqServer, setReqServer] = useState("");
  const [submittingReq, setSubmittingReq] = useState(false);

  const loadPending = async () => {
    try {
      const r = await api.listPendingRequests("all");
      setPending(r);
    } catch {
      /* silent — page still loads */
    }
  };

  const submitRequest = async () => {
    if (!reqUser.trim() || !reqFeature.trim()) {
      toast.error("user and feature are required");
      return;
    }
    setSubmittingReq(true);
    try {
      await api.createPendingRequest({
        user: reqUser.trim(),
        feature: reqFeature.trim(),
        seats: Number(reqSeats) || 1,
        server_id: reqServer || undefined,
      });
      toast.success(`Queued: ${reqUser} ↔ ${reqFeature}`);
      setReqUser("");
      setReqFeature("");
      setReqSeats(1);
      setTimeout(loadPending, 1500); // give the loop a moment to action it
      loadPending();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Submit failed");
    } finally {
      setSubmittingReq(false);
    }
  };

  const cancelReq = async (rid) => {
    try {
      await api.cancelPendingRequest(rid);
      loadPending();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Cancel failed");
    }
  };

  const loadSge = async () => {
    setSgeLoading(true);
    try {
      const [u, g, p] = await Promise.all([api.sgeUsers(), api.sgeGroups(), api.sgeProjects()]);
      setSge({ users: u.users || [], groups: g.groups || [], projects: p.projects || [], loaded: true });
      toast.success(
        `SGE: ${u.users?.length || 0} users · ${g.groups?.length || 0} groups · ${p.projects?.length || 0} projects`,
      );
    } catch (e) {
      toast.error(e?.response?.data?.detail || "SGE query failed. Is SGE enabled in Settings and is at least one server SSH-configured?");
    } finally {
      setSgeLoading(false);
    }
  };

  const load = async () => {
    const [r, s, st] = await Promise.all([api.listPriorityRules(), api.listServers(), api.stats()]);
    setRules(r);
    setServers(s);
    setStats(st);
  };

  useEffect(() => {
    load();
    loadPending();
    const t = setInterval(loadPending, 10000);
    return () => clearInterval(t);
  }, []);

  const startEdit = (rule) => {
    setEditing(rule);
    setForm({ ...rule, features: (rule.features || []).join(", ") });
  };

  const startNew = () => {
    setEditing("new");
    setForm(emptyRule);
  };

  const cancel = () => {
    setEditing(null);
    setForm(emptyRule);
  };

  const save = async () => {
    if (!form.name.trim()) {
      toast.error("Rule name is required");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        ...form,
        priority: Number(form.priority) || 0,
        features: form.features
          .split(/[,\s]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      };
      if (editing === "new") {
        await api.createPriorityRule(payload);
        toast.success(`Rule '${payload.name}' created`);
      } else {
        await api.updatePriorityRule(editing.id, payload);
        toast.success(`Rule '${payload.name}' updated`);
      }
      cancel();
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (rule) => {
    if (!window.confirm(`Delete priority rule "${rule.name}"?`)) return;
    try {
      await api.deletePriorityRule(rule.id);
      toast.success("Rule deleted");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const runPlan = async () => {
    if (!pServer || !pFeature || (!pUser && !pGroup && !pProject)) {
      toast.error("Server, feature and at least one of user/group/project are required");
      return;
    }
    setPlanning(true);
    setRunResult(null);
    try {
      const r = await api.preemptPlan({
        server_id: pServer,
        feature: pFeature,
        requester_user: pUser,
        requester_group: pGroup,
        requester_project: pProject,
        seats_needed: Number(pSeats) || 1,
      });
      setPlan(r);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Plan failed");
    } finally {
      setPlanning(false);
    }
  };

  const runPreempt = async () => {
    if (!plan || !plan.can_satisfy) {
      toast.error("Run PLAN first and ensure it can be satisfied");
      return;
    }
    if (!window.confirm(
      `Force-release ${plan.releasable_holders} holder(s) of "${pFeature}"?\n\n` +
      `Each target's running job will be killed (SGE qmod -d) or its license seat yanked (lmremove).`,
    )) return;
    setRunning(true);
    try {
      const r = await api.preemptRun({
        server_id: pServer,
        feature: pFeature,
        requester_user: pUser,
        requester_group: pGroup,
        requester_project: pProject,
        seats_needed: Number(pSeats) || 1,
      });
      setRunResult(r);
      if (r.ok) toast.success(`Preempted ${r.actions?.length || 0} holder(s)`);
      else toast.error(r.message || "Preempt failed");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Preempt failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="priority-page">
      <Header stats={stats} autoRefresh={false} onToggleRefresh={() => {}} />

      <main className="max-w-[1500px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              /// PREEMPTION
            </div>
            <h1 className="font-mono text-2xl font-bold tracking-tight mt-1 flex items-center gap-2">
              <Crown size={22} /> Priority &amp; Preemption
            </h1>
            <div className="font-mono text-[11px] text-[#6b7280] mt-1">
              SGE-aware · {rules.length} rule(s) configured
            </div>
          </div>
          <button
            onClick={startNew}
            className="btn-brutal primary flex items-center gap-1.5"
            data-testid="add-priority-rule-btn"
          >
            <Plus size={12} /> ADD RULE
          </button>
        </div>

        {/* SGE auto-discovery banner */}
        <section
          className="bg-[#111] border border-[#222] rounded-sm p-3 flex items-center justify-between flex-wrap gap-3"
          data-testid="sge-discovery-banner"
        >
          <div className="font-mono text-[11px] text-[#9ca3af] flex items-center gap-2">
            <Database size={14} className="text-blue-400" />
            {sge.loaded ? (
              <span>
                SGE catalogue loaded ·{" "}
                <span className="text-emerald-400">{sge.users.length}</span> users ·{" "}
                <span className="text-emerald-400">{sge.groups.length}</span> groups ·{" "}
                <span className="text-emerald-400">{sge.projects.length}</span> projects
              </span>
            ) : (
              <span>
                Pull users / @groups / projects directly from Son of Grid Engine — saves you from
                typing patterns by hand.
              </span>
            )}
          </div>
          <button
            onClick={loadSge}
            disabled={sgeLoading}
            className="btn-brutal flex items-center gap-1.5 disabled:opacity-50"
            data-testid="sge-pull-btn"
          >
            <RefreshCw size={11} className={sgeLoading ? "animate-spin" : ""} />
            {sgeLoading ? "QUERYING SGE…" : sge.loaded ? "REFRESH SGE" : "PULL FROM SGE"}
          </button>
        </section>

        {/* Rules table */}
        <section className="bg-[#111] border border-[#222] rounded-sm">
          <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              PRIORITY RULES (highest first)
            </div>
            <span className="font-mono text-xs text-emerald-400">[{rules.length}]</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full font-mono text-xs" data-testid="priority-rules-table">
              <thead className="bg-[#0a0a0a]">
                <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                  <th className="px-4 py-2 text-right">Priority</th>
                  <th className="px-4 py-2">Name</th>
                  <th className="px-4 py-2">User</th>
                  <th className="px-4 py-2">Group</th>
                  <th className="px-4 py-2">Project</th>
                  <th className="px-4 py-2">Features</th>
                  <th className="px-4 py-2">State</th>
                  <th className="px-4 py-2 text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr
                    key={r.id}
                    className="border-t border-[#1a1a1a] hover:bg-[#141414]"
                    data-testid={`priority-row-${r.id}`}
                  >
                    <td className="px-4 py-2 text-right">
                      <span className="font-bold tabular-nums text-amber-400">{r.priority}</span>
                    </td>
                    <td className="px-4 py-2 text-white">{r.name}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">{r.user_pattern || "—"}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">{r.group_pattern || "—"}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">{r.project_pattern || "—"}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">
                      {r.features?.length ? r.features.join(", ") : "ALL"}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className="text-[10px] uppercase tracking-wider font-bold"
                        style={{ color: r.enabled ? "#10b981" : "#6b7280" }}
                      >
                        {r.enabled ? "● ON" : "○ OFF"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => startEdit(r)}
                        className="inline-flex items-center gap-1 px-2 py-1 border border-[#222] text-[10px] uppercase tracking-wider hover:bg-[#1a1a1a] mr-1"
                        data-testid={`edit-priority-${r.id}`}
                      >
                        <Edit3 size={10} /> EDIT
                      </button>
                      <button
                        onClick={() => remove(r)}
                        className="inline-flex items-center gap-1 px-2 py-1 border border-red-900/60 text-red-400 hover:bg-red-900/20 text-[10px] uppercase tracking-wider"
                        data-testid={`delete-priority-${r.id}`}
                      >
                        <Trash2 size={10} /> DEL
                      </button>
                    </td>
                  </tr>
                ))}
                {rules.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-[#6b7280]">
                      {"// no priority rules yet — ADD RULE to start"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Editor */}
        {editing && (
          <section
            className="bg-[#111] border border-emerald-900/50 rounded-sm"
            data-testid="priority-editor"
          >
            <div className="px-4 py-3 border-b border-[#222] font-mono text-[10px] uppercase tracking-[0.25em] text-emerald-400">
              {editing === "new" ? "NEW RULE" : `EDIT · ${editing.name}`}
            </div>
            <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-3 font-mono text-xs">
              <Field label="Name *">
                <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="inp" data-testid="rule-name" />
              </Field>
              <Field label="Priority (0-1000)">
                <input
                  type="number" min={0} max={1000}
                  value={form.priority}
                  onChange={(e) => setForm({ ...form, priority: e.target.value })}
                  className="inp tabular-nums"
                  data-testid="rule-priority"
                />
              </Field>
              <Field label="User pattern (glob, e.g. rakella* )">
                <input
                  value={form.user_pattern}
                  onChange={(e) => setForm({ ...form, user_pattern: e.target.value })}
                  list="sge-users-list"
                  className="inp"
                  data-testid="rule-user"
                />
              </Field>
              <Field label="Group pattern (SGE @group)">
                <input
                  value={form.group_pattern}
                  onChange={(e) => setForm({ ...form, group_pattern: e.target.value })}
                  list="sge-groups-list"
                  className="inp"
                  data-testid="rule-group"
                />
              </Field>
              <Field label="Project pattern (SGE project)">
                <input
                  value={form.project_pattern}
                  onChange={(e) => setForm({ ...form, project_pattern: e.target.value })}
                  list="sge-projects-list"
                  className="inp"
                  data-testid="rule-project"
                />
              </Field>
              <Field label="Features (comma-sep, blank = ALL)">
                <input value={form.features} onChange={(e) => setForm({ ...form, features: e.target.value })} placeholder="Innovus, Genus, VCS-RuntimeNetlist" className="inp" data-testid="rule-features" />
              </Field>
              <Field label="Description" full>
                <input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="inp" data-testid="rule-description" />
              </Field>
              <div className="md:col-span-2 flex items-center justify-between flex-wrap gap-2 pt-2 border-t border-[#1a1a1a]">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                    data-testid="rule-enabled"
                  />
                  <span className="uppercase tracking-wider text-[10px]">enabled</span>
                </label>
                <div className="flex gap-2">
                  <button onClick={cancel} className="btn-brutal" data-testid="rule-cancel">CANCEL</button>
                  <button
                    onClick={save}
                    disabled={saving}
                    className="btn-brutal primary flex items-center gap-1.5 disabled:opacity-50"
                    data-testid="rule-save"
                  >
                    <Save size={12} /> {saving ? "SAVING…" : "SAVE"}
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* Pending requests queue */}
        <section className="bg-[#111] border border-[#222] rounded-sm" data-testid="pending-requests-panel">
          <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2">
            <Hourglass size={14} className="text-amber-400" />
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              PENDING REQUESTS QUEUE
            </div>
            <span className="font-mono text-[11px] text-[#6b7280]">
              · username-based · auto-actioned by the background loop · no scheduler needed
            </span>
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-5 gap-3 font-mono text-xs border-b border-[#1a1a1a]">
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">User *</div>
              <input
                value={reqUser}
                onChange={(e) => setReqUser(e.target.value)}
                list="sge-users-list"
                placeholder="ramkella"
                className="inp"
                data-testid="pending-user"
              />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">Feature *</div>
              <input
                value={reqFeature}
                onChange={(e) => setReqFeature(e.target.value)}
                placeholder="Innovus"
                className="inp"
                data-testid="pending-feature"
              />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">Seats</div>
              <input
                type="number" min={1}
                value={reqSeats}
                onChange={(e) => setReqSeats(e.target.value)}
                className="inp tabular-nums"
                data-testid="pending-seats"
              />
            </div>
            <div>
              <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">Server (optional hint)</div>
              <select
                value={reqServer}
                onChange={(e) => setReqServer(e.target.value)}
                className="inp"
                data-testid="pending-server"
              >
                <option value="">(any)</option>
                {servers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <div className="flex items-end">
              <button
                onClick={submitRequest}
                disabled={submittingReq}
                className="btn-brutal primary flex items-center gap-1.5 w-full justify-center disabled:opacity-50"
                data-testid="submit-pending-request"
              >
                <Plus size={12} /> {submittingReq ? "QUEUING…" : "QUEUE REQUEST"}
              </button>
            </div>
          </div>
          <div className="overflow-x-auto max-h-80 overflow-y-auto">
            <table className="w-full font-mono text-[11px]">
              <thead className="bg-[#0a0a0a] sticky top-0">
                <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                  <th className="px-4 py-2">State</th>
                  <th className="px-4 py-2">User</th>
                  <th className="px-4 py-2">Feature</th>
                  <th className="px-4 py-2 text-right">Seats</th>
                  <th className="px-4 py-2">Queued</th>
                  <th className="px-4 py-2">Resolved</th>
                  <th className="px-4 py-2 text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {pending.map((p) => {
                  const stateColor = {
                    open: "#f59e0b",
                    satisfied: "#10b981",
                    cancelled: "#6b7280",
                    expired: "#6b7280",
                  }[p.state] || "#9ca3af";
                  return (
                    <tr key={p.id} className="border-t border-[#1a1a1a] hover:bg-[#141414]">
                      <td className="px-4 py-1.5">
                        <span
                          className="text-[10px] uppercase tracking-wider font-bold"
                          style={{ color: stateColor }}
                        >
                          {p.state}
                        </span>
                      </td>
                      <td className="px-4 py-1.5 text-emerald-400">{p.user}</td>
                      <td className="px-4 py-1.5 text-white">{p.feature}</td>
                      <td className="px-4 py-1.5 text-right tabular-nums">{p.seats}</td>
                      <td className="px-4 py-1.5 text-[#9ca3af]">{p.created_at?.slice(0, 19).replace("T", " ")}</td>
                      <td className="px-4 py-1.5 text-[#9ca3af]">
                        {p.resolved_at ? `${p.resolution || ""} @ ${p.resolved_at.slice(11, 19)}` : "—"}
                      </td>
                      <td className="px-4 py-1.5 text-right">
                        {p.state === "open" && (
                          <button
                            onClick={() => cancelReq(p.id)}
                            className="inline-flex items-center gap-1 px-2 py-1 border border-red-900/60 text-red-400 hover:bg-red-900/20 text-[10px] uppercase tracking-wider"
                            data-testid={`cancel-pending-${p.id}`}
                          >
                            <X size={10} /> CANCEL
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {pending.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-[#6b7280]">
                      {"// no pending requests — queue one above"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Preemption tester */}
        <section className="bg-[#111] border border-[#222] rounded-sm" data-testid="preempt-tester">
          <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2 font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
            <Zap size={12} className="text-amber-400" /> MANUAL PREEMPTION
          </div>
          <div className="p-4 grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-3 font-mono text-xs">
            <Field label="Server">
              <select value={pServer} onChange={(e) => setPServer(e.target.value)} className="inp" data-testid="preempt-server">
                <option value="">(select)</option>
                {servers.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </Field>
            <Field label="Feature">
              <input value={pFeature} onChange={(e) => setPFeature(e.target.value)} placeholder="Innovus" className="inp" data-testid="preempt-feature" />
            </Field>
            <Field label="Requester user">
              <input value={pUser} onChange={(e) => setPUser(e.target.value)} placeholder="rakella" className="inp" data-testid="preempt-user" />
            </Field>
            <Field label="Group (optional)">
              <input value={pGroup} onChange={(e) => setPGroup(e.target.value)} className="inp" data-testid="preempt-group" />
            </Field>
            <Field label="Project (optional)">
              <input value={pProject} onChange={(e) => setPProject(e.target.value)} className="inp" data-testid="preempt-project" />
            </Field>
            <Field label="Seats">
              <input
                type="number" min={1}
                value={pSeats}
                onChange={(e) => setPSeats(e.target.value)}
                className="inp tabular-nums"
                data-testid="preempt-seats"
              />
            </Field>
          </div>
          <div className="px-4 pb-4 flex items-center gap-2 flex-wrap">
            <button
              onClick={runPlan}
              disabled={planning}
              className="btn-brutal flex items-center gap-1.5 disabled:opacity-50"
              data-testid="preempt-plan-btn"
            >
              {planning ? "PLANNING…" : "PLAN"}
            </button>
            <button
              onClick={runPreempt}
              disabled={running || !plan || !plan.can_satisfy}
              className="btn-brutal flex items-center gap-1.5 border-red-900/60 text-red-400 hover:bg-red-900/20 disabled:opacity-30"
              data-testid="preempt-run-btn"
            >
              <Zap size={12} /> {running ? "RELEASING…" : "PREEMPT NOW"}
            </button>
          </div>

          {plan && (
            <div className="px-4 pb-4" data-testid="preempt-plan-result">
              <div className="border border-[#222] bg-[#0a0a0a] rounded-sm">
                <div className="px-3 py-2 border-b border-[#222] flex items-center justify-between flex-wrap gap-2 font-mono text-[10px] uppercase tracking-wider">
                  <span className="text-[#9ca3af]">PLAN</span>
                  <div className="flex items-center gap-3">
                    <span className="text-amber-400">requester prio {plan.requester_priority}</span>
                    <span className="text-[#6b7280]">·</span>
                    <span className={plan.can_satisfy ? "text-emerald-400" : "text-red-400"}>
                      {plan.can_satisfy ? "CAN SATISFY" : "CANNOT SATISFY"}
                    </span>
                    <span className="text-[#6b7280]">
                      · {plan.releasable_holders}/{plan.current_holders} releasable
                    </span>
                  </div>
                </div>
                {!plan.can_satisfy && (
                  <div className="px-3 py-3 flex items-start gap-2 text-[11px] font-mono text-amber-400">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    <div>
                      Requester priority is not high enough to displace any current holder. Add or
                      raise a priority rule first.
                    </div>
                  </div>
                )}
                {plan.targets?.length > 0 && (
                  <table className="w-full font-mono text-[11px]">
                    <thead className="bg-[#0d0d0d]">
                      <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                        <th className="px-3 py-1.5">Holder</th>
                        <th className="px-3 py-1.5">Host</th>
                        <th className="px-3 py-1.5">Display</th>
                        <th className="px-3 py-1.5 text-right">Prio</th>
                      </tr>
                    </thead>
                    <tbody>
                      {plan.targets.map((t) => (
                        <tr key={t.id} className="border-t border-[#1a1a1a]">
                          <td className="px-3 py-1.5 text-emerald-400">{t.user}</td>
                          <td className="px-3 py-1.5 text-[#9ca3af]">{t.host}</td>
                          <td className="px-3 py-1.5 text-[#6b7280]">{t.display}</td>
                          <td className="px-3 py-1.5 text-right text-amber-400 tabular-nums">
                            {t.holder_priority}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          )}

          {runResult && (
            <div className="px-4 pb-4" data-testid="preempt-run-result">
              <div className="border border-emerald-900/40 bg-[#0a0a0a] rounded-sm">
                <div className="px-3 py-2 border-b border-[#222] font-mono text-[10px] uppercase tracking-wider text-emerald-400">
                  EXECUTED · {runResult.actions?.length || 0} action(s)
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full font-mono text-[11px]">
                    <thead className="bg-[#0d0d0d]">
                      <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                        <th className="px-3 py-1.5">User</th>
                        <th className="px-3 py-1.5">Host</th>
                        <th className="px-3 py-1.5">Method</th>
                        <th className="px-3 py-1.5">Exit</th>
                        <th className="px-3 py-1.5">Output</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(runResult.actions || []).map((a, i) => (
                        <tr key={i} className="border-t border-[#1a1a1a]">
                          <td className="px-3 py-1.5 text-emerald-400">{a.user}</td>
                          <td className="px-3 py-1.5 text-[#9ca3af]">{a.host}</td>
                          <td className="px-3 py-1.5">
                            <span
                              className="text-[10px] uppercase tracking-wider font-bold"
                              style={{
                                color: a.method === "sge" ? "#3b82f6" : a.method === "lmremove" ? "#f59e0b" : "#ef4444",
                              }}
                            >
                              {a.method}
                            </span>
                          </td>
                          <td className="px-3 py-1.5 tabular-nums">{a.result?.exit ?? "—"}</td>
                          <td className="px-3 py-1.5 text-[#6b7280] truncate max-w-md">
                            {(a.result?.output || "").slice(0, 120)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </section>
      </main>

      {/* Shared datalists for autocomplete from SGE */}
      <datalist id="sge-users-list">
        {sge.users.map((u) => (
          <option key={u} value={u} />
        ))}
      </datalist>
      <datalist id="sge-groups-list">
        {sge.groups.map((g) => (
          <option key={g} value={g} />
        ))}
      </datalist>
      <datalist id="sge-projects-list">
        {sge.projects.map((p) => (
          <option key={p} value={p} />
        ))}
      </datalist>

      <style>{`
        .inp {
          width: 100%;
          background: #0a0a0a;
          border: 1px solid #222;
          padding: 6px 8px;
          font-size: 12px;
          color: #fff;
          font-family: 'JetBrains Mono', monospace;
        }
        .inp:focus { outline: none; border-color: #444; }
      `}</style>
    </div>
  );
}

const Field = ({ label, children, full }) => (
  <div className={full ? "md:col-span-2 lg:col-span-6" : ""}>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1 font-mono">{label}</div>
    {children}
  </div>
);
