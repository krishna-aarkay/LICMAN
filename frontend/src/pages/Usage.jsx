import { useEffect, useMemo, useState } from "react";
import { BarChart3, Download, Filter, ArrowUpDown, ArrowUp, ArrowDown, RotateCw } from "lucide-react";
import { api, fmtDateTime, vendorMeta } from "@/lib/api";
import { prefs } from "@/lib/prefs";
import Header from "@/components/Header";
import { toast } from "sonner";

const PRESETS = [
  { k: "today", label: "TODAY", days: 0 },
  { k: "7d", label: "7 DAYS", days: 7 },
  { k: "30d", label: "30 DAYS", days: 30 },
  { k: "90d", label: "90 DAYS", days: 90 },
  { k: "365d", label: "1 YEAR", days: 365 },
  { k: "all", label: "ALL", days: -1 },
];

const SORT_DEFAULT = { col: "last_seen_iso", dir: "desc" };

const isoDate = (d) => d.toISOString().slice(0, 10);

export default function Usage() {
  const [stats, setStats] = useState(null);
  const [rows, setRows] = useState([]);
  const [facets, setFacets] = useState({ users: [], features: [], vendors: [], servers: [], total_rows: 0 });
  const [summary, setSummary] = useState({ rows: [], group_by: "user" });
  const [groupBy, setGroupBy] = useState("user");
  const [tz, setTz] = useState(prefs.load().tz || "IST");
  const [preset, setPreset] = useState("30d");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [user, setUser] = useState("");
  const [feature, setFeature] = useState("");
  const [vendor, setVendor] = useState("");
  const [loading, setLoading] = useState(false);
  const [sort, setSort] = useState(SORT_DEFAULT);

  useEffect(() => {
    const handler = (e) => setTz(e.detail);
    window.addEventListener("licman:tz", handler);
    return () => window.removeEventListener("licman:tz", handler);
  }, []);

  // Derived range
  const computedRange = useMemo(() => {
    if (preset === "custom") return { date_from: dateFrom, date_to: dateTo };
    const p = PRESETS.find((x) => x.k === preset);
    if (!p || p.days < 0) return { date_from: "", date_to: "" };
    if (p.days === 0) return { date_from: isoDate(new Date()), date_to: "" };
    const from = new Date();
    from.setUTCDate(from.getUTCDate() - p.days);
    return { date_from: isoDate(from), date_to: "" };
  }, [preset, dateFrom, dateTo]);

  const queryParams = useMemo(
    () => ({
      ...computedRange,
      user: user || undefined,
      feature: feature || undefined,
      vendor: vendor || undefined,
    }),
    [computedRange, user, feature, vendor],
  );

  const load = async () => {
    setLoading(true);
    try {
      const [s, r, f, sm] = await Promise.all([
        api.stats(),
        api.usage({ ...queryParams, limit: 2000 }),
        api.usageFacets(),
        api.usageSummary({ ...queryParams, group_by: groupBy }),
      ]);
      setStats(s);
      setRows(r);
      setFacets(f);
      setSummary(sm);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to load usage data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [queryParams, groupBy]);

  const sortedRows = useMemo(() => {
    const out = [...rows];
    const { col, dir } = sort;
    const mult = dir === "asc" ? 1 : -1;
    out.sort((a, b) => {
      const av = a[col] ?? "";
      const bv = b[col] ?? "";
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
      return String(av).localeCompare(String(bv)) * mult;
    });
    return out;
  }, [rows, sort]);

  const toggleSort = (col) => {
    setSort((cur) =>
      cur.col === col ? { col, dir: cur.dir === "asc" ? "desc" : "asc" } : { col, dir: "asc" },
    );
  };

  const sortIcon = (col) => {
    if (sort.col !== col) return <ArrowUpDown size={10} className="opacity-40" />;
    return sort.dir === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />;
  };

  const clear = () => {
    setUser("");
    setFeature("");
    setVendor("");
    setPreset("30d");
    setDateFrom("");
    setDateTo("");
    setSort(SORT_DEFAULT);
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="usage-page">
      <Header stats={stats} autoRefresh={false} onToggleRefresh={() => {}} />

      <main className="max-w-[1600px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              /// LICENSE TELEMETRY
            </div>
            <h1 className="font-mono text-2xl font-bold tracking-tight mt-1 flex items-center gap-2">
              <BarChart3 size={22} /> Usage History
            </h1>
            <div className="font-mono text-[11px] text-[#6b7280] mt-1">
              {facets.total_rows.toLocaleString()} session(s) recorded · {tz}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="btn-brutal flex items-center gap-1.5 disabled:opacity-50"
              data-testid="usage-refresh-btn"
            >
              <RotateCw size={12} className={loading ? "animate-spin" : ""} />
              {loading ? "LOADING…" : "REFRESH"}
            </button>
            <a
              href={api.usageExportUrl(queryParams)}
              className="btn-brutal primary flex items-center gap-1.5"
              data-testid="usage-export-csv-btn"
            >
              <Download size={12} /> EXPORT CSV
            </a>
          </div>
        </div>

        {/* Filters */}
        <section className="bg-[#111] border border-[#222] rounded-sm p-4 space-y-3" data-testid="usage-filters">
          <div className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-wider text-[#9ca3af]">
            <Filter size={12} /> RANGE
          </div>
          <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222] flex-wrap w-fit">
            {PRESETS.map((p) => (
              <button
                key={p.k}
                onClick={() => setPreset(p.k)}
                className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                  preset === p.k ? "bg-white text-black" : "text-[#9ca3af] hover:text-white"
                }`}
                data-testid={`usage-preset-${p.k}`}
              >
                {p.label}
              </button>
            ))}
            <button
              onClick={() => setPreset("custom")}
              className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                preset === "custom" ? "bg-white text-black" : "text-[#9ca3af] hover:text-white"
              }`}
              data-testid="usage-preset-custom"
            >
              CUSTOM
            </button>
          </div>
          {preset === "custom" && (
            <div className="flex items-center gap-2 flex-wrap">
              <label className="font-mono text-[10px] text-[#6b7280]">
                FROM
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                  className="ml-2 bg-[#0a0a0a] border border-[#222] px-2 py-1 font-mono text-xs text-white"
                  data-testid="usage-date-from"
                />
              </label>
              <label className="font-mono text-[10px] text-[#6b7280]">
                TO
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                  className="ml-2 bg-[#0a0a0a] border border-[#222] px-2 py-1 font-mono text-xs text-white"
                  data-testid="usage-date-to"
                />
              </label>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-[#1a1a1a]">
            <DropdownFilter
              label="USER"
              value={user}
              onChange={setUser}
              options={facets.users}
              testid="usage-filter-user"
            />
            <DropdownFilter
              label="LICENSE / FEATURE"
              value={feature}
              onChange={setFeature}
              options={facets.features}
              testid="usage-filter-feature"
            />
            <DropdownFilter
              label="VENDOR"
              value={vendor}
              onChange={setVendor}
              options={facets.vendors}
              testid="usage-filter-vendor"
            />
          </div>
          <div className="flex justify-end">
            <button
              onClick={clear}
              className="font-mono text-[10px] uppercase tracking-wider text-[#9ca3af] hover:text-white"
              data-testid="usage-clear-filters"
            >
              clear filters
            </button>
          </div>
        </section>

        {/* Summary */}
        <section className="bg-[#111] border border-[#222] rounded-sm">
          <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between flex-wrap gap-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              AGGREGATE BY
            </div>
            <div className="flex items-center gap-1 bg-[#0a0a0a] border border-[#222]">
              {["user", "feature", "vendor", "server_name"].map((g) => (
                <button
                  key={g}
                  onClick={() => setGroupBy(g)}
                  className={`px-2.5 py-1 font-mono text-[10px] uppercase tracking-wider ${
                    groupBy === g ? "bg-white text-black" : "text-[#9ca3af] hover:text-white"
                  }`}
                  data-testid={`usage-groupby-${g}`}
                >
                  {g.replace("_", " ")}
                </button>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto max-h-[40vh] overflow-y-auto">
            <table className="w-full font-mono text-xs">
              <thead className="bg-[#0a0a0a] sticky top-0 z-10">
                <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                  <th className="px-4 py-2">{groupBy.replace("_", " ")}</th>
                  <th className="px-4 py-2 text-right">Sessions</th>
                  <th className="px-4 py-2 text-right">Unique Users</th>
                  <th className="px-4 py-2 text-right">Unique Features</th>
                  <th className="px-4 py-2">First Seen</th>
                  <th className="px-4 py-2">Last Seen</th>
                </tr>
              </thead>
              <tbody>
                {summary.rows.map((r) => (
                  <tr
                    key={r.key}
                    className="border-t border-[#1a1a1a] hover:bg-[#1a1a1a]"
                    data-testid={`usage-summary-row-${r.key}`}
                  >
                    <td className="px-4 py-2 text-white">{r.key}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-emerald-400">{r.sessions}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-[#9ca3af]">{r.user_count}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-[#9ca3af]">{r.feature_count}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">{fmtDateTime(r.first_seen, tz)}</td>
                    <td className="px-4 py-2 text-[#9ca3af]">{fmtDateTime(r.last_seen, tz)}</td>
                  </tr>
                ))}
                {summary.rows.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-4 py-10 text-center text-[#6b7280]">
                      {"// no aggregated rows for the current filters"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Detail table */}
        <section className="bg-[#111] border border-[#222] rounded-sm">
          <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
            <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
              SESSIONS · {sortedRows.length.toLocaleString()}
            </div>
            <div className="font-mono text-[10px] text-[#6b7280]">
              {"// sort by clicking column headers"}
            </div>
          </div>
          <div className="overflow-x-auto max-h-[55vh] overflow-y-auto">
            <table className="w-full font-mono text-xs" data-testid="usage-detail-table">
              <thead className="bg-[#0a0a0a] sticky top-0 z-10">
                <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                  <SortableTh col="vendor" label="Vendor" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="feature" label="Feature" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="user" label="User" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="host" label="Host" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="server_name" label="Server" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="first_seen_iso" label="First Seen" sort={sort} onClick={toggleSort} icon={sortIcon} />
                  <SortableTh col="last_seen_iso" label="Last Seen" sort={sort} onClick={toggleSort} icon={sortIcon} />
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r, i) => {
                  const m = vendorMeta(r.vendor);
                  return (
                    <tr
                      key={r.id}
                      className={`border-t border-[#1a1a1a] hover:bg-[#1a1a1a] ${i % 2 ? "bg-[#0d0d0d]" : ""}`}
                      data-testid={`usage-row-${r.id}`}
                    >
                      <td className="px-4 py-2">
                        <span className="text-[10px] uppercase tracking-wider font-bold" style={{ color: m.color }}>
                          {m.label.split(" ")[0]}
                        </span>
                      </td>
                      <td className="px-4 py-2 text-white">{r.feature}</td>
                      <td className="px-4 py-2 text-emerald-400">{r.user}</td>
                      <td className="px-4 py-2 text-[#9ca3af]">{r.host}</td>
                      <td className="px-4 py-2 text-[#9ca3af]">{r.server_name}</td>
                      <td className="px-4 py-2 text-[#9ca3af]">{fmtDateTime(r.first_seen_iso, tz)}</td>
                      <td className="px-4 py-2 text-[#9ca3af]">{fmtDateTime(r.last_seen_iso, tz)}</td>
                    </tr>
                  );
                })}
                {sortedRows.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-12 text-center text-[#6b7280]">
                      {"// no sessions match the current filters"}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

const SortableTh = ({ col, label, sort, onClick, icon }) => (
  <th
    className="px-4 py-2 font-medium cursor-pointer select-none hover:text-white"
    onClick={() => onClick(col)}
    data-testid={`usage-sort-${col}`}
  >
    <span className="inline-flex items-center gap-1.5">
      {label}
      {icon(col)}
    </span>
  </th>
);

const DropdownFilter = ({ label, value, onChange, options, testid }) => (
  <div>
    <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b7280] mb-1">{label}</div>
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-1.5 font-mono text-xs text-white"
      data-testid={testid}
    >
      <option value="">(all)</option>
      {options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
    </select>
  </div>
);
