import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";

const AuthCtx = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [needsSetup, setNeedsSetup] = useState(null);
  const [loading, setLoading] = useState(true);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.setupStatus();
      setNeedsSetup(!!s.needs_setup);
      if (!s.needs_setup) {
        try {
          const me = await api.authMe();
          setUser(me);
        } catch {
          setUser(null);
        }
      } else {
        setUser(null);
      }
    } catch (e) {
      console.error("bootstrap failed", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    bootstrap();
  }, [bootstrap]);

  const login = async (email, password) => {
    const r = await api.authLogin({ email, password });
    setUser(r.user);
    setNeedsSetup(false);
    return r.user;
  };

  const setup = async (email, password, name) => {
    const r = await api.authSetup({ email, password, name });
    setUser(r.user);
    setNeedsSetup(false);
    return r.user;
  };

  const logout = async () => {
    try { await api.authLogout(); } catch {}
    setUser(null);
  };

  const refresh = bootstrap;

  return (
    <AuthCtx.Provider value={{ user, needsSetup, loading, login, setup, logout, refresh, isAdmin: user?.role === "admin" }}>
      {children}
    </AuthCtx.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error("useAuth must be inside AuthProvider");
  return ctx;
};
