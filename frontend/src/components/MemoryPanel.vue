<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from "vue";
import { api } from "../api";

const stats = ref(null);
const items = ref([]);
const query = ref("");
const testText = ref("");
const testHits = ref(null);
const testing = ref(false);
const learning = ref(false);
const loading = ref(false);
const syncing = ref(false);
const syncState = ref(null);
let pollTimer = null;
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

async function loadAll() {
  const [s, l] = await Promise.all([
    safe(() => api.memoryStats(), "记忆状态加载失败"),
    safe(() => api.memoryList(query.value), "记忆列表加载失败"),
  ]);
  if (s) stats.value = s;
  if (l) items.value = l.items || [];
}

async function toggleEnabled() {
  const d = await safe(() => api.memoryToggle(!stats.value?.enabled), "开关切换失败");
  if (d) {
    stats.value.enabled = d.enabled;
    showToast(d.enabled ? "记忆检索已开启" : "记忆检索已关闭（保留数据）", "ok");
  }
}

async function doLearn() {
  learning.value = true;
  const d = await safe(() => api.memoryLearn(), "学习失败");
  learning.value = false;
  if (d) {
    const l = d.learned || {};
    const n = (l.sessions || 0) + (l.events || 0);
    showToast(`学习完成：新增 ${n} 条（会话 ${l.sessions || 0}｜引擎 ${l.events || 0}）`, "ok");
    await loadAll();
  }
}

// ---- 一键同步客服记录（CDP 逐一遍历工作台所有历史会话） ----
function stopPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

async function pollSync() {
  const st = await safe(() => api.memorySyncStatus(), "获取同步状态失败");
  if (st) syncState.value = st;
  if (st && !st.busy && st.done) {
    stopPoll();
    if (st.total) {
      showToast(`同步完成：读入 ${st.pairs} 条问答，新增记忆 ${st.learned} 条`, "ok");
      await loadAll();
      loadTestRef();
    }
  }
}

function loadTestRef() {
  testHits.value = null;
}

async function doSync() {
  syncing.value = true;
  const d = await safe(() => api.memorySync(), "启动同步失败");
  if (d) {
    syncState.value = d.state || d;
    if (syncState.value?.busy) {
      showToast("已开始逐一读取客服记录…", "");
      startPoll();
    } else if (syncState.value?.learned > 0 || syncState.value?.pairs > 0) {
      showToast(`同步结果：读入 ${syncState.value.pairs} 条问答，新增记忆 ${syncState.value.learned} 条`, "ok");
    }
  }
  syncing.value = false;
}

function startPoll() {
  stopPoll();
  pollTimer = setInterval(pollSync, 2000);
}

async function doTest() {
  const t = (testText.value || "").trim();
  if (!t) return;
  testing.value = true;
  const d = await safe(() => api.memoryTest(t), "检索失败");
  testing.value = false;
  if (d) {
    testHits.value = d.hits || [];
    if (!testHits.value.length) showToast("记忆库无高度相似的问答（未命中）", "");
  }
}

async function doRemove(id) {
  const d = await safe(() => api.memoryRemove(id), "删除失败");
  if (d?.ok) {
    showToast("已删除该条记忆", "ok");
    await loadAll();
  }
}

onMounted(loadAll);
onBeforeUnmount(stopPoll);
</script>

