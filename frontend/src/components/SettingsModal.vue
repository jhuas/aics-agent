<script setup>
import { ref, watch } from "vue";
import { ICONS } from "../icons";

const props = defineProps({ visible: Boolean });
const emit = defineEmits(["close", "save"]);

const keyInput = ref("");
const saving = ref(false);

watch(() => props.visible, (v) => {
  if (v) keyInput.value = "";
});

async function save() {
  const key = keyInput.value.trim();
  if (!key || saving.value) return;
  saving.value = true;
  try {
    emit("save", key);
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="modal-mask" :hidden="!visible" @click.self="emit('close')">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <div class="modal-head">
        <h3 id="modalTitle">DeepSeek API 配置</h3>
        <button class="icon-btn" aria-label="关闭" v-html="ICONS.close" @click="emit('close')" />
      </div>
      <p class="modal-desc">密钥仅保存在本地 <code>backend/config.json</code>，不会上传 GitHub。填写后立即生效，无需重启。</p>
      <label class="field-label" for="keyInput">DeepSeek API Key</label>
      <input id="keyInput" v-model="keyInput" type="password" class="text-input" placeholder="sk-…" autocomplete="off"
             @keydown.enter="save" />
      <div class="modal-foot">
        <button class="btn-ghost" @click="emit('close')">取消</button>
        <button class="btn-primary" :disabled="saving" @click="save">保存</button>
      </div>
      <p class="modal-hint">获取密钥：platform.deepseek.com</p>
    </div>
  </div>
</template>
