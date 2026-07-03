const API = "";
const t = (key, vars) => window.FlowI18n.t(key, vars);

const NODE_IDS = ["productInfo", "productAssets", "benchmark", "brief", "script", "storyboard", "render", "qa"];
const OUTPUT_NODES = new Set(["render", "qa"]);
const NODE_WIDTH = 200;
const LINK_SNAP_RADIUS = 44;

const COPILOT_STATE = {
  PLANNING: "planning",
  READY: "ready",
  THINKING: "thinking",
  BUILDING: "building",
  ERROR: "error",
};

const THINKING_MIN_MS = 700;

const state = {
  appMeta: null,
  purchaseUrl: "",
  batchId: "",
  activeScriptId: "",
  scripts: [],
  prompts: [],
  videos: [],
  polling: null,
  selectedNode: "productInfo",
  workflow: {
    input: {
      brief: "",
      sourceUrl: "",
      referenceVideoUrl: "",
      materialContext: "",
      product: "",
      direction: "",
      language: "英语",
      count: 1,
      ratio: "9:16",
    },
  },
  canvas: {
    layout: {
      productInfo: { x: 40, y: 40 },
      productAssets: { x: 40, y: 200 },
      benchmark: { x: 40, y: 360 },
      brief: { x: 320, y: 120 },
      script: { x: 600, y: 40 },
      storyboard: { x: 600, y: 220 },
      render: { x: 880, y: 120 },
      qa: { x: 1140, y: 120 },
    },
    edges: [
      { from: "productInfo", to: "brief" },
      { from: "productAssets", to: "brief" },
      { from: "benchmark", to: "brief" },
      { from: "brief", to: "script" },
      { from: "script", to: "storyboard" },
      { from: "storyboard", to: "render" },
      { from: "render", to: "qa" },
    ],
    size: { w: 1460, h: 760 },
    zoom: 1,
    view: { x: 0, y: 0 },
    dirtyNodes: new Set(),
    dirtyReasons: {},
    linkDraft: { from: "", x: 0, y: 0, snapTo: "", active: false, pointerId: null },
    draggingNode: "",
    dragMoved: false,
    boardBound: false,
  },
  compare: {
    leftScriptId: "",
    rightScriptId: "",
    onlyDiff: false,
  },
  ui: {
    inspectorOpen: false,
    copilotOpen: true,
    showGrid: true,
    panMode: false,
    copilotState: COPILOT_STATE.PLANNING,
    thinkingAborted: false,
    thinkingTimer: null,
    pendingAttachments: [],
  },
  intakeFormats: null,
  chat: [],
};

const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

function esc(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(API + path, {
    method: opts.method || "GET",
    credentials: "include",
    headers,
    body: opts.body,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(formatApiError(data, `HTTP ${res.status}`));
    err.status = res.status;
    err.payload = data;
    throw err;
  }
  return data;
}

function formatApiError(data, fallback = "") {
  const detail = data?.detail ?? data?.message;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object") return item.msg || item.message || JSON.stringify(item);
        return String(item);
      })
      .filter(Boolean)
      .join("；");
  }
  return fallback || "请求失败";
}

function showError(msg) {
  const el = $("#error-box");
  if (!msg) {
    el.classList.add("hidden");
    el.textContent = "";
    return;
  }
  el.textContent = msg;
  el.classList.remove("hidden");
}

function updateEstimate(text) {
  const el = $("#estimate");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("hidden", !text);
}

function isWorkflowRunning() {
  if (!state.batchId) return false;
  return ["script", "storyboard", "render", "qa"].some((id) => nodeStatusFromData(id) === "running");
}

function isWorkflowSettled() {
  if (!state.batchId) return false;
  const qaStatus = nodeStatusFromData("qa");
  return qaStatus === "done" || qaStatus === "fail";
}

function isCanvasPaused() {
  return state.ui.copilotState === COPILOT_STATE.BUILDING;
}

function copilotStateKey(name) {
  return `copilotState${name.charAt(0).toUpperCase()}${name.slice(1)}`;
}

function deriveCopilotState() {
  if (state.ui.copilotState === COPILOT_STATE.THINKING) return COPILOT_STATE.THINKING;
  if (state.ui.copilotState === COPILOT_STATE.ERROR) return COPILOT_STATE.ERROR;
  if (isWorkflowRunning() || state.ui.copilotState === COPILOT_STATE.BUILDING) return COPILOT_STATE.BUILDING;
  if (!state.chat.length) return COPILOT_STATE.PLANNING;
  return COPILOT_STATE.READY;
}

function setCopilotState(next, { force = false } = {}) {
  if (!force && state.ui.copilotState === COPILOT_STATE.THINKING && next !== COPILOT_STATE.THINKING) {
    if (next !== COPILOT_STATE.BUILDING && next !== COPILOT_STATE.ERROR) return;
  }
  state.ui.copilotState = next;
  applyCopilotState();
}

function syncCopilotState() {
  if (state.ui.copilotState === COPILOT_STATE.THINKING || state.ui.copilotState === COPILOT_STATE.ERROR) return;
  state.ui.copilotState = deriveCopilotState();
  applyCopilotState();
}

function applyCopilotState() {
  const s = state.ui.copilotState;
  const badge = $("#copilot-status");
  const panel = $("#chat-float");
  const input = $("#chat-input");
  const sendBtn = $("#chat-send");
  const stopBtn = $("#chat-stop");
  const templates = $("#template-strip");
  const pill = $("#ai-status-pill");
  const runBtn = $("#run-workflow-btn");
  const board = $("#canvas-board");

  if (badge) {
    badge.textContent = t(copilotStateKey(s));
    badge.className = `creatify-copilot-badge state-${s}`;
  }
  panel?.setAttribute("data-copilot-state", s);

  const inputLocked = s === COPILOT_STATE.THINKING || s === COPILOT_STATE.BUILDING;
  if (input) {
    input.disabled = inputLocked;
    input.placeholder = s === COPILOT_STATE.THINKING ? t("copilotThinking") : t("chatPlaceholder");
  }
  templates?.classList.toggle("hidden", inputLocked);
  sendBtn?.classList.toggle("hidden", s === COPILOT_STATE.THINKING);
  stopBtn?.classList.toggle("hidden", s !== COPILOT_STATE.THINKING);

  pill?.classList.toggle("hidden", s !== COPILOT_STATE.BUILDING);
  if (runBtn) runBtn.disabled = inputLocked;
  $("#dock-run")?.toggleAttribute("disabled", inputLocked);
  board?.classList.toggle("canvas-paused", s === COPILOT_STATE.BUILDING);
}

function updateAiStatus() {
  syncCopilotState();
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.clearTimeout(state.ui.thinkingTimer);
    state.ui.thinkingTimer = window.setTimeout(resolve, ms);
  });
}

function openPurchase() {
  if (state.purchaseUrl) window.open(state.purchaseUrl, "_blank", "noopener,noreferrer");
}

function setCopilotOpen(open) {
  state.ui.copilotOpen = open;
  const panel = $("#chat-float");
  panel?.classList.toggle("collapsed", !open);
  $(".creatify-app")?.classList.toggle("copilot-collapsed", !open);
  $("#copilot-toggle")?.classList.toggle("active", open);
}

function toggleCopilot() {
  setCopilotOpen(!state.ui.copilotOpen);
}

function openInspector(nodeId = "") {
  if (nodeId) state.selectedNode = nodeId;
  state.ui.inspectorOpen = true;
  $("#inspector-float")?.classList.remove("hidden");
  renderCanvas();
  renderInspector();
  renderPreview();
  renderBranchCompare();
}

function closeInspector() {
  state.ui.inspectorOpen = false;
  $("#inspector-float")?.classList.add("hidden");
}

function clampZoom(v) {
  return Math.min(1.6, Math.max(0.6, v));
}

function applyCanvasZoom() {
  applyCanvasViewport();
}

function applyCanvasViewport() {
  const stage = $("#canvas-stage");
  const pan = $("#canvas-pan");
  const z = clampZoom(state.canvas.zoom);
  state.canvas.zoom = z;
  const { x, y } = state.canvas.view;
  if (pan) {
    pan.style.transform = `translate(${x}px, ${y}px)`;
    pan.style.width = `${state.canvas.size.w * z}px`;
    pan.style.height = `${state.canvas.size.h * z}px`;
  }
  if (stage) {
    stage.style.zoom = String(z);
    stage.style.width = `${state.canvas.size.w}px`;
    stage.style.height = `${state.canvas.size.h}px`;
  }
  const label = $("#zoom-label");
  if (label) label.textContent = `${Math.round(z * 100)}%`;
}

function centerCanvasView() {
  const board = $("#canvas-board");
  if (!board) return;
  const z = state.canvas.zoom;
  state.canvas.view.x = (board.clientWidth - state.canvas.size.w * z) / 2;
  state.canvas.view.y = (board.clientHeight - state.canvas.size.h * z) / 2;
}

function zoomAtPoint(clientX, clientY, targetZoom) {
  const board = $("#canvas-board");
  if (!board) return;
  const prevZoom = state.canvas.zoom || 1;
  const nextZoom = clampZoom(targetZoom);
  if (Math.abs(nextZoom - prevZoom) < 0.0001) return;
  const rect = board.getBoundingClientRect();
  const stageX = (clientX - rect.left - state.canvas.view.x) / prevZoom;
  const stageY = (clientY - rect.top - state.canvas.view.y) / prevZoom;
  state.canvas.zoom = nextZoom;
  state.canvas.view.x = clientX - rect.left - stageX * nextZoom;
  state.canvas.view.y = clientY - rect.top - stageY * nextZoom;
  applyCanvasViewport();
  renderCanvasLinks();
}

function boardPointerToStage(clientX, clientY) {
  const board = $("#canvas-board");
  if (!board) return { x: 0, y: 0 };
  const zoom = state.canvas.zoom || 1;
  const rect = board.getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.canvas.view.x) / zoom,
    y: (clientY - rect.top - state.canvas.view.y) / zoom,
  };
}

function applyLegacyFallbackCompat() {
  const langSel = $("#language");
  if (langSel) {
    const keep = langSel.value || "英语";
    langSel.innerHTML = `
      <option value="英语">English</option>
      <option value="西语">Español</option>
    `;
    if (keep === "西语") langSel.value = "西语";
  }

  const countSel = $("#count");
  if (countSel) {
    const keep = String(countSel.value || "1");
    countSel.innerHTML = `
      <option value="1">${t("count1")}</option>
      <option value="2">${t("count2")}</option>
      <option value="3">${t("count3")}</option>
    `;
    countSel.value = keep === "2" || keep === "3" ? keep : "1";
  }

  const ratioSel = $("#ratio");
  if (ratioSel) {
    ratioSel.innerHTML = `<option value="9:16">${t("ratio916")}</option>`;
    ratioSel.value = "9:16";
    ratioSel.disabled = true;
    ratioSel.title = t("legacyRatioLocked");
  }

  const guestHint = $("#guest-hint");
  if (guestHint) {
    guestHint.style.color = "var(--wf-muted, #9d9dab)";
    guestHint.style.marginTop = "8px";
    guestHint.style.fontSize = "12px";
  }
}

