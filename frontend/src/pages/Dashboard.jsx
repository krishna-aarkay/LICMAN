import { useEffect, useState, useCallback } from "react";
import { Plus } from "lucide-react";
import { api } from "@/lib/api";
import { prefs } from "@/lib/prefs";
import Header from "@/components/Header";
import ServerCard from "@/components/ServerCard";
import CheckoutTable from "@/components/CheckoutTable";
import AuditTimeline from "@/components/AuditTimeline";
import AddServerDialog from "@/components/AddServerDialog";
import { toast } from "sonner";

export default function Dashboard() {
  const initial = prefs.load();
  const [servers, setServers] = useState([]);
  const [checkouts, setCheckouts] = useState([]);
  const [audit, setAudit] = useState([]);
  const [stats, setStats] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(initial.autoRefresh);
  const [addOpen, setAddOpen] = useState(false);

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

  const handleReset = async () => {
    try {
      await api.resetSeed();
      toast.success("Demo data reseeded");
      load();
    } catch {
      toast.error("Reset failed");
    }
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="dashboard-page">
      <Header
        stats={stats}
        autoRefresh={autoRefresh}
        onToggleRefresh={toggleRefresh}
        onReset={handleReset}
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
            <button
              onClick={() => setAddOpen(true)}
              className="btn-brutal primary flex items-center gap-2"
              data-testid="add-server-btn"
            >
              <Plus size={14} /> ADD SERVER
            </button>
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
          <CheckoutTable rows={checkouts} servers={servers} />
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
