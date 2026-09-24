<script setup>
import { computed } from "vue";
import { ICONS, timeStr } from "../icons";

const props = defineProps({
  events: Array,
});
const emit = defineEmits(["select"]);

const takeovers = computed(() => {
  const list = [];
  for (let i = props.events.length - 1; i >= 0; i--) {
    const e = props.events[i];
    if (e.t === "human" || (e.t === "unknown")) list.push(e);
    if (list.length >= 50) break;
  }
  return list;
});
</script>

<template>
  <section class="takeover-panel">
    <div class="panel-head">
      <h3>人工接管记录</h3>
      <span class="panel-tag">{{ takeovers.length }} 次</span>
    </div>
    <div class="takeover-list">
      <div v-if="!takeovers.length" class="takeover-idle">
        <span v-html="ICONS.user" />
        <p>暂无接管记录<br /><span class="idle-sub">退款诉求与无法识别的会话会在此提示人工介入</span></p>
      </div>

      <button v-for="(e, i) in takeovers" :key="i" class="takeover-item" :class="{ refund: e.refund }"
              @click="emit('select', e)">
        <span class="takeover-icon" v-html="ICONS[e.refund ? 'alert' : e.t === 'unknown' ? 'alertTriangle' : 'user']" />
        <div class="takeover-body">
          <div class="takeover-title">
            <span class="takeover-tag" :class="e.refund ? 'tag-refund' : e.t === 'unknown' ? 'tag-unknown' : 'tag-human'">
              {{ e.refund ? "退款" : e.t === "unknown" ? "未识别" : "转人工" }}
            </span>
            <span class="takeover-session" v-if="e.session">会话「{{ e.session }}」</span>
            <span class="takeover-time">{{ timeStr(e.time) }}</span>
          </div>
          <div class="takeover-reason" v-if="e.reason">{{ e.reason }}</div>
          <div class="takeover-reason" v-else-if="e.t === 'unknown'">客户提问超出知识库与大模型识别范围</div>
        </div>
      </button>
    </div>
  </section>
</template>
