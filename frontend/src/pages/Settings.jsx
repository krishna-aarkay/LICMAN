import { useEffect, useState } from "react";
import { Save, Send, Mail, BellRing, Info, Webhook, Download, Crown } from "lucide-react";
import { api, fmtAgo } from "@/lib/api";
import Header from "@/components/Header";
import { toast } from "sonner";

export default function Settings() {
  const [stats, setStats] = useState(null);
  const [cfg, setCfg] = useState(null);
  const [recipients, setRecipients] = useState("");
  const [alerts, setAlerts] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendingWebhook, setSendingWebhook] = useState(false);

  const load = async () => {
    const [s, c, a] = await Promise.all([api.stats(), api.getSettings(), api.listAlerts(50)]);
    setStats(s);
    setCfg(c);
    setRecipients((c.to_addresses || []).join(", "));
    setAlerts(a);
    setDirty(false);
  };

  useEffect(() => {
    load();
  }, []);

  const upd = (patch) => {
    setCfg((p) => ({ ...p, ...patch }));
    setDirty(true);
  };

  const save = async () => {
    const to = recipients
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await api.saveSettings({ ...cfg, to_addresses: to });
      toast.success("Settings saved");
      setDirty(false);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    }
  };

  const sendTest = async () => {
    setSending(true);
    try {
      const r = await api.testEmail();
      if (r.ok) toast.success("Test email sent");
      else toast.error(`SMTP error: ${r.error}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Test failed");
    } finally {
      setSending(false);
    }
  };

  const sendTestWebhook = async () => {
    setSendingWebhook(true);
    try {
      const r = await api.testWebhook();
      if (r.ok) toast.success("Test webhook delivered");
      else toast.error(`Webhook error: ${r.error}`);
      load();
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Webhook test failed");
    } finally {
      setSendingWebhook(false);
    }
  };

  const useO365 = () => {
    upd({ smtp_host: "smtp.office365.com", smtp_port: 587, starttls: true });
    toast.success("Office 365 SMTP preset applied");
  };

  if (!cfg) {
    return (
      <div className="min-h-screen bg-[#050505] text-[#9ca3af] flex items-center justify-center font-mono">
        Loading <span className="cursor-blink ml-2" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="settings-page">
      <Header stats={stats} autoRefresh={false} onToggleRefresh={() => {}} />

      <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              /// CONFIGURATION
            </div>
            <h1 className="font-mono text-2xl font-bold tracking-tight mt-1">
              Alert Settings
            </h1>
          </div>
          <div className="flex gap-2">
            <button
              className="btn-brutal flex items-center gap-1.5"
              onClick={sendTest}
              disabled={sending}
              data-testid="send-test-email-btn"
            >
              <Send size={12} /> {sending ? "SENDING…" : "SEND TEST EMAIL"}
            </button>
            <button
              className="btn-brutal primary flex items-center gap-1.5"
              onClick={save}
              disabled={!dirty}
              data-testid="save-settings-btn"
            >
              <Save size={12} /> SAVE
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_440px] gap-6">
          {/* Form */}
          <section className="space-y-4">
            <Panel title="SMTP SERVER" icon={Mail}>
              <div className="flex items-center justify-between mb-3">
                <div className="font-mono text-[10px] text-[#9ca3af]">
                  Office 365 users: host <span className="text-white">smtp.office365.com</span>,
                  port <span className="text-white">587</span>, use an{" "}
                  <span className="text-amber-400">App Password</span> (MFA-required).
                </div>
                <button
                  className="btn-brutal text-[10px] py-1"
                  onClick={useO365}
                  data-testid="o365-preset-btn"
                >
                  USE O365 PRESET
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="SMTP Host">
                  <input
                    value={cfg.smtp_host || ""}
                    onChange={(e) => upd({ smtp_host: e.target.value })}
                    placeholder="smtp.office365.com"
                    className="inp"
                    data-testid="smtp-host"
                  />
                </Field>
                <Field label="Port">
                  <input
                    type="number"
                    value={cfg.smtp_port || 587}
                    onChange={(e) => upd({ smtp_port: Number(e.target.value) || 587 })}
                    className="inp tabular-nums"
                    data-testid="smtp-port"
                  />
                </Field>
                <Field label="Username (email)">
                  <input
                    value={cfg.smtp_username || ""}
                    onChange={(e) => upd({ smtp_username: e.target.value })}
                    placeholder="alerts@yourcompany.com"
                    className="inp"
                    data-testid="smtp-username"
                  />
                </Field>
                <Field label="Password / App Password">
                  <input
                    type="password"
                    value={cfg.smtp_password || ""}
                    onChange={(e) => upd({ smtp_password: e.target.value })}
                    placeholder="••••••••"
                    className="inp"
                    data-testid="smtp-password"
                  />
                </Field>
                <Field label="From Address">
                  <input
                    value={cfg.from_address || ""}
                    onChange={(e) => upd({ from_address: e.target.value })}
                    placeholder="licman-alerts@yourcompany.com"
                    className="inp"
                    data-testid="from-address"
                  />
                </Field>
                <Field label="STARTTLS">
                  <div className="flex border border-[#222]" data-testid="starttls-toggle">
                    {[true, false].map((v) => (
                      <button
                        key={String(v)}
                        onClick={() => upd({ starttls: v })}
                        className={`flex-1 py-2 text-[10px] uppercase tracking-wider font-mono ${
                          !!cfg.starttls === v
                            ? "bg-white text-black"
                            : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                        }`}
                        data-testid={`starttls-${v ? "on" : "off"}`}
                      >
                        {v ? "ENABLED" : "DISABLED"}
                      </button>
                    ))}
                  </div>
                </Field>
                <Field label="Recipients (comma-separated)" full>
                  <input
                    value={recipients}
                    onChange={(e) => {
                      setRecipients(e.target.value);
                      setDirty(true);
                    }}
                    placeholder="cad-team@yourcompany.com, you@yourcompany.com"
                    className="inp"
                    data-testid="recipients"
                  />
                </Field>
              </div>
            </Panel>

            <Panel title="ALERT TRIGGERS" icon={BellRing}>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Toggle
                  label="Master Enable"
                  value={cfg.enabled}
                  onChange={(v) => upd({ enabled: v })}
                  testid="alerts-enabled"
                  wrapperTestid="alert-master-toggle"
                />
                <Toggle
                  label="Saturation Alerts"
                  value={cfg.alert_on_saturation}
                  onChange={(v) => upd({ alert_on_saturation: v })}
                  testid="alerts-saturation"
                  wrapperTestid="alert-saturation-toggle"
                />
                <Toggle
                  label="Expiry Alerts"
                  value={cfg.alert_on_expiry}
                  onChange={(v) => upd({ alert_on_expiry: v })}
                  testid="alerts-expiry"
                  wrapperTestid="alert-expiry-toggle"
                />
                <Field label="Expiry warn threshold (days)" full>
                  <input
                    type="number"
                    min={1}
                    max={365}
                    value={cfg.expiry_warn_days || 30}
                    onChange={(e) => upd({ expiry_warn_days: Number(e.target.value) || 30 })}
                    className="inp tabular-nums w-32"
                    data-testid="expiry-warn-days"
                  />
                </Field>
              </div>
              <div className="mt-3 flex items-start gap-2 text-[10px] font-mono text-[#9ca3af]">
                <Info size={12} className="mt-0.5 shrink-0" />
                <div>
                  Alerts are throttled to one delivery per feature per 6 hours, so the inbox
                  stays sane during sustained saturation.
                </div>
              </div>
            </Panel>

            <Panel title="WEBHOOK (SLACK / TEAMS)" icon={Webhook}>
              <div className="flex items-center justify-between mb-3">
                <div className="font-mono text-[10px] text-[#9ca3af]">
                  Optional: post alerts to a Slack or Microsoft Teams incoming webhook.
                  Useful when your CAD team lives in chat more than email.
                </div>
                <button
                  className="btn-brutal flex items-center gap-1.5 text-[10px] py-1"
                  onClick={sendTestWebhook}
                  disabled={sendingWebhook || !cfg.webhook_url}
                  data-testid="send-test-webhook-btn"
                >
                  <Send size={11} /> {sendingWebhook ? "SENDING…" : "TEST WEBHOOK"}
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <Field label="Webhook URL" full>
                  <input
                    value={cfg.webhook_url || ""}
                    onChange={(e) => upd({ webhook_url: e.target.value })}
                    placeholder="https://hooks.slack.com/services/T000/B000/XXX"
                    className="inp"
                    data-testid="webhook-url"
                  />
                </Field>
                <Field label="Webhook Flavor">
                  <div className="flex border border-[#222]" data-testid="webhook-kind-toggle">
                    {[
                      { v: "slack", label: "SLACK" },
                      { v: "teams", label: "TEAMS" },
                      { v: "generic", label: "GENERIC" },
                    ].map((opt) => (
                      <button
                        key={opt.v}
                        onClick={() => upd({ webhook_kind: opt.v })}
                        className={`flex-1 py-2 text-[10px] uppercase tracking-wider font-mono ${
                          (cfg.webhook_kind || "generic") === opt.v
                            ? "bg-white text-black"
                            : "text-[#9ca3af] hover:bg-[#1a1a1a]"
                        }`}
                        data-testid={`webhook-kind-${opt.v}`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>
                </Field>
                <Toggle
                  label="Webhook Enabled"
                  value={cfg.webhook_enabled}
                  onChange={(v) => upd({ webhook_enabled: v })}
                  testid="webhook-enabled"
                  wrapperTestid="webhook-enabled-toggle"
                />
              </div>
            </Panel>

            <Panel title="SON OF GRID ENGINE (SGE)" icon={Crown}>
              <div className="flex items-center justify-between mb-3">
                <div className="font-mono text-[10px] text-[#9ca3af] flex-1 pr-4">
                  When SGE is enabled, the Priority &amp; Preemption page will try{" "}
                  <span className="text-emerald-400">qmod -d &lt;jobid&gt;</span> first
                  (graceful — kills the user&apos;s scheduled job) before falling back to
                  <span className="text-amber-400"> lmremove </span>
                  (force-yank the license seat). Auto-discovery uses{" "}
                  <span className="text-emerald-400">qconf -suserl / -shgrpl / -sprjl</span>.
                </div>
                <button
                  className="btn-brutal flex items-center gap-1.5 text-[10px] py-1"
                  onClick={async () => {
                    try {
                      const r = await api.sgeTest();
                      if (r.ok) toast.success("SGE reachable ✓");
                      else toast.error(r.error || r.output?.slice(0, 120) || "SGE test failed");
                    } catch (e) {
                      toast.error(e?.response?.data?.detail || "SGE test failed");
                    }
                  }}
                  disabled={!cfg.sge_enabled}
                  data-testid="sge-test-btn"
                >
                  <Send size={11} /> TEST SGE
                </button>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <Field label="qstat path">
                  <input
                    value={cfg.sge_qstat_path || ""}
                    onChange={(e) => upd({ sge_qstat_path: e.target.value })}
                    placeholder="qstat"
                    className="inp"
                    data-testid="sge-qstat-path"
                  />
                </Field>
                <Field label="qmod path">
                  <input
                    value={cfg.sge_qmod_path || ""}
                    onChange={(e) => upd({ sge_qmod_path: e.target.value })}
                    placeholder="qmod"
                    className="inp"
                    data-testid="sge-qmod-path"
                  />
                </Field>
                <Toggle
                  label="SGE Integration Enabled"
                  value={cfg.sge_enabled}
                  onChange={(v) => upd({ sge_enabled: v })}
                  testid="sge-enabled"
                  wrapperTestid="sge-enabled-toggle"
                />
              </div>
            </Panel>
          </section>

          {/* Alerts log */}
          <section className="bg-[#111] border border-[#222] rounded-sm h-fit sticky top-24">
            <div className="px-4 py-3 border-b border-[#222] flex items-center justify-between">
              <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
                RECENT ALERTS
              </div>
              <div className="flex items-center gap-2">
                <a
                  href={api.auditExportUrl(1000)}
                  className="font-mono text-[9px] uppercase tracking-wider text-[#9ca3af] hover:text-emerald-400 flex items-center gap-1"
                  data-testid="export-audit-csv-btn"
                  title="Download last 1000 audit events as CSV"
                >
                  <Download size={10} /> AUDIT CSV
                </a>
                <span className="font-mono text-xs text-emerald-400">[{alerts.length}]</span>
              </div>
            </div>
            <div className="divide-y divide-[#1a1a1a] max-h-[70vh] overflow-y-auto">
              {alerts.map((a) => {
                const kindColor =
                  a.kind === "saturation" ? "#f59e0b" : a.kind === "expiry" ? "#ef4444" : "#3b82f6";
                return (
                  <div key={a.id} className="px-4 py-2.5 hover:bg-[#1a1a1a]" data-testid={`alert-row-${a.id}`}>
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className="font-mono text-[9px] uppercase tracking-wider font-bold"
                        style={{ color: kindColor }}
                      >
                        {a.kind}
                      </span>
                      <span className="font-mono text-[10px] text-[#6b7280]">
                        {fmtAgo(a.timestamp)}
                      </span>
                    </div>
                    <div className="font-mono text-[11px] text-white mt-0.5">{a.detail}</div>
                    <div className="font-mono text-[10px] mt-0.5">
                      <span className="text-[#6b7280]">delivery: </span>
                      <span style={{ color: a.delivered ? "#10b981" : "#6b7280" }}>
                        {a.delivered ? "DELIVERED" : "logged-only"}
                      </span>
                      {a.error && <span className="text-red-400"> · {a.error}</span>}
                    </div>
                  </div>
                );
              })}
              {alerts.length === 0 && (
                <div className="px-4 py-10 text-center text-[#6b7280] font-mono text-xs">
                  {"// no alerts yet"}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>

      <style>{`
        .inp {
          width: 100%;
          background: #0a0a0a;
          border: 1px solid #222;
          padding: 8px;
          font-size: 12px;
          color: #fff;
          font-family: 'JetBrains Mono', monospace;
        }
        .inp:focus { outline: none; border-color: #444; }
      `}</style>
    </div>
  );
}

const Panel = ({ title, icon: Icon, children }) => (
  <div className="bg-[#111] border border-[#222] rounded-sm">
    <div className="px-4 py-3 border-b border-[#222] flex items-center gap-2">
      <Icon size={13} className="text-[#9ca3af]" />
      <span className="font-mono text-[10px] uppercase tracking-[0.25em] text-[#9ca3af]">
        {title}
      </span>
    </div>
    <div className="p-4">{children}</div>
  </div>
);

const Field = ({ label, children, full }) => (
  <div className={full ? "md:col-span-2" : ""}>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1 font-mono">
      {label}
    </div>
    {children}
  </div>
);

const Toggle = ({ label, value, onChange, testid, wrapperTestid }) => (
  <div data-testid={wrapperTestid}>
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1 font-mono">
      {label}
    </div>
    <div className="flex border border-[#222]">
      {[true, false].map((v) => (
        <button
          key={String(v)}
          onClick={() => onChange(v)}
          className={`flex-1 py-1.5 text-[10px] uppercase tracking-wider font-mono ${
            !!value === v
              ? v
                ? "bg-emerald-500/20 text-emerald-400"
                : "bg-[#1a1a1a] text-[#9ca3af]"
              : "text-[#6b7280] hover:bg-[#1a1a1a]"
          }`}
          data-testid={`${testid}-${v ? "on" : "off"}`}
        >
          {v ? "ON" : "OFF"}
        </button>
      ))}
    </div>
  </div>
);
