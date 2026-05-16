import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { ArrowLeft, FileText, Settings, ListChecks, Save, Plus, Trash2, RefreshCw, Power, Activity } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api, VENDOR_META, fmtAgo } from "@/lib/api";
import Header from "@/components/Header";
import CodeEditor from "@/components/CodeEditor";
import AuditTimeline from "@/components/AuditTimeline";
import ReservationDialog from "@/components/ReservationDialog";
import { toast } from "sonner";

export default function ServerDetail() {
  const { id } = useParams();
  const [server, setServer] = useState(null);
  const [licText, setLicText] = useState("");
  const [optText, setOptText] = useState("");
  const [licDirty, setLicDirty] = useState(false);
  const [optDirty, setOptDirty] = useState(false);
  const [checkouts, setCheckouts] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [audit, setAudit] = useState([]);
  const [resDialogOpen, setResDialogOpen] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [stats, setStats] = useState(null);

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

  const meta = VENDOR_META[server.vendor];
  const isUp = server.status === "up";

  const saveLicense = async () => {
    try {
      const r = await api.saveLicense(id, licText);
      toast.success(`License saved · ${r.features_parsed} features parsed`);
      setLicDirty(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const saveOptions = async () => {
    try {
      await api.saveOptions(id, optText);
      toast.success("Options saved");
      setOptDirty(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
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

  const inUse = (featName) =>
    checkouts.filter((c) => c.feature === featName).length;

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="server-detail-page">
      <Header
        stats={stats}
        autoRefresh={autoRefresh}
        onToggleRefresh={() => setAutoRefresh((v) => !v)}
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
            </div>

            <div className="flex flex-wrap gap-2">
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
            </div>
          </div>

          {/* features mini grid */}
          <div className="mt-5 grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
            {(server.features || []).map((f) => {
              const used = inUse(f.name);
              const pct = Math.min(100, Math.round((used / Math.max(1, f.total)) * 100));
              return (
                <div
                  key={f.name}
                  className="border border-[#222] bg-[#0a0a0a] p-3"
                  data-testid={`feature-cell-${f.name}`}
                >
                  <div className="font-mono text-xs text-white truncate">{f.name}</div>
                  <div className="font-mono text-[10px] text-[#6b7280] mt-0.5">v{f.version}</div>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="font-mono text-lg font-bold tabular-nums text-emerald-400">
                      {used}
                    </span>
                    <span className="font-mono text-[10px] text-[#6b7280]">/ {f.total}</span>
                  </div>
                  <div className="mt-2 h-[3px] bg-[#1a1a1a]">
                    <div
                      className="h-full transition-all"
                      style={{
                        width: `${pct}%`,
                        background: pct > 80 ? "#ef4444" : pct > 50 ? "#f59e0b" : "#10b981",
                      }}
                    />
                  </div>
                </div>
              );
            })}
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
                      </tr>
                    ))}
                    {checkouts.length === 0 && (
                      <tr>
                        <td colSpan={6} className="px-4 py-10 text-center text-[#6b7280]">
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
            </EditorPanel>
          </TabsContent>

          <TabsContent value="options" className="mt-4">
            <EditorPanel
              title={`OPTIONS FILE · ${server.daemon}.opt`}
              dirty={optDirty}
              onSave={saveOptions}
              testId="options-panel"
              saveTestId="save-options-btn"
              hint="Directives: RESERVE | INCLUDE | EXCLUDE | GROUP | MAX | TIMEOUT"
            >
              <CodeEditor
                value={optText}
                onChange={(v) => {
                  setOptText(v);
                  setOptDirty(true);
                }}
                language="options"
                testId="options-editor"
              />
            </EditorPanel>
          </TabsContent>

          <TabsContent value="reservations" className="mt-4">
            <div className="bg-[#111] border border-[#222] rounded-sm">
              <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
                <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
                  RESERVATIONS · {server.name}
                </div>
                <button
                  onClick={() => setResDialogOpen(true)}
                  className="btn-brutal primary flex items-center gap-1.5"
                  data-testid="add-reservation-btn"
                >
                  <Plus size={12} /> NEW RESERVATION
                </button>
              </div>
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
    </div>
  );
}

const EditorPanel = ({ title, dirty, onSave, children, testId, saveTestId, hint }) => (
  <div className="bg-[#111] border border-[#222] rounded-sm" data-testid={testId}>
    <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
      <div>
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">{title}</div>
        {hint && <div className="font-mono text-[10px] text-[#6b7280] mt-0.5">{hint}</div>}
      </div>
      <div className="flex items-center gap-2">
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
          <Save size={12} /> SAVE & APPLY
        </button>
      </div>
    </div>
    <div className="p-3">{children}</div>
  </div>
);
