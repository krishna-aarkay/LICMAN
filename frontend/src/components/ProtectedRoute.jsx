import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const Loader = () => (
  <div className="min-h-screen bg-[#050505] flex items-center justify-center font-mono text-[#9ca3af] text-sm">
    Loading<span className="cursor-blink ml-2" />
  </div>
);

export const ProtectedRoute = ({ children, adminOnly = false }) => {
  const { user, needsSetup, loading, isAdmin } = useAuth();
  const loc = useLocation();
  if (loading) return <Loader />;
  if (needsSetup) return <Navigate to="/setup" replace />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />;
  return children;
};

export const PublicOnlyRoute = ({ children }) => {
  const { user, needsSetup, loading } = useAuth();
  if (loading) return <Loader />;
  if (needsSetup && window.location.pathname !== "/setup") return <Navigate to="/setup" replace />;
  if (!needsSetup && user) return <Navigate to="/" replace />;
  return children;
};

export default ProtectedRoute;
