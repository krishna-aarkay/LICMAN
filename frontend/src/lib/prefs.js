const KEY = "licman_prefs_v1";

const defaults = {
  autoRefresh: true,
  vendorFilter: "ALL",
  searchQuery: "",
  lastServerId: null,
  tz: "IST",
};

export const prefs = {
  load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return { ...defaults };
      return { ...defaults, ...JSON.parse(raw) };
    } catch {
      return { ...defaults };
    }
  },
  save(patch) {
    try {
      const cur = this.load();
      const next = { ...cur, ...patch };
      localStorage.setItem(KEY, JSON.stringify(next));
      return next;
    } catch {
      return patch;
    }
  },
};
