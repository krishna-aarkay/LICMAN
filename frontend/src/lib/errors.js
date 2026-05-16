/** Pull a human-readable error string out of an axios error (handles FastAPI validation arrays). */
export function formatApiErrorDetail(err, fallback = "Request failed") {
  const d = err?.response?.data?.detail;
  if (Array.isArray(d)) {
    return d.map((e) => `${(e.loc || []).slice(-1)[0] || "field"}: ${e.msg || ""}`).join("; ");
  }
  if (typeof d === "string") return d;
  return err?.message || fallback;
}
