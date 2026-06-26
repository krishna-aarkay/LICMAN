import { useEffect, useState, useCallback } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { ArrowLeft, FileText, Settings, ListChecks, Save, Plus, Trash2, RefreshCw, Power, Activity, Plug, Download, RotateCw } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, vendorMeta, fmtAgo } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { prefs } from "@/lib/prefs";
import Header from "@/components/Header";
import CodeEditor from "@/components/CodeEditor";
import AuditTimeline from "@/components/AuditTimeline";
import ReservationDialog from "@/components/ReservationDialog";
import ExpiryBadge from "@/components/ExpiryBadge";
import SshConfigPanel from "@/components/SshConfigPanel";
import { toast } from "sonner";

const parseExpiry = (s) => {
  if (!s) return null;
  const t = s.trim().toLowerCase();
  if (["permanent", "0", "none"].includes(t)) return null;
  const months = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
  const m1 = t.match(/^(\d{1,2})-([a-z]{3})-(\d{4})$/);
  if (m1) {
    const mi = months.indexOf(m1[2]);
    if (mi >= 0) return new Date(parseInt(m1[3]), mi, parseInt(m1[1]));
  }
  const m2 = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m2) return new Date(parseInt(m2[1]), parseInt(m2[2]) - 1, parseInt(m2[3]));
  return null;
};
const daysUntil = (d) => (d ? Math.floor((d - new Date()) / 86400000) : null);