<template>
  <div class="ops-page memory-page">
    <div class="ops-card">
      <div class="ops-card-head">
        <h3>🧠 记忆库 · 历史问答复用</h3>
        <div class="mem-head-actions">
          <span class="mem-file" :title="stats?.memory_file">{{ stats?.memory_file }}</span>
          <button class="btn-ghost" :disabled="learning || loading" @click="doLearn">
            {{ learning ? "学习中…" : "🔄 学习历史记录" }}
          </button>
          <button class="btn-primary" :disabled="syncing || syncState?.busy" @click="doSync">
            {{ syncState?.busy ? "同步中…" : "📥 一键同步客服记录" }}
          </button>
        </div>
      </div>

      <div v-if="syncState" class="mem-sync">
        <div class="panel-head">
          <h4>客服记录同步</h4>
          <span class="ops-hint">通过 CDP 逐一读取工作台全部历史会话（含未滚动加载的），减少遗漏</span>
        </div>
        <div v-if="syncState.busy" class="mem-sync-progress">
          <span class="mem-sync-spinner"></span>
          正在读取会话 {{ syncState.scanned }}/{{ syncState.total }} · 当前「{{ syncState.last }}」 · 已新增记忆 {{ syncState.learned }} 条
        </div>
        <div v-else-if="syncState.total" class="mem-sync-done">
          同步完成：读入 {{ syncState.pairs }} 条问答｜新增记忆 {{ syncState.learned }} 条｜重复/无效 {{ syncState.skipped }} 条｜异常 {{ syncState.errored }} 条
        </div>
        <div v-else class="mem-sync-done">{{ syncState.message || "暂无数据（请确认已登录客服工作台后重试）" }}</div>
      </div>

      <div class="mem-grid">
        <section class="mem-col">
          <div class="mem-kpis">
            <div class="mem-kpi">
              <span class="mem-kpi-num">{{ stats?.total ?? 0 }}</span>
              <span class="mem-kpi-label">记忆问答</span>
            </div>
            <div class="mem-kpi">
              <span class="mem-kpi-num">{{ stats?.hits_total ?? 0 }}</span>
              <span class="mem-kpi-label">累计复用</span>
            </div>
            <div class="mem-kpi">
              <span class="mem-kpi-num">{{ (stats?.by_source?.sessions || 0) + (stats?.by_source?.events || 0) + (stats?.by_source?.live || 0) }}</span>
              <span class="mem-kpi-label">历史学习</span>
            </div>
            <label class="mem-switch-wrap">
              <span class="mem-switch-label">{{ stats?.enabled ? "记忆检索：开" : "记忆检索：关" }}</span>
              <button class="switch" :class="{ on: stats?.enabled }" role="switch" aria-checked="!!stats?.enabled"
                      @click="toggleEnabled">
                <span class="switch-knob"></span>
              </button>
            </label>
          </div>

          <div class="mem-test">
            <div class="panel-head">
              <h4>检索测试</h4>
              <span class="ops-hint">输入客户问题，查看是否命中历史问答</span>
            </div>
            <div class="input-row">
              <input v-model="testText" placeholder="例如：脚踏板怎么安装" @keyup.enter="doTest" />
              <button class="btn-primary" :disabled="testing" @click="doTest">测试</button>
            </div>
            <div v-if="testHits && testHits.length" class="mem-test-hits">
              <div v-for="h in testHits" :key="h.id" class="mem-test-hit">
                <div class="mem-test-q">
                  <span class="panel-tag hit-kb">相似度 {{ h.score.toFixed(2) }}</span>
                  {{ h.question }}
                </div>
                <div class="mem-test-r">→ {{ h.reply }}</div>
              </div>
            </div>
            <div v-else-if="testHits && !testHits.length" class="ops-empty">未命中（低于相似度阈值，不会误答）</div>
          </div>

          <div class="mem-list-wrap">
            <div class="panel-head">
              <h4>记忆列表</h4>
              <input class="mem-search" v-model="query" placeholder="搜索问题 / 回复…" @keyup.enter="loadAll" @blur="loadAll" />
            </div>
            <div v-if="!items.length" class="ops-empty">
              暂无记忆。点击右上角「学习历史记录」从过往客服回复中学习，或让引擎真实回复几次后自动积累。
            </div>
            <div v-for="it in items" :key="it.id" class="mem-item">
              <div class="mem-item-q">
                <span class="panel-tag" :class="it.source === 'live' ? 'hit-llm' : it.source === 'events' ? 'hit-kb' : ''">
                  {{ it.source === "live" ? "实时" : it.source === "events" ? "引擎" : "会话" }}
                </span>
                {{ it.question }}
              </div>
              <div class="mem-item-r">{{ it.reply }}</div>
              <div class="mem-item-meta">
                <span>复用 {{ it.hits }} 次</span>
                <span v-if="it.last_used">｜最近 {{ it.last_used }}</span>
                <span v-else>｜{{ it.updated_at }}</span>
                <button class="btn-ghost mem-del" title="删除该条记忆" @click="doRemove(it.id)">删除</button>
              </div>
            </div>
          </div>
        </section>

        <aside class="mem-side">
          <div class="ops-card mem-side-card">
            <div class="ops-card-head"><h4>来源分布</h4></div>
            <div v-for="(n, k) in stats?.by_source || {}" :key="k" class="mem-src-row">
              <span>{{ k === "live" ? "实时回复" : k === "events" ? "引擎事件流" : k === "sessions" ? "历史会话" : k }}</span>
              <b>{{ n }} 条</b>
            </div>
            <div v-if="!stats?.by_source || !Object.keys(stats.by_source).length" class="ops-empty">暂无数据</div>
          </div>
          <div class="ops-card mem-side-card">
            <div class="ops-card-head"><h4>工作方式</h4></div>
            <ol class="mem-how">
              <li>引擎每次<em>真实回复</em>后，自动把「客户问题 → 回复话术」记入记忆库</li>
              <li>遇到<em>库外/闲聊</em>问题，先检索记忆：相似度达标 → 复用历史回复</li>
              <li>所有记忆数据保存在程序<em>数据文件夹</em>，可随时查看、删除、开关</li>
            </ol>
          </div>
        </aside>
      </div>
    </div>

    <div class="toast" :class="toast.kind" :hidden="!toast.visible">{{ toast.text }}</div>
  </div>
