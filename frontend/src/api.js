const BASE = "/api";

async function request(path, options = {}) {
  const resp = await fetch(BASE + path, options);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${resp.status}`);
  }
  return resp.json();
}

const post = (path, body) =>
  request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });

async function upload(path, blob, filename) {
  const resp = await fetch(BASE + path, {
    method: "POST",
    headers: { "X-Filename": encodeURIComponent(filename) },
    body: blob,
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || err.error || `HTTP ${resp.status}`);
  }
  return resp.json();
}

export const api = {
  config: () => request("/config"),
  setKey: (deepseekApiKey) => post("/config/key", { deepseek_api_key: deepseekApiKey }),
  agentStart: (interval, dry) => post("/agent/start", { interval, dry }),
  agentStop: () => post("/agent/stop"),
  agentStatus: () => request("/agent/status"),
  agentEvents: (after) => request(`/agent/events?after=${after || 0}`),
  agentReplay: (limit = 200) => request(`/agent/replay?limit=${limit || 200}`),
  // ---- 运营中心 ----
  opsOverview: () => request("/ops/overview"),
  opsReport: (period) => request(`/ops/report?period=${period}`),
  opsReportRefresh: (period) => post(`/ops/report/refresh?period=${period}`, {}),
  opsRefunds: () => request("/ops/refunds"),
  opsHealth: () => request("/ops/health"),
  opsRoi: () => request("/ops/roi"),
  opsReallocate: (dailyBudget) => post("/ops/roi/reallocate", { daily_budget: dailyBudget }),
  opsImages: () => request("/ops/images"),
  opsCrawl: (platform, category, keyword, limit) =>
    post("/ops/images/crawl", { platform, category, keyword, limit }),
  opsOptimization: () => request("/ops/optimization"),
  opsCommands: () => request("/ops/commands"),
  opsCommandDetail: (name) => request(`/ops/commands/${encodeURIComponent(name)}`),
  opsCommandExecute: (name, args) => post("/ops/commands/execute", { name, args }),
  opsCommandCreate: (requirement, sampleArgs) =>
    post("/ops/commands/create", { requirement, sample_args: sampleArgs }),
  opsCommandEvolve: (name, requirement) =>
    post("/ops/commands/evolve", { name, requirement }),
  opsCommandRollback: (name, version) =>
    post("/ops/commands/rollback", { name, version }),
  opsCommandDelete: (name) => post("/ops/commands/delete", { name }),
  opsForgeStatus: () => request("/ops/forge/status"),
  opsImageUrl: (name) => `/api/ops/images/file/${encodeURIComponent(name)}`,
  // ---- 数据接入 ----
  opsDataSource: () => request("/ops/data/source"),
  opsDataLinks: () => request("/ops/data/links"),
  opsOverviewSource: () => request("/ops/data/overview-source"),
  opsDailySource: () => request("/ops/data/daily"),
  opsPeriodsSource: () => request("/ops/data/periods"),
  opsReconcile: () => request("/ops/reconcile"),
  opsLiveStatus: () => request("/ops/live/status"),
  opsLiveStart: (interval) => request(`/ops/live/start?interval=${interval || 1800}`, { method: "POST" }),
  opsLiveStop: () => request("/ops/live/stop", { method: "POST" }),
  opsTriggerPeriods: () => request("/ops/live/trigger-periods", { method: "POST" }),
  opsDataTemplate: (kind) => request(`/ops/data/template?kind=${kind}`),
  opsImportOrders: (blob, filename) => upload("/ops/data/import/orders", blob, filename),
  opsImportLinks: (blob, filename) => upload("/ops/data/import/links", blob, filename),
  opsSnapshot: (rows) => post("/ops/data/snapshot", { rows }),
  opsSync: (useCurrent, pageUrl) => post("/ops/data/sync", { use_current: useCurrent, page_url: pageUrl }),
  opsClearData: () => post("/ops/data/clear"),
  // ---- 实时监控 ----
  opsMonitorStatus: () => request("/ops/monitor/status"),
  opsMonitorStart: (interval) => post("/ops/monitor/start", { interval }),
  opsMonitorStop: () => post("/ops/monitor/stop"),
  opsMonitorRun: () => post("/ops/monitor/run"),
  opsMonitorAlerts: (limit = 50, level = "") =>
    request(`/ops/monitor/alerts?limit=${limit}&level=${encodeURIComponent(level)}`),
  // ---- 记忆库 ----
  memoryStats: () => request("/memory/stats"),
  memoryList: (query = "", limit = 100) =>
    request(`/memory/list?query=${encodeURIComponent(query || "")}&limit=${limit || 100}`),
  memoryLearn: () => post("/memory/learn"),
  memoryToggle: (enabled) => post("/memory/toggle", { enabled }),
  memoryRemove: (id) => post("/memory/remove", { id }),
  memoryTest: (text) => request(`/memory/test?text=${encodeURIComponent(text || "")}`),
  memorySync: () => post("/memory/sync"),
  memorySyncStatus: () => request("/memory/sync/status"),
};