export default function ServerDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const { isAdmin } = useAuth();
  const [server, setServer] = useState(null);
  const [licText, setLicText] = useState("");
  const [optText, setOptText] = useState("");
  const [licDirty, setLicDirty] = useState(false);
  const [optDirty, setOptDirty] = useState(false);
  const [checkouts, setCheckouts] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [audit, setAudit] = useState([]);
  const [resDialogOpen, setResDialogOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(prefs.load().autoRefresh);
  const [stats, setStats] = useState(null);
  const [optValidation, setOptValidation] = useState(null);
  const [validating, setValidating] = useState(false);
  const [selectedFeature, setSelectedFeature] = useState(null);
  const [killing, setKilling] = useState(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [rawLmstat, setRawLmstat] = useState(null);

  // remember last visited server
  useEffect(() => {
    if (id) prefs.save({ lastServerId: id });
  }, [id]);

  const load = useCallback(async () => {
    const s = await api.getServer(id);
    setServer(s);
    if (!licDirty) setLicText(s.license_file || "");
    if (!optDirty) setOptText(s.options_file || "");
    const [c, r, a, st] = await Promise.all([
      api.serverCheckouts(id),
      api.listReservations(id),
      api.audit(60),
      api.stats(),
    ]);
    setCheckouts(c);
    setReservations(r);
    setAudit(a.filter((x) => x.server_id === id || !x.server_id));
    setStats(st);
  }, [id, licDirty, optDirty]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => {
      api.serverCheckouts(id).then(setCheckouts).catch(() => {});
    }, 10000);
    return () => clearInterval(t);
  }, [autoRefresh, id]);

  if (!server) {
    return (
      <div className="min-h-screen bg-[#050505] text-[#9ca3af] flex items-center justify-center font-mono">
        Loading <span className="cursor-blink ml-2" />
      </div>
    );
  }

  const meta = vendorMeta(server.vendor);
  const isUp = server.status === "up";

  const saveLicense = async () => {
    try {
      const r = await api.saveLicense(id, licText);
      let msg = `License saved · ${r.features_parsed} features parsed`;
      if (r.pushed_to_disk) msg += ` · pushed to ${r.license_path}`;
      if (r.lmreread) msg += " · lmreread OK";
      if (r.push_error) msg += ` · push FAILED: ${r.push_error}`;
      if (r.push_error) toast.error(msg);
      else toast.success(msg);
      setLicDirty(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const fetchLicenseFromServer = async () => {
    try {
      const r = await api.fetchLicense(id);
      toast.success(`Fetched ${r.bytes} bytes from ${r.path}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Fetch failed");
    }
  };

  const saveOptions = async () => {
    try {
      const r = await api.saveOptions(id, optText);
      let msg = "Options saved";
      if (r.pushed_to_disk) msg += ` · pushed to ${r.options_path}`;
      if (r.lmreread) msg += " · lmreread OK";
      if (r.push_error) msg += ` · push FAILED: ${r.push_error}`;
      if (r.push_error) toast.error(msg);
      else toast.success(msg);
      setOptDirty(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const fetchOptionsFromServer = async () => {
    try {
      const r = await api.fetchOptions(id);
      toast.success(
        `Fetched ${r.bytes} bytes · ${r.reservations_imported} RESERVE entr${r.reservations_imported === 1 ? "y" : "ies"} imported`,
      );
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Fetch failed");
    }
  };

  const validateOpts = async () => {
    setValidating(true);
    try {
      const r = await api.validateOptions(id, optText);
      setOptValidation(r);
      if (r.ok) toast.success(`Options syntax OK · ${r.warnings} warning(s)`);
      else toast.error(`${r.errors} error(s) · ${r.warnings} warning(s)`);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Validation failed");
    } finally {
      setValidating(false);
    }
  };

  const killCheckout = async (co) => {
    if (!window.confirm(`Force-release ${co.feature} held by ${co.user}@${co.host}?\nThis runs lmremove.`)) return;
    setKilling(co.id);
    try {
      const r = await api.killCheckout(id, {
        feature: co.feature, user: co.user, host: co.host, display: co.display || "",
      });
      if (r.ok) toast.success(`Released ${co.feature} (${co.user})`);
      else toast.error(r?.exec?.output?.slice(0, 200) || "lmremove failed");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Kill failed");
    } finally {
      setKilling(null);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(
      `Permanently remove "${server?.name}" from LICMAN?\n\n` +
      `Deletes its SSH credentials, options file, reservations and live checkouts. ` +
      `The license server itself is NOT touched.`,
    )) return;
    try {
      await api.deleteServer(id);
      toast.success(`${server.name} removed`);
      nav("/");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Delete failed");
    }
  };

  const runDiagnose = async () => {
    setDiagnosing(true);
    setRawLmstat(null);
    try {
      const r = await api.diagnose(id);
      setRawLmstat(r);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Diagnose failed");
    } finally {
      setDiagnosing(false);
    }
  };

  const editPaths = async () => {
    const lic = window.prompt(
      "License file path on the license host (leave blank to clear):",
      server?.license_file_path || "",
    );
    if (lic === null) return;
    const opt = window.prompt(
      "Options file path on the license host (leave blank to clear):",
      server?.options_file_path || "",
    );
    if (opt === null) return;
    const dbg = window.prompt(
      "FlexLM debug log path (REQUIRED for auto-preempt to detect QUEUED users — e.g. /cadmgr/cadence/lic.log):",
      server?.debug_log_path || "",
    );
    if (dbg === null) return;
    try {
      await api.updateServer(id, {
        license_file_path: lic.trim(),
        options_file_path: opt.trim(),
        debug_log_path: dbg.trim(),
      });
      toast.success("Paths saved");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const requestForUser = async (featureName) => {
    const u = window.prompt(`Who is requesting "${featureName}"? (username)`, "");
    if (!u) return;
    try {
      const r = await api.requestLicense({
        server_id: id, feature: featureName, requester_user: u, seats_needed: 1,
      });
      if (r.action === "available") toast.success(r.message);
      else if (r.action === "preempted")
        toast.success(`${r.message} (priority ${r.requester_priority})`);
      else toast.error(r.message);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Request failed");
    }
  };

  const syncReservations = async () => {
    try {
      const r = await api.syncReservationsToOptions(id);
      if (r.pushed_to_disk)
        toast.success(`${r.reservations_merged} reservation(s) pushed to ${r.options_path} + lmreread`);
      else if (r.push_error)
        toast.error(`Sync failed: ${r.push_error}`);
      else
        toast.warning("Saved to DB. Set options_file_path on this server to push to disk + lmreread.");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Sync failed");
    }
  };

  const act = async (fn, msg) => {
    try {
      await fn();
      toast.success(msg);
      load();
    } catch {
      toast.error("Action failed");
    }
  };

  const removeRes = async (rid) => {
    try {
      await api.deleteReservation(rid);
      toast.success("Reservation removed");
      load();
    } catch {
      toast.error("Remove failed");
    }
  };

  // sum of count field across active checkouts + count of reservations
  // OR the server-reported `in use` count from lmstat header — whichever is HIGHER.
  // Real lmstat sometimes folds multi-seat checkouts into a single user row but
  // still reports the correct total in the feature header. The reservation count
  // is added because RESERVE seats are consumed even when no one is using them.
  const inUse = (featName) => {
    const fromCheckouts = checkouts
      .filter((c) => c.feature === featName)
      .reduce((sum, c) => sum + (c.count || 1), 0);
    const fromReservations = reservations
      .filter((r) => r.feature === featName)
      .reduce((sum, r) => sum + (r.count || 1), 0);
    const reported = (server?.features || []).find((f) => f.name === featName)?.in_use_reported || 0;
    return Math.max(fromCheckouts + fromReservations, reported);
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="server-detail-page">
      <Header
        stats={stats}
        autoRefresh={autoRefresh}
        onToggleRefresh={() => {
          setAutoRefresh((v) => {
            const nv = !v;
            prefs.save({ autoRefresh: nv });
            return nv;
          });
        }}
      />

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-6">
        {/* Breadcrumb */}
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 text-[#9ca3af] hover:text-white font-mono text-xs"
          data-testid="breadcrumb"
        >
          <ArrowLeft size={12} /> back to control room
        </Link>

        {/* Server header */}
        <section className="bg-[#111] border border-[#222] rounded-sm p-5">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: meta.color, boxShadow: `0 0 10px ${meta.color}` }}
                />
                <span
                  className="font-mono text-[10px] font-bold uppercase tracking-[0.25em]"
                  style={{ color: meta.color }}
                >
                  {meta.label}
                </span>
                <span className="font-mono text-[10px] text-[#6b7280] uppercase tracking-wider">
                  · daemon {server.daemon}
                </span>
              </div>
              <h1 className="font-mono text-3xl font-bold tracking-tight">{server.name}</h1>
              <div className="font-mono text-sm text-[#9ca3af] mt-1">
                {server.host}:<span className="text-white">{server.port}</span>
                <span className="mx-2 text-[#333]">·</span>
                <span
                  className="font-bold uppercase"
                  style={{ color: isUp ? "#10b981" : "#ef4444" }}
                >
                  {isUp ? "● UP" : "● DOWN"}
                </span>
              </div>
              {server.last_action && (
                <div className="font-mono text-[10px] text-[#6b7280] mt-1 uppercase tracking-wider">
                  last action · {server.last_action}
                </div>
              )}
              <div className="mt-2 font-mono text-[10px] text-[#9ca3af]">
                <span className="text-[#6b7280]">license →</span>{" "}
                <span className={server.license_file_path ? "text-emerald-400" : "text-amber-400"}>
                  {server.license_file_path || "(auto-discover)"}
                </span>
                <br />
                <span className="text-[#6b7280]">options →</span>{" "}
                <span className={server.options_file_path ? "text-emerald-400" : "text-amber-400"}>
                  {server.options_file_path || "(DB only — not pushed to lmgrd)"}
                </span>
                <br />
                <span className="text-[#6b7280]">debug log →</span>{" "}
                <span className={server.debug_log_path ? "text-emerald-400" : "text-red-400"}>
                  {server.debug_log_path || "(NOT SET — auto-preempt cannot detect QUEUED users without this)"}
                </span>
                {isAdmin && (
                  <button
                    onClick={editPaths}
                    className="ml-2 text-[10px] text-[#9ca3af] hover:text-white underline"
                    data-testid="edit-paths-btn"
                  >
                    edit paths
                  </button>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {server.adapter_mode === "ssh" && isAdmin && (
                <button
                  className="btn-brutal flex items-center gap-1.5"
                  onClick={async () => {
                    try {
                      const r = await api.sync(id);
                      toast.success(`Synced · ${r.features_parsed} features · ${r.checkouts_parsed} checkouts`);
                      load();
                    } catch (e) {
                      toast.error(e?.response?.data?.detail || "Sync failed");
                    }
                  }}
                  data-testid="srv-sync"
                  title="lmstat -a over SSH → parse features + checkouts"
                >
                  <RotateCw size={12} /> SYNC NOW
                </button>
              )}
              <button
                className="btn-brutal flex items-center gap-1.5"
                onClick={() => act(() => api.reread(id), "lmreread issued")}
                data-testid="srv-reread"
              >
                <RefreshCw size={12} /> LMREREAD
              </button>
              <button
                className="btn-brutal flex items-center gap-1.5"
                onClick={() => act(() => api.restart(id), `${server.daemon} restarted`)}
                data-testid="srv-restart"
              >
                <Power size={12} /> RESTART DAEMON
              </button>
              <button
                className="btn-brutal flex items-center gap-1.5"
                onClick={() => act(() => api.toggle(id), "Status toggled")}
                data-testid="srv-toggle"
              >
                <Activity size={12} /> {isUp ? "STOP" : "START"}
              </button>
              {server.adapter_mode === "ssh" && isAdmin && (
                <button
                  className="btn-brutal flex items-center gap-1.5"
                  onClick={runDiagnose}
                  disabled={diagnosing}
                  data-testid="srv-diagnose"
                  title="Show RAW lmstat output — verify your parser is seeing real checkouts"
                >
                  <ListChecks size={12} />
                  {diagnosing ? "RUNNING…" : "RAW LMSTAT"}
                </button>
              )}
              {isAdmin && (
                <button
                  className="btn-brutal flex items-center gap-1.5 border-red-900/60 text-red-400 hover:bg-red-900/20"
                  onClick={handleDelete}
                  data-testid="srv-delete"
                  title="Permanently remove this server from LICMAN"
                >
                  <Trash2 size={12} /> REMOVE
                </button>
              )}
            </div>
          </div>

          {rawLmstat && (
            <div
              className="mt-4 border border-amber-900/40 bg-[#0a0a0a] rounded-sm"
              data-testid="raw-lmstat-panel"
            >
              <div className="px-3 py-2 border-b border-[#222] flex items-center justify-between flex-wrap gap-2 font-mono text-[10px] uppercase tracking-wider">
                <div className="flex items-center gap-3">
                  <span className="text-amber-400 font-bold">RAW LMSTAT · {rawLmstat.mode}</span>
                  <span className="text-[#6b7280]">
                    {rawLmstat.lmstat.lines} lines · parsed {rawLmstat.lmstat.parsed_features}{" "}
                    features · {rawLmstat.lmstat.parsed_checkouts} checkouts · exit{" "}
                    {rawLmstat.lmstat.exit}
                  </span>
                </div>
                <button
                  onClick={() => setRawLmstat(null)}
                  className="text-[#9ca3af] hover:text-white"
                  data-testid="raw-lmstat-close"
                >
                  ✕ HIDE
                </button>
              </div>
              <div className="px-3 py-2 border-b border-[#1a1a1a] font-mono text-[10px] text-[#9ca3af]">
                <span className="text-[#6b7280]">lmutil →</span>{" "}
                <span className="text-white">{rawLmstat.lmutil_resolved || "—"}</span>
              </div>
              <pre
                className="px-3 py-2 font-mono text-[11px] text-[#9ca3af] whitespace-pre-wrap max-h-[40vh] overflow-y-auto"
                data-testid="raw-lmstat-output"
              >
                {rawLmstat.lmstat.output || "(no output)"}
              </pre>
              {rawLmstat.lmstat.parsed_features === 0 && rawLmstat.lmstat.lines > 0 && (
                <div className="px-3 py-2 border-t border-[#1a1a1a] font-mono text-[11px] text-amber-400">
                  ⚠ lmstat returned {rawLmstat.lmstat.lines} lines but the LICMAN parser
                  extracted 0 features. Common causes: locale (run `LANG=C lmstat` on host),
                  custom output format, or daemon name mismatch. Paste a snippet above to your
                  admin to update the regex.
                </div>
              )}
              {rawLmstat.lmstat.parsed_features > 0 && (
                <div className="px-3 py-2 border-t border-[#1a1a1a] font-mono text-[11px] text-emerald-400">
                  ✓ Parser is healthy. If the Dashboard still shows zero checkouts, click SYNC NOW
                  above — the parsed result is persisted to MongoDB on each sync.
                </div>
              )}
            </div>
          )}

          {/* features — clickable rows that drill into per-feature checkouts */}
          <div className="mt-5 border border-[#222] bg-[#0a0a0a] rounded-sm" data-testid="features-list">
            <div className="grid grid-cols-12 gap-2 px-3 py-2 border-b border-[#222] font-mono text-[10px] uppercase tracking-wider text-[#6b7280]">
              <div className="col-span-4">Feature</div>
              <div className="col-span-2">Version</div>
              <div className="col-span-1 text-right">Seats</div>
              <div className="col-span-1 text-right">In Use</div>
              <div className="col-span-3">Utilization</div>
              <div className="col-span-1 text-right">Open</div>
            </div>
            {(server.features || []).length === 0 ? (
              <div className="px-3 py-6 font-mono text-xs text-[#6b7280]">
                {"// no features parsed yet — run SYNC or save the license file"}
              </div>
            ) : (
              (server.features || []).map((f) => {
                const used = inUse(f.name);
                const pct = Math.min(100, Math.round((used / Math.max(1, f.total)) * 100));
                const color = pct > 80 ? "#ef4444" : pct > 50 ? "#f59e0b" : "#10b981";
                return (
                  <button
                    key={f.name}
                    onClick={() => setSelectedFeature(f.name)}
                    className="w-full text-left grid grid-cols-12 gap-2 items-center px-3 py-2 border-t border-[#1a1a1a] hover:bg-[#141414] transition-colors group"
                    data-testid={`feature-row-${f.name}`}
                  >
                    <div className="col-span-4 font-mono text-xs text-white truncate group-hover:text-emerald-400">
                      {f.name}
                    </div>
                    <div className="col-span-2 font-mono text-[10px] text-[#9ca3af]">v{f.version}</div>
                    <div className="col-span-1 font-mono text-xs text-right text-[#9ca3af] tabular-nums">
                      {f.total}
                    </div>
                    <div className="col-span-1 font-mono text-xs text-right tabular-nums font-bold" style={{ color }}>
                      {used}
                    </div>
                    <div className="col-span-3 flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-[#1a1a1a] rounded-sm overflow-hidden">
                        <div
                          className="h-full transition-all"
                          style={{ width: `${pct}%`, background: color }}
                        />
                      </div>
                      <span className="font-mono text-[10px] tabular-nums text-[#9ca3af] w-9 text-right">
                        {pct}%
                      </span>
                    </div>
                    <div className="col-span-1 text-right font-mono text-[10px] uppercase tracking-wider text-[#6b7280] group-hover:text-emerald-400 flex items-center justify-end gap-1.5">
                      {isAdmin && pct >= 100 && (
                        <span
                          role="button"
                          tabIndex={0}
                          onClick={(e) => {
                            e.stopPropagation();
                            requestForUser(f.name);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.stopPropagation();
                              requestForUser(f.name);
                            }
                          }}
                          className="px-1.5 py-0.5 border border-amber-700/60 text-amber-400 hover:bg-amber-900/20 cursor-pointer"
                          data-testid={`request-${f.name}`}
                          title="Request this license (auto-preempt if requester has higher priority)"
                        >
                          REQUEST
                        </span>
                      )}
                      <span>DETAILS →</span>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </section>

        {/* Tabs */}
        <Tabs defaultValue="checkouts" className="w-full">
          <TabsList className="bg-[#111] border border-[#222] rounded-sm h-auto p-1 font-mono">
            {[
              { v: "checkouts", l: "CHECKOUTS", i: ListChecks },
              { v: "license", l: "LICENSE FILE", i: FileText },
              { v: "options", l: "OPTIONS", i: Settings },
              { v: "reservations", l: "RESERVATIONS", i: ListChecks },
              { v: "ssh", l: "CONNECTION", i: Plug },
              { v: "audit", l: "AUDIT", i: Activity },
            ].map(({ v, l, i: Icon }) => (
              <TabsTrigger
                key={v}
                value={v}
                className="text-[10px] uppercase tracking-wider data-[state=active]:bg-white data-[state=active]:text-black rounded-none px-3 py-2"
                data-testid={`tab-${v}`}
              >
                <Icon size={12} className="mr-1.5" />
                {l}
              </TabsTrigger>
            ))}
          </TabsList>

          <TabsContent value="checkouts" className="mt-4">
            <div className="bg-[#111] border border-[#222] rounded-sm">
              <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
                  ACTIVE CHECKOUTS · {server.name}
                </div>
                <span className="font-mono text-xs text-emerald-400">[{checkouts.length}]</span>
              </div>
              <div className="overflow-x-auto max-h-[55vh] overflow-y-auto">
                <table className="w-full font-mono text-xs">
                  <thead className="bg-[#0a0a0a] sticky top-0">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                      <th className="px-4 py-2">Feature</th>
                      <th className="px-4 py-2">Version</th>
                      <th className="px-4 py-2">User</th>
                      <th className="px-4 py-2">Host</th>
                      <th className="px-4 py-2 text-right">PID</th>
                      <th className="px-4 py-2 text-right">Since</th>
                      {isAdmin && <th className="px-4 py-2 text-right">Action</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {checkouts.map((r) => (
                      <tr key={r.id} className="border-t border-[#1a1a1a] hover:bg-[#1a1a1a]">
                        <td className="px-4 py-2 text-white">{r.feature}</td>
                        <td className="px-4 py-2 text-[#9ca3af]">{r.version}</td>
                        <td className="px-4 py-2 text-emerald-400">{r.user}</td>
                        <td className="px-4 py-2 text-[#9ca3af]">{r.host}</td>
                        <td className="px-4 py-2 text-right text-[#9ca3af] tabular-nums">{r.pid}</td>
                        <td className="px-4 py-2 text-right text-[#9ca3af] tabular-nums">{fmtAgo(r.checkout_time)}</td>
                        {isAdmin && (
                          <td className="px-4 py-2 text-right">
                            <button
                              onClick={() => killCheckout(r)}
                              disabled={killing === r.id}
                              className="inline-flex items-center gap-1 px-2 py-1 border border-red-900/60 text-red-400 hover:bg-red-900/20 text-[10px] uppercase tracking-wider disabled:opacity-50"
                              data-testid={`detail-kill-${r.id}`}
                            >
                              {killing === r.id ? "…" : "KILL"}
                            </button>
                          </td>
                        )}
                      </tr>
                    ))}
                    {checkouts.length === 0 && (
                      <tr>
                        <td colSpan={isAdmin ? 7 : 6} className="px-4 py-10 text-center text-[#6b7280]">
                          {"// no active checkouts"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="license" className="mt-4">
            <EditorPanel
              title={`LICENSE FILE · ${server.name}`}
              dirty={licDirty}
              onSave={saveLicense}
              testId="license-panel"
              saveTestId="save-license-btn"
              saveLabel="SAVE & PUSH"
              extraActions={
                isAdmin ? (
                  <button
                    className="btn-brutal flex items-center gap-1.5"
                    onClick={fetchLicenseFromServer}
                    data-testid="fetch-license-btn"
                    title="Read the actual license file from the configured license_file_path"
                  >
                    <Download size={12} /> FETCH FROM SERVER
                  </button>
                ) : null
              }
            >
              <CodeEditor
                value={licText}
                onChange={(v) => {
                  setLicText(v);
                  setLicDirty(true);
                }}
                language="license"
                testId="license-editor"
              />
              {!server.license_file_path && isAdmin && (
                <div className="mt-3 px-3 py-2 border border-amber-900/40 bg-amber-900/10 font-mono text-[10px] text-amber-400">
                  ⚠ <b>license_file_path</b> is not set on this server. Save&nbsp;&amp;&nbsp;Push will
                  store the edited file in LICMAN&apos;s database only — it will NOT update the file
                  on disk and the daemon won&apos;t see your changes. Click <b>edit paths</b> at
                  the top of the page to point to the real file (e.g.{" "}
                  <code className="text-white">/cadmgr/cadence/license.dat</code>).
                </div>
              )}
            </EditorPanel>
          </TabsContent>

          <TabsContent value="options" className="mt-4">
            <EditorPanel
              title={`OPTIONS FILE · ${server.daemon}.opt`}
              dirty={optDirty}
              onSave={saveOptions}
              testId="options-panel"
              saveTestId="save-options-btn"
              saveLabel="SAVE & PUSH"
              hint="Directives: RESERVE | INCLUDE | EXCLUDE | GROUP | MAX | TIMEOUT"
              extraActions={
                <>
                  {isAdmin && (
                    <button
                      className="btn-brutal flex items-center gap-1.5"
                      onClick={fetchOptionsFromServer}
                      data-testid="fetch-options-btn"
                      title="Read the actual options file from options_file_path + import RESERVE lines into the reservations table"
                    >
                      <Download size={12} /> FETCH FROM SERVER
                    </button>
                  )}
                  <button
                    onClick={validateOpts}
                    disabled={validating}
                    className="btn-brutal flex items-center gap-1.5 disabled:opacity-50"
                    data-testid="validate-options-btn"
                    title="Lint the options file against FlexLM directive syntax"
                  >
                    <ListChecks size={12} />
                    {validating ? "VALIDATING…" : "VALIDATE"}
                  </button>
                </>
              }
            >
              <CodeEditor
                value={optText}
                onChange={(v) => {
                  setOptText(v);
                  setOptDirty(true);
                  setOptValidation(null);
                }}
                language="options"
                testId="options-editor"
              />
              {!server.options_file_path && isAdmin && (
                <div className="mt-3 px-3 py-2 border border-amber-900/40 bg-amber-900/10 font-mono text-[10px] text-amber-400">
                  ⚠ <b>options_file_path</b> is not set. Save&nbsp;&amp;&nbsp;Push will store the
                  file in LICMAN&apos;s database only — point to your real options file via the
                  edit-paths link at the top, then FETCH FROM SERVER to import what&apos;s
                  currently in production.
                </div>
              )}
              {optValidation && (
                <div
                  className="mt-3 border border-[#222] bg-[#0a0a0a] rounded-sm"
                  data-testid="options-validation-result"
                >
                  <div className="px-3 py-2 border-b border-[#222] flex items-center justify-between flex-wrap gap-2 font-mono text-[10px] uppercase tracking-wider">
                    <span className="text-[#9ca3af]">VALIDATION</span>
                    <div className="flex items-center gap-3">
                      <span
                        className="font-bold"
                        style={{ color: optValidation.ok ? "#10b981" : "#ef4444" }}
                      >
                        {optValidation.ok ? "PASS" : "FAIL"}
                      </span>
                      <span className="text-red-400">{optValidation.errors} err</span>
                      <span className="text-amber-400">{optValidation.warnings} warn</span>
                      <span className="text-[#6b7280]">
                        · RES {optValidation.summary.reserve} · GRP {optValidation.summary.group} ·
                        INC {optValidation.summary.include} · EXC {optValidation.summary.exclude} ·
                        MAX {optValidation.summary.max} · TO {optValidation.summary.timeout}
                      </span>
                    </div>
                  </div>
                  <div className="max-h-48 overflow-y-auto">
                    {optValidation.issues.length === 0 ? (
                      <div className="px-3 py-3 font-mono text-[11px] text-emerald-400">
                        ✓ no issues — directives parse cleanly
                      </div>
                    ) : (
                      <table className="w-full font-mono text-[11px]">
                        <tbody>
                          {optValidation.issues.map((iss, i) => (
                            <tr
                              key={i}
                              className="border-t border-[#1a1a1a]"
                              data-testid={`options-issue-${i}`}
                            >
                              <td className="px-3 py-1.5 text-[#6b7280] w-16 tabular-nums">
                                line {iss.line}
                              </td>
                              <td
                                className="px-2 py-1.5 uppercase text-[10px] tracking-wider w-20"
                                style={{
                                  color: iss.severity === "error" ? "#ef4444" : "#f59e0b",
                                }}
                              >
                                {iss.severity}
                              </td>
                              <td className="px-3 py-1.5 text-white">{iss.message}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </div>
              )}
            </EditorPanel>
          </TabsContent>

          <TabsContent value="reservations" className="mt-4">
            <div className="bg-[#111] border border-[#222] rounded-sm">
              <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
                  RESERVATIONS · {server.name}
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={syncReservations}
                    className="btn-brutal flex items-center gap-1.5"
                    data-testid="sync-reservations-btn"
                    title="Merge reservations into options file on disk + lmreread (requires options_file_path set on this server)"
                  >
                    <RefreshCw size={12} /> APPLY TO LMGRD
                  </button>
                  <button
                    onClick={() => setResDialogOpen(true)}
                    className="btn-brutal primary flex items-center gap-1.5"
                    data-testid="add-reservation-btn"
                  >
                    <Plus size={12} /> NEW RESERVATION
                  </button>
                </div>
              </div>
              {!server.options_file_path && (
                <div className="px-4 py-2 border-b border-amber-900/40 bg-amber-900/10 font-mono text-[10px] text-amber-400">
                  ⚠ options_file_path is not set on this server — reservations are stored in
                  LICMAN&apos;s database but NOT pushed to your running lmgrd&apos;s options
                  file. Click <b>edit paths</b> above and point to{" "}
                  <code className="text-white">/cadmgr/cadence/options.txt</code> (or wherever
                  your file lives) to enable automatic push + lmreread.
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full font-mono text-xs">
                  <thead className="bg-[#0a0a0a]">
                    <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                      <th className="px-4 py-2">Feature</th>
                      <th className="px-4 py-2">Type</th>
                      <th className="px-4 py-2">Target</th>
                      <th className="px-4 py-2 text-right">Count</th>
                      <th className="px-4 py-2">Added</th>
                      <th className="px-4 py-2 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reservations.map((r) => (
                      <tr key={r.id} className="border-t border-[#1a1a1a] hover:bg-[#1a1a1a]">
                        <td className="px-4 py-2 text-white">{r.feature}</td>
                        <td className="px-4 py-2">
                          <span className="text-[10px] uppercase tracking-wider font-bold text-[#3b82f6]">
                            {r.target_type}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-emerald-400">{r.target}</td>
                        <td className="px-4 py-2 text-right tabular-nums">{r.count}</td>
                        <td className="px-4 py-2 text-[#9ca3af]">{fmtAgo(r.created_at)}</td>
                        <td className="px-4 py-2 text-right">
                          <button
                            className="btn-brutal danger text-[10px] py-1"
                            onClick={() => removeRes(r.id)}
                            data-testid={`delete-reservation-${r.id}`}
                          >
                            <Trash2 size={11} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {reservations.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-10 text-center text-[#6b7280]">
                          {"// no reservations defined"}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="ssh" className="mt-4">
            <SshConfigPanel server={server} onChange={load} />
          </TabsContent>

          <TabsContent value="audit" className="mt-4">
            <AuditTimeline rows={audit} />
          </TabsContent>
        </Tabs>
      </main>

      <ReservationDialog
        open={resDialogOpen}
        onOpenChange={setResDialogOpen}
        server={server}
        onCreated={load}
      />

      {/* Feature detail drawer */}
      {selectedFeature && (
        <FeatureDetailModal
          feature={server.features?.find((x) => x.name === selectedFeature)}
          server={server}
          checkouts={checkouts.filter((c) => c.feature === selectedFeature)}
          reservations={reservations.filter((r) => r.feature === selectedFeature)}
          onClose={() => setSelectedFeature(null)}
          onKill={killCheckout}
          killing={killing}
          canKill={isAdmin}
        />
      )}
    </div>
  );
}

const FeatureDetailModal = ({ feature, server, checkouts, reservations, onClose, onKill, killing, canKill }) => {
  if (!feature) return null;
  // Same calculation as the row: sum multi-seat checkouts + reserved seats,
  // and take the max against lmstat's authoritative `in use` reading.
  const sumCheckouts = checkouts.reduce((s, c) => s + (c.count || 1), 0);
  const sumReservations = reservations.reduce((s, r) => s + (r.count || 1), 0);
  const reported = feature.in_use_reported || 0;
  const used = Math.max(sumCheckouts + sumReservations, reported);
  const pct = Math.min(100, Math.round((used / Math.max(1, feature.total)) * 100));
  const color = pct > 80 ? "#ef4444" : pct > 50 ? "#f59e0b" : "#10b981";
  return (
    <div
      className="fixed inset-0 z-50 bg-black/70 flex items-end sm:items-center justify-center p-4"
      onClick={onClose}
      data-testid="feature-detail-modal"
    >
      <div
        className="bg-[#0a0a0a] border border-[#222] rounded-sm max-w-4xl w-full max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-4 border-b border-[#222] flex items-start justify-between gap-4">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              {server.name} · {server.vendor}
            </div>
            <h2 className="font-mono text-xl font-bold mt-1">{feature.name}</h2>
            <div className="font-mono text-[11px] text-[#9ca3af] mt-0.5">
              v{feature.version} · expires {feature.expires}
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-[#9ca3af] hover:text-white font-mono text-sm"
            data-testid="feature-modal-close"
          >
            ✕ CLOSE
          </button>
        </div>

        <div className="grid grid-cols-3 gap-3 px-5 py-4 border-b border-[#222] font-mono text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[#6b7280]">SEATS</div>
            <div className="text-2xl font-bold tabular-nums mt-1">{feature.total}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[#6b7280]">IN USE</div>
            <div className="text-2xl font-bold tabular-nums mt-1" style={{ color }}>
              {used}
            </div>
            <div className="text-[9px] text-[#6b7280] mt-1 uppercase tracking-wider">
              {sumCheckouts} active · {sumReservations} reserved
              {reported > sumCheckouts + sumReservations && ` · ${reported} reported`}
            </div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-[#6b7280]">UTILIZATION</div>
            <div className="flex items-center gap-2 mt-2">
              <div className="flex-1 h-2 bg-[#1a1a1a] rounded-sm overflow-hidden">
                <div className="h-full" style={{ width: `${pct}%`, background: color }} />
              </div>
              <span className="tabular-nums">{pct}%</span>
            </div>
          </div>
        </div>

        <div className="px-5 py-3 font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
          ACTIVE CHECKOUTS · {checkouts.length}
        </div>
        <div className="overflow-x-auto">
          <table className="w-full font-mono text-xs">
            <thead className="bg-[#0d0d0d]">
              <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                <th className="px-4 py-2">User</th>
                <th className="px-4 py-2">Host</th>
                <th className="px-4 py-2">Display</th>
                <th className="px-4 py-2 text-right">PID</th>
                <th className="px-4 py-2 text-right">Since</th>
                {canKill && <th className="px-4 py-2 text-right">Action</th>}
              </tr>
            </thead>
            <tbody>
              {checkouts.map((c) => (
                <tr key={c.id} className="border-t border-[#1a1a1a] hover:bg-[#141414]">
                  <td className="px-4 py-2 text-emerald-400">{c.user}</td>
                  <td className="px-4 py-2 text-[#9ca3af]">{c.host}</td>
                  <td className="px-4 py-2 text-[#6b7280]">{c.display}</td>
                  <td className="px-4 py-2 text-right tabular-nums">{c.pid}</td>
                  <td className="px-4 py-2 text-right text-[#9ca3af]">{fmtAgo(c.checkout_time)}</td>
                  {canKill && (
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => onKill(c)}
                        disabled={killing === c.id}
                        className="inline-flex items-center gap-1 px-2 py-1 border border-red-900/60 text-red-400 hover:bg-red-900/20 text-[10px] uppercase tracking-wider disabled:opacity-50"
                        data-testid={`feature-kill-${c.id}`}
                      >
                        {killing === c.id ? "…" : "KILL"}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {checkouts.length === 0 && (
                <tr>
                  <td colSpan={canKill ? 6 : 5} className="px-4 py-8 text-center text-[#6b7280]">
                    {"// idle — nobody is using this feature right now"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {reservations.length > 0 && (
          <>
            <div className="px-5 py-3 border-t border-[#222] font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              RESERVATIONS · {reservations.length}
            </div>
            <ul className="px-5 pb-5 font-mono text-xs space-y-1">
              {reservations.map((r) => (
                <li key={r.id} className="text-[#9ca3af]">
                  <span className="text-[#3b82f6] font-bold">{r.target_type}</span>{" "}
                  <span className="text-white">{r.target}</span> · {r.count} seat(s)
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
};

const EditorPanel = ({ title, dirty, onSave, children, testId, saveTestId, hint, extraActions, saveLabel }) => (
  <div className="bg-[#111] border border-[#222] rounded-sm" data-testid={testId}>
    <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between flex-wrap gap-2">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">{title}</div>
        {hint && <div className="font-mono text-[10px] text-[#6b7280] mt-0.5">{hint}</div>}
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        {extraActions}
        {dirty && (
          <span className="font-mono text-[10px] text-[#f59e0b] uppercase tracking-wider" data-testid="editor-dirty-flag">
            ● UNSAVED
          </span>
        )}
        <button
          className="btn-brutal primary flex items-center gap-1.5"
          onClick={onSave}
          disabled={!dirty}
          data-testid={saveTestId || `${testId}-save`}
        >
          <Save size={12} /> {saveLabel || "SAVE & APPLY"}
        </button>
      </div>
    </div>
    <div className="p-3">{children}</div>
  </div>
);
