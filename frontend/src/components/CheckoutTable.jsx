import { useEffect, useMemo, useState } from "react";
import { Search } from "lucide-react";
import { fmtAgo, VENDOR_META } from "@/lib/api";
import { prefs } from "@/lib/prefs";

export const CheckoutTable = ({ rows, servers }) => {
  const initial = prefs.load();
  const [q, setQ] = useState(initial.searchQuery || "");
  const [vendorFilter, setVendorFilter] = useState(initial.vendorFilter || "ALL");

  useEffect(() => {
    prefs.save({ vendorFilter, searchQuery: q });
  }, [vendorFilter, q]);

  const serverMap = useMemo(() => {
    const m = {};
    (servers || []).forEach((s) => (m[s.id] = s));
    return m;
  }, [servers]);

  const filtered = useMemo(() => {
    return (rows || []).filter((r) => {
      const s = serverMap[r.server_id];
      if (vendorFilter !== "ALL" && s?.vendor !== vendorFilter) return false;
      if (!q) return true;
      const blob = `${r.feature} ${r.user} ${r.host} ${r.version} ${s?.name || ""}`.toLowerCase();
      return blob.includes(q.toLowerCase());
    });
  }, [rows, q, vendorFilter, serverMap]);

  return (
    <div
      className="bg-[#111] border border-[#222] rounded-sm"
      data-testid="checkouts-table"
    >
      {/* toolbar */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#222]">
        <div className="flex items-center gap-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
            LIVE CHECKOUTS
          </div>
          <span className="font-mono text-xs text-emerald-400 tabular-nums">
            [{filtered.length}]
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222]">
            {["ALL", "cadence", "synopsys", "mentor"].map((v) => (
              <button
                key={v}
                onClick={() => setVendorFilter(v)}
                className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                  vendorFilter === v
                    ? "bg-white text-black"
                    : "text-[#9ca3af] hover:text-white"
                }`}
                data-testid={`filter-vendor-${v}`}
              >
                {v}
              </button>
            ))}
          </div>
          <div className="relative">
            <Search
              size={12}
              className="absolute left-2 top-1/2 -translate-y-1/2 text-[#6b7280]"
            />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="search feature / user / host"
              className="bg-[#0a0a0a] border border-[#222] pl-7 pr-3 py-1 font-mono text-xs text-white w-64 focus:outline-none focus:border-[#444]"
              data-testid="checkout-search"
            />
          </div>
        </div>
      </div>

      {/* table */}
      <div className="overflow-x-auto max-h-[60vh] overflow-y-auto">
        <table className="w-full font-mono text-xs">
          <thead className="bg-[#0a0a0a] sticky top-0 z-10">
            <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
              <th className="px-4 py-2 font-medium">Vendor</th>
              <th className="px-4 py-2 font-medium">Feature</th>
              <th className="px-4 py-2 font-medium">Version</th>
              <th className="px-4 py-2 font-medium">User</th>
              <th className="px-4 py-2 font-medium">Host</th>
              <th className="px-4 py-2 font-medium">Display</th>
              <th className="px-4 py-2 font-medium text-right">PID</th>
              <th className="px-4 py-2 font-medium text-right">Since</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((r, i) => {
              const s = serverMap[r.server_id];
              const meta = s ? VENDOR_META[s.vendor] : null;
              return (
                <tr
                  key={r.id}
                  className={`border-t border-[#1a1a1a] hover:bg-[#1a1a1a] ${
                    i % 2 === 0 ? "" : "bg-[#0d0d0d]"
                  }`}
                  data-testid={`checkout-row-${r.id}`}
                >
                  <td className="px-4 py-2">
                    {meta && (
                      <span
                        className="text-[10px] uppercase tracking-wider font-bold"
                        style={{ color: meta.color }}
                      >
                        {meta.label.split(" ")[0]}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-white">{r.feature}</td>
                  <td className="px-4 py-2 text-[#9ca3af]">{r.version}</td>
                  <td className="px-4 py-2">
                    <span className="text-emerald-400">{r.user}</span>
                  </td>
                  <td className="px-4 py-2 text-[#9ca3af]">{r.host}</td>
                  <td className="px-4 py-2 text-[#6b7280]">{r.display}</td>
                  <td className="px-4 py-2 text-right text-[#9ca3af] tabular-nums">
                    {r.pid}
                  </td>
                  <td className="px-4 py-2 text-right text-[#9ca3af] tabular-nums">
                    {fmtAgo(r.checkout_time)}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="px-4 py-12 text-center text-[#6b7280] font-mono text-xs"
                >
                  {"// no active checkouts match current filters"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default CheckoutTable;
