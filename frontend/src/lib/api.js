import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND_URL}/api`;

const http = axios.create({ baseURL: API });

export const api = {
  // servers
  listServers: () => http.get("/servers").then((r) => r.data),
  getServer: (id) => http.get(`/servers/${id}`).then((r) => r.data),
  createServer: (data) => http.post("/servers", data).then((r) => r.data),
  updateServer: (id, data) => http.patch(`/servers/${id}`, data).then((r) => r.data),
  deleteServer: (id) => http.delete(`/servers/${id}`).then((r) => r.data),
  saveLicense: (id, content) =>
    http.put(`/servers/${id}/license`, { content }).then((r) => r.data),
  saveOptions: (id, content) =>
    http.put(`/servers/${id}/options`, { content }).then((r) => r.data),
  reread: (id) => http.post(`/servers/${id}/reread`).then((r) => r.data),
  restart: (id) => http.post(`/servers/${id}/restart`).then((r) => r.data),
  toggle: (id) => http.post(`/servers/${id}/toggle`).then((r) => r.data),

  // checkouts
  serverCheckouts: (id) => http.get(`/servers/${id}/checkouts`).then((r) => r.data),
  allCheckouts: () => http.get(`/checkouts`).then((r) => r.data),

  // reservations
  listReservations: (server_id) =>
    http
      .get(`/reservations`, { params: server_id ? { server_id } : {} })
      .then((r) => r.data),
  createReservation: (data) => http.post(`/reservations`, data).then((r) => r.data),
  deleteReservation: (id) => http.delete(`/reservations/${id}`).then((r) => r.data),

  // audit / stats
  audit: (limit = 50) =>
    http.get(`/audit`, { params: { limit } }).then((r) => r.data),
  stats: () => http.get(`/stats`).then((r) => r.data),
  resetSeed: () => http.post(`/seed/reset`).then((r) => r.data),
};

export const VENDOR_META = {
  cadence: { label: "CADENCE", color: "#ef4444", accent: "rgba(239,68,68,0.15)" },
  synopsys: { label: "SYNOPSYS", color: "#f59e0b", accent: "rgba(245,158,11,0.15)" },
  mentor: { label: "SIEMENS / MENTOR", color: "#3b82f6", accent: "rgba(59,130,246,0.15)" },
};

export const fmtAgo = (iso) => {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};
