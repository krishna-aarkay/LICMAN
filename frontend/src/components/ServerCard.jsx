import { Link } from "react-router-dom";
import { Server, Power, RefreshCw, ChevronRight } from "lucide-react";
import { vendorMeta, api } from "@/lib/api";
import { toast } from "sonner";

export const ServerCard = ({ server, onChange }) => {
  const meta = vendorMeta(server.vendor);
  const totalFeat = server.features?.length || 0;
  const totalSeats = server.features?.reduce((a, f) => a + f.total, 0) || 0;
  const isUp = server.status === "up";

  const handle = async (fn, msg) => {
    try {
      await fn();
      toast.success(msg);
      onChange?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Action failed");
    }
  };

  return (
    <div
      className="bg-[#111111] border border-[#222] rounded-sm p-4 hover:bg-[#141414] transition-colors group"
      data-testid={`server-card-${server.id}`}
    >
      {/* Top row: vendor + status */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{
              background: meta.color,
              boxShadow: `0 0 8px ${meta.color}`,
            }}
          />
          <span
            className="font-mono text-[10px] font-bold uppercase tracking-[0.2em]"
            style={{ color: meta.color }}
          >
            {meta.label}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className="status-dot"
            style={{ color: isUp ? "#10b981" : "#ef4444", background: isUp ? "#10b981" : "#ef4444" }}
          />
          <span
            className="font-mono text-[10px] uppercase tracking-wider font-bold"
            style={{ color: isUp ? "#10b981" : "#ef4444" }}
          >
            {server.status}
          </span>
        </div>
      </div>

      {/* Name */}
      <Link to={`/servers/${server.id}`} className="block group" data-testid={`server-link-${server.id}`}>
        <div className="font-mono text-base font-semibold text-white group-hover:text-emerald-400 transition-colors flex items-center justify-between">
          {server.name}
          <ChevronRight size={14} className="opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      </Link>

      {/* Host:port */}
      <div className="font-mono text-xs text-[#9ca3af] mt-1">
        {server.host}:<span className="text-white">{server.port}</span>
      </div>
      <div className="font-mono text-[10px] text-[#6b7280] uppercase tracking-wider mt-0.5">
        daemon · <span className="text-[#9ca3af] normal-case">{server.daemon}</span>
      </div>

      {/* Feature stats */}
      <div className="mt-4 pt-3 border-t border-[#1a1a1a] grid grid-cols-2 gap-2">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b7280]">Features</div>
          <div className="font-mono text-lg font-bold tabular-nums">{totalFeat}</div>
        </div>
        <div>
          <div className="font-mono text-[10px] uppercase tracking-wider text-[#6b7280]">Seats</div>
          <div className="font-mono text-lg font-bold tabular-nums">{totalSeats}</div>
        </div>
      </div>

      {/* Action bar */}
      <div className="mt-3 flex items-center gap-1.5">
        <button
          className="btn-brutal flex-1 flex items-center justify-center gap-1.5 text-[10px] py-1.5"
          onClick={() => handle(() => api.reread(server.id), `lmreread @ ${server.name}`)}
          data-testid={`btn-reread-${server.id}`}
        >
          <RefreshCw size={11} /> REREAD
        </button>
        <button
          className="btn-brutal flex-1 flex items-center justify-center gap-1.5 text-[10px] py-1.5"
          onClick={() => handle(() => api.restart(server.id), `${server.daemon} restarted`)}
          data-testid={`btn-restart-${server.id}`}
        >
          <Power size={11} /> RESTART
        </button>
        <button
          className="btn-brutal text-[10px] py-1.5 px-2"
          onClick={() =>
            handle(() => api.toggle(server.id), `Status toggled @ ${server.name}`)
          }
          data-testid={`btn-toggle-${server.id}`}
          title="Toggle UP/DOWN"
        >
          {isUp ? "STOP" : "START"}
        </button>
      </div>
    </div>
  );
};

export default ServerCard;
