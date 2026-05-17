import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Activity, RotateCw, Terminal, Calendar, Settings as SettingsIcon, LayoutDashboard, LogOut, Users as UsersIcon, Shield, User as UserIcon, BarChart3, Globe } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { fmtClock } from "@/lib/api";
import { prefs } from "@/lib/prefs";

export const Header = ({ stats, autoRefresh, onToggleRefresh, onReset }) => {
  const [time, setTime] = useState(new Date());
  const [tz, setTz] = useState(prefs.load().tz || "IST");
  const loc = useLocation();
  const nav = useNavigate();
  const { user, isAdmin, logout } = useAuth();

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const toggleTz = () => {
    const nv = tz === "IST" ? "UTC" : "IST";
    setTz(nv);
    prefs.save({ tz: nv });
    // Notify other mounted components that read prefs.tz on render
    window.dispatchEvent(new CustomEvent("licman:tz", { detail: nv }));
  };

  const navLinks = [
    { to: "/", label: "CONTROL ROOM", icon: LayoutDashboard, test: "nav-dashboard", show: true },
    { to: "/usage", label: "USAGE", icon: BarChart3, test: "nav-usage", show: true },
    { to: "/expiry", label: "EXPIRY", icon: Calendar, test: "nav-expiry", show: true },
    { to: "/users", label: "USERS", icon: UsersIcon, test: "nav-users", show: isAdmin },
    { to: "/settings", label: "SETTINGS", icon: SettingsIcon, test: "nav-settings", show: isAdmin },
  ].filter((l) => l.show);

  const onLogout = async () => {
    await logout();
    nav("/login");
  };

  return (
    <header
      className="border-b border-[#222] bg-[#0a0a0a] sticky top-0 z-30"
      data-testid="app-header"
    >
      <div className="relative grid-bg">
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0a0a0a]/60 to-[#0a0a0a]" />
        <div className="relative max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between gap-6 flex-wrap">
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
                MOSCHIP · LICENSE CONSOLE
              </div>
            </div>
          </Link>

          {/* Nav */}
          <nav className="flex items-center gap-1 border border-[#222] bg-[#0a0a0a]">
            {navLinks.map(({ to, label, icon: Icon, test }) => {
              const active =
                to === "/" ? loc.pathname === "/" || loc.pathname.startsWith("/servers/") : loc.pathname === to;
              return (
                <Link
                  key={to}
                  to={to}
                  data-testid={test}
                  className={`flex items-center gap-1.5 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors ${
                    active ? "bg-white text-black" : "text-[#9ca3af] hover:text-white hover:bg-[#1a1a1a]"
                  }`}
                >
                  <Icon size={11} /> {label}
                </Link>
              );
            })}
          </nav>

          {/* Stats strip */}
          <div className="hidden xl:flex items-center gap-5 font-mono text-[11px]">
            <Stat label="SRV" value={`${stats?.servers_up ?? 0}/${stats?.servers_total ?? 0}`} ok />
            <Stat label="FEAT" value={stats?.features_total ?? 0} />
            <Stat label="CHK-OUT" value={stats?.checkouts_active ?? 0} accent="#3b82f6" />
            <Stat label="RES" value={stats?.reservations ?? 0} accent="#f59e0b" />
            <button
              onClick={toggleTz}
              className="text-[#6b7280] hover:text-emerald-400 flex items-center gap-1.5 font-mono"
              data-testid="tz-toggle"
              title="Click to switch UTC ↔ IST"
            >
              <Globe size={11} />
              <span className="text-[#9ca3af]">{tz} </span>
              <span className="text-[#f3f4f6] tabular-nums">{fmtClock(time, tz)}</span>
            </button>
          </div>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {user && (
              <div className="hidden sm:flex items-center gap-2 px-2.5 py-1.5 border border-[#222] bg-[#0a0a0a]" data-testid="user-badge">
                {isAdmin
                  ? <Shield size={11} className="text-amber-400" />
                  : <UserIcon size={11} className="text-emerald-400" />}
                <span className="font-mono text-[10px] uppercase tracking-wider text-white truncate max-w-[180px]">
                  {user.email}
                </span>
                <span className="font-mono text-[9px] uppercase tracking-wider text-[#6b7280]">
                  {user.role}
                </span>
              </div>
            )}
            <button
              onClick={onToggleRefresh}
              className={`btn-brutal flex items-center gap-2 ${autoRefresh ? "primary" : ""}`}
              data-testid="auto-refresh-toggle"
              title="Toggle auto-refresh (10s)"
            >
              <Activity size={12} />
              {autoRefresh ? "LIVE" : "PAUSED"}
            </button>
            {loc.pathname === "/" && onReset && (
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
            {user && (
              <button
                onClick={onLogout}
                className="btn-brutal flex items-center gap-2"
                data-testid="logout-btn"
                title="Sign out"
              >
                <LogOut size={12} /> LOGOUT
              </button>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};

const Stat = ({ label, value, ok, accent }) => (
  <div className="flex items-center gap-2" data-testid={`stat-${label.toLowerCase().replace(/[^a-z]/g, "")}`}>
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
