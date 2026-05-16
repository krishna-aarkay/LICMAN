export const ExpiryBadge = ({ days, expires }) => {
  if (days === null || days === undefined) {
    return (
      <span
        className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider border"
        style={{ borderColor: "#333", color: "#6b7280" }}
        title="permanent"
      >
        ∞
      </span>
    );
  }
  let color, bg, label;
  if (days < 0) {
    color = "#ef4444";
    bg = "rgba(239,68,68,0.12)";
    label = `EXPIRED ${Math.abs(days)}d`;
  } else if (days <= 30) {
    color = "#ef4444";
    bg = "rgba(239,68,68,0.12)";
    label = `${days}d`;
  } else if (days <= 90) {
    color = "#f59e0b";
    bg = "rgba(245,158,11,0.12)";
    label = `${days}d`;
  } else {
    color = "#10b981";
    bg = "rgba(16,185,129,0.10)";
    label = `${days}d`;
  }
  return (
    <span
      className="px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider border tabular-nums"
      style={{ borderColor: color, color, background: bg }}
      title={`expires ${expires}`}
    >
      {label}
    </span>
  );
};

export default ExpiryBadge;
