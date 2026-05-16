import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import Dashboard from "@/pages/Dashboard";
import ServerDetail from "@/pages/ServerDetail";
import Settings from "@/pages/Settings";
import Expiry from "@/pages/Expiry";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/servers/:id" element={<ServerDetail />} />
          <Route path="/expiry" element={<Expiry />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
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
