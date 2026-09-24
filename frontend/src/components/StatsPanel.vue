<script setup>
import { computed } from "vue";

const props = defineProps({
  stats: Object,
});

const kpis = computed(() => {
  const s = props.stats || {};
  return [
    { label: "巡检轮次", val: s.rounds || 0 },
    { label: "自动处理", val: s.handled || 0 },
    { label: "转人工", val: s.human || 0 },
    { label: "退款拦截", val: s.refund || 0 },
  ];
});

const BAR_META = [
  { key: "send", label: "自动回复", cls: "ch-llm" },
  { key: "ack", label: "静默已读", cls: "ch-guardrail" },
  { key: "unknown", label: "未识别", cls: "ch-sensitive" },
  { key: "human", label: "转人工", cls: "ch-fallback" },
  { key: "refund", label: "退款拦截", cls: "ch-sensitive" },
  { key: "errors", label: "异常", cls: "ch-sensitive" },
];

const bars = computed(() => {
  const s = props.stats || {};
  const entries = BAR_META.map((b) => ({ ...b, val: s[b.key] || 0 })).filter((b) => b.val > 0);
  const max = Math.max(...entries.map((b) => b.val), 1);
  return entries.map((b) => ({ ...b, pct: Math.max((b.val / max) * 100, 3) }));
});

const autoRate = computed(() => {
  const s = props.stats || {};
  const done = (s.handled || 0) + (s.ack || 0);
  const total = done + (s.human || 0) + (s.unknown || 0) + (s.errors || 0);
  return total ? Math.round((done / total) * 100) : 0;
});
</script>

<template>
  <section class="stats-panel">
    <div class="panel-head">
      <h3>运行统计</h3>
      <span class="panel-tag" :class="autoRate >= 80 ? 'hit-kb' : 'hit-fallback'">自动处置率 {{ autoRate }}%</span>
    </div>
    <div class="kpi-row">
      <div v-for="k in kpis" :key="k.label" class="kpi">
        <span class="kpi-num">{{ k.val }}</span>
        <span class="kpi-label">{{ k.label }}</span>
      </div>
    </div>
    <div class="chart-block">
      <h4>处置分布</h4>
      <div v-if="bars.length" class="bars">
        <div v-for="b in bars" :key="b.key" class="bar-row">
          <span class="bar-name">{{ b.label }}</span>
          <div class="bar-track"><div class="bar-fill" :class="b.cls" :style="{ width: b.pct + '%' }"></div></div>
          <span class="bar-val">{{ b.val }}</span>
        </div>
      </div>
      <div v-else class="bars-empty">暂无数据，启动引擎后自动统计</div>
    </div>
  </section>
</template>
