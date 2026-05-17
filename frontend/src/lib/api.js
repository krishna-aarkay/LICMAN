import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

const http = axios.create({ baseURL: API, withCredentials: true });

// Refresh-on-401 interceptor — transparent for the UI
let _refreshing = null;
http.interceptors.response.use(
  (r) => r,
  async (error) => {
    const cfg = error.config;
    const status = error.response?.status;
    const url = cfg?.url || "";
    if (status === 401 && !cfg._retry && !url.includes("/auth/")) {
      cfg._retry = true;
      try {
        _refreshing = _refreshing || http.post("/auth/refresh");
        await _refreshing;
        return http(cfg);
      } catch {
        // fall through to error
      } finally {
        _refreshing = null;
      }
    }
    return Promise.reject(error);
  }
);

export const api = {
  // auth
  setupStatus: () => http.get("/setup-status").then((r) => r.data),
  authSetup: (data) => http.post("/auth/setup", data).then((r) => r.data),
  authLogin: (data) => http.post("/auth/login", data).then((r) => r.data),
  authMe: () => http.get("/auth/me").then((r) => r.data),
  authLogout: () => http.post("/auth/logout").then((r) => r.data),

  // users
  listUsers: () => http.get("/users").then((r) => r.data),
  createUser: (data) => http.post("/users", data).then((r) => r.data),
  updateUser: (id, data) => http.patch(`/users/${id}`, data).then((r) => r.data),
  deleteUser: (id) => http.delete(`/users/${id}`).then((r) => r.data),
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
  sync: (id) => http.post(`/servers/${id}/sync`).then((r) => r.data),
  syncAll: () => http.post(`/servers/sync-all`).then((r) => r.data),
  rereadAll: () => http.post(`/servers/reread-all`).then((r) => r.data),
  validateOptions: (id, content) =>
    http.post(`/servers/${id}/options/validate`, { content }).then((r) => r.data),
  fetchLicense: (id) => http.post(`/servers/${id}/fetch-license`).then((r) => r.data),
  saveSsh: (id, data) => http.put(`/servers/${id}/ssh`, data).then((r) => r.data),
  setAdapter: (id, mode) =>
    http.put(`/servers/${id}/adapter`, { adapter_mode: mode }).then((r) => r.data),
  testSsh: (id) => http.post(`/servers/${id}/ssh/test`).then((r) => r.data),

  // checkouts
  serverCheckouts: (id) => http.get(`/servers/${id}/checkouts`).then((r) => r.data),
  allCheckouts: () => http.get(`/checkouts`).then((r) => r.data),
  killCheckout: (server_id, data) =>
    http.post(`/servers/${server_id}/checkouts/kill`, data).then((r) => r.data),

  // usage history
  usage: (params) => http.get(`/usage`, { params }).then((r) => r.data),
  usageSummary: (params) => http.get(`/usage/summary`, { params }).then((r) => r.data),
  usageFacets: () => http.get(`/usage/facets`).then((r) => r.data),
  usageExportUrl: (params = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined),
    ).toString();
    return `${API}/usage/export${qs ? `?${qs}` : ""}`;
  },

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

  // expiry / settings / alerts
  expiry: (warn_days = 90) =>
    http.get(`/expiry`, { params: { warn_days } }).then((r) => r.data),
  expiryExportUrl: (warn_days = 180) =>
    `${API}/expiry/export?warn_days=${warn_days}`,
  auditExportUrl: (limit = 1000) => `${API}/audit/export?limit=${limit}`,
  getSettings: () => http.get(`/settings`).then((r) => r.data),
  saveSettings: (data) => http.put(`/settings`, data).then((r) => r.data),
  testEmail: () => http.post(`/settings/test-email`).then((r) => r.data),
  testWebhook: () => http.post(`/settings/test-webhook`).then((r) => r.data),
  listAlerts: (limit = 50) =>
    http.get(`/alerts`, { params: { limit } }).then((r) => r.data),
  evaluateAlerts: () => http.post(`/alerts/evaluate`).then((r) => r.data),
};

const VENDOR_PRESETS = {
  cadence: { label: "CADENCE", color: "#ef4444" },
  synopsys: { label: "SYNOPSYS", color: "#f59e0b" },
  mentor: { label: "SIEMENS / MENTOR", color: "#3b82f6" },
  siemens: { label: "SIEMENS / MENTOR", color: "#3b82f6" },
  xilinx: { label: "XILINX / AMD", color: "#8b5cf6" },
  amd: { label: "AMD / XILINX", color: "#8b5cf6" },
  defacto: { label: "DEFACTO", color: "#10b981" },
  ansys: { label: "ANSYS", color: "#eab308" },
  altair: { label: "ALTAIR", color: "#06b6d4" },
  keysight: { label: "KEYSIGHT", color: "#f43f5e" },
  intel: { label: "INTEL", color: "#0ea5e9" },
  arm: { label: "ARM", color: "#22d3ee" },
};

// Deterministic palette for unknown vendors
const FALLBACK_COLORS = [
  "#a78bfa", "#fb7185", "#34d399", "#fbbf24", "#60a5fa",
  "#f472b6", "#2dd4bf", "#fcd34d", "#c084fc", "#94a3b8",
];

function _hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export function vendorMeta(vendor) {
  if (!vendor) return { label: "UNKNOWN", color: "#6b7280", accent: "rgba(107,114,128,0.15)" };
  const key = String(vendor).trim().toLowerCase();
  if (VENDOR_PRESETS[key]) {
    const m = VENDOR_PRESETS[key];
    return { ...m, accent: m.color + "26" };
  }
  const color = FALLBACK_COLORS[_hashStr(key) % FALLBACK_COLORS.length];
  return { label: vendor.toUpperCase(), color, accent: color + "26" };
}

// Backward-compat: VENDOR_META acts like a dict via Proxy
export const VENDOR_META = new Proxy(VENDOR_PRESETS, {
  get(target, key) {
    if (typeof key !== "string") return undefined;
    return vendorMeta(key);
  },
});

export const KNOWN_VENDORS = Object.keys(VENDOR_PRESETS);

export const fmtAgo = (iso) => {
  if (!iso) return "—";
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  // Clamp clock-skew / TZ mismatches so we never show a negative "ago"
  if (diff < 0) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// Format a Date as a HH:MM:SS clock in the requested timezone label.
// Supported labels: "UTC" or "IST" (+05:30). Anything else falls back to UTC.
export const fmtClock = (d, tz = "IST") => {
  const date = d instanceof Date ? d : new Date(d);
  if (tz === "IST") {
    return date.toLocaleTimeString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }
  return date.toISOString().slice(11, 19);
};

// Format an ISO timestamp into a compact local label "YYYY-MM-DD HH:MM" in tz.
export const fmtDateTime = (iso, tz = "IST") => {
  if (!iso) return "—";
  const date = new Date(iso);
  if (isNaN(date.getTime())) return iso;
  if (tz === "IST") {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Kolkata",
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hour12: false,
    }).formatToParts(date);
    const get = (t) => parts.find((p) => p.type === t)?.value || "";
    return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
  }
  return date.toISOString().slice(0, 16).replace("T", " ");
};
