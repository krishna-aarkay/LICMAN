import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Activity, RotateCw, Terminal } from "lucide-react";

export const Header = ({ stats, autoRefresh, onToggleRefresh, onReset }) => {
  const [time, setTime] = useState(new Date());
  const loc = useLocation();

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header
      className="border-b border-[#222] bg-[#0a0a0a] sticky top-0 z-30"
      data-testid="app-header"
    >
      <div className="relative grid-bg">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0a0a0a]/60 to-[#0a0a0a]" />
        <div className="relative max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between gap-6">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-3" data-testid="logo-link">
            <div className="w-9 h-9 border border-[#333] flex items-center justify-center bg-[#111]">
              <Terminal size={18} className="text-emerald-400" />
            </div>
            <div className="leading-tight">
              <div className="font-mono text-lg font-bold tracking-tight">
                LICMAN<span className="text-emerald-400 cursor-blink"></span>
              </div>
              <div className="font-mono text-[10px] text-[#6b7280] uppercase tracking-[0.25em]">
                VLSI · LICENSE CONSOLE · v0.1
              </div>
            </div>
          </Link>

          {/* Stats strip */}
          <div className="hidden md:flex items-center gap-6 font-mono text-[11px]">
            <Stat label="SRV" value={`${stats?.servers_up ?? 0}/${stats?.servers_total ?? 0}`} ok />
            <Stat label="FEAT" value={stats?.features_total ?? 0} />
            <Stat label="CHK-OUT" value={stats?.checkouts_active ?? 0} accent="#3b82f6" />
            <Stat label="RES" value={stats?.reservations ?? 0} accent="#f59e0b" />
            <div className="text-[#6b7280]">
              <span className="text-[#9ca3af]">UTC </span>
              <span className="text-[#f3f4f6]">{time.toISOString().slice(11, 19)}</span>
            </div>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={onToggleRefresh}
              className={`btn-brutal flex items-center gap-2 ${autoRefresh ? "primary" : ""}`}
              data-testid="auto-refresh-toggle"
              title="Toggle auto-refresh (10s)"
            >
              <Activity size={12} />
              {autoRefresh ? "LIVE" : "PAUSED"}
            </button>
            {loc.pathname === "/" && (
              <button
                onClick={onReset}
                className="btn-brutal flex items-center gap-2"
                data-testid="reset-seed-btn"
                title="Reset demo data"
              >
                <RotateCw size={12} />
                RESET
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};

const Stat = ({ label, value, ok, accent }) => (
  <div className="flex items-center gap-2">
    <span className="text-[#6b7280] uppercase tracking-wider">{label}</span>
    <span
      className="font-bold tabular-nums"
      style={{ color: ok ? "#10b981" : accent || "#f3f4f6" }}
    >
      {value}
    </span>
  </div>
);

export default Header;
