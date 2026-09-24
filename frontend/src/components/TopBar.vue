<script setup>
import { ICONS } from "../icons";

defineProps({
  storeName: String,
  running: Boolean,
  checked: Boolean,
  activeTab: String,
});
defineEmits(["open-settings", "tab"]);
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="brand-logo" v-html="ICONS.robot" />
      <div class="brand-text">
        <h1>智客服驾驶舱</h1>
        <p>AI 电商客服 Agent 平台</p>
      </div>
    </div>
    <nav class="nav-tabs">
      <button class="nav-tab" :class="{ on: activeTab === 'cockpit' }" @click="$emit('tab', 'cockpit')">
        <span class="tab-ico" v-html="ICONS.terminal"></span>
        自动化驾驶舱
      </button>
      <button class="nav-tab nav-tab-ops" :class="{ on: activeTab === 'ops' }" @click="$emit('tab', 'ops')">
        <span class="tab-ico" v-html="ICONS.activity"></span>
        运营中心
        <span class="tab-badge">商单数据</span>
      </button>
      <button class="nav-tab nav-tab-ops" :class="{ on: activeTab === 'memory' }" @click="$emit('tab', 'memory')">
        <span class="tab-ico" v-html="ICONS.book"></span>
        记忆库
        <span class="tab-badge">问答复用</span>
      </button>
    </nav>
    <div class="topbar-right">
      <div class="store-name">{{ storeName }}</div>
      <div class="status-chip" :class="checked ? (running ? 'on' : 'off') : ''">
        <span class="dot"></span>
        <span class="status-text">{{ !checked ? "连接中" : running ? "自动化引擎运行中" : "自动化引擎已停止" }}</span>
      </div>
      <button class="icon-btn" title="API 配置" aria-label="API 配置" @click="$emit('open-settings')" v-html="ICONS.gear" />
    </div>
  </header>
</template>