function showAuthLoading(text) {
  $("#auth-loading-text").textContent = text || t("authConnecting");
  $("#auth-loading").classList.remove("hidden");
}

function hideAuthLoading() {
  $("#auth-loading").classList.add("hidden");
}

function updateUserHeader() {
  const authOn = !!state.appMeta?.auth_enabled;
  const user = state.appMeta?.current_user;
  const guest = authOn && !user;
  $("#login-btn").classList.toggle("hidden", !guest);
  $("#user-label").classList.toggle("hidden", guest || !user);
  $("#coin-badge").classList.toggle("hidden", guest || !user || typeof user?.coin === "undefined");
  $("#buy-btn").classList.toggle("hidden", guest || !user || !state.purchaseUrl);
  $("#guest-hint").classList.toggle("hidden", !guest);
  if (guest || !user) {
    $("#user-label").textContent = "";
    return;
  }
  $("#user-label").textContent = user.display_name || user.email || user.id || "";
  if (typeof user.coin !== "undefined") $("#coin-value").textContent = Number(user.coin || 0).toFixed(2);
}

async function refreshMeta() {
  state.appMeta = await api("/api/meta");
  updateUserHeader();
}

async function ensureAuthenticated() {
  if (!state.appMeta?.auth_enabled) return true;
  if (state.appMeta?.current_user) return true;
  const sso = state.appMeta?.sso;
  if (state.appMeta?.auth_mode === "platform" && sso?.enabled) {
    showAuthLoading(t("authChecking"));
    try {
      await window.VidauSsoHelper.tryExistingSession(sso).catch(() => null);
      await refreshMeta();
      if (state.appMeta.current_user) return true;
      showAuthLoading(t("authPopup"));
      await window.VidauSsoHelper.promptLogin(sso);
      await refreshMeta();
      return !!state.appMeta.current_user;
    } catch (err) {
      if (err?.message && !/cancel|closed|abort/i.test(err.message)) showError(err.message);
      return false;
    } finally {
      hideAuthLoading();
    }
  }
  location.href = `/login?next=${encodeURIComponent("/")}`;
  return false;
}

function parseMentions(text) {
  let brief = text;
  let product = "";
  let direction = "";
  for (const p of state.appMeta?.products || []) {
    const token = `@${p.name}`;
    if (brief.includes(token)) {
      product = p.name;
      brief = brief.replaceAll(token, p.name);
    }
  }
  for (const d of state.appMeta?.directions || []) {
    const token = `@${d.name}`;
    if (brief.includes(token)) {
      direction = d.name;
      brief = brief.replaceAll(token, d.name);
    }
  }
  return { brief: brief.trim(), product, direction };
}

function isGreetingOrSmallTalk(text) {
  const s = text.trim();
  if (!s) return true;
  if (
    /^(你好|您好|hi|hello|hey|哈喽|在吗|在不在|谢谢|感谢|thanks|thx|ok|okay|好的|嗯|哦|啊|嗨|morning|晚上好|早上好|下午好)[\s!！。.?？~,，、]*$/i.test(
      s
    )
  ) {
    return true;
  }
  return s.length <= 3 && !/@/.test(s);
}

function looksLikeAdIntent(text) {
  if (isGreetingOrSmallTalk(text)) return false;
  const s = text.trim();
  if (s.length >= 18) return true;
  if (/@/.test(s)) return true;
  return /广告|视频|ugc|tiktok|reels|口播|竖屏|9:16|钩子|hook|cta|卖点|测评|开箱|种草|带货|秒|15|30|45|60|露营|户外|电源|储能|充电宝|应急|停电|受众|人群|风格|画幅|转化|推广|宣传|讲解|演示|pdf|对标|爆款|参考片|参考视频/i.test(
    s
  );
}

const VIDEO_URL_RE =
  /https?:\/\/(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|youtube\.com|youtu\.be|instagram\.com|douyin\.com|v\.douyin\.com|bilibili\.com|facebook\.com|fb\.watch)[^\s\])"']+/i;

function extractVideoUrlFromText(text) {
  const m = (text || "").match(VIDEO_URL_RE);
  return m ? m[0].replace(/[.,;)]+$/, "") : "";
}

function extractProductUrlFromText(text) {
  const urls = (text || "").match(/https?:\/\/[^\s\])"']+/gi) || [];
  for (const raw of urls) {
    const url = raw.replace(/[.,;)]+$/, "");
    if (VIDEO_URL_RE.test(url)) continue;
    return url;
  }
  return "";
}

function hasPendingAttachments() {
  return (state.ui.pendingAttachments || []).length > 0;
}

function maxIntakeFiles() {
  return state.intakeFormats?.max_files || 8;
}

function intakeAcceptAttr() {
  return (
    state.intakeFormats?.accept ||
    ".pdf,.docx,.csv,.xlsx,.mp4,.webm,.mov,.m4v,.jpg,.jpeg,.png,.webp,.heic,.heif,.txt,.md"
  );
}

function attachmentLabel(file) {
  const ext = (file.name.split(".").pop() || "").toLowerCase();
  const fallbacks = {
    pdf: "PDF",
    docx: "Word",
    csv: "CSV",
    xlsx: "Excel",
    mp4: "视频",
    webm: "视频",
    mov: "视频",
    m4v: "视频",
    jpg: "图片",
    jpeg: "图片",
    png: "图片",
    webp: "图片",
    heic: "图片",
    heif: "图片",
    txt: "文本",
    md: "文本",
  };
  const key = {
    pdf: "attachPdf",
    docx: "attachDocx",
    csv: "attachCsv",
    xlsx: "attachXlsx",
    mp4: "attachVideo",
    webm: "attachVideo",
    mov: "attachVideo",
    m4v: "attachVideo",
    jpg: "attachImage",
    jpeg: "attachImage",
    png: "attachImage",
    webp: "attachImage",
    heic: "attachImage",
    heif: "attachImage",
    txt: "attachText",
    md: "attachText",
  }[ext];
  if (key) {
    const label = t(key);
    if (label !== key) return label;
  }
  return fallbacks[ext] || ext.toUpperCase() || "文件";
}

function renderAttachmentChips() {
  const box = $("#attachment-chips");
  if (!box) return;
  const files = state.ui.pendingAttachments || [];
  if (!files.length) {
    box.innerHTML = "";
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = files
    .map(
      (file, i) =>
        `<span class="attach-chip" data-idx="${i}">${esc(attachmentLabel(file))}: ${esc(file.name)}<button type="button" data-remove-idx="${i}" aria-label="remove">×</button></span>`
    )
    .join("");
  box.querySelectorAll("[data-remove-idx]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idx = Number(btn.getAttribute("data-remove-idx"));
      state.ui.pendingAttachments = (state.ui.pendingAttachments || []).filter((_, j) => j !== idx);
      renderAttachmentChips();
    });
  });
}

function addPendingFiles(fileList) {
  const max = maxIntakeFiles();
  const next = [...(state.ui.pendingAttachments || [])];
  for (const file of fileList) {
    if (next.length >= max) {
      showError(t("attachTooMany", { max }));
      break;
    }
    if (next.some((f) => f.name === file.name && f.size === file.size)) continue;
    next.push(file);
  }
  state.ui.pendingAttachments = next;
  renderAttachmentChips();
}

function isFileDragEvent(e) {
  const types = Array.from(e?.dataTransfer?.types || []);
  return types.includes("Files");
}

function syncDropzoneHint() {
  const box = $("#chat-form .creatify-composer-box");
  if (!box) return;
  box.setAttribute("data-drop-text", t("dropFilesHere"));
}

function clearPendingAttachments() {
  state.ui.pendingAttachments = [];
  const input = $("#attach-materials-input");
  if (input) input.value = "";
  renderAttachmentChips();
}

async function analyzeIntakeMaterials({ userNote = "", referenceVideoUrl = "", productPageUrl = "" } = {}) {
  const buildFormData = () => {
    const fd = new FormData();
    for (const file of state.ui.pendingAttachments || []) {
      fd.append("files", file);
    }
    if (referenceVideoUrl) fd.append("reference_video_url", referenceVideoUrl);
    if (productPageUrl) fd.append("product_page_url", productPageUrl);
    if (userNote) fd.append("user_note", userNote);
    if (state.workflow.input.product) fd.append("product_hint", state.workflow.input.product);
    return fd;
  };

  try {
    return await api("/api/toc/intake/analyze", { method: "POST", body: buildFormData() });
  } catch (err) {
    // SSO 会话偶发过期时，先重鉴权再自动重试一次，避免用户误以为上传失败。
    if (err?.status === 401) {
      await refreshMeta().catch(() => {});
      const ok = await ensureAuthenticated();
      if (ok) {
        return await api("/api/toc/intake/analyze", { method: "POST", body: buildFormData() });
      }
    }
    throw err;
  }
}

function applyIntakeResult(result) {
  let changed = false;
  const inp = state.workflow.input;
  if (result.product_name && !inp.product) {
    inp.product = result.product_name;
    changed = true;
  }
  if (result.suggested_direction && !inp.direction) {
    inp.direction = result.suggested_direction;
    changed = true;
  }
  if (result.material_context) {
    const merged = mergeInputBrief(inp.materialContext, result.material_context);
    if (merged !== inp.materialContext) {
      inp.materialContext = merged;
      changed = true;
    }
  }
  if (result.suggested_brief) {
    const mergedBrief = mergeInputBrief(inp.brief, result.suggested_brief);
    if (mergedBrief !== inp.brief) {
      inp.brief = mergedBrief;
      changed = true;
    }
  }
  const src = result.sources || {};
  if (src.reference_video_url && !inp.referenceVideoUrl) {
    inp.referenceVideoUrl = src.reference_video_url;
    changed = true;
  }
  if (src.product_page_url && !inp.sourceUrl) {
    inp.sourceUrl = src.product_page_url;
    changed = true;
  }
  if (changed) markDirtyFrom("brief", "Brief.materials");
  return changed;
}

function mergeInputBrief(existing, addition) {
  const next = (addition || "").trim();
  const prev = (existing || "").trim();
  if (!next) return prev;
  if (!prev) return next;
  if (prev === next || prev.includes(next)) return prev;
  if (next.includes(prev)) return next;
  return `${prev}\n${next}`;
}

function intakeStatus() {
  const inp = state.workflow.input;
  const missing = [];
  if (!inp.brief || inp.brief.length < 12) missing.push("brief");
  const brief = inp.brief || "";
  if (brief.length >= 12 && !/\d+\s*秒|15s|30s|\d+s\b/i.test(brief)) missing.push("duration");
  if (brief.length >= 12 && !/场景|受众|人群|tiktok|露营|户外|居家|通勤|应急|家庭|投放/i.test(brief) && !inp.direction) {
    missing.push("scenario");
  }
  return { missing, ready: missing.length === 0 };
}

