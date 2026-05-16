import { useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Terminal, LogIn } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { formatApiErrorDetail } from "@/lib/errors";

export default function Login() {
  const { user, login, needsSetup, loading } = useAuth();
  const loc = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  if (loading) return null;
  if (needsSetup) return <Navigate to="/setup" replace />;
  if (user) return <Navigate to={loc.state?.from || "/"} replace />;

  const onSubmit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email.trim().toLowerCase(), password);
      toast.success(`Welcome, ${email}`);
    } catch (err) {
      toast.error(formatApiErrorDetail(err, "Login failed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#050505] grid-bg flex items-center justify-center p-6" data-testid="login-page">
      <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0a0a0a]/40 to-[#050505] pointer-events-none" />
      <form
        onSubmit={onSubmit}
        className="relative w-full max-w-md bg-[#0a0a0a] border border-[#222] p-8 rounded-sm"
        data-testid="login-form"
      >
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 border border-[#333] bg-[#111] flex items-center justify-center">
            <Terminal size={20} className="text-emerald-400" />
          </div>
          <div>
            <div className="font-mono text-xl font-bold">
              LICMAN<span className="text-emerald-400 cursor-blink"></span>
            </div>
            <div className="font-mono text-[10px] text-[#6b7280] uppercase tracking-[0.25em]">
              VLSI · LICENSE CONSOLE
            </div>
          </div>
        </div>

        <h1 className="font-mono text-base uppercase tracking-wider mb-1">Sign in</h1>
        <p className="font-mono text-[11px] text-[#6b7280] mb-6">
          {"// authentication required to enter the control room"}
        </p>

        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@yourcompany.com"
            required
            autoFocus
            className="inp"
            data-testid="login-email"
          />
        </Field>
        <Field label="Password">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            required
            className="inp"
            data-testid="login-password"
          />
        </Field>

        <button
          type="submit"
          disabled={busy}
          className="btn-brutal primary w-full flex items-center justify-center gap-2 mt-4"
          data-testid="login-submit"
        >
          <LogIn size={13} /> {busy ? "SIGNING IN…" : "SIGN IN"}
        </button>

        <div className="mt-4 text-center font-mono text-[10px] text-[#6b7280]">
          {"// 5 failed attempts → 15 min lockout"}
        </div>
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
