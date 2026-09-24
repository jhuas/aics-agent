<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from "vue";
import TopBar from "./components/TopBar.vue";
import EngineBar from "./components/EngineBar.vue";
import EventLog from "./components/EventLog.vue";
import TakeoverPanel from "./components/TakeoverPanel.vue";
import DecisionTrace from "./components/DecisionTrace.vue";
import StatsPanel from "./components/StatsPanel.vue";
import SettingsModal from "./components/SettingsModal.vue";
import OpsCenter from "./components/OpsCenter.vue";
import MemoryPanel from "./components/MemoryPanel.vue";
import { api } from "./api";
import { store } from "./store";

const events = ref([]);
const cursor = ref(0);
const selected = ref(null);
const checked = ref(false);
const busy = ref(false);
const showSettings = ref(false);
const activeTab = ref("cockpit");
const toast = reactive({ text: "", kind: "", visible: false });

const agent = store.agent;
let timer = null;

function showToast(text, kind = "") {
  toast.text = text;
  toast.kind = kind;
  toast.visible = true;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { toast.visible = false; }, 2800);
}

function applyStatus(st) {
  if (!st) return;
  agent.running = !!st.running;
  agent.startedAt = st.started_at || null;
  agent.interval = st.interval || agent.interval;
  agent.dry = !!st.dry;
  agent.eventCount = st.event_count || 0;
  agent.stats = st.stats || agent.stats;
}

async function poll() {
  try {
    const st = await api.agentStatus();
    applyStatus(st);
    const ev = await api.agentEvents(cursor.value);
    if (ev.events && ev.events.length) {
      events.value.push(...ev.events);
      if (events.value.length > 800) events.value.splice(0, events.value.length - 800);
      cursor.value = ev.cursor;
    }
  } catch (e) {
    checked.value = false;
  }
}

async function refreshNow() {
  await poll();
  checked.value = true;
}

async function startEngine() {
  if (busy.value) return;
  busy.value = true;
  try {
    const r = await api.agentStart(agent.interval, agent.dry);
    showToast(r.message, r.ok ? "ok" : "err");
    await refreshNow();
  } catch (e) {
    showToast("启动失败：" + e.message, "err");
  } finally {
    busy.value = false;
  }
}

async function stopEngine() {
  if (busy.value) return;
  busy.value = true;
  try {
    const r = await api.agentStop();
    showToast(r.message, r.ok ? "ok" : "err");
    await refreshNow();
  } catch (e) {
    showToast("停止失败：" + e.message, "err");
  } finally {
    busy.value = false;
  }
}

function onInterval(v) {
  agent.interval = Math.max(5, Math.min(600, v || 30));
}

function onDry(v) {
  agent.dry = !!v;
}

function clearView() {
  events.value = [];
  selected.value = null;
  cursor.value = agent.eventCount || 0;
  showToast("日志已清屏", "ok");
}

function selectEvent(e) {
  selected.value = e;
}

async function onSaveKey(key) {
  try {
    const r = await api.setKey(key);
    if (r.ok) {
      store.llmReady = true;
      showSettings.value = false;
      showToast("API Key 已保存，立即生效", "ok");
    } else {
      showToast("保存失败，请检查 Key", "err");
    }
  } catch (e) {
    showToast("保存失败：" + e.message, "err");
  }
}

onMounted(async () => {
  try {
    const cfg = await api.config();
    if (cfg.store_name) store.storeName = cfg.store_name;
    store.llmReady = !!cfg.llm_ready;
  } catch { /* 后端未就绪，稍后重试 */ }
  await refreshNow();
  try {
    const st = await api.agentStatus();
    const rp = await api.agentReplay(200);
    events.value = rp.events || [];
    cursor.value = st.event_count || 0;
  } catch { /* 静默 */ }
  timer = setInterval(poll, 3000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <TopBar :store-name="store.storeName" :running="agent.running" :checked="checked"
          :active-tab="activeTab" @open-settings="showSettings = true" @tab="activeTab = $event" />

  <main v-if="activeTab === 'ops'" class="layout ops">
    <OpsCenter />
  </main>

  <main v-else-if="activeTab === 'memory'" class="layout ops">
    <MemoryPanel />
  </main>

  <main v-else class="layout cockpit">
    <section class="col-main">
      <EngineBar :running="agent.running" :started-at="agent.startedAt" :interval="agent.interval"
                 :dry="agent.dry" :stats="agent.stats" :busy="busy"
                 @start="startEngine" @stop="stopEngine" @interval="onInterval" @dry="onDry" />
      <EventLog :events="events" :selected="selected" @select="selectEvent" @clear="clearView" />
    </section>

    <aside class="side-panel">
      <DecisionTrace :event="selected" />
      <TakeoverPanel :events="events" @select="selectEvent" />
      <StatsPanel :stats="agent.stats" />
    </aside>
  </main>

  <SettingsModal :visible="showSettings" @close="showSettings = false" @save="onSaveKey" />
  <div class="toast" :class="toast.kind" :hidden="!toast.visible">{{ toast.text }}</div>
</template>