function knownProductByName(name) {
  const raw = (name || "").trim();
  if (!raw) return null;
  const products = state.appMeta?.products || [];
  return (
    products.find((p) => (p.name || "").trim() === raw) ||
    products.find((p) => (p.name || "").trim().toLowerCase() === raw.toLowerCase()) ||
    null
  );
}

function buildInputValidation() {
  const inp = state.workflow.input;
  if (!inp.brief || inp.brief.trim().length < 12) return { ok: false, level: "warn", message: t("chatGuideBrief") };
  if (!inp.product || !inp.product.trim()) return { ok: false, level: "warn", message: t("inputNeedProduct") };
  if (!knownProductByName(inp.product)) {
    return {
      ok: false,
      level: "error",
      message: t("errProductInvalid", { name: inp.product }),
    };
  }
  return { ok: true, level: "ok", message: t("inputReadyHint") };
}

function renderInputValidationHint() {
  const el = $("#ins-input-alert");
  if (!el) return;
  const v = buildInputValidation();
  el.textContent = v.message;
  el.className = `field-alert ${v.level === "ok" ? "ok" : v.level === "error" ? "error" : "warn"}`;
}

function intakeGuideMessage(status) {
  const { missing } = status;
  if (missing.includes("brief")) return t("chatGuideGreeting");
  if (missing.includes("duration")) return t("chatGuideDuration");
  if (missing.includes("scenario")) return t("chatGuideScenario");
  return t("chatBriefReady");
}

function insertIntoChatInput(snippet) {
  const input = $("#chat-input");
  if (!input) return;
  const token = `@${snippet}`;
  const start = input.selectionStart ?? input.value.length;
  const end = input.selectionEnd ?? input.value.length;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  const needSpaceBefore = before.length > 0 && !/\s$/.test(before);
  const needSpaceAfter = after.length > 0 && !/^\s/.test(after);
  const insert = `${needSpaceBefore ? " " : ""}${token}${needSpaceAfter ? " " : ""}`;
  input.value = before + insert + after;
  const pos = before.length + insert.length;
  input.setSelectionRange(pos, pos);
  input.focus();
}

function closeMentionPopover() {
  $("#mention-popover")?.classList.add("hidden");
  $("#mention-btn")?.classList.remove("active");
}

function renderMentionPopover() {
  const pop = $("#mention-popover");
  if (!pop) return;
  const products = state.appMeta?.products || [];
  const directions = state.appMeta?.directions || [];
  if (!products.length && !directions.length) {
    pop.innerHTML = `<p class="mention-popover-empty">${esc(t("mentionEmpty"))}</p>`;
    return;
  }
  let html = "";
  if (products.length) {
    html += `<div class="mention-popover-section"><div class="mention-popover-label">${esc(t("mentionProducts"))}</div>`;
    html += products
      .map(
        (p) =>
          `<button type="button" class="mention-popover-item" data-mention="${esc(p.name)}">${esc(p.name)}</button>`
      )
      .join("");
    html += "</div>";
  }
  if (directions.length) {
    html += `<div class="mention-popover-section"><div class="mention-popover-label">${esc(t("mentionStyles"))}</div>`;
    html += directions
      .map(
        (d) =>
          `<button type="button" class="mention-popover-item" data-mention="${esc(d.name)}">${esc(d.name)}</button>`
      )
      .join("");
    html += "</div>";
  }
  pop.innerHTML = html;
  pop.querySelectorAll("[data-mention]").forEach((btn) => {
    btn.addEventListener("click", () => {
      insertIntoChatInput(btn.getAttribute("data-mention") || "");
      closeMentionPopover();
    });
  });
}

function openMentionPopover() {
  const pop = $("#mention-popover");
  const btn = $("#mention-btn");
  if (!pop || !btn) return;
  renderMentionPopover();
  pop.classList.remove("hidden");
  btn.classList.add("active");
}

function toggleMentionPopover() {
  const pop = $("#mention-popover");
  if (!pop) return;
  if (pop.classList.contains("hidden")) openMentionPopover();
  else closeMentionPopover();
}

function applyChatToWorkflow(parsed, raw) {
  let changed = false;
  if (parsed.product && parsed.product !== state.workflow.input.product) {
    state.workflow.input.product = parsed.product;
    changed = true;
  }
  if (parsed.direction && parsed.direction !== state.workflow.input.direction) {
    state.workflow.input.direction = parsed.direction;
    changed = true;
  }
  if (looksLikeAdIntent(raw)) {
    const merged = mergeInputBrief(state.workflow.input.brief, parsed.brief);
    if (merged !== state.workflow.input.brief) {
      state.workflow.input.brief = merged;
      changed = true;
    }
  }
  if (changed) markDirtyFrom("brief", "Brief.text");
  return changed;
}

function finishChatTurn(assistantText, { focusInput = false } = {}) {
  addChat("assistant", assistantText);
  if (focusInput) state.selectedNode = "brief";
  setCopilotState(COPILOT_STATE.READY, { force: true });
  renderChat();
  renderCanvas();
  renderInspector();
}

function finishChatSilently({ focusNode = "" } = {}) {
  if (focusNode) state.selectedNode = focusNode;
  setCopilotState(COPILOT_STATE.READY, { force: true });
  renderChat();
  renderCanvas();
  renderInspector();
}