</template>

<style scoped>
.memory-page { display: flex; flex-direction: column; gap: 16px; }
.mem-head-actions { display: flex; align-items: center; gap: 12px; }
.mem-sync { background: var(--layer-2); border: 1px solid var(--line); border-radius: 12px; padding: 10px 14px; margin-bottom: 16px; }
.mem-sync-progress { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text); }
.mem-sync-done { font-size: 13px; color: var(--text-muted); }
.mem-sync-spinner { width: 14px; height: 14px; border: 2px solid var(--line-strong, #888); border-top-color: transparent; border-radius: 50%; animation: mem-rot 0.8s linear infinite; }
@keyframes mem-rot { to { transform: rotate(360deg); } }
.mem-file { font-size: 11px; color: var(--text-faint); max-width: 380px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mem-grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
.mem-col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.mem-kpis { display: grid; grid-template-columns: repeat(3, auto) 1fr; gap: 12px; align-items: center; }
.mem-kpi { display: flex; flex-direction: column; background: var(--layer-2); border: 1px solid var(--line); border-radius: 10px; padding: 8px 14px; }
.mem-kpi-num { font-size: 20px; font-weight: 700; }
.mem-kpi-label { font-size: 11px; color: var(--text-muted); }
.mem-switch-wrap { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
.mem-switch-label { font-size: 12px; color: var(--text-muted); }
.mem-test { background: var(--layer-2); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.mem-test-hits { margin-top: 10px; display: flex; flex-direction: column; gap: 8px; }
.mem-test-hit { background: var(--layer-3); border-radius: 8px; padding: 8px 10px; }
.mem-test-q { font-size: 13px; display: flex; align-items: center; gap: 8px; }
.mem-test-r { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
.mem-list-wrap { display: flex; flex-direction: column; gap: 8px; }
.mem-search { width: 180px; }
.mem-item { background: var(--layer-2); border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.mem-item-q { font-size: 13px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.mem-item-r { font-size: 12.5px; color: var(--text-muted); margin-top: 4px; line-height: 1.5; }
.mem-item-meta { font-size: 11px; color: var(--text-faint); margin-top: 6px; display: flex; align-items: center; gap: 4px; }
.mem-del { margin-left: auto; padding: 2px 8px; font-size: 11px; }
.mem-side { display: flex; flex-direction: column; gap: 16px; }
.mem-side-card { background: var(--layer-2); border: 1px solid var(--line); border-radius: 12px; padding: 12px 14px; }
.mem-src-row { display: flex; justify-content: space-between; font-size: 13px; padding: 6px 0; border-bottom: 1px dashed var(--line); }
.mem-src-row:last-child { border-bottom: none; }
.mem-how { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 8px; font-size: 12.5px; line-height: 1.6; color: var(--text-muted); }
.mem-how em { color: var(--text); font-style: normal; }
</style>
