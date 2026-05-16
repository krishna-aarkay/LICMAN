import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { toast } from "sonner";

export const ReservationDialog = ({ open, onOpenChange, server, onCreated }) => {
  const [feature, setFeature] = useState("");
  const [targetType, setTargetType] = useState("USER");
  const [target, setTarget] = useState("");
  const [count, setCount] = useState(1);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setFeature("");
    setTargetType("USER");
    setTarget("");
    setCount(1);
  };

  const submit = async () => {
    if (!feature || !target) {
      toast.error("Feature and target are required");
      return;
    }
    setBusy(true);
    try {
      await api.createReservation({
        server_id: server.id,
        feature,
        target_type: targetType,
        target,
        count: Number(count) || 1,
      });
      toast.success(`RESERVE ${count} ${feature} ${targetType} ${target}`);
      onCreated?.();
      reset();
      onOpenChange(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to create reservation");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#0a0a0a] border-[#222] rounded-sm font-mono max-w-md"
        data-testid="reservation-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-mono uppercase tracking-wider text-base">
            New Reservation
          </DialogTitle>
          <DialogDescription className="text-[#9ca3af] font-mono text-xs">
            {"// RESERVE <count> <feature> <type> <target>"}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 mt-2">
          <Field label="Feature">
            <select
              value={feature}
              onChange={(e) => setFeature(e.target.value)}
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="reservation-feature-select"
            >
              <option value="">— select feature —</option>
              {(server?.features || []).map((f) => (
                <option key={f.name} value={f.name}>
                  {f.name} · v{f.version} · {f.total} seats
                </option>
              ))}
            </select>
          </Field>

          <Field label="Target Type">
            <div className="flex">
              {["USER", "HOST", "GROUP", "INTERNET"].map((t) => (
                <button
                  key={t}
                  onClick={() => setTargetType(t)}
                  className={`flex-1 py-1.5 border border-[#222] text-[10px] uppercase tracking-wider ${
                    targetType === t
                      ? "bg-white text-black border-white"
                      : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                  }`}
                  data-testid={`reservation-type-${t}`}
                >
                  {t}
                </button>
              ))}
            </div>
          </Field>

          <Field label={`${targetType} name`}>
            <input
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={targetType === "USER" ? "e.g. asingh" : targetType === "HOST" ? "wks-bangalore-04" : "design_team"}
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="reservation-target-input"
            />
          </Field>

          <Field label="Count">
            <input
              type="number"
              min="1"
              max="999"
              value={count}
              onChange={(e) => setCount(e.target.value)}
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white tabular-nums"
              data-testid="reservation-count-input"
            />
          </Field>

          <div className="bg-[#000] border border-[#222] p-3 text-[11px] text-emerald-400">
            <span className="text-[#6b7280]">preview &gt; </span>
            RESERVE {count} {feature || "—"} {targetType} {target || "—"}
          </div>
        </div>

        <DialogFooter className="gap-2 mt-3">
          <button
            className="btn-brutal"
            onClick={() => onOpenChange(false)}
            data-testid="reservation-cancel"
          >
            CANCEL
          </button>
          <button
            className="btn-brutal primary"
            onClick={submit}
            disabled={busy}
            data-testid="reservation-submit-btn"
          >
            {busy ? "SAVING…" : "ADD RESERVATION"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const Field = ({ label, children }) => (
  <div>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
      {label}
    </div>
    {children}
  </div>
);

export default ReservationDialog;