function extractQuotedText(text) {
  const m = text.match(/[“"]([^”"]{2,})[”"]/);
  return (m?.[1] || "").trim();
}

function extractScriptHookFromChat(text) {
  const quoted = extractQuotedText(text);
  if (quoted) return quoted;
  const m = text.match(/(?:hook|开头|脚本|文案)(?:改成|改为|换成|调整为|写成|：|:)\s*([\s\S]{2,})/i);
  return (m?.[1] || "").trim();
}

function extractStoryboardNoteFromChat(text) {
  const quoted = extractQuotedText(text);
  if (quoted) return quoted;
  const m = text.match(/(?:分镜|镜头|storyboard)(?:改成|改为|换成|调整为|优化|：|:)\s*([\s\S]{2,})/i);
  return (m?.[1] || "").trim();
}

function hasNodeCommandVerb(text) {
  return /(重跑|rerun|重新|再跑|改|修改|调整|优化|保存|分支|branch|版本|出片|生成)/i.test(text);
}

function hasScriptCommand(text) {
  return /(hook|脚本|开头|文案)/i.test(text) && hasNodeCommandVerb(text);
}

function hasStoryboardCommand(text) {
  return /(分镜|storyboard|镜头)/i.test(text) && hasNodeCommandVerb(text);
}

function hasVideoCommand(text) {
  return /(视频|video|出片)/i.test(text) && hasNodeCommandVerb(text);
}

function shouldCreateBranchByChat(text) {
  return /(分支|branch|新版本|另一个版本)/i.test(text);
}

async function handleNodeAgentCommand(raw, low) {
  const script = activeScript();
  const hasScript = !!script;
  const scriptCmd = hasScriptCommand(low);
  const storyCmd = hasStoryboardCommand(low);
  const videoCmd = hasVideoCommand(low);
  if (!scriptCmd && !storyCmd && !videoCmd) return false;

  if (!hasScript) {
    finishChatTurn(t("chatGuideRunFirst"), { focusInput: true });
    return true;
  }

  if (scriptCmd) {
    state.selectedNode = "script";
    openInspector("script");
    const hookText = extractScriptHookFromChat(raw);
    const rerun = /(重跑|rerun|重新|再跑|branch|分支|版本)/i.test(low);
    const saveOnly = !rerun && /(保存|save)/i.test(low);
    const useBranch = shouldCreateBranchByChat(low);

    if (hookText) {
      const hookEl = $("#ins-hook");
      if (hookEl) hookEl.value = hookText;
      markDirtyFrom("script", "Script.hook");
    }

    if (saveOnly) {
      if (!hookText && !$("#ins-hook")?.value?.trim()) {
        finishChatTurn(t("chatGuideHookMissing"), { focusInput: false });
        return true;
      }
      try {
        await patchScriptOnly();
        finishChatTurn(t("chatGuideScriptSaved"), { focusInput: false });
      } catch (err) {
        finishChatTurn(t("actionFailed", { msg: err.message || err }), { focusInput: false });
      }
      return true;
    }

    if (rerun) {
      if (!hookText && !$("#ins-hook")?.value?.trim()) {
        finishChatTurn(t("chatGuideHookMissing"), { focusInput: false });
        return true;
      }
      await runNode("script", useBranch);
      finishChatSilently({ focusNode: "script" });
      return true;
    }

    if (hookText) {
      finishChatTurn(t("chatGuideScriptHookApplied"), { focusInput: false });
      return true;
    }
  }

  if (storyCmd) {
    state.selectedNode = "storyboard";
    openInspector("storyboard");
    const noteText = extractStoryboardNoteFromChat(raw);
    const rerun = /(重跑|rerun|重新|再跑|branch|分支|版本|生成)/i.test(low);
    const useBranch = shouldCreateBranchByChat(low);
    if (noteText) {
      const noteEl = $("#ins-note");
      if (noteEl) noteEl.value = noteText;
      markDirtyFrom("storyboard", "Storyboard.note");
    }
    if (rerun) {
      if (!noteText && !$("#ins-note")?.value?.trim()) {
        finishChatTurn(t("chatGuideStoryboardMissing"), { focusInput: false });
        return true;
      }
      await runNode("storyboard", useBranch);
      finishChatSilently({ focusNode: "storyboard" });
      return true;
    }
    if (noteText) {
      finishChatTurn(t("chatGuideStoryboardApplied"), { focusInput: false });
      return true;
    }
  }

  if (videoCmd) {
    state.selectedNode = "render";
    openInspector("render");
    const rerun = /(重跑|rerun|重新|再跑|出片|生成)/i.test(low);
    const useBranch = shouldCreateBranchByChat(low);
    if (rerun) {
      await runNode("render", useBranch);
      finishChatSilently({ focusNode: "render" });
      return true;
    }
    finishChatTurn(t("chatHintVideo"), { focusInput: false });
    return true;
  }

  return false;
}

function addChat(role, text) {
  state.chat.push({ role, text });
  renderChat();
}

function renderChat() {
  const el = $("#chat-log");
  const thinkingBlock =
    state.ui.copilotState === COPILOT_STATE.THINKING
      ? `<div class="chat-thinking-row" aria-live="polite">
          <span class="chat-thinking-orb" aria-hidden="true"></span>
          <span>${t("copilotThinking")}</span>
          <div class="chat-skeleton" aria-hidden="true"><span></span><span></span><span></span></div>
        </div>`
      : "";

  if (!state.chat.length) {
    el.innerHTML = `
      <div class="chat-msg assistant chat-welcome">
        <span class="chat-role">${t("assistantRole")}</span>
        ${t("chatWelcome")}
      </div>
      ${thinkingBlock}`;
    el.scrollTop = el.scrollHeight;
    applyCopilotState();
    return;
  }

  el.innerHTML =
    state.chat
      .map(
        (m) =>
          `<div class="chat-msg ${m.role}"><span class="chat-role">${m.role === "user" ? t("youRole") : t("assistantRole")}</span>${esc(
            m.text
          )}</div>`
      )
      .join("") + thinkingBlock;
  el.scrollTop = el.scrollHeight;
  applyCopilotState();
}

function activeScript() {
  return state.scripts.find((s) => s.id === state.activeScriptId) || state.scripts[0] || null;
}

function activePrompts() {
  if (!state.activeScriptId) return [];
  return state.prompts.filter((p) => p.script_id === state.activeScriptId);
}

function activeVideos() {
  if (!state.activeScriptId) return [];
  return state.videos.filter((v) => v.script_id === state.activeScriptId);
}

function branchLabel(script, idx) {
  const note = script.review_note || "";
  if (note.startsWith("branch:")) {
    const node = note.split(":")[2] || "script";
    const map = {
      productInfo: t("nodeProductInfo"),
      productAssets: t("nodeProductAssets"),
      benchmark: t("nodeBenchmark"),
      brief: t("nodeBrief"),
      script: t("stepScript"),
      storyboard: t("stepStoryboard"),
      video: t("stepRender"),
      render: t("stepRender"),
      qa: t("stepQA"),
    };
    return `${t("branchFrom")} · ${map[node] || node}`;
  }
  return idx === 0 ? t("branchMain") : `${t("branchFrom")} ${idx + 1}`;
}

function nodeStatusFromData(key) {
  if (key === "productInfo") {
    return state.workflow.input.product ? "done" : "idle";
  }
  if (key === "productAssets") {
    return state.workflow.input.materialContext ? "done" : "idle";
  }
  if (key === "benchmark") {
    return state.workflow.input.referenceVideoUrl ? "done" : "idle";
  }
  if (key === "brief") {
    return state.workflow.input.brief ? "done" : "idle";
  }
  if (key === "script") {
    const s = activeScript();
    if (!s) return state.batchId ? "running" : "idle";
    if (s.review_status === "失败") return "fail";
    if (s.review_status === "已通过") return "done";
    return "running";
  }
  if (key === "storyboard") {
    const p = activePrompts();
    if (!p.length) return activeScript()?.review_status === "已通过" ? "running" : "idle";
    if (p.some((x) => x.review_status === "失败")) return "fail";
    if (p.every((x) => x.review_status === "已通过")) return "done";
    return "running";
  }
  if (key === "render") {
    const v = activeVideos();
    if (!v.length) return activePrompts().length ? "running" : "idle";
    if (v.some((x) => (x.output_status || "").includes("失败"))) return "fail";
    if (v.some((x) => x.video_url)) return "done";
    return "running";
  }
  if (key === "qa") {
    const renderStatus = nodeStatusFromData("render");
    if (renderStatus === "fail") return "fail";
    if (renderStatus === "done") return "done";
    if (renderStatus === "running") return "running";
    return "idle";
  }
  return "idle";
}

function nodeStatusText(status) {
  if (status === "done") return t("statusDone");
  if (status === "running") return t("statusRunning");
  if (status === "fail") return t("statusFail");
  return t("statusPending");
}

function nodeSummary(key) {
  if (key === "productInfo")
    return state.workflow.input.product || state.workflow.input.sourceUrl || t("productInfoHint");
  if (key === "productAssets")
    return state.workflow.input.materialContext ? t("productAssetsReady") : t("productAssetsHint");
  if (key === "benchmark")
    return state.workflow.input.referenceVideoUrl || t("benchmarkHint");
  if (key === "brief") return state.workflow.input.brief || t("nodeInputHint");
  if (key === "script") {
    const s = activeScript();
    return s ? s.hook || s.direction || t("stepScript") : t("scriptWait");
  }
  if (key === "storyboard") {
    const p = activePrompts()[0];
    return p ? (p.prompt_text || "").slice(0, 80) : t("storyWait");
  }
  if (key === "render") {
    const v = activeVideos()[0];
    if (!v) return t("videoWait");
    return v.video_url ? t("previewReady") : (v.output_status || t("statusRunning"));
  }
  if (key === "qa") {
    const status = nodeStatusFromData("qa");
    if (status === "done") return t("qaDoneHint");
    if (status === "fail") return t("qaFailHint");
    if (status === "running") return t("qaRunningHint");
    return t("qaWaitHint");
  }
  return "";
}

function ensureDirtyReasonBucket(nodeId) {
  if (!state.canvas.dirtyReasons[nodeId]) state.canvas.dirtyReasons[nodeId] = new Set();
  return state.canvas.dirtyReasons[nodeId];
}

function downstreamNodes(start) {
  const out = new Set();
  const q = [start];
  while (q.length) {
    const cur = q.shift();
    state.canvas.edges.forEach((e) => {
      if (e.from === cur && !out.has(e.to)) {
        out.add(e.to);
        q.push(e.to);
      }
    });
  }
  return Array.from(out);
}

function markDirtyFrom(start, reason = "") {
  downstreamNodes(start).forEach((nodeId) => {
    state.canvas.dirtyNodes.add(nodeId);
    if (reason) ensureDirtyReasonBucket(nodeId).add(reason);
  });
  renderImpactLine();
  renderCanvasLinks();
}

function clearDirtyFrom(start) {
  [start, ...downstreamNodes(start)].forEach((nodeId) => {
    state.canvas.dirtyNodes.delete(nodeId);
    delete state.canvas.dirtyReasons[nodeId];
  });
  renderImpactLine();
  renderCanvasLinks();
}

function dirtyReasonText(nodeId) {
  const set = state.canvas.dirtyReasons[nodeId];
  if (!set || !set.size) return "";
  const reasons = Array.from(set);
  if (reasons.length <= 2) return reasons.join(" / ");
  return `${reasons.slice(0, 2).join(" / ")} +${reasons.length - 2}`;
}

function renderImpactLine() {
  const el = $("#impact-line");
  const nodes = Array.from(state.canvas.dirtyNodes);
  if (!nodes.length) {
    el.textContent = t("impactNone");
    return;
  }
  const map = {
    productInfo: t("nodeProductInfo"),
    productAssets: t("nodeProductAssets"),
    benchmark: t("nodeBenchmark"),
    brief: t("nodeBrief"),
    script: t("stepScript"),
    storyboard: t("stepStoryboard"),
    render: t("stepRender"),
    qa: t("stepQA"),
  };
  el.textContent = t("impactPending", { nodes: nodes.map((n) => map[n] || n).join(" -> ") });
}

function hasPath(from, to, seen = new Set()) {
  if (from === to) return true;
  if (seen.has(from)) return false;
  seen.add(from);
  const next = state.canvas.edges.filter((e) => e.from === from).map((e) => e.to);
  return next.some((n) => hasPath(n, to, seen));
}

function canAddEdge(from, to) {
  if (!from || !to || from === to) return false;
  if (state.canvas.edges.some((e) => e.from === from && e.to === to)) return false;
  if (to === "productInfo" || from === "qa") return false;
  if (hasPath(to, from)) return false;
  return true;
}

function getPortCenter(nodeId, type) {
  const board = $("#canvas-board");
  const port = $(`#canvas-nodes [data-node="${nodeId}"] .node-port.${type}`);
  if (!board || !port) return null;
  const zoom = state.canvas.zoom || 1;
  const b = board.getBoundingClientRect();
  const r = port.getBoundingClientRect();
  return {
    x: (r.left - b.left + r.width / 2 - state.canvas.view.x) / zoom,
    y: (r.top - b.top + r.height / 2 - state.canvas.view.y) / zoom,
  };
}

function linkPath(a, b) {
  const dx = Math.max(48, Math.abs(b.x - a.x) * 0.45);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

function nearestInputPort(x, y, fromNode) {
  let best = { nodeId: "", dist: Infinity };
  NODE_IDS.forEach((nodeId) => {
    if (!canAddEdge(fromNode, nodeId)) return;
    const c = getPortCenter(nodeId, "in");
    if (!c) return;
    const dist = Math.hypot(c.x - x, c.y - y);
    if (dist < best.dist) best = { nodeId, dist };
  });
  return best.dist <= LINK_SNAP_RADIUS ? best.nodeId : "";
}

function startLinkDraft(from, pointerX = 0, pointerY = 0, pointerId = null) {
  state.canvas.linkDraft = { from, x: pointerX, y: pointerY, snapTo: "", active: true, pointerId };
  renderCanvas();
}

function clearLinkDraft() {
  if (!state.canvas.linkDraft.active && !state.canvas.linkDraft.from) return;
  state.canvas.linkDraft = { from: "", x: 0, y: 0, snapTo: "", active: false, pointerId: null };
  renderCanvas();
}

function completeLinkDraft(to) {
  const from = state.canvas.linkDraft.from;
  state.canvas.linkDraft = { from: "", x: 0, y: 0, snapTo: "", active: false, pointerId: null };
  if (!canAddEdge(from, to)) {
    showError(t("errEdgeInvalid"));
    renderCanvas();
    return;
  }
  showError("");
  state.canvas.edges.push({ from, to });
  markDirtyFrom(from, `${from}->${to}`);
  renderCanvas();
}

function renderEdgeList() {
  const el = $("#edge-list");
  const map = {
    productInfo: t("nodeProductInfo"),
    productAssets: t("nodeProductAssets"),
    benchmark: t("nodeBenchmark"),
    brief: t("nodeBrief"),
    script: t("stepScript"),
    storyboard: t("stepStoryboard"),
    render: t("stepRender"),
    qa: t("stepQA"),
  };
  el.innerHTML = state.canvas.edges
    .map(
      (e, idx) =>
        `<span class="edge-chip">${esc(map[e.from])} -> ${esc(map[e.to])}<button type="button" data-edge-del="${idx}" aria-label="remove">x</button></span>`
    )
    .join("");
  el.querySelectorAll("[data-edge-del]").forEach((btn) => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const idx = Number(btn.dataset.edgeDel);
      const removed = state.canvas.edges[idx];
      state.canvas.edges.splice(idx, 1);
      if (removed?.from) markDirtyFrom(removed.from, `${removed.from}->${removed.to}`);
      renderCanvas();
    });
  });
}

