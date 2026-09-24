<script setup>
import { ref, computed, watch, nextTick } from "vue";
import { ICONS, EVENT_META, ACTION_TEXT, timeStr } from "../icons";

const props = defineProps({
  events: Array,
  selected: Object,
});
const emit = defineEmits(["select", "clear"]);

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "decision", label: "决策" },
  { key: "send", label: "回复" },
  { key: "human", label: "转人工" },
  { key: "unknown", label: "未识别" },
  { key: "errors", label: "异常" },
];
const filter = ref("all");
const stream = ref(null);
const pinned = ref(true);

function isError(e) {
  return e.t === "log" && String(e.msg || "").includes("⚠️");
}

const filtered = computed(() => {
  if (filter.value === "all") return props.events;
  if (filter.value === "errors") return props.events.filter(isError);
  return props.events.filter((e) => e.t === filter.value);
});

const eventCount = computed(() => props.events.length);

function onScroll() {
  const el = stream.value;
  if (!el) return;
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
}

async function scrollToBottom(force = false) {
  await nextTick();
  const el = stream.value;
  if (!el) return;
  if (force || pinned.value) el.scrollTop = el.scrollHeight;
}

watch(() => props.events.length, () => scrollToBottom());
watch(filter, () => scrollToBottom(true));

function summary(e) {
  const s = e.session ? `会话「${e.session}」` : "";
  switch (e.t) {
    case "log": return e.msg || "";
    case "round": return `开始新一轮巡检 · 待处理 ${e.pending ?? "0"} 个会话`;
    case "status":
      return e.state === "running"
        ? `引擎启动 · 每 ${e.interval}s 巡检 · ${e.dry ? "演练模式" : "真实接管"}`
        : `引擎停止${e.reason ? `（${e.reason}）` : ""}`;
    case "decision":
      return `${s} ${e.category ? `「${e.category}」` : ""} → ${ACTION_TEXT[e.action] || e.action}`;
    case "human": return `${s} 转人工处理${e.refund ? "（退款诉求）" : ""}`;
    case "unknown": return `${s} 无法识别意图，保持待命`;
    case "ack": return `${s} 已了解，静默处理`;
    case "send":
      return `${s} ${ACTION_TEXT[e.action] || e.action}${e.arg ? ` ${e.arg}` : ""}${e.dry ? "（演练）" : ""}`;
    default: return e.msg || e.text || "";
  }
}

function detailLines(e) {
  const lines = [];
  if (e.text) lines.push(["客户原文", e.text]);
  if (e.category) lines.push(["识别类别", e.category]);
  if (e.reason) lines.push(["原因", e.reason]);
  if (e.arg && e.t !== "send") lines.push(["参数", e.arg]);
  if (e.t === "send") {
    lines.push(["回复动作", `${ACTION_TEXT[e.action] || e.action}${e.dry ? "（演练，未真实发送）" : ""}`]);
    if (e.arg) lines.push(["素材/文本", e.arg]);
    if (e.result) lines.push(["发送结果", String(e.result).slice(0, 220)]);
  }
  if (e.msg && e.t === "log") lines.push(["详情", e.msg]);
  return lines;
}
</script>

<template>
  <section class="event-panel">
    <div class="event-head">
      <div class="event-head-title">
        <span class="live-dot"></span>
        <h3>实时接管日志</h3>
        <span class="event-count">{{ eventCount }} 条</span>
      </div>
      <button class="link-btn" @click="emit('clear')">清屏</button>
    </div>

    <div class="event-filters">
      <button v-for="f in FILTERS" :key="f.key" class="filter-chip" :class="{ on: filter === f.key }"
              @click="filter = f.key">{{ f.label }}</button>
    </div>

    <div ref="stream" class="event-stream" role="log" aria-live="polite" @scroll.passive="onScroll">
      <div v-if="!filtered.length" class="event-idle">
        <span v-html="ICONS.activity" />
        <p>暂无日志<br /><span class="idle-sub">启动自动化引擎后，接管与决策将实时显示在这里</span></p>
      </div>

      <div v-for="(e, i) in filtered" :key="i"
           class="event-row" :class="[EVENT_META[e.t]?.cls, { selected: e === selected }]"
           @click="emit('select', e)">
        <div class="event-icon" v-html="ICONS[EVENT_META[e.t]?.icon || 'terminal']" />
        <div class="event-body">
          <div class="event-line">
            <span class="event-time">{{ timeStr(e.time) }}</span>
            <span class="event-type">{{ EVENT_META[e.t]?.label || e.t }}</span>
            <span class="event-summary">{{ summary(e) }}</span>
          </div>
          <div v-if="e === selected && detailLines(e).length" class="event-detail">
            <div v-for="(d, j) in detailLines(e)" :key="j" class="event-detail-row">
              <span class="event-detail-key">{{ d[0] }}</span>
              <span class="event-detail-val">{{ d[1] }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
