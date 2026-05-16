import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { api, KNOWN_VENDORS, vendorMeta } from "@/lib/api";
import { toast } from "sonner";

const DAEMON_PRESETS = {
  cadence: { daemon: "cdslmd", port: 5280 },
  synopsys: { daemon: "snpslmd", port: 27020 },
  mentor: { daemon: "mgcld", port: 1717 },
  siemens: { daemon: "mgcld", port: 1717 },
  xilinx: { daemon: "xilinxd", port: 2100 },
  defacto: { daemon: "defacto", port: 27000 },
  ansys: { daemon: "ansyslmd", port: 1055 },
  altair: { daemon: "altairlmx", port: 6200 },
  keysight: { daemon: "agileesofd", port: 27009 },
};

export const AddServerDialog = ({ open, onOpenChange, onCreated }) => {
  const [name, setName] = useState("");
  const [vendor, setVendor] = useState("cadence");
  const [vendorMode, setVendorMode] = useState("preset"); // 'preset' | 'custom'
  const [host, setHost] = useState("");
  const [port, setPort] = useState(5280);
  const [daemon, setDaemon] = useState("cdslmd");
  const [busy, setBusy] = useState(false);

  const setVendorPreset = (v) => {
    setVendor(v);
    const p = DAEMON_PRESETS[v];
    if (p) {
      setDaemon(p.daemon);
      setPort(p.port);
    }
  };

  const submit = async () => {
    const finalVendor = (vendor || "").trim().toLowerCase();
    if (!name || !host || !finalVendor) {
      toast.error("Vendor, name and host are required");
      return;
    }
    setBusy(true);
    try {
      await api.createServer({
        name, vendor: finalVendor, host, port: Number(port), daemon,
      });
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

  const meta = vendorMeta(vendor);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="bg-[#0a0a0a] border-[#222] rounded-sm font-mono max-w-lg"
        data-testid="add-server-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-mono uppercase tracking-wider text-base">
            Register License Server
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1 flex items-center justify-between">
              <span>Vendor</span>
              <div className="flex border border-[#222]">
                {["preset", "custom"].map((m) => (
                  <button
                    key={m}
                    onClick={() => setVendorMode(m)}
                    className={`px-2 py-0.5 text-[9px] uppercase tracking-wider ${
                      vendorMode === m ? "bg-white text-black" : "text-[#9ca3af]"
                    }`}
                    data-testid={`vendor-mode-${m}`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
            {vendorMode === "preset" ? (
              <div className="grid grid-cols-3 gap-1">
                {KNOWN_VENDORS.map((v) => {
                  const m = vendorMeta(v);
                  return (
                    <button
                      key={v}
                      onClick={() => setVendorPreset(v)}
                      className={`py-1.5 border text-[10px] uppercase tracking-wider truncate ${
                        vendor === v ? "bg-white text-black border-white" : "border-[#222] text-[#9ca3af] hover:bg-[#1a1a1a]"
                      }`}
                      data-testid={`add-vendor-${v}`}
                      style={vendor === v ? {} : { borderLeftColor: m.color, borderLeftWidth: 2 }}
                    >
                      {v}
                    </button>
                  );
                })}
              </div>
            ) : (
              <input
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                placeholder="e.g. xilinx, defacto, ansys, altium, custom-vendor"
                className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
                data-testid="vendor-custom-input"
              />
            )}
            <div className="mt-1 text-[10px]" style={{ color: meta.color }}>
              tag preview · {meta.label}
            </div>
          </div>

          <Field label="Name">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="cadence-prod-02"
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="add-server-name"
            />
          </Field>

          <Field label="Host / IP">
            <input
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="10.10.11.111"
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
