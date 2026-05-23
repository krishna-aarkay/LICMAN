import { useEffect, useState, useCallback } from "react";
import { Plus, RefreshCw, Zap } from "lucide-react";
import { api } from "@/lib/api";
import { prefs } from "@/lib/prefs";
import { useAuth } from "@/contexts/AuthContext";
import Header from "@/components/Header";
import ServerCard from "@/components/ServerCard";
import CheckoutTable from "@/components/CheckoutTable";
import AuditTimeline from "@/components/AuditTimeline";
import AddServerDialog from "@/components/AddServerDialog";
import { toast } from "sonner";

export default function Dashboard() {
  const initial = prefs.load();
  const { isAdmin } = useAuth();
  const [servers, setServers] = useState([]);
  const [checkouts, setCheckouts] = useState([]);
  const [audit, setAudit] = useState([]);
  const [stats, setStats] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(initial.autoRefresh);
  const [addOpen, setAddOpen] = useState(false);
  const [busyBulk, setBusyBulk] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, c, a, st] = await Promise.all([
        api.listServers(),
        api.allCheckouts(),
        api.audit(40),
        api.stats(),
      ]);
      setServers(s);
      setCheckouts(c);
      setAudit(a);
      setStats(st);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [autoRefresh, load]);

  const toggleRefresh = () => {
    setAutoRefresh((v) => {
      const nv = !v;
      prefs.save({ autoRefresh: nv });
      return nv;
    });
  };

  const handleClearHistory = async () => {
    if (!window.confirm(
      "Clear transient history (live checkouts, alerts, audit log, usage)?\n\n" +
      "Your servers, SSH credentials, reservations and priority rules are PRESERVED."
    )) return;
    try {
      await api.clearHistory();
      toast.success("History cleared · servers preserved");
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Clear failed");
    }
  };

  const handleSyncAll = async () => {
    setBusyBulk("sync");
    try {
      const r = await api.syncAll();
      if (r.count === 0) {
        toast.info("No SSH-enabled servers to sync");
      } else {
        toast.success(
          `Synced ${r.count} server(s) · ${r.features_total} features · ${r.checkouts_total} checkouts`
        );
      }
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk sync failed");
    } finally {
      setBusyBulk(null);
    }
  };

  const handleRereadAll = async () => {
    setBusyBulk("reread");
    try {
      const r = await api.rereadAll();
      toast.success(`lmreread issued to ${r.count} server(s)`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Bulk lmreread failed");
    } finally {
      setBusyBulk(null);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="dashboard-page">
      <Header
        stats={stats}
        autoRefresh={autoRefresh}
        onToggleRefresh={toggleRefresh}
        onReset={handleClearHistory}
      />

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-6">
        {/* Hero / status row */}
        <section>
          <div className="flex items-end justify-between mb-3">
            <div>
              <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
                /// LICENSE SERVERS
              </div>
              <h1 className="font-mono text-2xl font-bold tracking-tight mt-1">
                Control Room
              </h1>
            </div>
            <div className="flex items-center gap-2">
              {isAdmin && servers.length > 0 && (
                <>
                  <button
                    onClick={handleSyncAll}
                    disabled={busyBulk !== null}
                    className="btn-brutal flex items-center gap-2 disabled:opacity-50"
                    data-testid="sync-all-btn"
                    title="Run lmstat across every SSH-enabled server"
                  >
                    <RefreshCw size={12} className={busyBulk === "sync" ? "animate-spin" : ""} />
                    {busyBulk === "sync" ? "SYNCING…" : "SYNC ALL"}
                  </button>
                  <button
                    onClick={handleRereadAll}
                    disabled={busyBulk !== null}
                    className="btn-brutal flex items-center gap-2 disabled:opacity-50"
                    data-testid="reread-all-btn"
                    title="Issue lmreread to every server"
                  >
                    <Zap size={12} />
                    {busyBulk === "reread" ? "RUNNING…" : "REREAD ALL"}
                  </button>
                </>
              )}
              <button
                onClick={() => setAddOpen(true)}
                className="btn-brutal primary flex items-center gap-2"
                data-testid="add-server-btn"
              >
                <Plus size={14} /> ADD SERVER
              </button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {servers.map((s) => (
              <ServerCard key={s.id} server={s} onChange={load} />
            ))}
            {servers.length === 0 && (
              <div className="col-span-full border border-dashed border-[#222] p-10 text-center font-mono text-xs text-[#6b7280]">
                no license servers registered. click ADD SERVER to begin.
              </div>
            )}
          </div>
        </section>

        {/* Main grid */}
        <section className="grid grid-cols-1 xl:grid-cols-[1fr_420px] gap-6">
          <CheckoutTable rows={checkouts} servers={servers} onChange={load} />
          <AuditTimeline rows={audit} />
        </section>

        {/* Footer */}
        <footer className="pt-8 pb-12 border-t border-[#1a1a1a] mt-12">
          <div className="font-mono text-[10px] text-[#4b5563] uppercase tracking-[0.3em] flex items-center justify-between flex-wrap gap-3">
            <span>LICMAN · vlsi license console</span>
            <span>
              {"// auto-refresh"} <span className="text-emerald-400">{autoRefresh ? "ON" : "OFF"}</span>{" "}
              · interval 10s
            </span>
          </div>
        </footer>
      </main>

      <AddServerDialog open={addOpen} onOpenChange={setAddOpen} onCreated={load} />
    </div>
  );
}
