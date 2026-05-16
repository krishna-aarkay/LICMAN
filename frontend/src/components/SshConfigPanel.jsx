import { useState, useEffect } from "react";
import { Server, Key, ShieldCheck, Save, Play } from "lucide-react";
import { api } from "@/lib/api";
import { toast } from "sonner";

export const SshConfigPanel = ({ server, onChange }) => {
  const [cfg, setCfg] = useState(server?.ssh || {});
  const [mode, setMode] = useState(server?.adapter_mode || "mock");
  const [dirty, setDirty] = useState(false);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    setCfg(server?.ssh || {});
    setMode(server?.adapter_mode || "mock");
    setDirty(false);
  }, [server]);

  const upd = (patch) => {
    setCfg((c) => ({ ...c, ...patch }));
    setDirty(true);
  };

  const save = async () => {
    try {
      await api.saveSsh(server.id, cfg);
      await api.setAdapter(server.id, mode);
      toast.success("SSH config saved");
      setDirty(false);
      onChange?.();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      const r = await api.testSsh(server.id);
      if (r.ok) toast.success(r.message);
      else toast.error(r.message);
    } catch {
      toast.error("Test failed");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="bg-[#111] border border-[#222] rounded-sm" data-testid="ssh-panel">
      <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between flex-wrap gap-2">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
            SSH CONNECTION · {server.name}
          </div>
          <div className="font-mono text-[10px] text-[#6b7280] mt-0.5">
            mock-only today — backed paramiko adapter ready to swap in
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="flex border border-[#222]">
            {["mock", "ssh"].map((m) => (
              <button
                key={m}
                onClick={() => {
                  setMode(m);
                  setDirty(true);
                }}
                className={`px-3 py-1.5 text-[10px] uppercase tracking-wider font-mono ${
                  mode === m ? "bg-white text-black" : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                }`}
                data-testid={`adapter-mode-${m}`}
              >
                {m === "mock" ? "MOCK" : "SSH"}
              </button>
            ))}
          </div>
          {dirty && (
            <span className="font-mono text-[10px] text-[#f59e0b] uppercase tracking-wider">
              ● UNSAVED
            </span>
          )}
          <button className="btn-brutal flex items-center gap-1.5" onClick={test} disabled={testing} data-testid="ssh-test-btn">
            <Play size={11} /> {testing ? "TESTING…" : "TEST"}
          </button>
          <button className="btn-brutal primary flex items-center gap-1.5" onClick={save} disabled={!dirty} data-testid="ssh-save-btn">
            <Save size={11} /> SAVE
          </button>
        </div>
      </div>

      <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
        <Field label="Enabled">
          <div className="flex border border-[#222]">
            {[true, false].map((v) => (
              <button
                key={String(v)}
                onClick={() => upd({ enabled: v })}
                className={`flex-1 py-1.5 text-[10px] uppercase tracking-wider ${
                  !!cfg.enabled === v
                    ? v
                      ? "bg-emerald-500/20 text-emerald-400"
                      : "bg-[#1a1a1a] text-[#9ca3af]"
                    : "text-[#6b7280] hover:bg-[#1a1a1a]"
                }`}
                data-testid={`ssh-enabled-${v ? "on" : "off"}`}
              >
                {v ? "ON" : "OFF"}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Auth Method">
          <div className="flex border border-[#222]">
            {["key", "password"].map((a) => (
              <button
                key={a}
                onClick={() => upd({ auth_method: a })}
                className={`flex-1 py-1.5 text-[10px] uppercase tracking-wider ${
                  cfg.auth_method === a
                    ? "bg-white text-black"
                    : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                }`}
                data-testid={`ssh-auth-${a}`}
              >
                {a}
              </button>
            ))}
          </div>
        </Field>

        <Field label="SSH Host">
          <input
            value={cfg.host || ""}
            onChange={(e) => upd({ host: e.target.value })}
            placeholder="lic-cadence-01.eda.local"
            className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
            data-testid="ssh-host"
          />
        </Field>

        <Field label="SSH Port">
          <input
            type="number"
            value={cfg.port || 22}
            onChange={(e) => upd({ port: Number(e.target.value) || 22 })}
            className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white tabular-nums"
            data-testid="ssh-port"
          />
        </Field>

        <Field label="Username">
          <input
            value={cfg.username || ""}
            onChange={(e) => upd({ username: e.target.value })}
            placeholder="cadops"
            className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
            data-testid="ssh-username"
          />
        </Field>

        <Field label="lmutil path">
          <input
            value={cfg.lmutil_path || ""}
            onChange={(e) => upd({ lmutil_path: e.target.value })}
            placeholder="/usr/local/flexlm/lmutil"
            className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
            data-testid="ssh-lmutil"
          />
        </Field>

        {cfg.auth_method === "password" ? (
          <Field label="Password" full>
            <input
              type="password"
              value={cfg.password || ""}
              onChange={(e) => upd({ password: e.target.value })}
              placeholder="••••••••"
              className="w-full bg-[#0a0a0a] border border-[#222] px-2 py-2 text-xs text-white"
              data-testid="ssh-password"
            />
          </Field>
        ) : (
          <Field label="Private Key (PEM)" full>
            <textarea
              value={cfg.private_key || ""}
              onChange={(e) => upd({ private_key: e.target.value })}
              placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
              rows={5}
              className="w-full bg-[#000] border border-[#222] px-2 py-2 text-xs text-emerald-400 font-mono"
              data-testid="ssh-private-key"
            />
          </Field>
        )}
      </div>

      <div className="px-4 pb-4">
        <div className="bg-[#000] border border-[#222] p-3 text-[11px] font-mono text-emerald-400">
          <div className="text-[#6b7280] mb-1">// adapter preview</div>
          {mode === "ssh"
            ? `> ssh ${cfg.username || "user"}@${cfg.host || "host"}:${cfg.port || 22} -- ${cfg.lmutil_path || "lmutil"} lmstat -a -c @${server.port}@${server.host}`
            : `> [MOCK MODE] internal simulator generates checkouts (no SSH)`}
        </div>
      </div>
    </div>
  );
};

const Field = ({ label, children, full }) => (
  <div className={full ? "md:col-span-2" : ""}>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1">
      {label}
    </div>
    {children}
  </div>
);

export default SshConfigPanel;
