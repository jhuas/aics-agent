<script setup>
import { ref, reactive, computed, onMounted, watch, onBeforeUnmount } from "vue";
import { api } from "../api";

const tab = ref("overview");
const loading = ref(false);
const toast = reactive({ text: "", kind: "", visible: false });

function showToast(text, kind = "") {
  toast.text = text;
  toast.kind = kind;
  toast.visible = true;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toast.visible = false; }, 3000);
}

async function safe(fn, errMsg) {
  loading.value = true;
  try {
    return await fn();
  } catch (e) {
    showToast((errMsg || "请求失败") + "：" + e.message, "err");
    return null;
  } finally {
    loading.value = false;
  }
}

// ---------- 总览 ----------
const overview = ref(null);
async function loadOverview() {
  const d = await safe(() => api.opsOverview(), "总览加载失败");
  if (d) overview.value = d;
}

// ---------- 报表 ----------
const periods = ["day", "week", "month", "year"];
const period = ref("day");
const report = ref(null);
const reportLoading = ref(false);
async function loadReport(p = period.value) {
  reportLoading.value = true;
  const d = await safe(() => api.opsReport(p), "报表加载失败");
  if (d) { report.value = d; period.value = p; }
  reportLoading.value = false;
}
const trendMax = computed(() => {
  const t = report.value?.趋势 || [];
  return Math.max(1, ...t.map((x) => x.amount));
});
const reportRefreshBusy = ref(false);
async function doRefreshReport() {
  reportRefreshBusy.value = true;
  try {
    const d = await safe(() => api.opsReportRefresh(period.value), "一键更新失败");
    if (d && d.ok) {
      showToast(`已刷新：${(d.刷新?.权威日统计天数 ?? 0)} 天权威日统计 / ${d.刷新?.订单 ?? 0} 订单` +
        (d.刷新?.多周期?.ok ? `，多周期 ${(d.刷新?.多周期?.periods || []).length} 维度已采集` : ""), "ok");
      report.value = d.report;
    } else if (d) {
      showToast(d.message || "已运行采集，但数据未更新", "warn");
    }
    await Promise.all([loadReport(period.value), loadDailySource(),
                       loadPeriodsSource(), loadLiveStatus()]);
  } finally {
    reportRefreshBusy.value = false;
  }
}

// ---------- 退款 ----------
const refunds = ref(null);
async function loadRefunds() {
  const d = await safe(() => api.opsRefunds(), "退款分析加载失败");
  if (d) refunds.value = d;
}

// ---------- 体检 ----------
const health = ref(null);
async function loadHealth() {
  const d = await safe(() => api.opsHealth(), "体检加载失败");
  if (d) health.value = d;
}

// ---------- ROI ----------
const roi = ref(null);
const realloc = ref(null);
const budgetInput = ref(5000);
async function loadRoi() {
  const d = await safe(() => api.opsRoi(), "ROI 加载失败");
  if (d) roi.value = d;
}
async function doReallocate() {
  const d = await safe(() => api.opsReallocate(Number(budgetInput.value) || 5000), "预算再分配失败");
  if (d) realloc.value = d;
}

// ---------- 图库 ----------
const images = ref(null);
const crawl = reactive({ platform: "taobao", category: "", keyword: "", limit: 6 });
const crawling = ref(false);
async function loadImages() {
  const d = await safe(() => api.opsImages(), "图库加载失败");
  if (d) images.value = d;
}
async function doCrawl() {
  crawling.value = true;
  const d = await safe(
    () => api.opsCrawl(crawl.platform, crawl.category, crawl.keyword, Number(crawl.limit) || 6),
    "采集失败");
  if (d) {
    images.value = { 图片: d.结果, 统计: d.统计, 提示: d.提示 || [] };
    showToast(`已采集 ${(d.结果 || []).length} 张参考图`, "ok");
  }
  crawling.value = false;
}
const platforms = [
  ["taobao", "淘宝"], ["jd", "京东"], ["pdd", "拼多多"], ["douyin", "抖音"],
];

// ---------- 命令工厂 ----------
const commands = ref([]);
const cmdDetail = ref(null);
const cmdExec = ref(null);
const forgeLog = ref(null);
const cmdForm = reactive({ requirement: "", sampleArgs: "", execArgs: "{}" });
const cmdBusy = ref(false);

async function loadCommands() {
  const d = await safe(() => api.opsCommands(), "命令列表加载失败");
  if (d) commands.value = d.commands || [];
}
async function loadCmdDetail(name) {
  const d = await safe(() => api.opsCommandDetail(name), "命令详情加载失败");
  if (d) cmdDetail.value = d;
}
async function loadForge() {
  const d = await safe(() => api.opsForgeStatus(), "命令工厂日志加载失败");
  if (d) forgeLog.value = d;
}
async function doCreate() {
  if (!cmdForm.requirement.trim()) return showToast("请先描述你的需求", "err");
  cmdBusy.value = true;
  const d = await safe(
    () => api.opsCommandCreate(cmdForm.requirement, cmdForm.sampleArgs),
    "命令生成失败");
  if (d) {
    cmdForm.requirement = "";
    cmdForm.sampleArgs = "";
    await Promise.all([loadCommands(), loadForge()]);
    if (d.ok) showToast(d.message || "命令已生成", "ok");
    else showToast((d.message || d.error || "生成失败"), "err");
  }
  cmdBusy.value = false;
}
async function doExecute() {
  if (!cmdDetail.value) return;
  let args = {};
  try { args = JSON.parse(cmdForm.execArgs || "{}"); }
  catch { return showToast("参数必须是合法 JSON", "err"); }
  const d = await safe(
    () => api.opsCommandExecute(cmdDetail.value.name, args), "执行失败");
  if (d) cmdExec.value = d;
}
async function doEvolve() {
  const req = prompt("用自然语言描述要改进什么：", "例如：再加上平台佣金 5% 的影响");
  if (!req) return;
  const d = await safe(() => api.opsCommandEvolve(cmdDetail.value.name, req), "命令进化失败");
  if (d) {
    if (d.ok) showToast(d.message || "已升级", "ok");
    else showToast((d.error || d.message || "进化失败"), "err");
    await Promise.all([loadCommands(), loadCmdDetail(cmdDetail.value.name), loadForge()]);
  }
}
async function doRollback() {
  const v = prompt("输入要回滚到的版本号：");
  if (!v) return;
  const d = await safe(() => api.opsCommandRollback(cmdDetail.value.name, Number(v)), "回滚失败");
  if (d) {
    if (d.ok) showToast(d.message || "已回滚", "ok");
    else showToast(d.error || "回滚失败", "err");
    await Promise.all([loadCmdDetail(cmdDetail.value.name), loadForge()]);
  }
}
async function doDelete() {
  if (!confirm(`确定删除命令 [${cmdDetail.value.name}]？此操作不可撤销`)) return;
  const d = await safe(() => api.opsCommandDelete(cmdDetail.value.name), "删除失败");
  if (d) {
    showToast(d.message || (d.ok ? "已删除" : "删除失败"), d.ok ? "ok" : "err");
    cmdDetail.value = null;
    cmdExec.value = null;
    await Promise.all([loadCommands(), loadForge()]);
  }
}

// ---------- 优化方案 ----------
const opt = ref(null);
const optLoading = ref(false);
async function loadOpt() {
  optLoading.value = true;
  const d = await safe(() => api.opsOptimization(), "方案生成失败");
  if (d) opt.value = d;
  optLoading.value = false;
}

// ---------- 数据接入 ----------
const dataSource = ref(null);
const dataLinks = ref(null);
const importBusy = ref(false);
const syncing = ref(false);
const dailySource = ref([]);
const reconcileData = ref(null);
async function loadReconcile() {
  const d = await safe(() => api.opsReconcile(), "严格对账加载失败");
  if (d) reconcileData.value = d;
}
const liveSync = ref(null);
const liveBusy = ref(false);
const liveInterval = ref(1800);
const periodsSource = ref([]);
const periodsBusy = ref(false);
const snapForm = reactive({ product_id: "", name: "", date: "",
                            cost: "", revenue: "", orders: "", clicks: "", impressions: "" });
const snapRows = ref([]);