function renderCanvas() {
  const map = {
    productInfo: t("nodeProductInfo"),
    productAssets: t("nodeProductAssets"),
    benchmark: t("nodeBenchmark"),
    brief: t("nodeBrief"),
    script: t("stepScript"),
    storyboard: t("stepStoryboard"),
    render: t("stepRender"),
    qa: t("stepQA"),
  };
  const glyph = { productInfo: "ⓘ", productAssets: "🖼", benchmark: "◎", brief: "✎", script: "T", storyboard: "▦", render: "▶", qa: "✓" };
  $("#canvas-nodes").innerHTML = NODE_IDS.map((id) => {
    const pos = state.canvas.layout[id] || { x: 0, y: 0 };
    const st = nodeStatusFromData(id);
    const cls = st === "done" ? "done" : st === "running" ? "running" : st === "fail" ? "fail" : "";
    const isDirty = state.canvas.dirtyNodes.has(id);
    const reason = dirtyReasonText(id);
    const snapIn = state.canvas.linkDraft.snapTo === id;
    return `
      <article class="canvas-node ${state.selectedNode === id ? "active" : ""} ${isDirty ? "dirty" : ""}" data-node="${id}" style="left:${pos.x}px;top:${pos.y}px;">
        <div class="canvas-node-head">
          <div class="canvas-node-title">
            <span class="canvas-node-glyph">${glyph[id] || "•"}</span>
            <span class="canvas-node-label">${esc(map[id])}</span>
          </div>
          <div class="canvas-node-tools">
            <button type="button" class="canvas-node-tool" data-node-tool="inspect" data-node="${id}" title="Inspect">◉</button>
            <button type="button" class="canvas-node-tool ${["script", "storyboard", "render"].includes(id) ? "" : "hidden"}" data-node-tool="rerun" data-node="${id}" title="Rerun">↻</button>
          </div>
          <span class="node-badge ${cls}">${esc(nodeStatusText(st))}</span>
        </div>
        <div class="canvas-node-body">${esc(nodeSummary(id))}</div>
        ${isDirty && reason ? `<div class="canvas-node-reason">${esc(t("impactedBy", { reason }))}</div>` : ""}
        <div class="canvas-node-ports">
          <button type="button" class="node-port in ${id === "productInfo" ? "hidden-port" : ""} ${snapIn ? "snap-target" : ""}" data-port-in="${id}"></button>
          <button type="button" class="node-port out ${id === "qa" ? "hidden-port" : ""} ${state.canvas.linkDraft.from === id ? "linking" : ""}" data-port-out="${id}"></button>
        </div>
      </article>`;
  }).join("");
  renderEdgeList();
  bindNodeInteractions();
  applyCanvasZoom();
  renderCanvasLinks();
  renderImpactLine();
  updateAiStatus();
}

function bindNodeInteractions() {
  const board = $("#canvas-board");
  $$("#canvas-nodes .canvas-node").forEach((nodeEl) => {
    const nodeId = nodeEl.dataset.node;
    nodeEl.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".node-port")) return;
      if (state.ui.panMode || isCanvasPaused()) return;
      e.stopPropagation();
      state.canvas.dragMoved = false;
      state.canvas.draggingNode = nodeId;
      nodeEl.classList.add("dragging");
      const boardRect = board.getBoundingClientRect();
      const nodeRect = nodeEl.getBoundingClientRect();
      const zoom = state.canvas.zoom || 1;
      const offsetX = (e.clientX - nodeRect.left) / zoom;
      const offsetY = (e.clientY - nodeRect.top) / zoom;
      nodeEl.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const nodeWidth = (nodeEl.offsetWidth || nodeRect.width || NODE_WIDTH) / zoom;
        const nodeHeight = (nodeEl.offsetHeight || nodeRect.height || 120) / zoom;
        const ptr = boardPointerToStage(ev.clientX, ev.clientY);
        const maxX = Math.max(0, state.canvas.size.w - nodeWidth - 8);
        const maxY = Math.max(0, state.canvas.size.h - nodeHeight - 8);
        const x = Math.min(maxX, Math.max(8, ptr.x - offsetX));
        const y = Math.min(maxY, Math.max(8, ptr.y - offsetY));
        state.canvas.layout[nodeId] = { x, y };
        nodeEl.style.left = `${x}px`;
        nodeEl.style.top = `${y}px`;
        state.canvas.dragMoved = true;
        renderCanvasLinks();
      };
      const up = (ev) => {
        nodeEl.classList.remove("dragging");
        nodeEl.releasePointerCapture(ev.pointerId);
        nodeEl.removeEventListener("pointermove", move);
        nodeEl.removeEventListener("pointerup", up);
        nodeEl.removeEventListener("pointercancel", up);
        const moved = state.canvas.dragMoved;
        state.canvas.draggingNode = "";
        state.canvas.dragMoved = false;
        if (!moved) {
          openInspector(nodeId);
        } else {
          renderCanvasLinks();
        }
      };
      nodeEl.addEventListener("pointermove", move);
      nodeEl.addEventListener("pointerup", up);
      nodeEl.addEventListener("pointercancel", up);
    });
  });

  $$("#canvas-nodes [data-node-tool]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const node = btn.dataset.node;
      const tool = btn.dataset.nodeTool;
      if (tool === "inspect") {
        openInspector(node);
        return;
      }
      if (tool === "rerun") {
        if (node === "script" || node === "storyboard" || node === "render") {
          runNode(node, false);
        }
      }
    });
  });

  $$("#canvas-nodes [data-port-out]").forEach((btn) => {
    btn.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const from = btn.dataset.portOut;
      const pt = boardPointerToStage(e.clientX, e.clientY);
      startLinkDraft(from, pt.x, pt.y, e.pointerId);
      if (board.setPointerCapture) {
        try {
          board.setPointerCapture(e.pointerId);
        } catch {}
      }
    });
  });

  $$("#canvas-nodes [data-port-in]").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      if (!state.canvas.linkDraft.active) return;
      const to = btn.dataset.portIn;
      if (to === "productInfo") return;
      completeLinkDraft(to);
    });
  });
}

function bindCanvasBoardInteractions() {
  if (state.canvas.boardBound) return;
  state.canvas.boardBound = true;
  const board = $("#canvas-board");
  let panSession = null;

  const isPanEligible = (target) => {
    if (!target || !board.contains(target)) return false;
    if (target.closest(".creatify-dock")) return false;
    if (target.closest(".node-port")) return false;
    if (state.ui.panMode || isCanvasPaused()) return true;
    return !target.closest(".canvas-node");
  };

  const onPanMove = (e) => {
    if (!panSession) return;
    state.canvas.view.x = panSession.vx + (e.clientX - panSession.x);
    state.canvas.view.y = panSession.vy + (e.clientY - panSession.y);
    applyCanvasViewport();
    renderCanvasLinks();
  };

  const endPan = (e) => {
    if (!panSession) return;
    const activeBoard = panSession.board;
    activeBoard.classList.remove("is-panning");
    if (activeBoard.releasePointerCapture && e?.pointerId != null) {
      try {
        activeBoard.releasePointerCapture(e.pointerId);
      } catch {}
    }
    panSession = null;
    window.removeEventListener("pointermove", onPanMove);
    window.removeEventListener("pointerup", endPan);
    window.removeEventListener("pointercancel", endPan);
  };

  board.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 && e.button !== 1) return;
    if (state.canvas.linkDraft.active) return;
    if (!isPanEligible(e.target)) return;
    e.preventDefault();
    panSession = {
      board,
      x: e.clientX,
      y: e.clientY,
      vx: state.canvas.view.x,
      vy: state.canvas.view.y,
    };
    board.classList.add("is-panning");
    if (board.setPointerCapture) {
      try {
        board.setPointerCapture(e.pointerId);
      } catch {}
    }
    window.addEventListener("pointermove", onPanMove);
    window.addEventListener("pointerup", endPan);
    window.addEventListener("pointercancel", endPan);
  });

  board.addEventListener(
    "wheel",
    (e) => {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.08 : 0.92;
      zoomAtPoint(e.clientX, e.clientY, state.canvas.zoom * factor);
    },
    { passive: false }
  );

  board.addEventListener("pointermove", (e) => {
    if (!state.canvas.linkDraft.active) return;
    const pt = boardPointerToStage(e.clientX, e.clientY);
    state.canvas.linkDraft.x = pt.x;
    state.canvas.linkDraft.y = pt.y;
    state.canvas.linkDraft.snapTo = nearestInputPort(pt.x, pt.y, state.canvas.linkDraft.from);
    renderCanvas();
  });
  board.addEventListener("pointerup", (e) => {
    if (!state.canvas.linkDraft.active) return;
    if (state.canvas.linkDraft.snapTo) {
      completeLinkDraft(state.canvas.linkDraft.snapTo);
      return;
    }
    state.canvas.linkDraft = { from: "", x: 0, y: 0, snapTo: "", active: false, pointerId: null };
    renderCanvas();
    if (board.releasePointerCapture && e.pointerId != null) {
      try {
        board.releasePointerCapture(e.pointerId);
      } catch {}
    }
  });
  board.addEventListener("click", (e) => {
    if (e.target === board || e.target.id === "canvas-links") clearLinkDraft();
  });
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") clearLinkDraft();
  });
}

function renderCanvasLinks() {
  const svg = $("#canvas-links");
  if (!svg) return;
  const lines = [];
  state.canvas.edges.forEach((e) => {
    const a = getPortCenter(e.from, "out");
    const b = getPortCenter(e.to, "in");
    if (!a || !b) return;
    const dirty = state.canvas.dirtyNodes.has(e.to) ? "dirty" : "";
    lines.push(`<path class="canvas-link ${dirty}" d="${linkPath(a, b)}"></path>`);
  });
  if (state.canvas.linkDraft.active) {
    const a = getPortCenter(state.canvas.linkDraft.from, "out");
    let b = { x: state.canvas.linkDraft.x, y: state.canvas.linkDraft.y };
    if (state.canvas.linkDraft.snapTo) {
      const snap = getPortCenter(state.canvas.linkDraft.snapTo, "in");
      if (snap) b = snap;
    }
    if (a) lines.push(`<path class="canvas-link draft" d="${linkPath(a, b)}"></path>`);
  }
  svg.innerHTML = lines.join("");
}

function renderBranchTabs() {
  const wrap = $("#branch-tabs");
  if (!state.scripts.length) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = state.scripts
    .map(
      (s, i) =>
        `<button type="button" class="flow-branch-tab ${s.id === state.activeScriptId ? "active" : ""}" data-script="${esc(
          s.id
        )}">${esc(branchLabel(s, i))}</button>`
    )
    .join("");
  wrap.querySelectorAll("[data-script]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.activeScriptId = btn.dataset.script;
      renderCanvas();
      renderInspector();
      renderPreview();
      renderBranchCompare();
      renderBranchTabs();
    });
  });
}

function branchArtifacts(scriptId) {
  const script = state.scripts.find((s) => s.id === scriptId) || null;
  const prompt = state.prompts.find((p) => p.script_id === scriptId) || null;
  const video = state.videos.find((v) => v.script_id === scriptId) || null;
  return { script, prompt, video };
}

function compareCell(left, right) {
  const same = String(left || "") === String(right || "");
  return { same, left: left || "-", right: right || "-" };
}

function compareRows(leftA, rightA) {
  const leftVideoStatus = leftA.video?.video_url ? t("statusDone") : leftA.video?.output_status || t("statusPending");
  const rightVideoStatus = rightA.video?.video_url ? t("statusDone") : rightA.video?.output_status || t("statusPending");
  return [
    { label: t("compareHook"), ...compareCell(leftA.script?.hook || "", rightA.script?.hook || "") },
    {
      label: t("compareStoryboard"),
      ...compareCell((leftA.prompt?.prompt_text || "").slice(0, 160), (rightA.prompt?.prompt_text || "").slice(0, 160)),
    },
    { label: t("compareVideoStatus"), ...compareCell(leftVideoStatus, rightVideoStatus) },
  ];
}

