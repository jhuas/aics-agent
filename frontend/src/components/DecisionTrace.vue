<script setup>
import { computed } from "vue";
import { ICONS, ACTION_TEXT, timeStr } from "../icons";

const props = defineProps({
  event: Object,
});

const chain = computed(() => {
  const e = props.event;
  if (!e) return [];
  const steps = [];
  steps.push({
    icon: "user",
    label: "会话接入",
    status: "pass",
    detail: `会话「${e.session || "—"}」 · ${timeStr(e.time)}`,
  });
  if (e.t === "unknown") {
    steps.push({ icon: "tag", label: "意图识别", status: "block", detail: "无法识别，保持待命" });
  } else if (e.category) {
    steps.push({ icon: "tag", label: "品类 / 意图识别", status: "hit", detail: e.category });
  } else {
    steps.push({ icon: "tag", label: "意图识别", status: "pass", detail: e.reason || "规则命中" });
  }
  if (e.t === "send") {
    steps.push({ icon: "shield", label: "安全护栏", status: "pass", detail: "敏感词与合规检查通过" });
  }
  const act = ACTION_TEXT[e.action] || e.action || (e.t === "human" ? "转人工" : e.t === "unknown" ? "保持待命" : e.t);
  steps.push({
    icon: "chip",
    label: "决策动作",
    status: e.t === "human" ? "warn" : e.t === "unknown" ? "block" : "hit",
    detail: act,
  });
  if (e.t === "send") {
    steps.push({
      icon: "send",
      label: "执行结果",
      status: "hit",
      detail: `${e.dry ? "演练（未真实发送）" : "已真实发送"}${e.result ? ` · ${String(e.result).slice(0, 90)}` : ""}`,
    });
  }
  return steps;
});

const resultText = computed(() => {
  const e = props.event;
  if (!e) return "";
  if (e.refund) return "退款诉求已转人工";
  if (e.reason) return `转人工原因：${e.reason}`;
  if (e.text) return `客户原文：${e.text}`;
  return "";
});
</script>

<template>
  <section class="trace-panel">
    <div class="panel-head">
      <h3>决策链路明细</h3>
      <span class="panel-tag" :class="event && (event.refund || event.t === 'unknown') ? 'hit-sens' : event ? 'hit-llm' : ''">
        {{ event ? (ACTION_TEXT[event.action] || event.action || "已接管") : "待选择" }}
      </span>
    </div>
    <div class="trace-body">
      <div v-if="!event" class="trace-idle">
        <span v-html="ICONS.clock" />
        <p>点击左侧日志中的事件，<br />查看该次接管的决策链路与执行结果</p>
      </div>

      <template v-else>
        <div v-for="(step, i) in chain" :key="i"
             class="trace-step" :class="['st-' + step.status]"
             :style="{ animationDelay: i * 70 + 'ms' }">
          <div class="trace-icon" v-html="ICONS[step.icon]" />
          <div class="trace-info">
            <div class="trace-label">
              <span>{{ step.label }}</span>
              <span class="trace-status">{{ { pass: "放行", hit: "命中", warn: "警示", block: "拦截" }[step.status] }}</span>
            </div>
            <div class="trace-detail">{{ step.detail }}</div>
          </div>
        </div>

        <div v-if="resultText" class="trace-result">
          <span>{{ resultText }}</span>
        </div>
      </template>
    </div>
  </section>
</template>
