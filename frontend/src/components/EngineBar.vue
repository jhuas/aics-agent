<script setup>
import { computed } from "vue";
import { ICONS, timeStr } from "../icons";

const props = defineProps({
  running: Boolean,
  startedAt: Number,
  interval: Number,
  dry: Boolean,
  stats: Object,
  busy: Boolean,
});
const emit = defineEmits(["start", "stop", "interval", "dry"]);

const kpis = computed(() => {
  const s = props.stats || {};
  return [
    { label: "巡检轮次", val: s.rounds || 0, cls: "" },
    { label: "自动处理", val: s.handled || 0, cls: "kpi-ok" },
    { label: "转人工", val: s.human || 0, cls: "kpi-warn" },
    { label: "退款拦截", val: s.refund || 0, cls: "kpi-danger" },
  ];
});

const startedText = computed(() =>
  props.startedAt ? timeStr(new Date(props.startedAt)) : "--:--:--"
);
</script>

<template>
  <section class="engine-bar" :class="{ running }">
    <div class="engine-status">
      <div class="engine-dot" :class="{ on: running }"></div>
      <div class="engine-status-text">
        <h3>自动化引擎</h3>
        <p>
          <template v-if="running">
            运行中 · 启动于 {{ startedText }} · 每 {{ interval }} 秒巡检一次
            <span v-if="dry" class="dry-tag">演练模式</span>
          </template>
          <template v-else>未运行 · 点击右侧按钮启动</template>
        </p>
      </div>
    </div>

    <div class="engine-ctrl">
      <label class="ctrl-field">
        <span class="ctrl-label">巡检间隔</span>
        <input class="num-input" type="number" min="5" max="600" step="5"
               :value="interval" :disabled="running"
               @change="emit('interval', parseInt($event.target.value, 10) || 30)" />
        <span class="ctrl-unit">秒</span>
      </label>

      <label class="ctrl-field switch-field">
        <span class="ctrl-label">演练模式</span>
        <button class="switch" :class="{ on: dry }" :disabled="running" role="switch"
                :aria-checked="dry" @click="emit('dry', !dry)">
          <span class="switch-knob"></span>
        </button>
        <span class="ctrl-unit">{{ dry ? "开启" : "关闭" }}</span>
      </label>

      <button v-if="!running" class="btn-engine start" :disabled="busy" @click="emit('start')">
        <span v-html="ICONS.play" /> 启动引擎
      </button>
      <button v-else class="btn-engine stop" :disabled="busy" @click="emit('stop')">
        <span v-html="ICONS.stop" /> 停止引擎
      </button>
    </div>

    <div class="engine-kpis">
      <div v-for="k in kpis" :key="k.label" class="ekpi">
        <span class="ekpi-num" :class="k.cls">{{ k.val }}</span>
        <span class="ekpi-label">{{ k.label }}</span>
      </div>
    </div>
  </section>
</template>