async function loadDataSource() {
  const d = await safe(() => api.opsDataSource(), "数据源加载失败");
  if (d) dataSource.value = d;
}
async function loadDataLinks() {
  const d = await safe(() => api.opsDataLinks(), "链接表加载失败");
  if (d) dataLinks.value = d;
}
const overviewSource = ref(null);
async function loadOverviewSource() {
  const d = await safe(() => api.opsOverviewSource(), "交易概况加载失败");
  if (d) overviewSource.value = d;
}
async function loadDailySource() {
  const d = await safe(() => api.opsDailySource(), "权威日统计加载失败");
  if (d) dailySource.value = d;
}
async function loadPeriodsSource() {
  const d = await safe(() => api.opsPeriodsSource(), "多周期统计加载失败");
  if (d) periodsSource.value = d;
}
async function triggerPeriodsCollect() {
  periodsBusy.value = true;
  try {
    const d = await safe(() => api.opsTriggerPeriods(), "多周期采集执行失败");
    if (d && d.data) {
      const r = d.data;
      showToast(r.message || (r.ok ? "采集完成" : "采集未完成"), r.ok ? "ok" : (r.reason ? "err" : "warn"));
    }
  } finally {
    await Promise.all([loadPeriodsSource(), loadLiveStatus()]);
    periodsBusy.value = false;
  }
}
async function loadLiveStatus() {
  const d = await safe(() => api.opsLiveStatus(), "实时同步状态加载失败");
  if (d) liveSync.value = d;
}
async function doLive(action) {
  liveBusy.value = true;
  let d = null;
  if (action === "start") {
    d = await safe(() => api.opsLiveStart(Number(liveInterval.value) || 1800), "启动失败");
    if (d && d.data) showToast(Array.isArray(d.data) ? d.data[1] : "已启动", d.data?.[0] ? "ok" : "err");
  } else {
    d = await safe(() => api.opsLiveStop(), "停止失败");
    if (d && d.data) showToast(Array.isArray(d.data) ? d.data[1] : "已停止", d.data?.[0] ? "ok" : "err");
  }
  await Promise.all([loadLiveStatus(), loadDailySource(), loadPeriodsSource()]);
  liveBusy.value = false;
}
function refreshData() {
  return Promise.all([loadDataSource(), loadDataLinks(), loadOverviewSource(),
                      loadDailySource(), loadPeriodsSource(), loadReconcile(), loadLiveStatus()]);
}
const dailyMetricChips = (rec) => {
  const chips = [["revenue", "成交额"], ["orders", "订单数"], ["buyers", "买家数"],
                 ["customer_unit_price", "客单价"], ["conversion_rate", "转化率"],
                 ["refund_orders", "退款单数"], ["old_buyer_rate", "老买家占比"]];
  return chips.filter(([k]) => rec[k] !== undefined && rec[k] !== null);
};
const periodMetricChips = (rec) => {
  const chips = [["orders", "订单"], ["buyers", "买家"], ["customer_unit_price", "客单价"],
                 ["conversion_rate", "转化率"], ["refund_orders", "退款单"]];
  return chips.filter(([k]) => rec[k] !== undefined && rec[k] !== null);
};
const fmtNum = (v) => (v === undefined || v === null || v === "" ? "—" : Number(v).toLocaleString());
const rcDevText = (m) => m.dev === null ? "不可比" : `${(m.dev * 100).toFixed(1)}%`;
const rcBadge = (s) => ({ ok: "✓ 通过", warn: "⚠ 有偏差", only_daily: "○ 无明细" }[s] || s);
const reconcileFlat = () => {
  const out = [];
  for (const row of reconcileData.value?.rows || []) {
    if (!row.metrics?.length) {
      out.push({ date: row.date, source: row.source || "", status: row.status,
                 first: true, group: 1, note: row.note || "—", metric: "", auth: null, orders: null, dev: null, warn: false });
      continue;
    }
    row.metrics.forEach((m, i) => {
      out.push({ date: row.date, source: row.source || "", status: row.status,
                 first: i === 0, group: row.metrics.length, note: "",
                 metric: m.name, auth: m.authority, orders: m.orders, dev: m.dev, warn: !!m.warn });
    });
  }
  return out;
};
function onFilePicked(e, kind) {
  const f = e.target.files && e.target.files[0];
  if (!f) return;
  importBusy.value = true;
  f.arrayBuffer()
    .then((buf) => (kind === "orders"
      ? api.opsImportOrders(buf, f.name)
      : api.opsImportLinks(buf, f.name)))
    .then((r) => {
      showToast(r.message || "导入成功", r.ok ? "ok" : "err");
      refreshData();
    })
    .catch((err) => showToast("导入失败：" + err.message, "err"))
    .finally(() => { importBusy.value = false; e.target.value = ""; });
}
async function downloadTemplate(kind) {
  try {
    const text = await api.opsDataTemplate(kind);
    const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = kind === "orders" ? "订单报表模板.csv" : "推广报表模板.csv";
    a.click();
    URL.revokeObjectURL(url);
  } catch (err) { showToast("模板获取失败：" + err.message, "err"); }
}
function addSnapRow() {
  const r = { ...snapForm };
  if (!r.product_id.trim()) return showToast("商品ID 必填", "err");
  r.date = r.date || new Date().toISOString().slice(0, 10);
  snapRows.value.push(r);
  Object.keys(snapForm).forEach((k) => (snapForm[k] = ""));
}
function removeSnapRow(i) { snapRows.value.splice(i, 1); }
async function submitSnapshot() {
  if (!snapRows.value.length) return showToast("请先添加至少一条记录", "err");
  const d = await safe(() => api.opsSnapshot(snapRows.value), "快照保存失败");
  if (d) {
    showToast(d.message, d.ok ? "ok" : "err");
    snapRows.value = [];
    refreshData();
  }
}
async function doSync(useCurrent) {
  syncing.value = true;
  const d = await safe(() => api.opsSync(useCurrent, ""), "同步失败");
  if (d) {
    showToast(d.message || (d.ok ? "同步成功" : "同步未完成"), d.ok ? "ok" : "err");
    if (d.ok) refreshData();
  }
  syncing.value = false;
}
async function doClearData() {
  if (!confirm("确定清空全部真实数据？运营中心将回到演示口径。此操作不可撤销！")) return;
  const d = await safe(() => api.opsClearData(), "清空失败");
  if (d) { showToast(d.message, d.ok ? "ok" : "err"); refreshData(); }
}

// ---------- 实时监控 ----------
const monStatus = ref(null);
const monAlerts = ref(null);
const monInterval = ref(60);
const monBusy = ref(false);
const alertLevel = ref("");
let monTimer = null;

async function loadMonitor() {
  const [s, a] = await Promise.all([
    safe(() => api.opsMonitorStatus(), "监控状态加载失败"),
    safe(() => api.opsMonitorAlerts(50, ""), "告警加载失败"),
  ]);
  if (s) monStatus.value = s;
  if (a) monAlerts.value = a;
}
async function doMonitor(action) {
  monBusy.value = true;
  let d = null;
  if (action === "start") {
    d = await safe(() => api.opsMonitorStart(Number(monInterval.value) || 60), "启动失败");
    if (d) showToast(d.message, d.ok ? "ok" : "err");
  } else if (action === "stop") {
    d = await safe(() => api.opsMonitorStop(), "停止失败");
    if (d) showToast(d.message, d.ok ? "ok" : "err");
  } else {
    d = await safe(() => api.opsMonitorRun(), "巡检失败");
    if (d) showToast(`巡检完成：发现 ${d.summary?.alerts ?? 0} 条告警`, "ok");
  }
  await loadMonitor();
  monBusy.value = false;
}
function setAlertLevel(lv) { alertLevel.value = lv; }
const filteredAlerts = computed(() => {
  const list = monAlerts.value?.alerts || [];
  return alertLevel.value ? list.filter((a) => a.level === alertLevel.value) : list;
});
function alertMetrics(a) {
  const m = a.metrics || {};
  const chips = { "ROI": m.roi, "花费": m.cost, "成交": m.revenue, "CPC": m.cpc, "CVR": m.cvr, "净利": m.net_profit };
  return Object.entries(chips).filter(([, v]) => v !== undefined && v !== null);
}

watch(tab, (t) => {
  if (t === "monitor") {
    loadMonitor();
    monTimer = setInterval(loadMonitor, 5000);
  } else if (monTimer) {
    clearInterval(monTimer);
    monTimer = null;
  }
});
onBeforeUnmount(() => { if (monTimer) clearInterval(monTimer); });

// 渲染辅助
function fmtPct(v) { return typeof v === "string" ? v : (v ?? "—"); }
function fmtMoney(v) { return typeof v === "number" ? "¥" + v.toLocaleString() : (v ?? "—"); }

const metricCards = computed(() => {
  const o = overview.value;
  if (!o) return [];
  return [
    { label: "今日成交额", val: fmtMoney(o.今日?.成交额), cls: "" },
    { label: "今日订单", val: String(o.今日?.订单数 ?? "—"), cls: "" },
    { label: "退款率", val: fmtPct(o.退款率), cls: parseFloat(o.退款率) >= 10 ? "danger" : parseFloat(o.退款率) >= 5 ? "warn" : "ok" },
    { label: "健康度", val: `${o.健康度?.总分 ?? "—"}`, sub: o.健康度?.等级, cls: (o.健康度?.总分 ?? 0) >= 85 ? "ok" : (o.健康度?.总分 ?? 0) >= 70 ? "" : "warn" },
    { label: "整体 ROI", val: fmtPct(o.ROI?.整体投产比), cls: (o.ROI?.整体投产比 ?? 0) >= 3 ? "ok" : (o.ROI?.整体投产比 ?? 0) >= 2.2 ? "" : "warn" },
    { label: "客服反哺", val: String(o.客服反哺?.客服退款诉求数 ?? 0), sub: "退款诉求事件", cls: "" },
  ];
});

const reportMetrics = computed(() => {
  const m = report.value?.指标 || {};
  return [
    ["成交额", fmtMoney(m.成交额)], ["订单数", m.订单数], ["客单价", fmtMoney(m.客单价)],
    ["退款率", m.退款率], ["新客占比", m.新客占比], ["退款金额", fmtMoney(m.退款金额)],
  ];
});
function compareOf(key) {
  const c = report.value?.环比 || {};
  const v = c[key];
  if (v == null || v === "—") return null;
  const up = !v.startsWith("-");
  return { up, text: (up ? "↑ " : "↓ ") + v.replace("-", "") };
}

const refundBuckets = computed(() => {
  const b = refunds.value?.问题归类;
  if (!b) return [];
  const total = Object.values(b).reduce((s, x) => s + x, 0) || 1;
  return Object.entries(b).map(([k, v]) => ({ k, v, pct: Math.round((v / total) * 100) }));
});

const healthDims = computed(() => (health.value?.维度 || []).map((d) => ({
  ...d,
  ratio: d.满分 ? Math.min(1, d.得分 / d.满分) : 0,
})));

const roiPlans = computed(() => (roi.value?.计划 || []).map((p) => ({
  ...p,
  roiCls: p.roi >= 3 ? "ok" : p.roi >= 2.2 ? "" : "warn",
})));

const cmdTypes = computed(() => {
  const t = {};
  for (const c of commands.value) t[c.type] = (t[c.type] || 0) + 1;
  return t;
});

function parseArgsPreview(argsText) {
  try { return JSON.stringify(JSON.parse(argsText || "{}"), null, 2); }
  catch { return "（JSON 格式错误）"; }
}

onMounted(async () => {
  await Promise.all([loadOverview(), loadReport("day"), loadRefunds(),
                     loadHealth(), loadRoi(), loadImages(), loadCommands(), loadForge(),
                     refreshData()]);
});
</script>

