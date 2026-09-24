/* ═══════════════════════════════════════════════
   智客服 · AI 电商客服 Agent 平台
   前端交互：对话演示 + 决策追踪 + 统计
   ═══════════════════════════════════════════════ */
(() => {
  "use strict";

  const $ = (sel) => document.querySelector(sel);
  const API = {
    chat: "/api/chat",
    config: "/api/config",
    setKey: "/api/config/key",
    stats: "/api/stats",
    clear: "/api/sessions/clear",
  };

  const sessionId = localStorage.getItem("zc_session") || ("demo-" + Math.random().toString(36).slice(2, 8));
  localStorage.setItem("zc_session", sessionId);

  /* ── 渠道展示配置 ── */
  const CHANNEL_META = {
    kb:        { label: "知识库",   cls: "ch-kb" },
    llm:       { label: "大模型",   cls: "ch-llm" },
    guardrail: { label: "规则护栏", cls: "ch-guardrail" },
    fallback:  { label: "兜底",     cls: "ch-fallback" },
    sensitive: { label: "合规拦截", cls: "ch-sensitive" },
    ack:       { label: "已了解",   cls: "ch-ack" },
  };

  const STAGE_META = {
    guardrail: { label: "规则护栏", en: "SAFETY GUARDRAIL", icon: "shield" },
    category:  { label: "品类识别", en: "CATEGORY ROUTING", icon: "tag" },
    kb:        { label: "知识库匹配", en: "KNOWLEDGE BASE", icon: "book" },
    llm:       { label: "大模型生成", en: "LARGE MODEL", icon: "chip" },
    sensitive: { label: "敏感词合规", en: "COMPLIANCE FILTER", icon: "filter" },
  };

  const STATUS_TEXT = { pass: "放行", hit: "命中", block: "拦截", warn: "警示", skip: "跳过" };

  const ICONS = {
    shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l7 3v5c0 4.5-3 8.4-7 10-4-1.6-7-5.5-7-10V6l7-3z"/></svg>',
    tag:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.5"/></svg>',
    book:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z"/><path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5"/></svg>',
    chip:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/></svg>',
    filter: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h18l-7 8v6l-4 2v-8L3 5z"/></svg>',
    video:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="14" height="12" rx="2"/><path d="M16 10l6-3v10l-6-3"/></svg>',
    image:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5-9 9"/></svg>',
    alert:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
    check:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    refresh:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 21v-5h5"/></svg>',
  };

  const els = {
    stream: $("#chatStream"),
    input: $("#chatInput"),
    btnSend: $("#btnSend"),
    quick: $("#quickChips"),
    storeName: $("#storeName"),
    llmStatus: $("#llmStatus"),
    statusText: $("#llmStatus .status-text"),
    traceBody: $("#traceBody"),
    traceTag: $("#traceResultTag"),
    kpiSessions: $("#kpiSessions"),
    kpiMessages: $("#kpiMessages"),
    kpiEscalated: $("#kpiEscalated"),
    channelBars: $("#channelBars"),
    actionBars: $("#actionBars"),
    modal: $("#settingsModal"),
    keyInput: $("#keyInput"),
    btnSaveKey: $("#btnSaveKey"),
    btnSettings: $("#btnSettings"),
    btnClear: $("#btnClear"),
    toast: $("#toast"),
  };

  /* ── 工具 ── */
  function toast(msg, kind) {
    els.toast.textContent = msg;
    els.toast.className = "toast" + (kind ? " " + kind : "");
    els.toast.hidden = false;
    clearTimeout(toast._t);
    toast._t = setTimeout(() => { els.toast.hidden = true; }, 2600);
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function fileName(path) {
    return String(path || "").split(/[\\/]/).pop() || path;
  }

  async function api(url, opts) {
    const resp = await fetch(url, opts);
    return resp.json();
  }

  /* ── 消息渲染 ── */
  function renderMedia(media) {
    if (!media || !media.length) return "";
    const cards = media.map((m) => {
      const type = m.type === "video" ? "video" : "image";
      const name = fileName(m.path);
      return `<span class="media-card" title="${esc(m.path)}">${ICONS[type]}<span class="media-type ${type}">${type === "video" ? "视频" : "图片"}</span><span class="media-name">${esc(name)}</span></span>`;
    });
    return `<div class="media-list">${cards.join("")}</div>`;
  }

  function renderUser(text) {
    const el = document.createElement("div");
    el.className = "msg user";
    el.innerHTML = `
      <div class="msg-avatar">客</div>
      <div class="msg-body">
        <div class="msg-meta"><span>${new Date().toLocaleTimeString("zh-CN", { hour12: false })}</span></div>
        <div class="msg-bubble">${esc(text)}</div>
      </div>`;
    els.stream.appendChild(el);
  }

  function renderBot(result) {
    const meta = CHANNEL_META[result.channel] || { label: result.channel, cls: "" };
    const el = document.createElement("div");
    el.className = "msg bot";
    const tagHtml = `<span class="channel-tag ${meta.cls}">${ICONS[result.channel === "guardrail" ? "shield" : result.channel === "sensitive" ? "alert" : result.channel === "llm" ? "chip" : result.channel === "kb" ? "book" : "refresh"]}${meta.label}</span>`;
    el.innerHTML = `
      <div class="msg-avatar">AI</div>
      <div class="msg-body">
        <div class="msg-meta">${tagHtml}<span>${new Date().toLocaleTimeString("zh-CN", { hour12: false })}</span></div>
        <div class="msg-bubble">${esc(result.reply || "")}</div>
        ${renderMedia(result.media)}
      </div>`;
    els.stream.appendChild(el);
  }

  function renderSystemNote(result) {
    const isAck = result.action === "ack";
    const el = document.createElement("div");
    el.className = "sys-note" + (isAck ? " ack" : "");
    el.innerHTML = `${ICONS[isAck ? "check" : "alert"]}<span>${esc(result.reason || "")}</span>`;
    els.stream.appendChild(el);
  }

  /* ── 决策追踪渲染 ── */
  function traceClass(step, index) {
    const base = "trace-step st-" + step.status + " " + (step.stage || "");
    return base;
  }

  function renderTrace(result) {
    const trace = result.trace || [];
    const tagCls = {
      kb: "hit-kb", llm: "hit-llm", guardrail: "hit-guard", fallback: "hit-fallback", sensitive: "hit-sens",
    }[result.channel] || "";
    els.traceTag.className = "panel-tag " + tagCls;
    els.traceTag.textContent = (CHANNEL_META[result.channel] || { label: result.channel }).label;

    if (!trace.length) {
      els.traceBody.innerHTML = `<div class="trace-idle">${ICONS.filter}<p>该响应未生成决策链路</p></div>`;
      return;
    }

    const steps = trace.map((step, i) => {
      const meta = STAGE_META[step.stage] || { label: step.stage, en: "", icon: "shield" };
      return `
        <div class="${traceClass(step, i)}" style="animation-delay:${i * 70}ms">
          <div class="trace-icon">${ICONS[meta.icon]}</div>
          <div class="trace-info">
            <div class="trace-label"><span>${meta.label}</span>${meta.en ? `<span class="trace-en">${meta.en}</span>` : ""}<span class="trace-status">${STATUS_TEXT[step.status] || step.status}</span></div>
            <div class="trace-detail">${esc(step.detail || "")}</div>
          </div>
        </div>`;
    }).join("");

    const resultHtml = `
      <div class="trace-result" style="animation-delay:${trace.length * 70}ms">
        <span>响应动作：<b>${esc(String(result.action).toUpperCase())}</b>${result.escalate ? " · 转人工" : ""}</span>
        ${result.rule ? `<span>命中规则：<b class="tr-monkey">${esc(result.rule)}</b></span>` : ""}
        ${result.replaced && result.replaced.length ? `<span>合规替换：${esc(result.replaced.slice(0, 5).join("、"))}</span>` : ""}
        ${result.llm_error ? `<span style="color:var(--c-guard)">${esc(result.llm_error)}</span>` : ""}
      </div>`;

    els.traceBody.innerHTML = steps + resultHtml;
  }

  /* ── 统计渲染 ── */
  function countUp(el, target, duration = 650) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      el.textContent = target;
      el.dataset.v = target;
      return;
    }
    const start = performance.now();
    const from = parseInt(el.dataset.v || "0", 10) || 0;
    function tick(now) {
      const p = Math.min((now - start) / duration, 1);
      const ease = 1 - Math.pow(1 - p, 3);
      const v = Math.round(from + (target - from) * ease);
      el.textContent = v;
      el.dataset.v = v;
      if (p < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }

  function renderBars(container, data, colorMap) {
    const entries = Object.entries(data || {});
    if (!entries.length) {
      container.innerHTML = `<div class="bars-empty">暂无数据，发送消息后自动统计</div>`;
      return;
    }
    const max = Math.max(...entries.map(([, v]) => v), 1);
    container.innerHTML = entries.map(([k, v]) => {
      const cls = colorMap[k] || "";
      const pct = Math.max((v / max) * 100, 3);
      return `
        <div class="bar-row">
          <span class="bar-name">${esc(k)}</span>
          <div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div>
          <span class="bar-val">${v}</span>
        </div>`;
    }).join("");
  }

  async function refreshStats() {
    try {
      const s = await api(API.stats);
      countUp(els.kpiSessions, s.total_sessions || 0);
      countUp(els.kpiMessages, s.total_messages || 0);
      countUp(els.kpiEscalated, (s.actions || {}).silent || 0);
      renderBars(els.channelBars, s.channels, {
        kb: "ch-kb", llm: "ch-llm", guardrail: "ch-guardrail", fallback: "ch-fallback", sensitive: "ch-sensitive",
      });
      renderBars(els.actionBars, s.actions, { reply: "ch-llm", silent: "ch-sensitive", ack: "ch-guardrail" });
    } catch (e) { /* 静默失败，下次刷新重试 */ }
  }

  /* ── 发送消息 ── */
  let sending = false;

  async function send(text) {
    text = String(text || "").trim();
    if (!text || sending) return;
    sending = true;
    els.btnSend.disabled = true;

    renderUser(text);
    els.input.value = "";
    scrollBottom();

    // 思考中指示
    const typing = document.createElement("div");
    typing.className = "msg bot";
    typing.innerHTML = `<div class="msg-avatar">AI</div><div class="msg-body"><div class="typing"><span></span><span></span><span></span></div></div>`;
    els.stream.appendChild(typing);
    scrollBottom();

    try {
      const result = await api(API.chat, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, text }),
      });
      typing.remove();
      if (result.error) {
        toast(result.error, "err");
        return;
      }
      if (result.action === "reply" && result.reply) renderBot(result);
      else renderSystemNote(result);
      scrollBottom();
      renderTrace(result);
      refreshStats();
    } catch (e) {
      typing.remove();
      toast("服务未启动或网络异常：" + e.message, "err");
    } finally {
      sending = false;
      els.btnSend.disabled = false;
      els.input.focus();
    }
  }

  function scrollBottom() {
    els.stream.scrollTop = els.stream.scrollHeight;
  }

  /* ── 初始化 ── */
  async function init() {
    try {
      const cfg = await api(API.config);
      if (cfg.store_name) els.storeName.textContent = cfg.store_name;
      if (cfg.llm_ready) {
        els.llmStatus.classList.add("on");
        els.statusText.textContent = "大模型在线";
      } else {
        els.llmStatus.classList.add("off");
        els.statusText.textContent = "未配置 API Key";
      }
    } catch (e) {
      els.llmStatus.classList.add("off");
      els.statusText.textContent = "服务未连接";
    }
    refreshStats();
  }

  /* ── 事件绑定 ── */
  els.btnSend.addEventListener("click", () => send(els.input.value));
  els.input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") send(els.input.value);
  });
  els.quick.addEventListener("click", (e) => {
    const chip = e.target.closest(".chip");
    if (chip) send(chip.dataset.text);
  });

  els.btnSettings.addEventListener("click", () => { els.modal.hidden = false; els.keyInput.focus(); });
  els.modal.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]") || e.target === els.modal) els.modal.hidden = true;
  });

  els.btnSaveKey.addEventListener("click", async () => {
    const key = els.keyInput.value.trim();
    if (!key) { toast("请输入 API Key", "err"); return; }
    try {
      const r = await api(API.setKey, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ deepseek_api_key: key }),
      });
      if (r.ok) {
        toast("API Key 已保存，立即生效", "ok");
        els.modal.hidden = true;
        els.keyInput.value = "";
        els.llmStatus.classList.add("on");
        els.llmStatus.classList.remove("off");
        els.statusText.textContent = "大模型在线";
      }
    } catch (e) {
      toast("保存失败：" + e.message, "err");
    }
  });

  els.btnClear.addEventListener("click", async () => {
    await api(API.clear, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sessionId }) });
    els.stream.innerHTML = "";
    els.traceBody.innerHTML = `<div class="trace-idle">${ICONS.filter}<p>会话已清空，发送一条消息重新开始</p></div>`;
    els.traceTag.className = "panel-tag";
    els.traceTag.textContent = "待命";
    refreshStats();
    els.input.focus();
  });

  init();
})();
