import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { Calendar, Search } from "lucide-react";
import { api, VENDOR_META } from "@/lib/api";
import Header from "@/components/Header";
import ExpiryBadge from "@/components/ExpiryBadge";

export default function Expiry() {
  const [rows, setRows] = useState([]);
  const [stats, setStats] = useState(null);
  const [q, setQ] = useState("");
  const [vendorFilter, setVendorFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");

  useEffect(() => {
    api.expiry(180).then(setRows);
    api.stats().then(setStats);
  }, []);

  const grouped = useMemo(() => {
    const filtered = rows.filter((r) => {
      if (vendorFilter !== "ALL" && r.vendor !== vendorFilter) return false;
      if (statusFilter !== "ALL" && r.status !== statusFilter) return false;
      if (q && !`${r.feature} ${r.server_name}`.toLowerCase().includes(q.toLowerCase()))
        return false;
      return true;
    });
    return filtered;
  }, [rows, vendorFilter, statusFilter, q]);

  const summary = useMemo(() => {
    return rows.reduce(
      (acc, r) => {
        acc[r.status] = (acc[r.status] || 0) + 1;
        return acc;
      },
      {}
    );
  }, [rows]);

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="expiry-page">
      <Header stats={stats} autoRefresh={false} onToggleRefresh={() => {}} />

      <main className="max-w-[1500px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              /// LICENSE CALENDAR
            </div>
            <h1 className="font-mono text-2xl font-bold tracking-tight mt-1 flex items-center gap-2">
              <Calendar size={22} /> Expiry Timeline
            </h1>
          </div>

          {/* Summary tiles */}
          <div className="flex items-center gap-2 font-mono text-[11px]">
            <Tile label="EXPIRED" n={summary.expired || 0} color="#ef4444" />
            <Tile label="CRITICAL" n={summary.critical || 0} color="#ef4444" />
            <Tile label="WARN" n={summary.warning || 0} color="#f59e0b" />
            <Tile label="OK" n={summary.ok || 0} color="#10b981" />
            <Tile label="PERMANENT" n={summary.permanent || 0} color="#6b7280" />
          </div>
        </div>

        {/* Toolbar */}
        <div className="bg-[#111] border border-[#222] rounded-sm">
          <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222]">
              {["ALL", "cadence", "synopsys", "mentor"].map((v) => (
                <button
                  key={v}
                  onClick={() => setVendorFilter(v)}
                  className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                    vendorFilter === v ? "bg-white text-black" : "text-[#9ca3af] hover:text-white"
                  }`}
                  data-testid={`expiry-filter-${v}`}
                >
                  {v}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222]">
              {["ALL", "expired", "critical", "warning", "ok", "permanent"].map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                    statusFilter === s ? "bg-white text-black" : "text-[#9ca3af] hover:text-white"
                  }`}
                  data-testid={`expiry-status-${s}`}
                >
                  {s}
                </button>
              ))}
            </div>
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[#6b7280]" />
              <input
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="search feature / server"
                className="bg-[#0a0a0a] border border-[#222] pl-7 pr-3 py-1 font-mono text-xs text-white w-72"
                data-testid="expiry-search"
              />
            </div>
          </div>

          <div className="overflow-x-auto max-h-[68vh] overflow-y-auto">
            <table className="w-full font-mono text-xs">
              <thead className="bg-[#0a0a0a] sticky top-0 z-10">
                <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                  <th className="px-4 py-2">Vendor</th>
                  <th className="px-4 py-2">Feature</th>
                  <th className="px-4 py-2">Server</th>
                  <th className="px-4 py-2">Version</th>
                  <th className="px-4 py-2 text-right">Seats</th>
                  <th className="px-4 py-2">Expires</th>
                  <th className="px-4 py-2 text-right">Days</th>
                  <th className="px-4 py-2 text-right">Status</th>
                </tr>
              </thead>
              <tbody>
                {grouped.map((r, i) => {
                  const meta = VENDOR_META[r.vendor];
                  return (
                    <tr
                      key={`${r.server_id}-${r.feature}`}
                      className={`border-t border-[#1a1a1a] hover:bg-[#1a1a1a] ${i % 2 ? "bg-[#0d0d0d]" : ""}`}
                      data-testid={`expiry-row-${r.feature}-${r.server_id}`}
                    >
                      <td className="px-4 py-2">
                        <span className="text-[10px] uppercase tracking-wider font-bold" style={{ color: meta.color }}>
                          {meta.label.split(" ")[0]}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-white">{r.feature}</td>
                      <td className="px-4 py-2">
                        <Link to={`/servers/${r.server_id}`} className="text-emerald-400 hover:underline">
                          {r.server_name}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-[#9ca3af]">{r.version}</td>
                      <td className="px-4 py-2 text-right tabular-nums">{r.total}</td>
                      <td className="px-4 py-2 text-[#9ca3af]">{r.expires}</td>
                      <td className="px-4 py-2 text-right tabular-nums">
                        {r.days_remaining === null ? "—" : r.days_remaining}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <ExpiryBadge days={r.days_remaining} expires={r.expires} />
                      </td>
                    </tr>
                  );
                })}
                {grouped.length === 0 && (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-[#6b7280]">
                      {"// no matching features"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}

const Tile = ({ label, n, color }) => (
  <div
    className="border border-[#222] bg-[#111] px-3 py-1.5 flex items-center gap-2"
    data-testid={`expiry-tile-${label.toLowerCase()}`}
  >
    <span className="uppercase tracking-wider text-[#6b7280]">{label}</span>
    <span className="font-bold tabular-nums" style={{ color }}>
      {n}
    </span>
  </div>
);
