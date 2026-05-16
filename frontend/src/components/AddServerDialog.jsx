import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";
import { toast } from "sonner";

const DEFAULTS = {
  cadence: { daemon: "cdslmd", port: 5280 },
  synopsys: { daemon: "snpslmd", port: 27020 },
  mentor: { daemon: "mgcld", port: 1717 },
};

export const AddServerDialog = ({ open, onOpenChange, onCreated }) => {
  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("cadence");
  const [host, setHost] = useState("");
  const [port, setPort] = useState(5280);
  const [daemon, setDaemon] = useState("cdslmd");
  const [busy, setBusy] = useState(false);

  const onVendor = (v) => {
    setVendor(v);
    setDaemon(DEFAULTS[v].daemon);
    setPort(DEFAULTS[v].port);
  };

  const submit = async () => {
    if (!name || !host) {
      toast.error("Name and host are required");
      return;
    }
    setBusy(true);
    try {
      await api.createServer({ name, vendor, host, port: Number(port), daemon });
      toast.success(`Server ${name} added`);
      onCreated?.();
      onOpenChange(false);
      setName("");
      setHost("");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Failed to add server");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#0a0a0a] border-[#222] rounded-sm font-mono max-w-md"
        data-testid="add-server-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-mono uppercase tracking-wider text-base">
            Register License Server
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <Field label="Vendor">
            <div className="flex">
              {["cadence", "synopsys", "mentor"].map((v) => (
                <button
                  key={v}
                  onClick={() => onVendor(v)}
                  className={`flex-1 py-1.5 border border-[#222] text-[10px] uppercase tracking-wider ${
                    vendor === v ? "bg-white text-black border-white" : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                  }`}
                  data-testid={`add-vendor-${v}`}
                >
                  {v}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="lic-cadence-prod-02"
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="add-server-name"
            />
          </Field>

          <Field label="Host">
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="lic-cadence-02.eda.local"
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="add-server-host"
            />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Port">
              <input
                type="number"
                value={port}
                onChange={(e) => setPort(e.target.value)}
                className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white tabular-nums"
                data-testid="add-server-port"
              />
            </Field>
            <Field label="Daemon">
              <input
                value={daemon}
                onChange={(e) => setDaemon(e.target.value)}
                className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
                data-testid="add-server-daemon"
              />
            </Field>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <button className="btn-brutal" onClick={() => onOpenChange(false)} data-testid="add-server-cancel">
            CANCEL
          </button>
          <button className="btn-brutal primary" onClick={submit} disabled={busy} data-testid="add-server-submit">
            {busy ? "ADDING…" : "REGISTER"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

const Field = ({ label, children }) => (
  <div>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">{label}</div>
    {children}
  </div>
);

export default AddServerDialog;
