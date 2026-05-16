import { useEffect, useMemo, useState } from "react";
import { Search, X, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { api, fmtAgo, vendorMeta, fmtDateTime } from "@/lib/api";
import { prefs } from "@/lib/prefs";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

export const CheckoutTable = ({ rows, servers, onChange }) => {
  const initial = prefs.load();
  const { isAdmin } = useAuth();
  const [q, setQ] = useState(initial.searchQuery || "");
  const [vendorFilter, setVendorFilter] = useState(initial.vendorFilter || "ALL");
  const [tz, setTz] = useState(initial.tz || "IST");
  const [sort, setSort] = useState({ col: "checkout_time", dir: "desc" });
  const [killing, setKilling] = useState(null);

  useEffect(() => {
    prefs.save({ vendorFilter, searchQuery: q });
  }, [vendorFilter, q]);

  useEffect(() => {
    const h = (e) => setTz(e.detail);
    window.addEventListener("licman:tz", h);
    return () => window.removeEventListener("licman:tz", h);
  }, []);

  const serverMap = useMemo(() => {
    const m = {};
    (servers || []).forEach((s) => (m[s.id] = s));
    return m;
  }, [servers]);

  const vendors = useMemo(() => {
    const set = new Set((servers || []).map((s) => s.vendor).filter(Boolean));
    return ["ALL", ...Array.from(set).sort()];
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

  const sorted = useMemo(() => {
    const out = [...filtered];
    const { col, dir } = sort;
    const mult = dir === "asc" ? 1 : -1;
    out.sort((a, b) => {
      const av = a[col] ?? "";
      const bv = b[col] ?? "";
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
      return String(av).localeCompare(String(bv)) * mult;
    });
    return out;
  }, [filtered, sort]);

  const toggleSort = (col) =>
    setSort((cur) => (cur.col === col ? { col, dir: cur.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" }));

  const sortIcon = (col) => {
    if (sort.col !== col) return <ArrowUpDown size={10} className="opacity-40" />;
    return sort.dir === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />;
  };

  const handleKill = async (r) => {
    if (!window.confirm(`Force-release ${r.feature} held by ${r.user}@${r.host}?\nThis runs lmremove on the license server.`)) {
      return;
    }
    setKilling(r.id);
    try {
      const res = await api.killCheckout(r.server_id, {
        feature: r.feature, user: r.user, host: r.host, display: r.display || "",
      });
      if (res.ok) toast.success(`Released ${r.feature} (${r.user})`);
      else toast.error(res?.exec?.output?.slice(0, 200) || "lmremove failed");
      onChange?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Kill failed");
    } finally {
      setKilling(null);
    }
  };

  return (
    <div
      className="bg-[#111] border border-[#222] rounded-sm"
      data-testid="checkouts-table"
    >
      {/* toolbar */}
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-[#222] flex-wrap">
        <div className="flex items-center gap-2">
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
            LIVE CHECKOUTS
          </div>
          <span className="font-mono text-xs text-emerald-400 tabular-nums">
            [{filtered.length}]
          </span>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222] flex-wrap">
            {vendors.map((v) => (
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
              <Th col="_vendor" label="Vendor" sort={sort} onClick={() => toggleSort("server_id")} icon={sortIcon} />
              <Th col="feature" label="Feature" sort={sort} onClick={() => toggleSort("feature")} icon={sortIcon} />
              <Th col="version" label="Version" sort={sort} onClick={() => toggleSort("version")} icon={sortIcon} />
              <Th col="user" label="User" sort={sort} onClick={() => toggleSort("user")} icon={sortIcon} />
              <Th col="host" label="Host" sort={sort} onClick={() => toggleSort("host")} icon={sortIcon} />
              <th className="px-4 py-2 font-medium">Display</th>
              <Th col="pid" label="PID" sort={sort} onClick={() => toggleSort("pid")} icon={sortIcon} align="right" />
              <Th col="checkout_time" label="Since" sort={sort} onClick={() => toggleSort("checkout_time")} icon={sortIcon} align="right" />
              {isAdmin && <th className="px-4 py-2 font-medium text-right">Action</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const s = serverMap[r.server_id];
              const meta = s ? vendorMeta(s.vendor) : null;
              return (
                <tr
                  key={r.id}
                  className={`border-t border-[#1a1a1a] hover:bg-[#1a1a1a] ${i % 2 === 0 ? "" : "bg-[#0d0d0d]"}`}
                  data-testid={`checkout-row-${r.id}`}
                >
                  <td className="px-4 py-2">
                    {meta && (
                      <span className="text-[10px] uppercase tracking-wider font-bold" style={{ color: meta.color }}>
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
                  <td className="px-4 py-2 text-right text-[#9ca3af] tabular-nums">{r.pid}</td>
                  <td
                    className="px-4 py-2 text-right text-[#9ca3af] tabular-nums"
                    title={fmtDateTime(r.checkout_time, tz)}
                  >
                    {fmtAgo(r.checkout_time)}
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => handleKill(r)}
                        disabled={killing === r.id}
                        className="inline-flex items-center gap-1 px-2 py-1 border border-red-900/60 text-red-400 hover:bg-red-900/20 text-[10px] uppercase tracking-wider disabled:opacity-50"
                        data-testid={`kill-checkout-${r.id}`}
                        title="lmremove this checkout"
                      >
                        <X size={10} /> {killing === r.id ? "…" : "KILL"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
            {sorted.length === 0 && (
              <tr>
                <td
                  colSpan={isAdmin ? 9 : 8}
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

const Th = ({ label, onClick, icon, col, align }) => (
  <th
    className={`px-4 py-2 font-medium cursor-pointer select-none hover:text-white ${align === "right" ? "text-right" : ""}`}
    onClick={onClick}
    data-testid={`checkouts-sort-${col}`}
  >
    <span className={`inline-flex items-center gap-1.5 ${align === "right" ? "justify-end" : ""}`}>
      {label}
      {icon(col)}
    </span>
  </th>
);

export default CheckoutTable;