function renderBranchCompare() {
  const el = $("#branch-compare");
  if (!state.scripts.length) {
    el.textContent = t("compareEmpty");
    return;
  }
  if (!state.compare.leftScriptId || !state.scripts.some((s) => s.id === state.compare.leftScriptId)) {
    state.compare.leftScriptId = state.activeScriptId || state.scripts[0].id;
  }
  if (!state.compare.rightScriptId || !state.scripts.some((s) => s.id === state.compare.rightScriptId)) {
    state.compare.rightScriptId = state.scripts.find((s) => s.id !== state.compare.leftScriptId)?.id || state.compare.leftScriptId;
  }
  const options = state.scripts.map((s, i) => `<option value="${esc(s.id)}">${esc(branchLabel(s, i))}</option>`).join("");
  const leftA = branchArtifacts(state.compare.leftScriptId);
  const rightA = branchArtifacts(state.compare.rightScriptId);
  const rows = compareRows(leftA, rightA);
  const filtered = state.compare.onlyDiff ? rows.filter((r) => !r.same) : rows;
  const rowHtml = filtered.length
    ? filtered
        .map(
          (r) => `
      <div class="compare-row">
        <div class="compare-row-key">${esc(r.label)} ${r.same ? `· ${esc(t("diffSame"))}` : `· ${esc(t("diffChanged"))}`}</div>
        <div class="compare-row-values">
          <div class="${r.same ? "" : "compare-changed"}">${esc(r.left)}</div>
          <div class="${r.same ? "" : "compare-changed"}">${esc(r.right)}</div>
        </div>
      </div>`
        )
        .join("")
    : `<div class="compare-empty muted">${esc(t("compareNoDiff"))}</div>`;

  el.innerHTML = `
    <div class="compare-controls">
      <label>${t("compareLeft")}<select id="compare-left">${options}</select></label>
      <label>${t("compareRight")}<select id="compare-right">${options}</select></label>
    </div>
    <div class="compare-toolbar">
      <label class="compare-toggle"><input id="compare-only-diff" type="checkbox" ${state.compare.onlyDiff ? "checked" : ""} /> ${esc(
    t("compareOnlyDiff")
  )}</label>
      <div class="compare-activate-actions">
        <button type="button" class="btn ghost btn-sm" id="compare-activate-left">${esc(t("setActiveLeft"))}</button>
        <button type="button" class="btn ghost btn-sm" id="compare-activate-right">${esc(t("setActiveRight"))}</button>
      </div>
    </div>
    <div class="compare-grid">${rowHtml}</div>`;

  $("#compare-left").value = state.compare.leftScriptId;
  $("#compare-right").value = state.compare.rightScriptId;
  $("#compare-left").addEventListener("change", () => {
    state.compare.leftScriptId = $("#compare-left").value;
    renderBranchCompare();
  });
  $("#compare-right").addEventListener("change", () => {
    state.compare.rightScriptId = $("#compare-right").value;
    renderBranchCompare();
  });
  $("#compare-only-diff").addEventListener("change", () => {
    state.compare.onlyDiff = $("#compare-only-diff").checked;
    renderBranchCompare();
  });
  $("#compare-activate-left").addEventListener("click", () => {
    state.activeScriptId = state.compare.leftScriptId;
    renderCanvas();
    renderInspector();
    renderPreview();
    renderBranchTabs();
    renderBranchCompare();
  });
  $("#compare-activate-right").addEventListener("click", () => {
    state.activeScriptId = state.compare.rightScriptId;
    renderCanvas();
    renderInspector();
    renderPreview();
    renderBranchTabs();
    renderBranchCompare();
  });
}

function syncInputFromInspector() {
  state.workflow.input.brief = $("#ins-brief")?.value?.trim() || state.workflow.input.brief;
  state.workflow.input.sourceUrl = $("#ins-url")?.value?.trim() || "";
  state.workflow.input.referenceVideoUrl = $("#ins-ref-video")?.value?.trim() || "";
  state.workflow.input.product = $("#ins-product")?.value?.trim() || "";
  state.workflow.input.direction = $("#ins-direction-input")?.value?.trim() || "";
  state.workflow.input.language = $("#ins-language")?.value || "英语";
}

function syncRunCountControl() {
  const sel = $("#header-count");
  if (!sel) return;
  const keep = String(state.workflow.input.count || 1);
  sel.innerHTML = `
    <option value="1">${t("count1")}</option>
    <option value="2">${t("count2")}</option>
    <option value="3">${t("count3")}</option>
  `;
  sel.value = keep === "2" || keep === "3" ? keep : "1";
}

async function runWorkflow() {
  syncInputFromInspector();
  const check = buildInputValidation();
  if (!check.ok) {
    showError(check.message);
    openInspector("brief");
    renderInputValidationHint();
    syncCopilotState();
    return;
  }
  if (!state.workflow.input.brief) {
    showError(t("errBrief"));
    syncCopilotState();
    return;
  }
  if (!(await ensureAuthenticated())) {
    syncCopilotState();
    return;
  }
  showError("");
  setCopilotState(COPILOT_STATE.BUILDING, { force: true });
  renderChat();
  try {
    const est = await api("/api/toc/quick-generate/estimate", {
      method: "POST",
      body: JSON.stringify({
        brief: state.workflow.input.brief,
        duration_sec: 15,
        ratio: state.workflow.input.ratio,
        resolution: "1080p",
      }),
    });
    const rangeText =
      est.range?.length === 2 && est.range[0] !== est.range[1]
        ? `${est.range[0]}-${est.range[1]}`
        : `${est.range?.[0] ?? est.estimated_credits ?? "300-650"}`;
    updateEstimate(t("estimateCredits", { range: rangeText, fallback: est.fallback ? t("estimateFallback") : "" }));
    const res = await api("/api/toc/quick-generate", {
      method: "POST",
      body: JSON.stringify({
        brief: state.workflow.input.brief,
        source_url: state.workflow.input.sourceUrl,
        reference_video_url: state.workflow.input.referenceVideoUrl,
        material_context: state.workflow.input.materialContext,
        product: state.workflow.input.product,
        direction: state.workflow.input.direction,
        language: state.workflow.input.language,
        count: state.workflow.input.count,
        use_first_frame: true,
      }),
    });
    state.batchId = res.batch_id;
    state.selectedNode = "script";
    $("#batch-label").textContent = t("batchLabel", { id: state.batchId });
    ["productInfo", "productAssets", "benchmark", "brief"].forEach((n) => clearDirtyFrom(n));
    addChat("assistant", t("chatRunStarted", { id: state.batchId }));
    await pollBatch();
    startPolling();
  } catch (err) {
    if (err.status === 401) showError(t("loginRequired"));
    else if (err.status === 402) {
      const p = err.payload || {};
      showError(t("errInsufficient", { coin: p.coin ?? "-", needed: p.needed ?? "-" }));
      if (p.purchase_url) state.purchaseUrl = p.purchase_url;
      updateUserHeader();
    } else showError(t("errCreate", { msg: err.message }));
    setCopilotState(COPILOT_STATE.ERROR, { force: true });
  }
  applyCopilotState();
}

async function patchScriptOnly() {
  const script = activeScript();
  if (!script) return;
  if (!(await ensureAuthenticated())) return;
  const hook = $("#ins-hook")?.value?.trim();
  if (!hook) {
    alert(t("hookRequired"));
    return;
  }
  await api(`/api/toc/scripts/${script.id}`, {
    method: "PATCH",
    body: JSON.stringify({ hook, direction: $("#ins-direction")?.value || script.direction }),
  });
  await pollBatch();
}

async function runNode(node, createBranch) {
  const script = activeScript();
  if (!script) return;
  if (!(await ensureAuthenticated())) return;
  const backendNode = node === "render" ? "video" : node;
  const body = {
    node: backendNode,
    create_branch: createBranch,
    note: $("#ins-note")?.value?.trim() || "",
  };
  if (backendNode === "script") {
    body.hook = $("#ins-hook")?.value?.trim() || script.hook;
    body.direction = $("#ins-direction")?.value || script.direction;
  }
  try {
    const res = await api(`/api/toc/scripts/${script.id}/branch`, { method: "POST", body: JSON.stringify(body) });
    if (createBranch && res.target_script_id) state.activeScriptId = res.target_script_id;
    clearDirtyFrom(node);
    addChat("assistant", t("chatNodeQueued", { node }));
    startPolling();
    await pollBatch();
  } catch (err) {
    alert(t("actionFailed", { msg: err.message }));
  }
}

