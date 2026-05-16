import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider } from "@/contexts/AuthContext";
import { ProtectedRoute, PublicOnlyRoute } from "@/components/ProtectedRoute";
import Dashboard from "@/pages/Dashboard";
import ServerDetail from "@/pages/ServerDetail";
import Settings from "@/pages/Settings";
import Expiry from "@/pages/Expiry";
import Login from "@/pages/Login";
import Setup from "@/pages/Setup";
import Users from "@/pages/Users";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/setup" element={<PublicOnlyRoute><Setup /></PublicOnlyRoute>} />
            <Route path="/login" element={<PublicOnlyRoute><Login /></PublicOnlyRoute>} />
            <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
            <Route path="/servers/:id" element={<ProtectedRoute><ServerDetail /></ProtectedRoute>} />
            <Route path="/expiry" element={<ProtectedRoute><Expiry /></ProtectedRoute>} />
            <Route path="/settings" element={<ProtectedRoute adminOnly><Settings /></ProtectedRoute>} />
            <Route path="/users" element={<ProtectedRoute adminOnly><Users /></ProtectedRoute>} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#111111",
            color: "#f3f4f6",
            border: "1px solid #222222",
            borderRadius: "2px",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: "12px",
          },
        }}
      />
    </div>
  );
}

export default App;
