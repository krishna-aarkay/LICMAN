import { useEffect, useState } from "react";
import { Plus, Trash2, Shield, User as UserIcon, KeyRound, Power } from "lucide-react";
import { api, fmtAgo } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import Header from "@/components/Header";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { toast } from "sonner";
import { formatApiErrorDetail } from "@/lib/errors";

export default function Users() {
  const [users, setUsers] = useState([]);
  const [stats, setStats] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [pwUser, setPwUser] = useState(null);
  const { user: me } = useAuth();

  const load = async () => {
    try {
      const [u, s] = await Promise.all([api.listUsers(), api.stats()]);
      setUsers(u);
      setStats(s);
    } catch (e) {
      toast.error(formatApiErrorDetail(e, "Failed to load users"));
    }
  };

  useEffect(() => { load(); }, []);

  const toggleActive = async (u) => {
    try {
      await api.updateUser(u.id, { active: !u.active });
      toast.success(`${u.email} ${u.active ? "disabled" : "enabled"}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e));
    }
  };

  const changeRole = async (u, role) => {
    try {
      await api.updateUser(u.id, { role });
      toast.success(`${u.email} → ${role}`);
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e));
    }
  };

  const remove = async (u) => {
    if (!confirm(`Delete user ${u.email}?`)) return;
    try {
      await api.deleteUser(u.id);
      toast.success("User deleted");
      load();
    } catch (e) {
      toast.error(formatApiErrorDetail(e));
    }
  };

  return (
    <div className="min-h-screen bg-[#050505]" data-testid="users-page">
      <Header stats={stats} autoRefresh={false} onToggleRefresh={() => {}} />

      <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">
        <div className="flex items-end justify-between flex-wrap gap-3">
          <div>
            <div className="font-mono text-[10px] uppercase tracking-[0.3em] text-[#6b7280]">
              /// ACCESS CONTROL
            </div>
            <h1 className="font-mono text-2xl font-bold tracking-tight mt-1">Users</h1>
          </div>
          <button
            onClick={() => setAddOpen(true)}
            className="btn-brutal primary flex items-center gap-2"
            data-testid="add-user-btn"
          >
            <Plus size={14} /> ADD USER
          </button>
        </div>

        <div className="bg-[#111] border border-[#222] rounded-sm" data-testid="users-table">
          <table className="w-full font-mono text-xs">
            <thead className="bg-[#0a0a0a]">
              <tr className="text-left text-[10px] uppercase tracking-wider text-[#6b7280]">
                <th className="px-4 py-3">Email</th>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Role</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Created</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => {
                const isMe = me?.id === u.id;
                return (
                  <tr key={u.id} className="border-t border-[#1a1a1a] hover:bg-[#1a1a1a]" data-testid={`user-row-${u.id}`}>
                    <td className="px-4 py-2 text-white flex items-center gap-2">
                      {u.role === "admin"
                        ? <Shield size={12} className="text-amber-400" />
                        : <UserIcon size={12} className="text-[#6b7280]" />}
                      {u.email}
                      {isMe && <span className="text-[9px] text-emerald-400 ml-1">(you)</span>}
                    </td>
                    <td className="px-4 py-2 text-[#9ca3af]">{u.name || "—"}</td>
                    <td className="px-4 py-2">
                      <div className="flex border border-[#222]">
                        {["admin", "engineer"].map((r) => (
                          <button
                            key={r}
                            onClick={() => !isMe && changeRole(u, r)}
                            disabled={isMe || u.role === r}
                            className={`px-2 py-0.5 text-[9px] uppercase tracking-wider ${
                              u.role === r ? "bg-white text-black" : "text-[#9ca3af] hover:bg-[#222]"
                            } disabled:opacity-60 disabled:cursor-not-allowed`}
                            data-testid={`role-${u.id}-${r}`}
                          >
                            {r}
                          </button>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <span className={u.active ? "text-emerald-400" : "text-red-400"}>
                        ● {u.active ? "ACTIVE" : "DISABLED"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-[#9ca3af]">{fmtAgo(u.created_at)}</td>
                    <td className="px-4 py-2 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => setPwUser(u)}
                          className="btn-brutal text-[10px] py-1 flex items-center gap-1"
                          title="Reset password"
                          data-testid={`reset-pw-${u.id}`}
                        >
                          <KeyRound size={11} />
                        </button>
                        <button
                          onClick={() => !isMe && toggleActive(u)}
                          disabled={isMe}
                          className="btn-brutal text-[10px] py-1 flex items-center gap-1 disabled:opacity-50"
                          title={u.active ? "Disable" : "Enable"}
                          data-testid={`toggle-active-${u.id}`}
                        >
                          <Power size={11} />
                        </button>
                        <button
                          onClick={() => !isMe && remove(u)}
                          disabled={isMe}
                          className="btn-brutal danger text-[10px] py-1 flex items-center gap-1 disabled:opacity-50"
                          title="Delete"
                          data-testid={`delete-user-${u.id}`}
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {users.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-[#6b7280]">// no users</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </main>

      <AddUserDialog open={addOpen} onOpenChange={setAddOpen} onCreated={load} />
      <ResetPwDialog open={!!pwUser} user={pwUser} onClose={() => setPwUser(null)} />
    </div>
  );
}

const AddUserDialog = ({ open, onOpenChange, onCreated }) => {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("engineer");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (password.length < 8) return toast.error("Password must be 8+ chars");
    setBusy(true);
    try {
      await api.createUser({ email: email.trim().toLowerCase(), name, password, role });
      toast.success("User created");
      onCreated();
      onOpenChange(false);
      setEmail(""); setName(""); setPassword(""); setRole("engineer");
    } catch (e) {
      toast.error(formatApiErrorDetail(e));
    } finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-[#0a0a0a] border-[#222] rounded-sm font-mono max-w-md" data-testid="add-user-dialog">
        <DialogHeader><DialogTitle className="font-mono uppercase tracking-wider text-base">New User</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" className="inp" data-testid="new-user-email" />
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="full name" className="inp" data-testid="new-user-name" />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password (8+)" className="inp" data-testid="new-user-password" />
          <div className="flex border border-[#222]">
            {["admin", "engineer"].map((r) => (
              <button key={r} onClick={() => setRole(r)} className={`flex-1 py-2 text-[10px] uppercase tracking-wider ${role === r ? "bg-white text-black" : "text-[#9ca3af] hover:bg-[#1a1a1a]"}`} data-testid={`new-user-role-${r}`}>{r}</button>
            ))}
          </div>
        </div>
        <DialogFooter className="gap-2">
          <button className="btn-brutal" onClick={() => onOpenChange(false)} data-testid="new-user-cancel">CANCEL</button>
          <button className="btn-brutal primary" onClick={submit} disabled={busy} data-testid="new-user-submit">{busy ? "CREATING…" : "CREATE"}</button>
        </DialogFooter>
        <style>{`.inp{width:100%;background:#000;border:1px solid #222;padding:8px;font-size:12px;color:#fff;font-family:'JetBrains Mono',monospace;outline:none}.inp:focus{border-color:#10b981}`}</style>
      </DialogContent>
    </Dialog>
  );
};

const ResetPwDialog = ({ open, user, onClose }) => {
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (pw.length < 8) return toast.error("Password must be 8+ chars");
    setBusy(true);
    try {
      await api.updateUser(user.id, { password: pw });
      toast.success("Password reset");
      setPw(""); onClose();
    } catch (e) { toast.error(formatApiErrorDetail(e)); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[#0a0a0a] border-[#222] rounded-sm font-mono max-w-md">
        <DialogHeader><DialogTitle className="font-mono uppercase tracking-wider text-base">Reset password — {user?.email}</DialogTitle></DialogHeader>
        <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="new password (8+)" className="w-full bg-black border border-[#222] px-2 py-2 text-xs text-white font-mono" data-testid="reset-pw-input" />
        <DialogFooter className="gap-2">
          <button className="btn-brutal" onClick={onClose}>CANCEL</button>
          <button className="btn-brutal primary" onClick={submit} disabled={busy} data-testid="reset-pw-submit">{busy ? "SAVING…" : "RESET"}</button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