<template>
  <div class="ops-page">
    <!-- 顶部子页签 -->
    <nav class="ops-tabs">
      <button v-for="t in [
        ['overview', '总览'], ['report', '经营报表'], ['refunds', '退款归因'],
        ['health', '店铺体检'], ['roi', 'ROI 监控'], ['images', '参考图库'],
        ['data', '数据接入'], ['monitor', '实时监控'],
        ['forge', '命令工厂'], ['opt', '优化方案']]"
        :key="t[0]" class="ops-tab" :class="{ on: tab === t[0] }" @click="tab = t[0]">
        {{ t[1] }}
      </button>
    </nav>

    <div class="ops-body" :class="{ loading }">

      <!-- ═══ 总览 ═══ -->
      <section v-if="tab === 'overview'" class="ops-section">
        <div class="ops-grid-kpi">
          <div v-for="(c, i) in metricCards" :key="i" class="ops-kpi">
            <span class="ops-kpi-num" :class="c.cls">{{ c.val }}</span>
            <span class="ops-kpi-label">{{ c.label }}</span>
            <span v-if="c.sub" class="ops-kpi-sub">{{ c.sub }}</span>
          </div>
        </div>

        <div class="ops-cards">
          <div class="ops-card">
            <h3>今日环比</h3>
            <div v-if="overview?.环比" class="ops-compare">
              <div v-for="(v, k) in overview.环比" :key="k" class="cmp-item">
                <span class="cmp-key">{{ k }}</span>
                <span class="cmp-val" :class="String(v).startsWith('-') ? 'down' : 'up'">{{ v }}</span>
              </div>
            </div>
            <div v-else class="ops-empty">暂无环比数据</div>
          </div>
          <div class="ops-card">
            <h3>客服反哺运营</h3>
            <p class="ops-desc">
              客服自动化会话中识别到的「退款诉求」事件会自动进入退款归因与健康体检，
              实现客服 → 运营的数据闭环。
            </p>
            <div class="ops-feedback">
              <span class="fb-num">{{ overview?.客服反哺?.客服退款诉求数 ?? 0 }}</span>
              <span class="fb-label">条退款诉求事件已接入</span>
            </div>
          </div>
          <div class="ops-card">
            <h3>数据来源说明</h3>
            <ul class="ops-src-list">
              <li>· 经营数据：<b :class="overview?.数据口径 === 'real' ? 'up' : ''">
                {{ overview?.数据口径 === "real" ? "真实数据（报表导入 / CDP 同步 / 手动快照）" : "演示数据（本地造数，解压即演示）" }}</b></li>
              <li>· 客服数据：自动化引擎实时事件流（真实转人工退款诉求）</li>
              <li>· 接入方式：「数据接入」页签支持拼多多商家后台 CSV 导入、CDP 自动同步、手动快照</li>
            </ul>
          </div>
        </div>
      </section>

      <!-- ═══ 报表 ═══ -->
      <section v-if="tab === 'report'" class="ops-section">
        <div class="ops-card">
          <div class="ops-card-head">
            <h3>经营数据报表</h3>
            <div class="period-tabs">
              <button v-for="p in periods" :key="p" class="period-tab"
                      :class="{ on: period === p }" @click="loadReport(p)">
                {{ { day: "日报", week: "周报", month: "月报", year: "年报" }[p] }}
              </button>
              <button class="btn-primary refresh-btn" :disabled="reportRefreshBusy"
                      title="立即跑一轮 CDP 采集（权威日统计+订单+多周期 4 维度），并基于最新数据重算本报表"
                      @click="doRefreshReport">
                {{ reportRefreshBusy ? "更新中…" : "一键更新数据" }}
              </button>
            </div>
          </div>
          <div v-if="report" class="report-title">{{ report.label }}</div>
          <div v-if="reportLoading" class="ops-empty">加载中…</div>
          <template v-else-if="report">
            <div class="ops-grid-metric">
              <div v-for="(m, i) in reportMetrics" :key="i" class="ops-metric">
                <span class="m-label">{{ m[0] }}</span>
                <span class="m-val">{{ m[1] }}</span>
              </div>
            </div>
            <div v-if="report?.指标?.数据来源" class="report-src">
              <span class="rs-dot"></span>数据来源：{{ report.指标.数据来源 }}
            </div>
            <div class="cmp-row">
              <span v-for="(v, k) in report.环比" :key="k" class="cmp-chip"
                    :class="String(v).startsWith('-') ? 'down' : 'up'">
                {{ k }} {{ v }}
              </span>
            </div>
            <div v-if="report.趋势 && report.趋势.length" class="trend-block">
              <h4>成交趋势</h4>
              <div class="bars">
                <div v-for="t in report.趋势" :key="t.date" class="bar-row">
                  <span class="bar-name">{{ t.date.slice(5) }}</span>
                  <div class="bar-track"><div class="bar-fill" :style="{ width: Math.max(4, (t.amount / trendMax) * 100) + '%' }"></div></div>
                  <span class="bar-val">¥{{ t.amount }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>
      </section>

      <!-- ═══ 退款归因 ═══ -->
      <section v-if="tab === 'refunds'" class="ops-section">
        <div class="ops-cards">
          <div class="ops-card">
            <h3>退款概况</h3>
            <div v-if="refunds" class="ops-grid-metric">
              <div class="ops-metric"><span class="m-label">退款率</span><span class="m-val" :class="parseFloat(refunds.退款率) >= 10 ? 'danger' : ''">{{ refunds.退款率 }}</span></div>
              <div class="ops-metric"><span class="m-label">退款单数</span><span class="m-val">{{ refunds.退款单数 }}</span></div>
              <div class="ops-metric"><span class="m-label">退款金额</span><span class="m-val">{{ fmtMoney(refunds.退款金额) }}</span></div>
              <div class="ops-metric"><span class="m-label">平均退款时长</span><span class="m-val">{{ refunds.平均退款时长 }}</span></div>
            </div>
            <p v-if="refunds?.总结" class="ops-empty">{{ refunds.总结 }}</p>
          </div>
          <div class="ops-card">
            <h3>原因分布</h3>
            <div class="bars">
              <div v-for="r in (refunds?.退款原因分布 || [])" :key="r.原因" class="bar-row">
                <span class="bar-name">{{ r.原因 }}</span>
                <div class="bar-track"><div class="bar-fill" :style="{ width: Math.max(3, parseFloat(r.占比) * 3) + '%' }"></div></div>
                <span class="bar-val">{{ r.数量 }} · {{ r.占比 }}</span>
              </div>
              <div v-if="!(refunds?.退款原因分布 || []).length" class="ops-empty">暂无数据</div>
            </div>
          </div>
          <div class="ops-card">
            <h3>问题归类</h3>
            <div class="bucket-list">
              <div v-for="b in refundBuckets" :key="b.k" class="bucket-row">
                <span class="bucket-name">{{ b.k }}</span>
                <div class="bucket-track"><div class="bucket-fill" :style="{ width: b.pct + '%' }"></div></div>
                <span class="bucket-val">{{ b.v }} 单</span>
              </div>
            </div>
            <div v-if="(refunds?.高退款风险商品 || []).length" class="risk-box">
              <h4>高退款风险商品</h4>
              <div v-for="p in refunds.高退款风险商品" :key="p.product_id" class="risk-item">
                <code>{{ p.product_id }}</code>
                <span>退款率 {{ p.refund_rate }}</span>
                <span class="risk-orders">{{ p.orders }} 单</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ 体检 ═══ -->
      <section v-if="tab === 'health'" class="ops-section">
        <div class="ops-card">
          <div class="health-score">
            <div class="score-ring" :class="(health?.总分 ?? 0) >= 85 ? 'ok' : (health?.总分 ?? 0) >= 70 ? 'good' : 'warn'">
              <span class="score-num">{{ health?.总分 ?? "—" }}</span>
              <span class="score-grade">{{ health?.等级 || "" }}</span>
            </div>
            <div class="health-dims">
              <div v-for="d in healthDims" :key="d.维度" class="dim-row">
                <div class="dim-head">
                  <span class="dim-name">{{ d.维度 }}</span>
                  <span class="dim-val">{{ d.得分 }}/{{ d.满分 }}</span>
                </div>
                <div class="bar-track"><div class="bar-fill" :style="{ width: d.ratio * 100 + '%' }"></div></div>
                <div class="dim-meta">实测 {{ d.实测 }} · 基准 {{ d.行业基准 }}</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ ROI ═══ -->
      <section v-if="tab === 'roi'" class="ops-section">
        <div class="ops-cards">
          <div class="ops-card">
            <h3>投放大盘</h3>
            <div v-if="roi?.汇总" class="ops-grid-metric">
              <div class="ops-metric"><span class="m-label">整体投产比</span><span class="m-val" :class="roi.汇总.整体投产比 >= 3 ? 'ok' : 'warn'">{{ roi.汇总.整体投产比 }}</span></div>
              <div class="ops-metric"><span class="m-label">总花费</span><span class="m-val">{{ fmtMoney(roi.汇总.总花费) }}</span></div>
              <div class="ops-metric"><span class="m-label">总成交</span><span class="m-val">{{ fmtMoney(roi.汇总.总成交) }}</span></div>
              <div class="ops-metric"><span class="m-label">总净利</span><span class="m-val">{{ fmtMoney(roi.汇总.总净利) }}</span></div>
              <div class="ops-metric"><span class="m-label">健康/预警计划</span><span class="m-val">{{ roi.汇总.健康计划数 }} / {{ roi.汇总.预警计划数 }}</span></div>
            </div>
          </div>
          <div class="ops-card">
            <h3>预算再分配</h3>
            <p class="ops-desc">按 ROI 加权把预算从低效计划转移到高效计划，整体提升投产比。</p>
            <div class="realloc-row">
              <input v-model.number="budgetInput" type="number" class="text-input" placeholder="每日预算" />
              <button class="btn-primary" @click="doReallocate">生成建议</button>
            </div>
            <div v-if="realloc" class="realloc-list">
              <div v-for="a in realloc.allocation" :key="a.plan_id" class="realloc-item">
                <span class="ra-name">{{ a.name }}</span>
                <span class="ra-roi">ROI {{ a.roi }}</span>
                <span class="ra-delta" :class="a.delta > 0 ? 'up' : a.delta < 0 ? 'down' : ''">
                  {{ a.delta > 0 ? "↑" : a.delta < 0 ? "↓" : "=" }} ¥{{ Math.abs(a.delta) }} {{ a.action }}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div class="ops-card">
          <h3>逐条计划诊断</h3>
          <div class="plan-table">
            <div class="plan-row plan-head">
              <span>计划</span><span>ROI</span><span>净利</span><span>CTR</span><span>CVR</span><span>调节指令</span>
            </div>
            <div v-for="p in roiPlans" :key="p.plan_id" class="plan-row">
              <span class="pl-name">{{ p.name }}</span>
              <span class="pl-roi" :class="p.roiCls">{{ p.roi }}</span>
              <span class="pl-num" :class="p.net_profit < 0 ? 'danger' : ''">¥{{ p.net_profit }}</span>
              <span class="pl-num">{{ p.ctr }}</span>
              <span class="pl-num">{{ p.cvr }}</span>
              <span class="pl-actions">{{ (roi?.逐条诊断 || []).find(d => d.plan_id === p.plan_id)?.actions?.join(" / ") || "—" }}</span>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ 图库 ═══ -->
      <section v-if="tab === 'images'" class="ops-section">
        <div class="ops-card">
          <div class="ops-card-head">
            <h3>参考图库</h3>
            <span class="ops-tag">共 {{ images?.统计?.总图片数 ?? 0 }} 张</span>
          </div>
          <div class="crawl-row">
            <select v-model="crawl.platform" class="text-input sel">
              <option v-for="p in platforms" :key="p[0]" :value="p[0]">{{ p[1] }}</option>
            </select>
            <input v-model="crawl.category" class="text-input" placeholder="品类，如 摩托车配件" />
            <input v-model="crawl.keyword" class="text-input" placeholder="关键词，如 定风翼" />
            <input v-model.number="crawl.limit" type="number" class="text-input num" placeholder="数量" />
            <button class="btn-primary" :disabled="crawling" @click="doCrawl">
              {{ crawling ? "采集中…" : "采集主图" }}
            </button>
          </div>
          <p class="ops-hint">采集时复用调试浏览器(9222)已登录会话截图真实主图；浏览器未就绪时自动拉起，仍失败才生成演示占位图。</p>
          <div v-if="images?.提示?.length" class="crawl-warns">
            <span v-for="(w, wi) in images.提示" :key="wi" class="crawl-warn">⚠ {{ w }}</span>
          </div>
          <div v-if="images?.图片?.length" class="img-grid">
            <div v-for="img in images.图片" :key="img.file" class="img-card">
              <img :src="api.opsImageUrl(img.file)" :alt="img.title" loading="lazy" />
              <div class="img-meta">
                <span class="img-title">{{ img.title }}</span>
                <span class="img-sub">{{ img.platform }} · {{ img.category }} · {{ img.price }}</span>
              </div>
            </div>
          </div>
          <div v-else class="ops-empty">图库为空，用上方表单采集一批参考图吧</div>
        </div>
      </section>

      <!-- ═══ 命令工厂 ═══ -->
      <section v-if="tab === 'forge'" class="ops-section">
        <div class="ops-cards forge-cols">
          <div class="ops-card">
            <h3>AI 命令工厂</h3>
            <p class="ops-desc">店家不写代码，只提需求。Agent 自动生成代码 → 安全审查 → 沙箱试运行 → 上线。</p>
            <textarea v-model="cmdForm.requirement" class="text-input area" rows="3"
                      placeholder="例：我要一个命令，输入商品原价、折扣率、成本率、运费，算出打折后的利润和利润率，利润率低于10%返回警告"></textarea>
            <input v-model="cmdForm.sampleArgs" class="text-input" placeholder='试运行参数（JSON，可选）：{"price":100,"discount":0.8}' />
            <button class="btn-primary" :disabled="cmdBusy" @click="doCreate">
              {{ cmdBusy ? "生成中…" : "生成并上线命令" }}
            </button>
          </div>

          <div class="ops-card">
            <h3>已注册命令 <span class="ops-tag">{{ commands.length }} 个</span></h3>
            <div class="cmd-list">
              <button v-for="c in commands" :key="c.name" class="cmd-item"
                      :class="{ on: cmdDetail?.name === c.name }"
                      @click="loadCmdDetail(c.name)">
                <span class="cmd-name">{{ c.name }}</span>
                <span class="cmd-type" :class="'tp-' + c.layer">{{ c.type }}</span>
              </button>
            </div>
          </div>
        </div>

        <div v-if="cmdDetail" class="ops-card">
          <div class="ops-card-head">
            <h3>命令详情 · {{ cmdDetail.name }} <span class="ops-tag">v{{ cmdDetail.current_version || "?" }}</span></h3>
            <div class="cmd-ops">
              <button class="btn-ghost" @click="doEvolve">🧬 进化</button>
              <button class="btn-ghost" @click="doRollback">↩ 回滚</button>
              <button class="btn-danger" @click="doDelete">删除</button>
            </div>
          </div>
          <p class="ops-desc">{{ cmdDetail.description }}</p>
          <div class="cmd-params">
            <code v-for="(pspec, pname) in (cmdDetail.parameters?.properties || {})" :key="pname">
              {{ pname }}{{ (cmdDetail.parameters?.required || []).includes(pname) ? "*" : "" }}: {{ pspec.type }}
            </code>
          </div>
          <div class="exec-row">
            <input v-model="cmdForm.execArgs" class="text-input mono" placeholder='执行参数 JSON，如 {"plan_id":"PLAN1"}' />
            <button class="btn-primary" @click="doExecute">执行</button>
          </div>
          <div v-if="cmdExec" class="trace-result">
            <template v-if="cmdExec.ok">
              <b>✓ 执行成功（{{ cmdExec.elapsed }}）</b>
              <pre class="json-pre">{{ JSON.stringify(cmdExec.result, null, 2) }}</pre>
            </template>
            <template v-else><b class="danger">✕ {{ cmdExec.error }}</b></template>
          </div>
          <details v-if="cmdDetail.code" class="code-box">
            <summary>查看生成代码（已通过 AST 安全审查 + 沙箱试运行）</summary>
            <pre class="json-pre">{{ cmdDetail.code }}</pre>
          </details>
        </div>

        <div class="ops-card">
          <h3>命令工厂运行日志</h3>
          <div class="forge-log">
            <div v-for="(lg, i) in (forgeLog?.audit_log || []).slice().reverse()" :key="i" class="log-item">
              <span class="log-at">{{ lg.at.slice(11, 19) }}</span>
              <code>{{ lg.action }}</code>
              <span class="log-data">{{ JSON.stringify(lg.data).slice(0, 120) }}</span>
            </div>
            <div v-if="!(forgeLog?.audit_log || []).length" class="ops-empty">暂无生成记录，去提一个需求试试</div>
          </div>
        </div>
      </section>

      <!-- ═══ 数据接入 ═══ -->
      <section v-if="tab === 'data'" class="ops-section">
        <div class="ops-cards">
          <div class="ops-card">
            <div class="ops-card-head">
              <h3>数据源状态</h3>
              <span class="ops-tag" :class="dataSource?.mode === 'real' ? 'tag-real' : 'tag-demo'">
                {{ dataSource?.mode === "real" ? "● 真实数据" : "○ 演示数据" }}
              </span>
            </div>
            <div v-if="dataSource" class="ops-grid-metric">
              <div class="ops-metric"><span class="m-label">订单数</span><span class="m-val">{{ dataSource.订单数 }}</span></div>
              <div class="ops-metric"><span class="m-label">商品链接数</span><span class="m-val">{{ dataSource.商品链接数 }}</span></div>
              <div class="ops-metric"><span class="m-label">链接日记录</span><span class="m-val">{{ dataSource.链接日记录数 }}</span></div>
            </div>
            <p class="ops-desc">{{ dataSource?.说明 }}</p>
            <div class="probe-box" :class="{ ok: dataSource?.probe?.cdp_ok && dataSource?.probe?.mms_open }">
              <span class="probe-dot"></span>
              <span>{{ dataSource?.probe?.message || "探测中…" }}</span>
            </div>
            <div v-if="dataSource?.最近导入" class="ops-hint">
              最近导入：{{ dataSource.最近导入.kind }} · {{ dataSource.最近导入.rows }} 条 · {{ dataSource.最近导入.ts }}
            </div>
            <div v-if="dataSource?.导入记录?.length" class="ops-hint">最近 {{ dataSource.导入记录.length }} 次导入记录：{{ dataSource.导入记录.map(x => x.kind + "×" + x.rows).join("，") }}</div>
          </div>

          <div class="ops-card" v-if="overviewSource">
            <div class="ops-card-head">
              <h3>交易概况（CDP 同步）</h3>
              <span class="ops-tag tag-real">{{ overviewSource.updated ? "需逐日更新" : "暂无数据" }}</span>
            </div>
            <p class="ops-desc">来自商家后台「交易数据」页（省份成交分布 + 月份完成度），随 CDP 同步自动入库。</p>
            <template v-if="overviewSource.provinces?.length">
              <h4>省份成交分布</h4>
              <table class="mini-tbl">
                <thead><tr><th>省份</th><th>成交金额</th><th>订单数</th><th>买家数</th><th>客单价</th></tr></thead>
                <tbody>
                  <tr v-for="p in overviewSource.provinces" :key="p.region">
                    <td>{{ p.region }}</td><td>{{ p.amount }}</td><td>{{ p.orders }}</td>
                    <td>{{ p.buyers }}</td><td>{{ p.customer_unit_price }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <template v-if="overviewSource.months?.length">
              <h4>月份成交与完成度</h4>
              <table class="mini-tbl">
                <thead>
                  <tr>
                    <th>月份</th>
                    <th v-for="(v, k) in overviewSource.months[0].metrics" :key="k">{{ k }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="m in overviewSource.months" :key="m.month">
                    <td>{{ m.month }}</td>
                    <td v-for="(v, k) in m.metrics" :key="k">{{ v }}</td>
                  </tr>
                </tbody>
              </table>
            </template>
            <div v-if="!overviewSource.provinces?.length && !overviewSource.months?.length" class="ops-hint">
              暂无交易概况。打开商家后台「交易数据」页后点击「同步当前商家后台页」即可写入。
            </div>
          </div>

          <div class="ops-card">
            <h3>报表文件导入</h3>
            <p class="ops-desc">从拼多多商家后台导出「订单报表 / 推广报表」CSV 直接导入，按订单号 / 商品+日期自动去重合并，列名智能匹配。</p>
            <div class="import-row">
              <label class="btn-ghost file-btn">
                导入订单报表
                <input type="file" accept=".csv,.txt" hidden @change="onFilePicked($event, 'orders')" />
              </label>
              <button class="btn-ghost" @click="downloadTemplate('orders')">下载模板</button>
            </div>
            <div class="import-row">
              <label class="btn-ghost file-btn">
                导入推广报表
                <input type="file" accept=".csv,.txt" hidden @change="onFilePicked($event, 'links')" />
              </label>
              <button class="btn-ghost" @click="downloadTemplate('links')">下载模板</button>
            </div>
            <div v-if="importBusy" class="ops-hint">正在解析导入…</div>
          </div>

          <div class="ops-card">
            <h3>CDP 自动同步</h3>
            <p class="ops-desc">复用调试浏览器中已登录的商家后台会话，自动抓取当前页表格（商品 / 花费 / 成交等列自动识别）并入库，无需手动导出。</p>
            <div class="import-row">
              <button class="btn-primary" :disabled="syncing" @click="doSync(true)">
                {{ syncing ? "同步中…" : "同步当前商家后台页" }}
              </button>
            </div>
            <p class="ops-hint">未打开商家后台时，会尝试自动打开候选数据页（backend/ops/settings.py 的 OP_PAGES 可配置）。</p>
          </div>

          <div class="ops-card">
            <div class="ops-card-head">
              <h3>实时同步（跟随平台）</h3>
              <span class="ops-tag" :class="liveSync?.running ? 'tag-real' : 'tag-demo'">
                {{ liveSync?.running ? "● 运行中" : "○ 已停止" }}
              </span>
            </div>
            <p class="ops-desc">常驻后台按间隔自动刷新交易数据页「交易概况」权威日统计 + 订单明细，今日指标实时跟随平台，禁止演示数据冒充真实成交。</p>
            <div class="import-row">
              <input v-model.number="liveInterval" type="number" class="text-input num" placeholder="间隔(秒)" />
              <button class="btn-primary" :disabled="liveBusy || liveSync?.running" @click="doLive('start')">
                {{ liveBusy ? "处理中…" : "启动实时同步" }}
              </button>
              <button class="btn-ghost" :disabled="liveBusy || !liveSync?.running" @click="doLive('stop')">停止</button>
            </div>
            <div class="live-meta">
              <span class="lm-label">运行间隔</span>
              <span class="lm-val">{{ liveSync?.interval }} 秒</span>
            </div>
            <div v-if="liveSync?.last_sync" class="live-meta">
              <span class="lm-label">最近同步</span>
              <span class="lm-val">{{ liveSync.last_sync }}</span>
            </div>
            <div v-if="liveSync?.last" class="live-meta" :class="{ ok: liveSync.last.ok }">
              <span class="lm-label">最近采样</span>
              <span class="lm-val">
                {{ liveSync.last.ok
                  ? `权威日统计 ${liveSync.last.daily_days ?? 0} 天 · 订单 ${liveSync.last.orders ?? 0} 单`
                  : (liveSync.last.reason || "本轮跳过") }}
              </span>
            </div>
            <p v-if="!liveSync" class="ops-hint">正在获取实时同步状态…</p>
          </div>

          <div class="ops-card">
            <div class="ops-card-head">
              <h3>交易概况 · 权威日统计</h3>
              <span class="ops-tag">{{ dailySource.length }} 天</span>
            </div>
            <p class="ops-desc">取自商家后台「交易数据」页顶部交易概况卡，为商店级权威口径，日报 / 总览会优先采用并标注来源。</p>
            <div v-if="dailySource.length" class="daily-table">
              <div class="daily-row daily-head">
                <span>日期</span><span v-for="n in 4" :key="n">指标</span>
              </div>
              <div v-for="rec in dailySource" :key="rec.date" class="daily-row">
                <span class="daily-date">{{ rec.date }}<em>{{ rec.source || "" }}</em></span>
                <template v-for="(chip, i) in dailyMetricChips(rec)" :key="i">
                  <span class="daily-chip"><b>{{ chip[1] }}</b>{{ rec[chip[0]] }}</span>
                </template>
                <span v-for="n in Math.max(0, 4 - dailyMetricChips(rec).length)" :key="'e' + n" class="daily-chip faint">—</span>
              </div>
            </div>
            <div v-else class="ops-hint">暂无权威日统计。打开商家后台「交易数据」页并启动实时同步后自动写入。</div>
          </div>

          <div class="ops-card">
            <div class="ops-card-head">
              <h3>多周期交易数据 · 自动点击采集</h3>
              <span class="ops-tag">{{ periodsSource.length }} 个周期</span>
            </div>
            <p class="ops-desc">Python 自动点击交易数据页「实时 / 昨日 / 7日 / 30日」时间按钮，逐维度抓取交易概况并独立入库，从根本上避免「30日 / 实时聚合值被当成单日口径」的数据对不上问题。定时每 <b>30 分钟</b>自动采集一轮，也可手动立即触发。</p>
            <div class="import-row">
              <button class="btn-primary" :disabled="periodsBusy" @click="triggerPeriodsCollect">
                {{ periodsBusy ? "采集中…" : "立即采集一轮（定时 30 分钟）" }}
              </button>
            </div>
            <div v-if="periodsSource.length" class="periods-table">
              <div class="periods-row periods-head">
                <span>周期</span>
                <span>成交额</span><span v-for="n in 3" :key="n">指标</span>
                <span>更新时间</span>
              </div>
              <div v-for="rec in periodsSource" :key="rec.period" class="periods-row">
                <span class="periods-label">{{ rec.period }}</span>
                <span class="periods-val">{{ fmtNum(rec.revenue) }}</span>
                <template v-for="(m, i) in periodMetricChips(rec)" :key="'m' + i">
                  <span class="periods-val"><b>{{ m[1] }}</b>{{ rec[m[0]] }}</span>
                </template>
                <span v-for="n in Math.max(0, 3 - periodMetricChips(rec).length)" :key="'e' + n" class="periods-val faint">—</span>
                <span class="periods-update">{{ (rec.updated || "").slice(5, 16) }}</span>
              </div>
            </div>
            <div v-else class="ops-hint">暂无多周期数据。确认商家后台「交易数据」页已登录后，点击上方「立即采集一轮」或等待 30 分钟定时执行。</div>
          </div>

          <div class="ops-card">
            <div class="ops-card-head">
              <h3>严格对账（权威日统计 vs 订单明细）</h3>
              <span class="ops-tag" :class="reconcileData?.summary?.warn ? 'tag-demo' : 'tag-real'">
                {{ reconcileData?.conclusion || "加载中…" }}
              </span>
            </div>
            <p class="ops-desc">以「交易数据-实时」权威日统计为基准，与本地订单明细逐日比对成交额 / 订单数 / 买家数 / 退款，任一字段偏差超阈值（{{ reconcileData?.threshold != null ? (reconcileData.threshold * 100) : 5 }}%）即告警，用于自检明细是否完整、同步是否有误。</p>
            <p v-if="reconcileData?.summary" class="ops-desc">
              可对账 {{ reconcileData.summary.dates }} 天 ·
              <span :class="{ 'rc-warn': reconcileData.summary.warn }">偏差 {{ reconcileData.summary.warn }} 天</span>
              · 通过 {{ reconcileData.summary.ok }} 天 ·
              无明细 {{ reconcileData.summary.only_daily }} 天
              <template v-if="reconcileData.summary.orders_wo_authority">· 订单无对应权威日 {{ reconcileData.summary.orders_wo_authority }} 天</template>
            </p>
            <div v-if="reconcileFlat().length" class="rc-table">
              <table>
                <thead><tr><th>日期</th><th>状态</th><th>指标</th><th>权威日统计</th><th>订单明细</th><th>偏差</th></tr></thead>
                <tbody>
                  <template v-for="(row, i) in reconcileFlat()" :key="i">
                    <tr :class="{ 'rc-warn-row': row.warn }">
                      <td v-if="row.first" :rowspan="row.group" class="daily-date">{{ row.date }}<em>{{ row.source }}</em></td>
                      <td v-if="row.first" :rowspan="row.group"><span class="rc-badge" :class="{ warn: row.status === 'warn' }">{{ rcBadge(row.status) }}</span></td>
                      <template v-if="row.note">
                        <td colspan="4" class="rc-empty">{{ row.note }}</td>
                      </template>
                      <template v-else>
                        <td class="rc-metric">{{ row.metric }}</td>
                        <td class="rc-num">{{ row.auth }}</td>
                        <td class="rc-num">{{ row.orders }}</td>
                        <td class="rc-num" :class="{ 'rc-warn': row.warn }">{{ rcDevText(row) }}</td>
                      </template>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
            <div v-else class="ops-hint">{{ reconcileData ? "暂无权威日统计，无可对账数据。" : "正在获取对账结果…" }}</div>
          </div>
        </div>

        <div class="ops-cards">
          <div class="ops-card">
            <div class="ops-card-head">
              <h3>手动快照录入</h3>
              <button class="btn-danger" @click="doClearData">清空真实数据</button>
            </div>
            <p class="ops-desc">没有报表时，每日手动录入各商品链接的推广花费与成交，实时监控引擎同样可用。</p>
            <div class="snap-grid">
              <input v-model="snapForm.product_id" class="text-input" placeholder="商品ID *" />
              <input v-model="snapForm.name" class="text-input" placeholder="商品名称" />
              <input v-model="snapForm.date" class="text-input" placeholder="日期(默认今天)" />
              <input v-model="snapForm.cost" class="text-input num" placeholder="花费" />
              <input v-model="snapForm.revenue" class="text-input num" placeholder="成交额" />
              <input v-model="snapForm.orders" class="text-input num" placeholder="订单数" />
              <input v-model="snapForm.clicks" class="text-input num" placeholder="点击" />
              <input v-model="snapForm.impressions" class="text-input num" placeholder="展现" />
              <button class="btn-ghost" @click="addSnapRow">+ 加入列表</button>
            </div>
            <div v-if="snapRows.length" class="snap-list">
              <div v-for="(r, i) in snapRows" :key="i" class="snap-item">
                <code>{{ r.product_id }}</code>
                <span>{{ r.date }}</span>
                <span v-if="r.cost">花费 {{ r.cost }}</span>
                <span v-if="r.revenue">成交 {{ r.revenue }}</span>
                <button class="snap-del" @click="removeSnapRow(i)">✕</button>
              </div>
              <button class="btn-primary" @click="submitSnapshot">提交 {{ snapRows.length }} 条快照</button>
            </div>
          </div>
        </div>

        <div class="ops-card">
          <div class="ops-card-head">
            <h3>商品链接日指标表</h3>
            <span class="ops-tag">{{ dataLinks?.rows?.length ?? 0 }} 个链接 · 近 7 天汇总</span>
          </div>
          <div v-if="dataLinks?.rows?.length" class="link-table">
            <div class="link-row link-head">
              <span>商品链接</span><span>近7天花费</span><span>近7天成交</span><span>订单</span><span>ROI</span><span>记录天数</span><span>最新日期</span>
            </div>
            <div v-for="r in dataLinks.rows" :key="r.product_id" class="link-row">
              <span class="lk-name"><code>{{ r.product_id }}</code><span>{{ r.name }}</span></span>
              <span class="lk-num">¥{{ r.cost_7d.toLocaleString() }}</span>
              <span class="lk-num">¥{{ r.revenue_7d.toLocaleString() }}</span>
              <span class="lk-num">{{ r.orders_7d }}</span>
              <span class="lk-roi" :class="r.roi_7d >= 3 ? 'ok' : r.roi_7d >= 2.2 ? '' : 'warn'">{{ r.roi_7d }}</span>
              <span class="lk-num">{{ r.day_count }}</span>
              <span class="lk-num faint">{{ r.last_date }}</span>
            </div>
          </div>
          <div v-else class="ops-empty">暂无真实数据：通过报表导入 / CDP 同步 / 手动快照接入后，这里会展示每个商品链接的投放表现</div>
        </div>
      </section>

      <!-- ═══ 实时监控 ═══ -->
      <section v-if="tab === 'monitor'" class="ops-section">
        <div class="ops-cards">
          <div class="ops-card">
            <div class="ops-card-head">
              <h3>监控引擎</h3>
              <span class="ops-tag" :class="monStatus?.running ? 'tag-real' : 'tag-demo'">
                {{ monStatus?.running ? "● 运行中" : "○ 已停止" }}
              </span>
            </div>
            <p class="ops-desc">后台线程按间隔巡检商品链接日指标：识别「推广成本上升 + 成交额下降」「ROI 低于保本线」等异常，给出规则建议；配置 API Key 后由 LLM 生成经营解读。</p>
            <div class="import-row">
              <input v-model.number="monInterval" type="number" class="text-input num" placeholder="巡检秒数" />
              <button class="btn-primary" :disabled="monBusy || monStatus?.running" @click="doMonitor('start')">启动监控</button>
              <button class="btn-ghost" :disabled="monBusy || !monStatus?.running" @click="doMonitor('stop')">停止</button>
              <button class="btn-ghost" :disabled="monBusy" @click="doMonitor('run')">立即巡检</button>
            </div>
            <div v-if="monStatus?.last_run" class="ops-hint">最近巡检：{{ monStatus.last_run }} · 累计告警 {{ monStatus.alert_count }} 条</div>
          </div>

          <div class="ops-card">
            <h3>最近巡检快照</h3>
            <div v-if="monStatus?.last_summary" class="ops-grid-metric">
              <div class="ops-metric"><span class="m-label">监控链接</span><span class="m-val">{{ monStatus.last_summary.links }}</span></div>
              <div class="ops-metric"><span class="m-label">总花费</span><span class="m-val">¥{{ monStatus.last_summary.total_cost.toLocaleString() }}</span></div>
              <div class="ops-metric"><span class="m-label">总成交</span><span class="m-val">¥{{ monStatus.last_summary.total_revenue.toLocaleString() }}</span></div>
              <div class="ops-metric"><span class="m-label">整体 ROI</span><span class="m-val" :class="monStatus.last_summary.roi >= 3 ? 'ok' : monStatus.last_summary.roi >= 2.2 ? '' : 'warn'">{{ monStatus.last_summary.roi }}</span></div>
              <div class="ops-metric"><span class="m-label">本轮告警</span><span class="m-val" :class="monStatus.last_summary.alerts ? 'danger' : 'ok'">{{ monStatus.last_summary.alerts }}</span></div>
            </div>
            <div v-else class="ops-empty">尚未巡检：启动监控或点「立即巡检」生成第一轮结果</div>
          </div>
        </div>

        <div class="ops-card">
          <div class="ops-card-head">
            <h3>实时告警 <span class="ops-tag">{{ filteredAlerts.length }} 条</span></h3>
            <div class="alert-filter">
              <button v-for="lv in [['', '全部'], ['danger', '严重'], ['warn', '预警']]" :key="lv[0]"
                      class="period-tab" :class="{ on: alertLevel === lv[0] }"
                      @click="setAlertLevel(lv[0])">{{ lv[1] }}</button>
            </div>
          </div>
          <div v-if="filteredAlerts.length" class="alert-list">
            <div v-for="(a, i) in filteredAlerts" :key="i" class="alert-item" :class="'lv-' + a.level">
              <div class="alert-head">
                <span class="alert-level" :class="'lv-' + a.level">{{ a.level === "danger" ? "严重" : "预警" }}</span>
                <span class="alert-name">{{ a.name }}<code>{{ a.product_id }}</code></span>
                <span class="alert-ts">{{ a.ts.slice(5, 16) }}</span>
              </div>
              <p class="alert-msg">{{ a.message }}</p>
              <div class="alert-metrics">
                <span v-for="(chip, k) in alertMetrics(a)" :key="k" class="alert-chip">{{ chip[0] }} {{ chip[1] }}</span>
              </div>
              <details class="alert-sug" open>
                <summary>规则建议</summary>
                <p>{{ a.suggestion }}</p>
              </details>
              <details v-if="a.llm_advice" class="alert-sug llm">
                <summary>AI 经营解读</summary>
                <p>{{ a.llm_advice }}</p>
              </details>
            </div>
          </div>
          <div v-else class="ops-empty">暂无告警。接入商品链接日指标并启动监控后，这里会实时展示异常与调整建议</div>
        </div>
      </section>

      <!-- ═══ 优化方案 ═══ -->
      <section v-if="tab === 'opt'" class="ops-section">
        <div class="ops-card">
          <div class="ops-card-head">
            <h3>AI 优化方案</h3>
            <button class="btn-primary" :disabled="optLoading" @click="loadOpt">
              {{ optLoading ? "生成中…" : "重新生成" }}
            </button>
          </div>
          <div v-if="opt?.输入" class="opt-inputs">
            <span class="ops-tag">体检 {{ opt.输入.体检分 }} 分</span>
            <span class="ops-tag">退款率 {{ opt.输入.退款率 }}</span>
            <span class="ops-tag">整体 ROI {{ opt.输入.ROI }}</span>
          </div>
          <div v-if="opt?.方案" class="opt-text">{{ opt.方案 }}</div>
          <div v-else class="ops-empty">点击「重新生成」获取基于当前体检/退款/报表的优化方案（LLM 生成，离线时规则引擎兜底）</div>
        </div>
      </section>
    </div>

    <div class="toast" :class="toast.kind" :hidden="!toast.visible">{{ toast.text }}</div>
  </div>
</template>

<style scoped>
.ops-page {
  height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  max-width: 1500px;
  margin: 0 auto;
  width: 100%;
}
.ops-tabs {
  display: flex;
  gap: 6px;
  padding: 12px 16px 0;
  flex-wrap: wrap;
}
.ops-tab {
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-muted);
  padding: 7px 14px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--layer-1);
  transition: color .15s, border-color .15s, background .15s;
}
.ops-tab:hover { color: var(--text); border-color: var(--text-faint); }
.ops-tab.on {
  color: oklch(98% 0 0);
  background: linear-gradient(135deg, var(--brand), var(--brand-dim));
  border-color: transparent;
}
.ops-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px 16px 28px;
  display: flex;
  flex-direction: column;
}
.ops-body::-webkit-scrollbar { width: 8px; }
.ops-body::-webkit-scrollbar-thumb { background: var(--layer-3); border-radius: 4px; }
.ops-body.loading { opacity: .7; }
.ops-section { display: flex; flex-direction: column; gap: 14px; }
.ops-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 14px;
}
.ops-card {
  background: oklch(18% 0.018 260 / 0.72);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid var(--border);
  border-radius: var(--r-l);
  padding: var(--s-5);
  position: relative;
}
.ops-card::before {
  content: "";
  position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, oklch(100% 0 0 / 0.16), transparent);
  pointer-events: none;
}
.ops-card h3 { font-size: 14.5px; font-weight: 600; margin-bottom: 12px; }
.ops-card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; gap: 8px; flex-wrap: wrap; }
.ops-card-head h3 { margin-bottom: 0; }
.ops-tag {
  font-size: 11px; font-weight: 600;
  color: var(--text-muted);
  background: var(--layer-2);
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px 10px;
}
.ops-desc { font-size: 12.5px; color: var(--text-muted); line-height: 1.7; margin-bottom: 12px; }
.ops-empty { font-size: 12.5px; color: var(--text-faint); padding: 18px 0; text-align: center; }
.ops-hint { font-size: 11.5px; color: var(--text-faint); margin-top: 8px; }
.crawl-warns { display: flex; flex-direction: column; gap: 6px; margin: 8px 0; }
.crawl-warn { font-size: 12px; color: var(--warn, #b8860b); background: rgba(184,134,11,.12);
  border: 1px dashed var(--warn, #b8860b); padding: 6px 10px; border-radius: 8px; line-height: 1.5; }
.ops-card h4 { font-size: 12px; color: var(--text); margin: 12px 0 6px; }
.mini-tbl { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px; }
.mini-tbl th, .mini-tbl td { border: 1px solid var(--line, #e5e7eb); padding: 4px 6px; text-align: left; }
.mini-tbl th { background: var(--line-faint, #f5f6f7); color: var(--text-faint); font-weight: 600; }

/* 指标卡 */
.ops-grid-kpi {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px;
}
.ops-kpi {
  background: oklch(18% 0.018 260 / 0.72);
  border: 1px solid var(--border);
  border-radius: var(--r-l);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  position: relative;
}
.ops-kpi::before {
  content: "";
  position: absolute; top: 0; left: 0; right: 0; height: 1px;
  background: linear-gradient(90deg, transparent, oklch(100% 0 0 / 0.16), transparent);
}
.ops-kpi-num {
  font-size: 26px; font-weight: 700;
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.ops-kpi-num.ok { color: var(--c-ok); }
.ops-kpi-num.warn { color: var(--c-guard); }
.ops-kpi-num.danger { color: var(--c-sens); }
.ops-kpi-label { font-size: 11.5px; color: var(--text-faint); }
.ops-kpi-sub { font-size: 11px; color: var(--brand-strong); }

/* 指标格 */
.ops-grid-metric {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.ops-metric {
  background: var(--layer-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-m);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.m-label { font-size: 11px; color: var(--text-faint); }
.m-val { font-size: 19px; font-weight: 650; font-variant-numeric: tabular-nums; }
.m-val.ok, .up { color: var(--c-ok); }
.m-val.warn, .warn { color: var(--c-guard); }
.m-val.danger, .danger, .down { color: var(--c-sens); }

/* 环比 */
.ops-compare { display: flex; flex-direction: column; gap: 8px; }
.cmp-item { display: flex; justify-content: space-between; font-size: 12.5px; }
.cmp-key { color: var(--text-muted); }
.cmp-val { font-family: var(--font-mono); font-weight: 600; }
.cmp-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
.cmp-chip {
  font-size: 11.5px;
  font-family: var(--font-mono);
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--layer-2);
  border: 1px solid var(--border);
}
.cmp-chip.up { color: var(--c-ok); border-color: oklch(76% 0.14 160 / 0.3); }
.cmp-chip.down { color: var(--c-sens); border-color: oklch(65% 0.19 25 / 0.3); }

/* 报表 */
.report-title { font-size: 12px; color: var(--brand-strong); margin-bottom: 12px; font-weight: 600; }
.period-tabs { display: flex; gap: 4px; }
.period-tab {
  font-size: 12px;
  color: var(--text-muted);
  padding: 5px 12px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--layer-1);
}
.period-tab.on { color: var(--brand-strong); border-color: var(--brand-dim); background: oklch(66% 0.17 287 / 0.12); }
.trend-block h4 { font-size: 12px; font-weight: 600; color: var(--text-muted); margin-bottom: 10px; }

/* 退款 */
.bucket-list { display: flex; flex-direction: column; gap: 8px; }
.bucket-row { display: grid; grid-template-columns: 130px 1fr 46px; align-items: center; gap: 8px; font-size: 12px; }
.bucket-name { color: var(--text-muted); }
.bucket-track { height: 8px; background: var(--layer-2); border-radius: 999px; overflow: hidden; }
.bucket-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--c-sens), var(--c-guard)); }
.bucket-val { font-family: var(--font-mono); font-size: 11px; color: var(--text-muted); text-align: right; }
.risk-box { margin-top: 14px; }
.risk-box h4 { font-size: 12px; font-weight: 600; color: var(--c-sens); margin-bottom: 8px; }
.risk-item { display: flex; align-items: center; gap: 10px; font-size: 12px; padding: 6px 10px; background: var(--layer-2); border: 1px solid oklch(65% 0.19 25 / 0.25); border-radius: var(--r-s); margin-bottom: 6px; }
.risk-item code { color: var(--text); }
.risk-item .risk-orders { margin-left: auto; color: var(--text-faint); }

/* 体检 */
.health-score { display: flex; gap: 28px; align-items: center; flex-wrap: wrap; }
.score-ring {
  width: 132px; height: 132px;
  flex-shrink: 0;
  border-radius: 50%;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border: 6px solid;
  background: var(--layer-2);
}
.score-ring.ok { border-color: var(--c-ok); color: var(--c-ok); }
.score-ring.good { border-color: var(--brand); color: var(--brand-strong); }
.score-ring.warn { border-color: var(--c-guard); color: var(--c-guard); }
.score-num { font-size: 40px; font-weight: 750; line-height: 1.1; font-variant-numeric: tabular-nums; }
.score-grade { font-size: 13px; font-weight: 600; }
.health-dims { flex: 1; min-width: 260px; display: flex; flex-direction: column; gap: 12px; }
.dim-row .bar-track { height: 9px; }
.dim-head { display: flex; justify-content: space-between; font-size: 12.5px; margin-bottom: 4px; }
.dim-name { color: var(--text); font-weight: 600; }
.dim-val { color: var(--text-muted); font-family: var(--font-mono); }
.dim-meta { font-size: 11px; color: var(--text-faint); margin-top: 3px; }

/* ROI */
.realloc-row { display: flex; gap: 8px; margin-bottom: 12px; }
.realloc-row .text-input { flex: 1; }
.realloc-list { display: flex; flex-direction: column; gap: 6px; }
.realloc-item {
  display: flex; align-items: center; gap: 10px;
  font-size: 12.5px;
  padding: 8px 12px;
  background: var(--layer-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
}
.ra-name { font-weight: 600; }
.ra-roi { font-family: var(--font-mono); color: var(--text-muted); }
.ra-delta { margin-left: auto; font-family: var(--font-mono); font-weight: 600; }

.plan-table { display: flex; flex-direction: column; gap: 4px; }
.plan-row {
  display: grid;
  grid-template-columns: 1.4fr .7fr .8fr .6fr .6fr 1.8fr;
  gap: 8px;
  align-items: center;
  font-size: 12px;
  padding: 8px 10px;
  border-radius: var(--r-s);
}
.plan-row:nth-child(even) { background: var(--layer-1); }
.plan-head { color: var(--text-faint); font-size: 11px; background: var(--layer-2) !important; font-weight: 600; }
.pl-name { font-weight: 600; }
.pl-roi { font-family: var(--font-mono); font-weight: 700; }
.pl-roi.ok { color: var(--c-ok); }
.pl-roi.warn { color: var(--c-guard); }
.pl-num { font-family: var(--font-mono); color: var(--text-muted); }
.pl-actions { color: var(--brand-strong); font-size: 11.5px; }

/* 图库 */
.crawl-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 6px; }
.text-input {
  min-height: 38px;
  padding: 0 12px;
  color: var(--text);
  background: var(--layer-1);
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  outline: none;
  font: inherit;
  font-size: 13px;
}
.text-input:focus { border-color: var(--brand-dim); }
.text-input.sel { min-width: 110px; }
.text-input.num { width: 84px; }
.text-input.mono { font-family: var(--font-mono); font-size: 12px; }
.text-input.area { padding: 10px 12px; resize: vertical; width: 100%; margin-bottom: 8px; }
.img-grid {
  margin-top: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}
.img-card {
  border: 1px solid var(--border);
  border-radius: var(--r-m);
  overflow: hidden;
  background: var(--layer-2);
  transition: transform .15s, border-color .15s;
}
.img-card:hover { transform: translateY(-2px); border-color: var(--brand-dim); }
.img-card img { width: 100%; aspect-ratio: 1; object-fit: cover; display: block; }
.img-meta { padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.img-title { font-size: 12px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.img-sub { font-size: 10.5px; color: var(--text-faint); }

/* 命令工厂 */
.forge-cols { grid-template-columns: 1.2fr 1fr; }
.cmd-list { display: flex; flex-direction: column; gap: 5px; max-height: 320px; overflow-y: auto; }
.cmd-list::-webkit-scrollbar { width: 8px; }
.cmd-list::-webkit-scrollbar-thumb { background: var(--layer-3); border-radius: 4px; }
.cmd-item {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
  background: var(--layer-1);
  text-align: left;
  transition: border-color .15s, background .15s;
}
.cmd-item:hover { border-color: var(--brand-dim); }
.cmd-item.on { border-color: var(--brand); background: oklch(66% 0.17 287 / 0.1); }
.cmd-name { font-family: var(--font-mono); font-size: 12px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cmd-type {
  font-size: 10px; font-weight: 700;
  padding: 1px 8px; border-radius: 999px; letter-spacing: 0.03em;
}
.cmd-type.tp-builtin { color: var(--c-kb); background: oklch(72% 0.13 235 / 0.12); }
.cmd-type.tp-agent { color: var(--c-llm); background: oklch(70% 0.16 300 / 0.12); }
.cmd-type.tp-manual { color: var(--c-guard); background: oklch(78% 0.12 75 / 0.12); }
.cmd-ops { display: flex; gap: 6px; }
.btn-ghost {
  font-size: 12px; color: var(--text-muted);
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-s);
  background: var(--layer-1);
}
.btn-ghost:hover { color: var(--text); }
.btn-danger {
  font-size: 12px; font-weight: 600; color: var(--c-sens);
  padding: 6px 12px;
  border: 1px solid oklch(65% 0.19 25 / 0.4);
  border-radius: var(--r-s);
  background: oklch(65% 0.19 25 / 0.1);
}
.btn-primary {
  font-size: 13px; font-weight: 600;
  color: oklch(98% 0 0);
  padding: 9px 18px;
  border-radius: var(--r-s);
  background: linear-gradient(135deg, var(--brand), var(--brand-dim));
  white-space: nowrap;
}
.btn-primary:hover { filter: brightness(1.1); }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
.cmd-params { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.cmd-params code {
  font-size: 11px;
  color: var(--c-kb);
  background: oklch(72% 0.13 235 / 0.1);
  border: 1px solid oklch(72% 0.13 235 / 0.25);
  padding: 2px 8px;
  border-radius: 999px;
}
.exec-row { display: flex; gap: 8px; margin: 10px 0; }
.exec-row .text-input { flex: 1; }
.json-pre {
  font-family: var(--font-mono);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--text-muted);
  background: var(--layer-1);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
  padding: 10px 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.code-box { margin-top: 12px; }
.code-box summary { font-size: 12px; color: var(--text-faint); cursor: pointer; }
.code-box summary:hover { color: var(--text); }
.forge-log { display: flex; flex-direction: column; gap: 5px; max-height: 260px; overflow-y: auto; }
.forge-log::-webkit-scrollbar { width: 8px; }
.forge-log::-webkit-scrollbar-thumb { background: var(--layer-3); border-radius: 4px; }
.log-item {
  display: flex; gap: 10px; align-items: baseline;
  font-size: 11.5px;
  padding: 6px 10px;
  background: var(--layer-1);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
}
.log-at { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-faint); flex-shrink: 0; }
.log-item code { color: var(--brand-strong); }
.log-data { color: var(--text-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 优化方案 */
.opt-inputs { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
.opt-text {
  font-size: 13px;
  line-height: 1.8;
  color: var(--text);
  background: var(--layer-1);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-m);
  padding: 16px 18px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 严格对账 */
.rc-table { width: 100%; max-height: 320px; overflow: auto; }
.rc-table table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.rc-table thead th { text-align: left; font-weight: 600; color: var(--text-faint); font-size: 11.5px; padding: 6px 8px; background: var(--layer-2); border-bottom: 1px solid var(--border-soft); position: sticky; top: 0; }
.rc-table tbody td { padding: 6px 8px; border-bottom: 1px solid var(--border-soft); vertical-align: top; }
.rc-table .rc-metric { color: var(--text-muted); white-space: nowrap; }
.rc-table .rc-num { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.rc-table .rc-warn { color: var(--c-sens); font-weight: 650; }
.rc-table .rc-warn-row { background: oklch(65% 0.19 25 / 0.08); }
.rc-table .rc-empty { color: var(--text-faint); }
.rc-badge { font-size: 11.5px; padding: 2px 8px; border-radius: var(--r-s); background: oklch(76% 0.14 160 / 0.1); color: var(--c-ok); white-space: nowrap; }
.rc-badge.warn { background: oklch(65% 0.19 25 / 0.12); color: var(--c-sens); }
p .rc-warn { color: var(--c-sens); font-weight: 650; }

/* 反哺 */
.ops-feedback { display: flex; align-items: baseline; gap: 10px; }
.fb-num { font-size: 34px; font-weight: 750; color: var(--c-ok); font-variant-numeric: tabular-nums; }
.fb-label { font-size: 12px; color: var(--text-muted); }
.ops-src-list { list-style: none; display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; color: var(--text-muted); line-height: 1.6; }

/* 数据接入 */
.tag-real { color: var(--c-ok); border-color: oklch(76% 0.14 160 / 0.4); background: oklch(76% 0.14 160 / 0.1); }
.tag-demo { color: var(--text-muted); }
.import-row { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.file-btn { cursor: pointer; display: inline-flex; align-items: center; }
.probe-box {
  display: flex; align-items: center; gap: 8px;
  font-size: 12px; color: var(--c-guard);
  padding: 8px 12px; border: 1px solid oklch(78% 0.12 75 / 0.3);
  background: oklch(78% 0.12 75 / 0.08);
  border-radius: var(--r-s); margin-bottom: 8px;
}
.probe-box.ok { color: var(--c-ok); border-color: oklch(76% 0.14 160 / 0.3); background: oklch(76% 0.14 160 / 0.08); }
.probe-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; flex-shrink: 0; }
.snap-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-bottom: 10px; }
.snap-list { display: flex; flex-direction: column; gap: 6px; }
.snap-item {
  display: flex; align-items: center; gap: 10px;
  font-size: 12px; padding: 7px 12px;
  background: var(--layer-2); border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
}
.snap-item code { color: var(--c-kb); }
.snap-del { margin-left: auto; color: var(--c-sens); background: none; border: none; cursor: pointer; font-size: 13px; }
.link-table { display: flex; flex-direction: column; gap: 4px; }
.link-row {
  display: grid;
  grid-template-columns: 2.2fr 1fr 1fr .6fr .6fr .6fr .9fr;
  gap: 8px; align-items: center;
  font-size: 12px; padding: 8px 10px; border-radius: var(--r-s);
}
.link-row:nth-child(even) { background: var(--layer-1); }
.link-head { color: var(--text-faint); font-size: 11px; background: var(--layer-2) !important; font-weight: 600; }
.lk-name { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.lk-name code { font-size: 10.5px; color: var(--c-kb); }
.lk-num { font-family: var(--font-mono); color: var(--text-muted); }
.lk-num.faint { color: var(--text-faint); }
.lk-roi { font-family: var(--font-mono); font-weight: 700; }
.lk-roi.ok { color: var(--c-ok); }
.lk-roi.warn { color: var(--c-guard); }
.live-meta { display: flex; flex-direction: column; gap: 2px; font-size: 12px; padding: 8px 12px; margin-top: 8px; background: var(--layer-2); border: 1px solid var(--border-soft); border-radius: var(--r-s); }
.live-meta.ok { border-color: oklch(76% 0.14 160 / 0.3); }
.lm-label { font-size: 10.5px; letter-spacing: .03em; color: var(--text-faint); text-transform: uppercase; }
.lm-val { font-family: var(--font-mono); color: var(--text); margin-top: 2px; word-break: break-all; }
.daily-table { display: flex; flex-direction: column; gap: 4px; }
.daily-row { display: grid; grid-template-columns: 1.6fr repeat(4, 1fr); gap: 8px; align-items: center; font-size: 12px; padding: 8px 10px; border-radius: var(--r-s); }
.daily-row:nth-child(even) { background: var(--layer-1); }
.daily-head { color: var(--text-faint); font-size: 11px; background: var(--layer-2) !important; font-weight: 600; }
.daily-date { font-family: var(--font-mono); font-weight: 600; }
.daily-date em { display: block; font-style: normal; font-size: 10px; color: var(--text-faint); font-family: var(--font-sans); }
.daily-chip { font-family: var(--font-mono); color: var(--text-muted); }
.daily-chip b { font-family: var(--font-sans); color: var(--text-faint); font-weight: 500; margin-right: 5px; }
.daily-chip.faint { color: var(--text-faint); }
.periods-table { display: flex; flex-direction: column; gap: 4px; }
.periods-row {
  display: grid;
  grid-template-columns: .7fr repeat(4, 1fr) 1fr;
  gap: 8px; align-items: center;
  font-size: 12px; padding: 8px 10px; border-radius: var(--r-s);
}
.periods-row:nth-child(even) { background: var(--layer-1); }
.periods-head { color: var(--text-faint); font-size: 11px; background: var(--layer-2) !important; font-weight: 600; }
.periods-label { font-weight: 600; color: var(--c-kb); }
.periods-val { font-family: var(--font-mono); color: var(--text-muted); }
.periods-val b { font-family: var(--font-sans); color: var(--text-faint); font-weight: 500; margin-right: 5px; }
.periods-val.faint { color: var(--text-faint); }
.periods-update { font-size: 11px; color: var(--text-faint); font-family: var(--font-mono); text-align: right; }
.report-src { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--brand-strong); margin-bottom: 12px; padding: 5px 11px; border: 1px solid oklch(66% 0.17 287 / 0.25); background: oklch(66% 0.17 287 / 0.08); border-radius: 999px; }
.rs-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--brand-strong); flex-shrink: 0; }

/* 实时监控 */
.alert-filter { display: flex; gap: 4px; }
.alert-list { display: flex; flex-direction: column; gap: 10px; max-height: 560px; overflow-y: auto; }
.alert-list::-webkit-scrollbar { width: 8px; }
.alert-list::-webkit-scrollbar-thumb { background: var(--layer-3); border-radius: 4px; }
.alert-item {
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: var(--r-m);
  background: var(--layer-2);
  padding: 12px 14px;
}
.alert-item.lv-danger { border-left-color: var(--c-sens); }
.alert-item.lv-warn { border-left-color: var(--c-guard); }
.alert-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
.alert-level {
  font-size: 10.5px; font-weight: 700;
  padding: 2px 9px; border-radius: 999px; letter-spacing: 0.03em;
}
.alert-level.lv-danger { color: var(--c-sens); background: oklch(65% 0.19 25 / 0.14); }
.alert-level.lv-warn { color: var(--c-guard); background: oklch(78% 0.12 75 / 0.14); }
.alert-name { font-size: 13px; font-weight: 600; }
.alert-name code { font-size: 10.5px; color: var(--c-kb); margin-left: 6px; }
.alert-ts { margin-left: auto; font-family: var(--font-mono); font-size: 10.5px; color: var(--text-faint); }
.alert-msg { font-size: 12.5px; line-height: 1.6; color: var(--text); margin-bottom: 8px; }
.alert-metrics { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.alert-chip {
  font-size: 10.5px; font-family: var(--font-mono);
  color: var(--text-muted);
  background: var(--layer-1);
  border: 1px solid var(--border-soft);
  padding: 2px 8px; border-radius: 999px;
}
.alert-sug { font-size: 12px; margin-top: 6px; }
.alert-sug summary { color: var(--brand-strong); cursor: pointer; font-weight: 600; margin-bottom: 4px; }
.alert-sug p {
  color: var(--text-muted); line-height: 1.7;
  background: var(--layer-1);
  border: 1px solid var(--border-soft);
  border-radius: var(--r-s);
  padding: 10px 12px;
}
.alert-sug.llm summary { color: var(--c-llm); }
.alert-sug.llm p { border-color: oklch(70% 0.16 300 / 0.3); background: oklch(70% 0.16 300 / 0.06); }

@media (max-width: 900px) {
  .forge-cols { grid-template-columns: 1fr; }
  .plan-row { grid-template-columns: 1.4fr .7fr .8fr 1.6fr; }
  .plan-row span:nth-child(4), .plan-row span:nth-child(5) { display: none; }
  .link-row { grid-template-columns: 2.2fr 1fr 1fr .6fr .6fr; }
  .link-row span:nth-child(6), .link-row span:nth-child(7) { display: none; }
}
</style>
