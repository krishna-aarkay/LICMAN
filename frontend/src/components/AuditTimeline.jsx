import { fmtAgo } from "@/lib/api";

const SEVERITY = {
  success: { dot: "#10b981", label: "OK" },
  info: { dot: "#3b82f6", label: "INFO" },
  warning: { dot: "#f59e0b", label: "WARN" },
  error: { dot: "#ef4444", label: "ERR" },
};

export const AuditTimeline = ({ rows, compact = false }) => {
  return (
    <div className="bg-[#111] border border-[#222] rounded-sm" data-testid="audit-timeline">
      <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
          AUDIT LOG
        </div>
        <span className="font-mono text-xs text-emerald-400 tabular-nums">[{rows?.length || 0}]</span>
      </div>
      <div
        className={`divide-y divide-[#1a1a1a] overflow-y-auto ${
          compact ? "max-h-[50vh]" : "max-h-[65vh]"
        }`}
      >
        {(rows || []).map((r) => {
          const sv = SEVERITY[r.severity] || SEVERITY.info;
          return (
            <div
              key={r.id}
              className="px-4 py-2.5 hover:bg-[#1a1a1a] grid grid-cols-[14px_1fr_auto] gap-3 items-start"
              data-testid={`audit-row-${r.id}`}
            >
              <div
                className="w-2 h-2 mt-1.5 rounded-full"
                style={{ background: sv.dot, boxShadow: `0 0 6px ${sv.dot}` }}
              />
              <div className="min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className="font-mono text-[9px] uppercase tracking-wider font-bold"
                    style={{ color: sv.dot }}
                  >
                    {sv.label}
                  </span>
                  <span className="font-mono text-[11px] text-white">{r.action}</span>
                  {r.server_name && (
                    <span className="font-mono text-[10px] text-[#6b7280]">
                      · {r.server_name}
                    </span>
                  )}
                </div>
                <div className="font-mono text-[11px] text-[#9ca3af] truncate">
                  {r.detail}
                </div>
              </div>
              <div className="font-mono text-[10px] text-[#6b7280] tabular-nums whitespace-nowrap">
                {fmtAgo(r.timestamp)}
              </div>
            </div>
          );
        })}
        {(!rows || rows.length === 0) && (
          <div className="px-4 py-10 text-center text-[#6b7280] font-mono text-xs">
            {"// no events"}
          </div>
        )}
      </div>
    </div>
  );
};

export default AuditTimeline;
