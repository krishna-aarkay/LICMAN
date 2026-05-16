import { useState } from "react";
import { Navigate } from "react-router-dom";
import { Terminal, UserPlus, ShieldCheck } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { formatApiErrorDetail } from "@/lib/errors";

export default function Setup() {
  const { user, needsSetup, loading, setup } = useAuth();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("Administrator");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  if (loading) return null;
  if (!needsSetup && user) return <Navigate to="/" replace />;
  if (!needsSetup && !user) return <Navigate to="/login" replace />;

  const onSubmit = async (e) => {
    e.preventDefault();
    if (password.length < 8) return toast.error("Password must be at least 8 characters");
    if (password !== confirm) return toast.error("Passwords do not match");
    setBusy(true);
    try {
      await setup(email.trim().toLowerCase(), password, name);
      toast.success("Admin account created. Welcome to LICMAN.");
    } catch (err) {
      toast.error(formatApiErrorDetail(err, "Setup failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] grid-bg flex items-center justify-center p-6" data-testid="setup-page">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0a0a0a]/40 to-[#050505] pointer-events-none" />
      <form
        onSubmit={onSubmit}
        className="relative w-full max-w-md bg-[#0a0a0a] border border-[#222] p-8 rounded-sm"
        data-testid="setup-form"
      >
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 border border-[#333] bg-[#111] flex items-center justify-center">
            <Terminal size={20} className="text-emerald-400" />
          </div>
          <div>
            <div className="font-mono text-xl font-bold">LICMAN</div>
            <div className="font-mono text-[10px] text-[#6b7280] uppercase tracking-[0.25em]">
              FIRST-RUN · CREATE ADMINISTRATOR
            </div>
          </div>
        </div>

        <div className="bg-emerald-500/10 border border-emerald-500/30 text-emerald-300 px-3 py-2 text-[11px] font-mono mb-5 flex items-start gap-2">
          <ShieldCheck size={14} className="mt-0.5 shrink-0" />
          <div>
            This is the very first run. The account you create now becomes the <b>administrator</b>.
            Other users can be added later from the <b>USERS</b> page.
          </div>
        </div>

        <Field label="Admin Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@yourcompany.com"
            required
            autoFocus
            className="inp"
            data-testid="setup-email"
          />
        </Field>
        <Field label="Display Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="inp"
            data-testid="setup-name"
          />
        </Field>
        <Field label="Password (min 8 chars)">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            className="inp"
            data-testid="setup-password"
          />
        </Field>
        <Field label="Confirm Password">
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            minLength={8}
            className="inp"
            data-testid="setup-confirm"
          />
        </Field>

        <button
          type="submit"
          disabled={busy}
          className="btn-brutal primary w-full flex items-center justify-center gap-2 mt-4"
          data-testid="setup-submit"
        >
          <UserPlus size={13} /> {busy ? "CREATING…" : "CREATE ADMINISTRATOR"}
        </button>
      </form>

      <style>{`
        .inp { width:100%; background:#000; border:1px solid #222; padding:10px 12px; font-size:13px; color:#fff; font-family:'JetBrains Mono',monospace; outline:none; }
        .inp:focus { border-color:#10b981; }
      `}</style>
    </div>
  );
}

const Field = ({ label, children }) => (
  <div className="mb-3">
    <div className="text-[10px] uppercase tracking-[0.2em] text-[#6b7280] mb-1 font-mono">
      {label}
    </div>
    {children}
  </div>
);