function renderInspector() {
  const box = $("#inspector-body");
  const node = state.selectedNode;
  const input = state.workflow.input;
  if (node === "productInfo") {
    box.innerHTML = `
      <label class="field">${t("fieldProduct")}<input id="ins-product" value="${esc(input.product)}" /></label>
      <label class="field">${t("fieldUrl")}<input id="ins-url" value="${esc(input.sourceUrl)}" /></label>
      <p class="field-alert warn">${esc(t("productInfoHint"))}</p>
      <div class="inspector-actions"><button type="button" class="btn primary" id="ins-run">${t("runWorkflow")}</button></div>`;
    ["ins-product", "ins-url"].forEach((id) => {
      $(`#${id}`)?.addEventListener("input", () => {
        syncInputFromInspector();
        markDirtyFrom("productInfo", `Input.${id.replace("ins-", "")}`);
        renderCanvas();
      });
    });
    $("#ins-run").addEventListener("click", runWorkflow);
    return;
  }

  if (node === "productAssets") {
    const materialPreview = (input.materialContext || "").slice(0, 500);
    box.innerHTML = `
      <label class="field">${t("fieldMaterialCtx")}<textarea id="ins-material" readonly>${esc(materialPreview || t("productAssetsHint"))}</textarea></label>
      <p class="field-alert warn">${esc(t("productAssetsHint"))}</p>`;
    return;
  }

  if (node === "benchmark") {
    box.innerHTML = `
      <label class="field">${t("fieldRefVideo")}<input id="ins-ref-video" value="${esc(input.referenceVideoUrl)}" placeholder="${esc(t("fieldRefVideoPh"))}" /></label>
      <p class="field-alert warn">${esc(t("benchmarkHint"))}</p>`;
    $("#ins-ref-video")?.addEventListener("input", () => {
      syncInputFromInspector();
      markDirtyFrom("benchmark", "Benchmark.reference");
      renderCanvas();
    });
    return;
  }

  if (node === "brief") {
    const input = state.workflow.input;
    const materialPreview = (input.materialContext || "").slice(0, 400);
    box.innerHTML = `
      <label class="field">${t("fieldBrief")}<textarea id="ins-brief">${esc(input.brief)}</textarea></label>
      ${materialPreview ? `<label class="field">${t("fieldMaterialCtx")}<textarea id="ins-material" readonly>${esc(materialPreview)}${input.materialContext.length > 400 ? "…" : ""}</textarea></label>` : ""}
      <label class="field">${t("fieldDirection")}<input id="ins-direction-input" value="${esc(input.direction)}" /></label>
      <label class="field">${t("optVoice")}
        <select id="ins-language">
          <option value="英语" ${input.language === "英语" ? "selected" : ""}>English</option>
          <option value="西语" ${input.language === "西语" ? "selected" : ""}>Español</option>
        </select>
      </label>
      <p id="ins-input-alert" class="field-alert warn"></p>
      <div class="inspector-actions"><button type="button" class="btn primary" id="ins-run">${t("runWorkflow")}</button></div>`;
    ["ins-brief", "ins-direction-input", "ins-language"].forEach((id) => {
      $(`#${id}`)?.addEventListener("input", () => {
        syncInputFromInspector();
        markDirtyFrom("brief", `Brief.${id.replace("ins-", "")}`);
        renderCanvas();
        renderInputValidationHint();
      });
    });
    renderInputValidationHint();
    $("#ins-run").addEventListener("click", runWorkflow);
    return;
  }

  const script = activeScript();
  if (!script) {
    box.innerHTML = `<p class="muted">${t("inspectorEmpty")}</p>`;
    return;
  }

  if (node === "script") {
    box.innerHTML = `
      <label class="field">Hook<textarea id="ins-hook">${esc(script.hook || "")}</textarea></label>
      <label class="field">${t("fieldDirection")}
        <select id="ins-direction">
          ${(state.appMeta?.directions || [])
            .map((d) => `<option value="${esc(d.name)}" ${d.name === script.direction ? "selected" : ""}>${esc(d.name)}</option>`)
            .join("")}
        </select>
      </label>
      <label class="field">${t("fieldNote")}<textarea id="ins-note" placeholder="${esc(t("notePlaceholderScript"))}"></textarea></label>
      <div class="inspector-actions">
        <button type="button" class="btn ghost" id="ins-save">${t("saveOnly")}</button>
        <button type="button" class="btn primary" id="ins-branch-script">${t("branchRunStoryboard")}</button>
        <button type="button" class="btn ghost" id="ins-rerun-script">${t("rerunCurrentStoryboard")}</button>
      </div>`;
    $("#ins-hook")?.addEventListener("input", () => {
      markDirtyFrom("script", "Script.hook");
      renderCanvas();
    });
    $("#ins-direction")?.addEventListener("input", () => {
      markDirtyFrom("script", "Script.direction");
      renderCanvas();
    });
    $("#ins-save").addEventListener("click", patchScriptOnly);
    $("#ins-branch-script").addEventListener("click", () => runNode("script", true));
    $("#ins-rerun-script").addEventListener("click", () => runNode("script", false));
    return;
  }

  if (node === "storyboard") {
    const p = activePrompts()[0];
    box.innerHTML = `
      <label class="field">${t("storyPromptPreview")}<textarea readonly>${esc((p?.prompt_text || "").slice(0, 850))}</textarea></label>
      <label class="field">${t("fieldNote")}<textarea id="ins-note" placeholder="${esc(t("notePlaceholderStoryboard"))}"></textarea></label>
      <div class="inspector-actions">
        <button type="button" class="btn primary" id="ins-branch-story">${t("branchRunStoryboard")}</button>
        <button type="button" class="btn ghost" id="ins-rerun-story">${t("rerunCurrentStoryboard")}</button>
      </div>`;
    $("#ins-note")?.addEventListener("input", () => {
      markDirtyFrom("storyboard", "Storyboard.note");
      renderCanvas();
    });
    $("#ins-branch-story").addEventListener("click", () => runNode("storyboard", true));
    $("#ins-rerun-story").addEventListener("click", () => runNode("storyboard", false));
    return;
  }

  if (node === "render") {
    box.innerHTML = `
      <p class="muted">${t("videoNodeHint")}</p>
      <div class="inspector-actions">
        <button type="button" class="btn primary" id="ins-branch-video">${t("branchRunVideo")}</button>
        <button type="button" class="btn ghost" id="ins-rerun-video">${t("rerunCurrentVideo")}</button>
      </div>`;
    $("#ins-branch-video").addEventListener("click", () => runNode("render", true));
    $("#ins-rerun-video").addEventListener("click", () => runNode("render", false));
    return;
  }

  box.innerHTML = `<p class="muted">${t("qaWaitHint")}</p>`;
}

function renderPreview() {
  const previewBlock = $("#preview-block");
  const compareBlock = $("#compare-block");
  const showOutputPanel = OUTPUT_NODES.has(state.selectedNode);
  previewBlock?.classList.toggle("hidden", !showOutputPanel);
  compareBlock?.classList.toggle("hidden", !showOutputPanel);
  if (!showOutputPanel) return;
  const videos = activeVideos();
  const video = videos.find((v) => v.video_url);
  const videoEl = $("#preview-video");
  const empty = $("#preview-empty");
  const status = $("#preview-status");
  const dlVideo = $("#download-video");
  const dlZip = $("#download-zip");
  if (!state.batchId) {
    empty.classList.remove("hidden");
    empty.innerHTML = `<p>${t("previewEmpty")}</p>`;
    videoEl.classList.add("hidden");
    status.textContent = t("previewNotStarted");
    dlVideo.classList.add("hidden");
    dlZip.classList.add("hidden");
    return;
  }
  if (!video) {
    const running = videos.some((v) => (v.output_status || "").includes("生成中"));
    videoEl.classList.add("hidden");
    empty.classList.remove("hidden");
    empty.innerHTML = `<p>${running ? t("previewRendering") : t("previewWaiting")}</p>`;
    status.textContent = running ? t("previewRenderingStatus") : t("previewWaitingStatus");
    dlVideo.classList.add("hidden");
    dlZip.classList.add("hidden");
    return;
  }
  videoEl.src = video.video_url;
  videoEl.classList.remove("hidden");
  empty.classList.add("hidden");
  status.textContent = t("previewReady");
  dlVideo.href = video.video_url;
  dlVideo.classList.remove("hidden");
  if (video.script_id) {
    dlZip.href = `/api/scripts/${video.script_id}/download/zip`;
    dlZip.classList.remove("hidden");
  } else {
    dlZip.classList.add("hidden");
  }
}

async function pollBatch() {
  if (!state.batchId) {
    renderCanvas();
    renderInspector();
    renderPreview();
    renderBranchTabs();
    renderBranchCompare();
    return;
  }
  try {
    const scripts = await api(`/api/scripts?batch_id=${encodeURIComponent(state.batchId)}`);
    const ids = scripts.map((s) => s.id);
    const [prompts, videos] = await Promise.all([api("/api/prompts"), api("/api/videos")]);
    state.scripts = scripts;
    state.prompts = prompts.filter((p) => ids.includes(p.script_id));
    state.videos = videos.filter((v) => ids.includes(v.script_id));
    if (!state.activeScriptId && scripts.length) state.activeScriptId = scripts[scripts.length - 1].id;
    if (state.activeScriptId && !ids.includes(state.activeScriptId)) state.activeScriptId = scripts[scripts.length - 1]?.id || "";
    renderCanvas();
    renderInspector();
    renderPreview();
    renderBranchTabs();
    renderBranchCompare();
    if (state.ui.copilotState === COPILOT_STATE.BUILDING && isWorkflowSettled()) {
      if (state.polling) {
        clearInterval(state.polling);
        state.polling = null;
      }
      setCopilotState(COPILOT_STATE.READY, { force: true });
    }
    updateAiStatus();
  } catch (err) {
    if (err.status !== 401) showError(t("errSync", { msg: err.message }));
  }
}

function startPolling() {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(pollBatch, 4500);
  updateAiStatus();
}

function resetProject() {
  if (state.polling) {
    clearInterval(state.polling);
    state.polling = null;
  }
  state.batchId = "";
  state.activeScriptId = "";
  state.scripts = [];
  state.prompts = [];
  state.videos = [];
  state.selectedNode = "productInfo";
  state.workflow.input = {
    brief: "",
    sourceUrl: "",
    referenceVideoUrl: "",
    materialContext: "",
    product: "",
    direction: "",
    language: "英语",
    count: 1,
    ratio: "9:16",
  };
  syncRunCountControl();
  state.ui.pendingAttachments = [];
  state.canvas.dirtyNodes.clear();
  state.canvas.dirtyReasons = {};
  state.compare.leftScriptId = "";
  state.compare.rightScriptId = "";
  state.compare.onlyDiff = false;
  state.ui.inspectorOpen = false;
  state.ui.copilotState = COPILOT_STATE.PLANNING;
  state.ui.thinkingAborted = false;
  state.canvas.zoom = 1;
  state.canvas.view = { x: 0, y: 0 };
  clearLinkDraft();
  closeInspector();
  clearPendingAttachments();
  $("#batch-label").textContent = "";
  updateEstimate("");
  showError("");
  renderCanvas();
  renderInspector();
  renderPreview();
  renderBranchTabs();
  renderBranchCompare();
  updateAiStatus();
}

function focusInputNode() {
  openInspector("brief");
  const board = $("#canvas-board");
  const pos = state.canvas.layout.brief || { x: 320, y: 120 };
  const z = state.canvas.zoom || 1;
  if (board) {
    state.canvas.view.x = board.clientWidth / 2 - (pos.x + NODE_WIDTH / 2) * z;
    state.canvas.view.y = board.clientHeight / 2 - 80 * z;
    applyCanvasViewport();
    renderCanvasLinks();
  }
}

function applyTemplate(name) {
  const templates = {
    "quick-ugc": "用真实 UGC 口吻做 15 秒户外电源广告，前 2 秒强钩子。",
    "product-demo": "做一条产品讲解广告，突出三大卖点并给明确 CTA。",
    "benefit-hook": "从痛点切入，先讲停电焦虑，再给产品解决方案。",
  };
  const txt = templates[name];
  if (!txt) return;
  state.workflow.input.brief = txt;
  markDirtyFrom("brief", "Brief.template");
  addChat("assistant", t("chatTplApplied"));
  setCopilotState(COPILOT_STATE.READY, { force: true });
  renderChat();
  renderCanvas();
  renderInspector();
}

function stopThinking() {
  if (state.ui.copilotState !== COPILOT_STATE.THINKING) return;
  state.ui.thinkingAborted = true;
  window.clearTimeout(state.ui.thinkingTimer);
}

async function handleChat(text) {
  const raw = text.trim();
  const hasAttach = hasPendingAttachments();
  if (!raw && !hasAttach) return;
  if (state.ui.copilotState === COPILOT_STATE.THINKING || state.ui.copilotState === COPILOT_STATE.BUILDING) return;

  if (state.ui.copilotState === COPILOT_STATE.ERROR) {
    state.ui.copilotState = state.chat.length ? COPILOT_STATE.READY : COPILOT_STATE.PLANNING;
  }

  const videoUrl = extractVideoUrlFromText(raw);
  const productUrl = extractProductUrlFromText(raw);
  // 仅在上传了文件时走素材解析；链接在下方并入 workflow，不强制解析
  const shouldAnalyzeMaterials = hasAttach;

  addChat("user", raw || (hasAttach ? t("chatAttachOnly") : raw));
  state.ui.thinkingAborted = false;
  setCopilotState(COPILOT_STATE.THINKING, { force: true });
  renderChat();

  await sleep(THINKING_MIN_MS);
  if (state.ui.thinkingAborted) {
    setCopilotState(state.chat.length ? COPILOT_STATE.READY : COPILOT_STATE.PLANNING, { force: true });
    renderChat();
    return;
  }

  if (shouldAnalyzeMaterials) {
    if (!(await ensureAuthenticated())) {
      setCopilotState(COPILOT_STATE.READY, { force: true });
      renderChat();
      return;
    }
    try {
      const result = await analyzeIntakeMaterials({
        userNote: raw,
        referenceVideoUrl: videoUrl || state.workflow.input.referenceVideoUrl,
        productPageUrl: productUrl || state.workflow.input.sourceUrl,
      });
      clearPendingAttachments();
      applyIntakeResult(result);
      if (videoUrl) state.workflow.input.referenceVideoUrl = videoUrl;
      if (productUrl) state.workflow.input.sourceUrl = productUrl;
      let reply = t("chatIntakeDone", { product: result.product_name || t("mentionProduct") });
      if (result.confidence_notes) reply += `\n\n${result.confidence_notes}`;
      const status = intakeStatus();
      if (!status.ready) reply += `\n\n${intakeGuideMessage(status)}`;
      finishChatTurn(reply, { focusInput: true });
      renderInspector();
      renderCanvas();
      return;
    } catch (err) {
      const msg = err.message || formatApiError(err.payload || {}, "素材解析失败");
      if (err.status === 401) showError(t("loginRequired"));
      else showError(msg);
      const failTpl = t("chatIntakeFailed");
      const failText =
        failTpl !== "chatIntakeFailed"
          ? failTpl.replace("{msg}", msg)
          : `素材解析失败：${msg}`;
      finishChatTurn(failText, { focusInput: true });
      return;
    }
  }

  const parsed = parseMentions(raw);
  const low = raw.toLowerCase();

  // 对话里带的链接：轻量写入 Input，不触发整段素材解析
  if (videoUrl) state.workflow.input.referenceVideoUrl = videoUrl;
  if (productUrl) state.workflow.input.sourceUrl = productUrl;

  if (low.includes("run") || low.includes("运行") || low.includes("开始")) {
    if (!state.workflow.input.brief) {
      finishChatTurn(t("chatGuideBrief"), { focusInput: true });
      return;
    }
    await runWorkflow();
    return;
  }
  if (await handleNodeAgentCommand(raw, low)) return;
  if ((low.includes("hook") || low.includes("开头")) && /(节点|脚本|查看|切到|inspect|open)/i.test(low)) {
    state.selectedNode = "script";
    finishChatTurn(t("chatHintHook"));
    return;
  }
  if ((low.includes("分镜") || low.includes("story")) && /(节点|查看|切到|inspect|open)/i.test(low)) {
    state.selectedNode = "storyboard";
    finishChatTurn(t("chatHintStoryboard"));
    return;
  }
  if ((low.includes("视频") || low.includes("video")) && /(节点|查看|切到|inspect|open)/i.test(low)) {
    state.selectedNode = "render";
    finishChatTurn(t("chatHintVideo"));
    return;
  }

  if (isGreetingOrSmallTalk(raw)) {
    finishChatTurn(t("chatGuideGreeting"), { focusInput: true });
    return;
  }

  const changed = applyChatToWorkflow(parsed, raw);
  const hasMention = !!(parsed.product || parsed.direction);

  if (!looksLikeAdIntent(raw) && !hasMention) {
    finishChatTurn(t("chatGuideVague"), { focusInput: true });
    return;
  }

  const status = intakeStatus();
  let reply = intakeGuideMessage(status);
  if (changed && parsed.brief && looksLikeAdIntent(raw)) {
    const snippet = parsed.brief.length > 48 ? `${parsed.brief.slice(0, 48)}…` : parsed.brief;
    if (!status.ready) {
      reply = t("chatBriefPartial", { snippet, next: intakeGuideMessage(status) });
    }
  }
  finishChatTurn(reply, { focusInput: true });
}

async function boot() {
  await window.FlowI18n.initLocale();
  applyLegacyFallbackCompat();
  state.appMeta = await api("/api/meta");
  const [cfg, pricing, intakeFormats] = await Promise.all([
    api("/api/toc/config").catch(() => ({ default_language: "英语" })),
    api("/api/billing/pricing").catch(() => ({})),
    api("/api/toc/intake/formats").catch(() => null),
  ]);
  state.intakeFormats = intakeFormats;
  const attachInput = $("#attach-materials-input");
  if (attachInput && intakeFormats?.accept) attachInput.setAttribute("accept", intakeFormats.accept);
  syncDropzoneHint();
  state.purchaseUrl = pricing.purchase_url || "";
  state.workflow.input.language = cfg.default_language || "英语";
  syncRunCountControl();
  updateUserHeader();
  bindCanvasBoardInteractions();
  renderChat();
  renderCanvas();
  renderInspector();
  renderPreview();
  renderBranchCompare();
  applyCanvasViewport();
  if (localStorage.getItem("promo_dismissed")) $("#promo-banner")?.classList.add("hidden");
  setCopilotOpen(window.innerWidth > 1024);
  centerCanvasView();
  applyCanvasViewport();
  updateAiStatus();
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const v = input.value.trim();
  if (!v && !hasPendingAttachments()) return;
  input.value = "";
  await handleChat(v);
});
$("#run-workflow-btn").addEventListener("click", runWorkflow);
$("#new-project-btn").addEventListener("click", resetProject);
$("#login-btn").addEventListener("click", ensureAuthenticated);
$("#buy-btn").addEventListener("click", openPurchase);
$("#vip-banner-cta")?.addEventListener("click", openPurchase);
$("#template-strip").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-template]");
  if (!btn) return;
  applyTemplate(btn.dataset.template);
});
$("#zoom-out-btn")?.addEventListener("click", () => {
  state.canvas.zoom = clampZoom(state.canvas.zoom - 0.1);
  applyCanvasZoom();
  renderCanvasLinks();
});
$("#zoom-in-btn")?.addEventListener("click", () => {
  state.canvas.zoom = clampZoom(state.canvas.zoom + 0.1);
  applyCanvasZoom();
  renderCanvasLinks();
});
$("#zoom-label")?.addEventListener("click", () => {
  state.canvas.zoom = 1;
  centerCanvasView();
  applyCanvasViewport();
  renderCanvasLinks();
});
$("#zoom-fit-btn")?.addEventListener("click", () => {
  const board = $("#canvas-board");
  if (!board) return;
  const fitByWidth = board.clientWidth / state.canvas.size.w;
  const fitByHeight = board.clientHeight / state.canvas.size.h;
  state.canvas.zoom = clampZoom(Math.min(fitByWidth, fitByHeight));
  centerCanvasView();
  applyCanvasViewport();
  renderCanvasLinks();
});
$$("[data-ui-locale]").forEach((btn) => {
  btn.addEventListener("click", () => window.FlowI18n.setLocale(btn.dataset.uiLocale));
});
window.addEventListener("ui-locale-change", () => {
  applyLegacyFallbackCompat();
  syncRunCountControl();
  syncDropzoneHint();
  renderChat();
  renderCanvas();
  renderInspector();
  renderPreview();
  renderBranchCompare();
  updateUserHeader();
});
$("#inspector-close")?.addEventListener("click", closeInspector);

$("#promo-close")?.addEventListener("click", () => {
  localStorage.setItem("promo_dismissed", "1");
  $("#promo-banner")?.classList.add("hidden");
});
$("#chat-stop")?.addEventListener("click", stopThinking);
$("#copilot-toggle")?.addEventListener("click", toggleCopilot);
$("#copilot-close")?.addEventListener("click", () => setCopilotOpen(false));
$("#copilot-collapse")?.addEventListener("click", () => setCopilotOpen(false));
$("#toggle-grid-btn")?.addEventListener("click", () => {
  state.ui.showGrid = !state.ui.showGrid;
  $("#canvas-board")?.classList.toggle("no-grid", !state.ui.showGrid);
  $("#toggle-grid-btn")?.setAttribute("aria-pressed", String(state.ui.showGrid));
});
$("#dock-pan")?.addEventListener("click", () => {
  state.ui.panMode = !state.ui.panMode;
  $("#canvas-board")?.classList.toggle("pan-mode", state.ui.panMode);
  $("#dock-pan")?.classList.toggle("active", state.ui.panMode);
  $("#dock-pan")?.setAttribute("aria-pressed", String(state.ui.panMode));
});
$("#dock-run")?.addEventListener("click", runWorkflow);
$("#dock-focus-input")?.addEventListener("click", focusInputNode);
$("#header-count")?.addEventListener("change", (e) => {
  state.workflow.input.count = Number(e.target.value || 1);
});
$("#chat-input")?.addEventListener("input", (e) => {
  const input = e.target;
  const pos = input.selectionStart ?? 0;
  // 产品以 Input 节点为主；这里只保留显式按钮触发的 @ 插入，避免对话区二次选择打断。
  if (pos > 0 && input.value[pos - 1] === "@") closeMentionPopover();
});
$("#add-files-btn")?.addEventListener("click", () => $("#attach-materials-input")?.click());
$("#attach-materials-input")?.addEventListener("change", (e) => {
  const files = [...(e.target.files || [])];
  if (!files.length) return;
  addPendingFiles(files);
  e.target.value = "";
});

(() => {
  const box = $("#chat-form .creatify-composer-box");
  if (!box) return;
  let dragDepth = 0;
  const setActive = (active) => box.classList.toggle("drag-over", active);

  box.addEventListener("dragenter", (e) => {
    if (!isFileDragEvent(e)) return;
    e.preventDefault();
    dragDepth += 1;
    setActive(true);
  });
  box.addEventListener("dragover", (e) => {
    if (!isFileDragEvent(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    setActive(true);
  });
  box.addEventListener("dragleave", (e) => {
    if (!isFileDragEvent(e)) return;
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) setActive(false);
  });
  box.addEventListener("drop", (e) => {
    if (!isFileDragEvent(e)) return;
    e.preventDefault();
    dragDepth = 0;
    setActive(false);
    const files = [...(e.dataTransfer.files || [])];
    if (!files.length) return;
    addPendingFiles(files);
  });

  document.addEventListener("dragover", (e) => {
    if (isFileDragEvent(e)) e.preventDefault();
  });
  document.addEventListener("drop", (e) => {
    const inDropzone = e.target instanceof Element && !!e.target.closest("#chat-form .creatify-composer-box");
    if (isFileDragEvent(e) && !inDropzone) {
      e.preventDefault();
    }
  });
})();

boot().catch((err) => showError(t("errInit", { msg: err.message })));
