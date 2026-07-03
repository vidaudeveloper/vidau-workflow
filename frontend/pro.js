const API = "";

let redirectingToLogin = false;

function redirectToLogin() {
  if (redirectingToLogin) return;
  redirectingToLogin = true;
  const next = encodeURIComponent(location.pathname + location.search + location.hash);
  location.href = `/login?next=${next}`;
}

function isAuthRequired() {
  return !!window.appMeta?.auth_enabled;
}

function isLoggedIn() {
  return !isAuthRequired() || !!window.appMeta?.current_user;
}

/** 401 时若已有 Flow session Cookie 则重试，不静默用主站 SSO 自动登录 */
async function tryRecoverSession() {
  try {
    const res = await fetch(API + "/api/meta", { credentials: "include" });
    const meta = await res.json();
    window.appMeta = meta;
    if (meta.current_user) {
      renderCurrentUser(meta.current_user);
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

/** 需要登录的操作：未登录则跳转登录页 */
function ensureLoggedInOrRedirect() {
  if (isLoggedIn()) return true;
  redirectToLogin();
  return false;
}

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const processingKeys = new Set();
const backgroundTasks = [];
let videoPollTimer = null;

function getActiveTab() {
  return document.querySelector("#tabs .tab.active")?.dataset.tab || "";
}

function switchTab(name) {
  $(`#tabs .tab[data-tab="${name}"]`)?.click();
}

function getDefaultReviewer() {
  return $("#default-reviewer")?.value?.trim() || localStorage.getItem("reviewer") || "";
}

function saveDefaultReviewer() {
  const v = $("#default-reviewer")?.value?.trim();
  if (v) localStorage.setItem("reviewer", v);
}

function removeTask(task, animate = false) {
  const idx = backgroundTasks.indexOf(task);
  if (idx < 0) return;
  if (!animate) {
    backgroundTasks.splice(idx, 1);
    renderTaskTray();
    return;
  }
  const tray = $("#task-tray");
  const el = tray?.querySelector(`[data-task-id="${task.id}"]`);
  if (el) {
    el.classList.add("fade-out");
    setTimeout(() => {
      const i = backgroundTasks.indexOf(task);
      if (i >= 0) backgroundTasks.splice(i, 1);
      renderTaskTray();
    }, 350);
  } else {
    backgroundTasks.splice(idx, 1);
    renderTaskTray();
  }
}

function scheduleTaskRemoval(task, delayMs = 2800) {
  if (task._removeTimer) clearTimeout(task._removeTimer);
  task._removeTimer = setTimeout(() => removeTask(task, true), delayMs);
}

function renderTaskTray() {
  const tray = $("#task-tray");
  const visible = backgroundTasks.filter((t) => t.status === "running");
  if (!visible.length) {
    tray.classList.add("hidden");
    tray.innerHTML = "";
    return;
  }
  tray.classList.remove("hidden");
  tray.innerHTML = visible
    .slice(-3)
    .map(
      (t) => `
    <div class="task-item ${t.status}" data-task-id="${t.id}" data-panel="${esc(t.panel)}" title="点击跳转">
      <span class="task-dot"></span>
      <span>${esc(t.label)}…</span>
    </div>`
    )
    .join("");
  tray.querySelectorAll(".task-item").forEach((el) => {
    el.onclick = () => {
      const panel = el.dataset.panel;
      if (panel) $(`#tabs .tab[data-tab="${panel}"]`)?.click();
    };
  });
}

let backgroundPollTimer = null;

function startBackgroundPoll(panel, opts = {}) {
  const maxRounds = opts.maxRounds ?? 36;
  const intervalMs = opts.intervalMs ?? 5000;
  const extraPanels = opts.extraPanels || [];
  if (backgroundPollTimer) clearInterval(backgroundPollTimer);
  let n = 0;
  backgroundPollTimer = setInterval(() => {
    n++;
    refreshBadges();
    const active = getActiveTab();
    if (active === panel || extraPanels.includes(active)) loadPanel(active);
    if (n >= maxRounds) {
      clearInterval(backgroundPollTimer);
      backgroundPollTimer = null;
    }
  }, intervalMs);
}

function runInBackground(label, panel, fn) {
  const task = { id: crypto.randomUUID(), label, panel, status: "running", error: "" };
  backgroundTasks.push(task);
  renderTaskTray();
  (async () => {
    try {
      const result = await fn();
      if (result?.queued) {
        const msg = result?.autopilot
          ? `${label} — 全流程已在后台运行，请到「视频产出」查看进度`
          : panel === "videos"
            ? `${label} — Seedance 2.0 已启动，见视频产出进度`
            : `${label} — 已提交后台，可继续其他操作`;
        toast(msg);
        removeTask(task);
        startBackgroundPoll(panel, result?.autopilot ? { maxRounds: 720, intervalMs: 10000, extraPanels: ["scripts", "prompts", "videos", "batches"] } : {});
        refreshBadges();
        if (getActiveTab() === panel) loadPanel(panel);
        return;
      }
      task.status = "done";
      toast(`${label} 完成`);
      refreshBadges();
      if (getActiveTab() === panel) loadPanel(panel);
      scheduleTaskRemoval(task);
    } catch (err) {
      task.status = "error";
      task.error = err.message;
      if (err.status === 402 && err.payload) {
        handleApiError(err, err.payload, `${label} 失败: `);
      } else {
        toast(`${label} 失败: ${err.message}`);
      }
      if (getActiveTab() === panel) loadPanel(panel);
      scheduleTaskRemoval(task);
    } finally {
      renderTaskTray();
    }
  })();
}

function markCardProcessing(type, id, on) {
  const key = `${type}:${id}`;
  if (on) processingKeys.add(key);
  else processingKeys.delete(key);
  const el = document.querySelector(`[data-type="${type}"][data-id="${id}"]`);
  if (el) el.classList.toggle("is-processing", on);
}

window.toggleRejectPanel = (panelId) => {
  const el = document.getElementById(`reject-${panelId}`);
  if (el) el.classList.toggle("hidden");
};

// --- tabs ---
$$("#tabs .tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (window.appMeta?.auth_enabled && !window.appMeta?.current_user) {
      redirectToLogin();
      return;
    }
    $$("#tabs .tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $(`#panel-${tab.dataset.tab}`).classList.add("active");
    loadPanel(tab.dataset.tab);
  });
});

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 3000);
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (opts.body && !(opts.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }
  const res = await fetch(API + path, { credentials: "include", ...opts, headers });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    if (!opts._authRetried) {
      const recovered = await tryRecoverSession();
      if (recovered) {
        return api(path, { ...opts, _authRetried: true });
      }
    }
    if (opts.background) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "未登录");
    }
    redirectToLogin();
    await new Promise(() => {});
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const detail = err.detail;
    let msg = res.statusText;
    if (typeof detail === "string") msg = detail;
    else if (Array.isArray(detail)) msg = detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
    else if (detail && typeof detail === "object") msg = detail.message || JSON.stringify(detail);
    const error = new Error(msg || `HTTP ${res.status}`);
    error.status = res.status;
    error.payload = err;
    throw error;
  }
  return res.json();
}

async function uploadProductImage(file) {
  const fd = new FormData();
  fd.append("file", file);
  return api("/api/uploads/product-image", { method: "POST", body: fd });
}

const MAX_PRODUCT_IMAGES = 9;
const MAX_IMAGE_BYTES = 30 * 1024 * 1024;

let metaProducts = [];

function updateProductConversionHint() {
  const ps = $("#product-select");
  const hint = $("#product-conversion-hint");
  if (!ps || !hint) return;
  const prod = metaProducts.find((p) => p.id === ps.value);
  if (prod) {
    const m = prod.conversion_method || "视频挂链";
    hint.textContent =
      m === "Bio引流"
        ? `转化方式：${m}（不挂车，CTA 引导点主页 Bio）`
        : `转化方式：${m}（CTA 引导点视频下方商品链接）`;
  } else {
    hint.textContent = "";
  }
}

function productImageUrls(item) {
  if (item.image_urls?.length) return item.image_urls;
  return item.image_url ? [item.image_url] : [];
}

function renderProductImageGrid(container, { serverUrls, pendingFiles, onRemoveServer, onRemovePending }) {
  const items = [
    ...serverUrls.map((url, i) => ({ type: "server", url, index: i })),
    ...pendingFiles.map((file, i) => ({
      type: "pending",
      url: URL.createObjectURL(file),
      index: i,
      file,
    })),
  ];
  if (!items.length) {
    container.classList.add("hidden");
    container.innerHTML = "";
    return;
  }
  container.classList.remove("hidden");
  container.innerHTML = items
    .map(
      (item) => `
    <div class="image-thumb">
      <img src="${esc(item.url)}" alt="产品图" />
      <button type="button" class="btn-remove" data-type="${item.type}" data-index="${item.index}">×</button>
    </div>`
    )
    .join("");
  container.querySelectorAll(".btn-remove").forEach((btn) => {
    btn.onclick = () => {
      const type = btn.dataset.type;
      const index = Number(btn.dataset.index);
      if (type === "server") onRemoveServer(index);
      else onRemovePending(index);
    };
  });
}

// --- meta & batch form ---

async function loadMeta(options = {}) {
  const res = await fetch(API + "/api/meta", { credentials: "include" });
  const meta = await res.json();
  window.appMeta = meta;
  renderCurrentUser(meta.current_user);
  updateConfigSyncButtons(meta.current_user);
  if (meta.auth_enabled && !meta.current_user && !options.allowGuest) {
    redirectToLogin();
    return meta;
  }
  const { products, directions, accounts, difficulties } = meta;
  metaProducts = products || [];
  const ps = $("#product-select");
  const ds = $("#direction-select");
  const as = $("#account-select");
  const ls = $("#difficulty-select");
  ps.innerHTML = "";
  ds.innerHTML = "";
  products.forEach((p) => {
    let label = p.name;
    if (!p.image_count) label += "（未上传图片）";
    else if (!p.specs_confirmed) label += "（外观未确认）";
    const opt = new Option(label, p.id);
    opt.disabled = !p.image_count || !p.specs_confirmed;
    ps.add(opt);
  });
  ps.onchange = updateProductConversionHint;
  updateProductConversionHint();
  directions.forEach((d) => {
    const label = d.short_code ? `${d.short_code} · ${d.name}` : d.name;
    ds.add(new Option(label, d.id));
  });
  if (as) {
    as.innerHTML = '<option value="">不指定（通用）</option>';
    (accounts || []).forEach((a) => as.add(new Option(a.label, a.id)));
  }
  if (ls) {
    ls.innerHTML = "";
    const diffs = difficulties?.length ? difficulties : [{ name: "低级" }];
    diffs.forEach((d) => ls.add(new Option(d.name, d.name)));
  }
}

function renderCurrentUser(user) {
  const account = $("#user-account");
  const logoutBtn = $("#logout-btn");
  const displayName = $("#user-display-name");
  const emailEl = $("#user-email");
  const avatarImg = $("#user-avatar");
  const avatarFallback = $("#user-avatar-fallback");
  const testBanner = $("#test-env-banner");
  if (!account) return;
  if (!user) {
    account.classList.add("hidden");
    if (logoutBtn) logoutBtn.classList.add("hidden");
    if (testBanner) testBanner.classList.add("hidden");
    renderCreditsBadge(null);
    return;
  }
  account.classList.remove("hidden");
  if (logoutBtn) logoutBtn.classList.remove("hidden");
  const name = user.display_name || user.email || user.id || "用户";
  if (displayName) displayName.textContent = name;
  if (emailEl) emailEl.textContent = user.email || "";
  if (avatarImg && avatarFallback) {
    const avatar = (user.avatar || "").trim();
    if (avatar) {
      avatarImg.src = avatar;
      avatarImg.classList.remove("hidden");
      avatarFallback.classList.add("hidden");
    } else {
      avatarImg.classList.add("hidden");
      avatarFallback.textContent = name.charAt(0).toUpperCase();
      avatarFallback.classList.remove("hidden");
    }
  }
  renderCreditsBadge(user.coin);
  applyCurrentUserToForms(user);
  if (testBanner) {
    const notice =
      sessionStorage.getItem("test_login_notice") ||
      (user.is_test
        ? "当前为测试账号：仅能看到本账号创建的批次/脚本/成片，与正式账号数据不互通。"
        : "");
    if (user.is_test && notice) {
      testBanner.innerHTML = `<strong>测试环境</strong> — ${esc(notice)}`;
      testBanner.classList.remove("hidden");
    } else {
      testBanner.classList.add("hidden");
    }
  }
}

function getPurchaseUrl() {
  return window.appMeta?.billing?.purchase_url || "https://www.vidau.ai/agent-price?agent_code=vidau_flow";
}

function openPurchasePage() {
  window.open(getPurchaseUrl(), "_blank", "noopener,noreferrer");
}

function renderCreditsBadge(coin) {
  const badge = $("#credits-badge");
  const val = $("#credits-value");
  const buyBtn = $("#buy-credits-btn");
  const billing = window.appMeta?.billing;
  const showBilling = billing?.enabled && window.appMeta?.auth_mode === "platform";
  if (buyBtn) {
    if (showBilling) buyBtn.classList.remove("hidden");
    else buyBtn.classList.add("hidden");
  }
  if (!badge || !val) return;
  if (!showBilling || coin === undefined || coin === null) {
    badge.classList.add("hidden");
    return;
  }
  val.textContent = Number(coin).toLocaleString("en-US");
  badge.classList.remove("hidden");
  badge.title = `主站积分余额 · 点击购买`;
  badge.style.cursor = "pointer";
  badge.onclick = openPurchasePage;
}

function handleApiError(err, data, fallbackMsg) {
  if (data?.code === "insufficient_credits" || data?.purchase_url) {
    const url = data.purchase_url || getPurchaseUrl();
    toast(`积分不足（余额 ${data.coin ?? "—"}，需 ${data.needed ?? "—"}）`);
    if (confirm(`积分不足，是否前往购买套餐？\n${url}`)) {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return;
  }
  toast(`${fallbackMsg}${err?.message || data?.detail || "未知错误"}`);
}

// 出片完成等场景刷新主站积分余额
async function refreshCredits() {
  if (window.appMeta?.auth_mode !== "platform") return;
  try {
    const me = await api("/api/user/me", { background: true });
    renderCreditsBadge(me.coin);
  } catch {
    /* 保留上次余额 */
  }
}
window.refreshCredits = refreshCredits;

function applyCurrentUserToForms(user) {
  if (!user || !window.appMeta?.auth_enabled) return;
  const name = user.display_name || user.email || "";
  const creator = document.querySelector('input[name="creator"]');
  if (creator) {
    creator.value = name;
    creator.readOnly = true;
    creator.title = "已绑定当前登录用户";
  }
  const reviewer = $("#default-reviewer");
  if (reviewer && !reviewer.value.trim()) {
    reviewer.value = name;
    localStorage.setItem("reviewer", name);
  }
}

$("#buy-credits-btn")?.addEventListener("click", openPurchasePage);

$("#logout-btn")?.addEventListener("click", async () => {
  try {
    if (window.appMeta?.sso?.enabled) {
      await window.VidauSsoHelper?.logout(window.appMeta.sso);
    }
    await fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
  } catch {
    /* ignore */
  }
  redirectingToLogin = false;
  redirectToLogin();
});

function readBatchForm(form) {
  const fd = new FormData(form);
  const productId = fd.get("product");
  const selected = metaProducts.find((p) => p.id === productId);
  if (!productId || !selected?.image_count) {
    toast("所选产品未上传图片，请先在「固定配置 → 产品」中为该产品上传 1-9 张产品图");
    return null;
  }
  if (!selected?.specs_confirmed) {
    toast("所选产品外观说明尚未确认，请先在「固定配置 → 产品」中 AI 识别并人工确认");
    return null;
  }
  const count = Number(fd.get("count")) || 3;
  return {
    product: fd.get("product"),
    direction: fd.get("direction"),
    count,
    extra_instruction: fd.get("extra_instruction") || "",
    creator: fd.get("creator") || "",
    difficulty_level: fd.get("difficulty_level") || "低级",
    account_id: fd.get("account_id") || "",
    language: fd.get("language") || "英语",
    producer: fd.get("producer") || "",
    use_first_frame: fd.get("use_first_frame") === "on",
    selected,
  };
}

$("#batch-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!ensureLoggedInOrRedirect()) return;
  const body = readBatchForm(e.target);
  if (!body) return;
  const { selected, ...payload } = body;
  runInBackground(`批次生成 ${payload.count} 条脚本`, "scripts", async () => {
    const res = await api("/api/batches", { method: "POST", body: JSON.stringify(payload) });
    const result = $("#batch-result");
    result.classList.remove("hidden");
    result.innerHTML = `批次 <strong>${res.batch_id}</strong> 已提交，脚本后台生成中 → <a href="#" onclick="document.querySelector('[data-tab=scripts]').click();return false" style="color:var(--accent)">去脚本审核</a>`;
    loadBatches();
    return res;
  });
});

$("#submit-batch-autopilot")?.addEventListener("click", () => {
  if (!ensureLoggedInOrRedirect()) return;
  const form = $("#batch-form");
  const body = readBatchForm(form);
  if (!body) return;
  const { selected, ...payload } = body;
  const ok = confirm(
    `将自动完成以下步骤（跳过人工审核）：\n\n` +
      `1. 生成 ${payload.count} 条脚本\n` +
      `2. 自动通过脚本审核并生成分镜 Prompt\n` +
      `3. 自动通过 Prompt 审核并提交 Seedance 出片\n\n` +
      `全程在后台运行，单条视频约需 10–30 分钟。是否继续？`
  );
  if (!ok) return;
  runInBackground(`一键全流程 ${payload.count} 条`, "videos", async () => {
    const res = await api("/api/batches/autopilot", { method: "POST", body: JSON.stringify(payload) });
    const result = $("#batch-result");
    result.classList.remove("hidden");
    result.innerHTML =
      `批次 <strong>${res.batch_id}</strong> 全流程已启动（自动审核 + 出片）→ ` +
      `<a href="#" onclick="document.querySelector('[data-tab=videos]').click();return false" style="color:var(--accent)">查看视频产出</a>`;
    loadBatches();
    return res;
  });
});

// --- badges ---
const SCRIPT_GEN_REVIEW = new Set(["生成中", "排队中", "重生成中"]);
const SCRIPT_GEN_FLOW = new Set(["脚本生成中", "Prompt生成中", "重生成中", "处理中", "排队中"]);
const PROMPT_GEN_REVIEW = new Set(["Prompt重生成中"]);
const PROMPT_GEN_FLOW = new Set(["出片中", "Prompt重生成中", "处理中"]);

function scriptNeedsAttention(s) {
  return (
    s.review_status === "待审核" ||
    s.review_status === "失败" ||
    SCRIPT_GEN_REVIEW.has(s.review_status) ||
    SCRIPT_GEN_FLOW.has(s.flow_status)
  );
}

function promptNeedsAttention(p) {
  return (
    p.review_status === "待审核" ||
    PROMPT_GEN_REVIEW.has(p.review_status) ||
    PROMPT_GEN_FLOW.has(p.flow_status)
  );
}

function isScriptGenerating(s) {
  return SCRIPT_GEN_REVIEW.has(s.review_status) || SCRIPT_GEN_FLOW.has(s.flow_status);
}

function isPromptGenerating(p) {
  return PROMPT_GEN_REVIEW.has(p.review_status) || PROMPT_GEN_FLOW.has(p.flow_status);
}

function displayScriptStatus(s) {
  if (isScriptGenerating(s)) return s.flow_status || s.review_status;
  return s.review_status || "";
}

function displayPromptStatus(p) {
  if (isPromptGenerating(p)) return p.flow_status || p.review_status;
  return p.review_status || "";
}

function scriptSortKey(s) {
  if (isScriptGenerating(s)) return 0;
  if (s.review_status === "待审核") return 1;
  return 2;
}

function promptSortKey(p) {
  if (isPromptGenerating(p)) return 0;
  if (p.review_status === "待审核") return 1;
  return 2;
}

async function refreshBadges() {
  if (!window.appMeta?.current_user) {
    $("#badge-scripts").textContent = "0";
    $("#badge-prompts").textContent = "0";
    return;
  }
  try {
    const [scripts, prompts] = await Promise.all([
      api("/api/scripts", { background: true }),
      api("/api/prompts", { background: true }),
    ]);
    $("#badge-scripts").textContent = scripts.filter(scriptNeedsAttention).length;
    $("#badge-prompts").textContent = prompts.filter(promptNeedsAttention).length;
  } catch {
    /* 未登录时忽略 */
  }
}

// --- scripts ---
function statusTag(status) {
  const pending = [
    "待审核",
    "生成中",
    "排队中",
    "重生成中",
    "Prompt重生成中",
    "Prompt生成中",
    "出片中",
    "处理中",
    "脚本生成中",
    "自动审核中",
    "视频生成中",
    "待脚本审核",
  ];
  const pass = ["通过", "已交付", "待交付", "已生成", "全流程完成", "ok"];
  let cls = "fail";
  if (pending.includes(status)) cls = "pending";
  else if (pass.includes(status)) cls = "pass";
  return `<span class="tag ${cls}">${esc(status)}</span>`;
}

function formatVisionError(err) {
  if (!err) return "未知错误";
  if (typeof err === "string") return err;
  return err.message || String(err);
}

function clearVisionStatus(el) {
  if (!el) return;
  if (el._visionTimer) {
    clearInterval(el._visionTimer);
    el._visionTimer = null;
  }
  el.classList.add("hidden");
  el.innerHTML = "";
}

function renderVisionStatus(el, state, opts = {}) {
  if (!el) return;
  if (el._visionTimer) {
    clearInterval(el._visionTimer);
    el._visionTimer = null;
  }
  if (state === "idle") {
    clearVisionStatus(el);
    return;
  }
  el.classList.remove("hidden");
  if (state === "uploading") {
    const { done = 0, total = 0, name = "" } = opts;
    el.innerHTML = `
      <div class="gen-banner vision-status">
        <div class="gen-banner-head">
          <span class="pulse-dot"></span>
          <strong>步骤 1/2 · 上传产品图</strong>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${total ? Math.round((done / total) * 100) : 0}%"></div></div>
        <p class="muted vision-status-detail" style="margin-top:6px">正在上传 ${done}/${total}${name ? ` · ${esc(name)}` : ""}</p>
      </div>`;
    return;
  }
  if (state === "analyzing") {
    const { imageCount = 1, startedAt = Date.now() } = opts;
    el.innerHTML = `
      <div class="gen-banner vision-status">
        <div class="gen-banner-head">
          <span class="pulse-dot"></span>
          <strong>步骤 2/2 · AI 视觉分析中</strong>
        </div>
        <div class="progress-bar progress-bar-indeterminate"><div class="progress-fill"></div></div>
        <p class="muted vision-status-detail" data-vision-elapsed style="margin-top:6px">
          已分析 ${imageCount} 张参考图 · 已等待 0 秒（通常 15–90 秒，请勿关闭页面）
        </p>
      </div>`;
    const detail = el.querySelector("[data-vision-elapsed]");
    el._visionTimer = setInterval(() => {
      const sec = Math.floor((Date.now() - startedAt) / 1000);
      if (detail) {
        detail.textContent = `已分析 ${imageCount} 张参考图 · 已等待 ${sec} 秒（通常 15–90 秒，请勿关闭页面）`;
      }
    }, 1000);
    return;
  }
  if (state === "error") {
    const msg = formatVisionError(opts.error);
    el.innerHTML = `
      <div class="fail-reason vision-error">
        <strong>AI 识别失败</strong>
        <pre class="vision-error-body">${esc(msg)}</pre>
        <p class="muted" style="margin-top:8px">可检查：本地服务是否已重启并走 Vertex；产品图是否已上传成功。</p>
      </div>`;
  }
}

function renderGeneratingBanner(kind, item) {
  const scriptMsgs = {
    脚本生成中: "AI 正在撰写脚本（通常 10–40 秒）…",
    生成中: "AI 正在撰写脚本（通常 10–40 秒）…",
    排队中: "并行队列中，最多同时 3 条脚本生成，即将开始…",
    Prompt生成中: "脚本已通过，AI 正在生成分镜 Prompt…",
    重生成中: "按审核备注重生成脚本中…",
    处理中: "后台处理中，请稍候…",
  };
  const promptMsgs = {
    出片中: "已通过出片，Seedance 2.0 正在生成视频（见「视频产出」进度）",
    Prompt重生成中: "按审核备注重生成 Prompt 中…",
    处理中: "后台处理中，请稍候…",
  };
  const msgs = kind === "script" ? scriptMsgs : promptMsgs;
  const msg = msgs[item.flow_status] || msgs[item.review_status];
  if (!msg) return "";
  const label = kind === "script" ? displayScriptStatus(item) : displayPromptStatus(item);
  return `
    <div class="gen-banner">
      <div class="gen-banner-head">
        <span class="pulse-dot"></span>
        <strong>${esc(label)}</strong>
      </div>
      <p class="muted" style="margin:0">${esc(msg)}</p>
    </div>`;
}

function renderBatchGeneratingCards(batches, scripts) {
  return batches
    .filter((b) => b.status === "生成中")
    .map((b) => {
      const batchScripts = scripts.filter((s) => s.batch_id === b.id);
      const done = batchScripts.filter((s) => s.review_status === "待审核").length;
      const active = batchScripts.filter((s) =>
        ["生成中", "排队中"].includes(s.review_status)
      ).length;
      const total = b.count || 0;
      const pct = total ? Math.round((done / total) * 100) : 0;
      return `
    <article class="item-card is-generating" data-type="batch" data-id="${esc(b.id)}">
      <header>
        <div>
          ${workflowIdentity({ product: b.product, direction: b.direction, account_name: "见各脚本" }, b.id)}
        </div>
        ${statusTag("生成中")}
      </header>
      <div class="gen-banner">
        <div class="gen-banner-head">
          <span class="pulse-dot"></span>
          <strong>脚本生成中 · ${done}/${total}</strong>
        </div>
        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
        <p class="muted" style="margin-top:6px">已完成 ${done} 条${active ? ` · ${active} 条生成中` : ""}，共 ${total} 条</p>
      </div>
    </article>`;
    })
    .join("");
}

function renderFailedBatchCards(batches) {
  return batches
    .filter((b) => b.status === "生成失败")
    .map(
      (b) => `
    <article class="item-card" data-type="batch" data-id="${esc(b.id)}">
      <header>
        <div>
          ${workflowIdentity({ product: b.product, direction: b.direction, account_name: "见各脚本" }, b.id)}
        </div>
        ${statusTag("失败")}
      </header>
      <p class="muted">脚本生成未完成（可能因服务重启或接口错误）。可重新生成。</p>
      <div class="card-actions">
        <button class="btn warn btn-sm" onclick="retryBatch('${b.id}')">重新生成脚本</button>
        <button class="btn danger btn-sm" onclick="deleteFailedBatch('${b.id}')">删除</button>
      </div>
    </article>`
    )
    .join("");
}

window.retryBatch = (batchId) => {
  runInBackground("批次脚本重试", "scripts", async () => {
    const res = await api(`/api/batches/${batchId}/retry`, { method: "POST" });
    loadScripts();
    refreshBadges();
    return res;
  });
};

window.deleteFailedBatch = (batchId) => {
  if (!confirm("确认删除该失败批次？相关脚本记录将一并移除。")) return;
  runInBackground("删除失败批次", "scripts", async () => {
    await api(`/api/batches/${batchId}`, { method: "DELETE" });
    loadScripts();
    loadBatches();
    refreshBadges();
    return { ok: true };
  });
};

function formatProductSpec(raw) {
  if (!raw) return "";
  try {
    const spec = typeof raw === "string" ? JSON.parse(raw) : raw;
    const pu = spec.product_understanding;
    const beats = spec.interaction_beats || [];
    let html = "";
    if (pu && Object.keys(pu).length) {
      html += `<p class="muted"><strong>产品理解（AI）：</strong>${esc(pu.hero_product || "")} — ${esc(pu.appearance_notes || "")}</p>`;
      if (pu.forbidden_in_frame?.length) {
        html += `<p class="muted"><strong>禁止入镜：</strong>${esc(pu.forbidden_in_frame.join("；"))}</p>`;
      }
    }
    if (beats.length) {
      html += `<p class="muted"><strong>交互节拍：</strong></p><ul class="beats-list">${beats
        .map((b) => {
          const vo = b.voiceover ? ` · 口播：${esc(b.voiceover)}` : "";
          return `<li><span class="muted">${esc(b.time || "")}</span> ${esc(b.action || "")}${vo}</li>`;
        })
        .join("")}</ul>`;
    }
    const arc = spec.narrative_arc;
    if (arc && Object.keys(arc).length) {
      html += `<p class="muted"><strong>叙事结构：</strong>吸睛「${esc(arc.attention_0_3s || "")}」→ 悬念「${esc(arc.suspense_hook_12_15s || "")}」</p>`;
    }
    const vp = spec.voice_profile;
    if (vp && Object.keys(vp).length) {
      html += `<p class="muted"><strong>口播音色：</strong>${esc(vp.gender || "")} · ${esc(vp.tone || "")}${vp.age_tone ? " · " + esc(vp.age_tone) : ""}</p>`;
      if (vp.tts_voice) {
        html += `<p class="muted"><strong>TTS 音色：</strong>${esc(vp.tts_voice)}</p>`;
      }
      if (vp.seedance_hint) {
        html += `<p class="muted"><strong>Seedance 音色：</strong>${esc(vp.seedance_hint)}</p>`;
      }
    }
    const vb = spec.voiceover_budget;
    if (vb && typeof vb.total_words === "number") {
      const budgetTag = vb.within_budget
        ? `<span class="tag pass">预算内</span>`
        : `<span class="tag fail">超预算</span>`;
      html += `<p class="muted"><strong>口播预算：</strong>${vb.total_words} 词（A ${vb.words_part_a || 0} / B ${vb.words_part_b || 0}）· 预计 TTS ${vb.estimated_tts_sec || "?"}s ${budgetTag}</p>`;
      if (vb.warnings?.length) {
        html += `<ul class="beats-list">${vb.warnings.map((w) => `<li class="muted">⚠ ${esc(w)}</li>`).join("")}</ul>`;
      }
    }
    const voA = spec.voiceover_part_a || [];
    const voB = spec.voiceover_part_b || [];
    if (voA.length || voB.length) {
      const renderVo = (items, label) =>
        items.length
          ? `<p class="muted"><strong>${label}</strong></p><ul class="beats-list">${items
              .map(
                (v) =>
                  `<li><span class="muted">${esc(v.time || "")}</span> 「${esc(v.spoken || v.voiceover || "")}」</li>`
              )
              .join("")}</ul>`
          : "";
      html += renderVo(voA, "口播 Part A") + renderVo(voB, "口播 Part B");
    }
    return html;
  } catch {
    return "";
  }
}

function videoStatusTag(status) {
  let cls = "pass";
  if (status === "失败") cls = "fail";
  else if (["生成中", "排队中", "剪辑中", "待剪辑", "Prompt重生成中"].includes(status)) cls = "pending";
  return `<span class="tag ${cls}">${esc(status)}</span>`;
}

function isManualVideo(v) {
  return (v.output_mode || "").includes("人工") || (v.id || "").endsWith("-manual");
}

function displayVideoStatus(v) {
  if (isManualVideo(v) && v.output_status === "排队中") return "待剪辑";
  return v.output_status || "";
}

function parseSegmentJson(v) {
  try {
    const raw = v.segment_urls_json;
    if (!raw) return {};
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  } catch {
    return {};
  }
}

const SEEDANCE_PHASE_LABELS = {
  first_frame: "Part A 首帧",
  first_frame_part_b: "Part B 首帧",
  part_a: "Part A",
  part_b: "Part B",
  concat: "拼接",
  subtitles: "字幕",
  done: "完成",
};

function renderFirstFramePreview(v) {
  const blocks = [];
  if (v.first_frame_url) {
    blocks.push(`
    <div class="first-frame-preview">
      <p class="muted" style="margin-bottom:6px">Part A 首帧（0-15s · Nano Banana Pro）</p>
      <a href="${esc(v.first_frame_url)}" target="_blank" title="点击查看大图">
        <img src="${esc(v.first_frame_url)}" alt="Part A 首帧" class="first-frame-thumb" />
      </a>
    </div>`);
  }
  if (v.first_frame_url_part_b) {
    blocks.push(`
    <div class="first-frame-preview">
      <p class="muted" style="margin-bottom:6px">Part B 首帧（15-30s · Nano Banana Pro）</p>
      <a href="${esc(v.first_frame_url_part_b)}" target="_blank" title="点击查看大图">
        <img src="${esc(v.first_frame_url_part_b)}" alt="Part B 首帧" class="first-frame-thumb" />
      </a>
    </div>`);
  }
  return blocks.join("");
}

function renderSeedanceProgress(v) {
  if (isManualVideo(v)) {
    return `<p class="seedance-hint muted">未调用 Seedance 2.0（人工二次剪辑流程）</p>`;
  }
  const seg = parseSegmentJson(v);
  const p = seg.progress;
  const status = displayVideoStatus(v);
  if (!p && status === "生成中") {
    return `
    <div class="seedance-progress seedance-progress-active">
      <div class="seedance-progress-head">
        <strong>Seedance 2.0</strong>
        <span>启动中 · 0%</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
      <p class="muted" style="margin-top:6px">已通过出片，Seedance 正在排队/提交任务…</p>
    </div>`;
  }
  if (
    !p ||
    (!p.percent &&
      !p.task_id &&
      p.phase !== "first_frame" &&
      p.phase !== "first_frame_part_b" &&
      status !== "生成中")
  ) {
    if (status === "失败") return "";
    if (status === "待交付" && seg.part_a) {
      return `<p class="seedance-hint muted">Seedance 2.0 已完成 · Part A + Part B 已出片</p>`;
    }
    return "";
  }
  const pct = Math.min(100, Math.max(0, Number(p.percent) || 0));
  const phaseKey = p.phase || "";
  const phase = SEEDANCE_PHASE_LABELS[phaseKey] || phaseKey;
  const isFirstFrame = phaseKey === "first_frame" || phaseKey === "first_frame_part_b";
  const title = isFirstFrame ? "首帧生成 · Nano Banana Pro" : "Seedance 2.0";
  const defaultMsg = isFirstFrame
    ? phaseKey === "first_frame_part_b"
      ? "正在生成 Part B 首帧图…"
      : "正在用 Nano Banana Pro 生成首帧交互图…"
    : "";
  const apiStatus = p.seedance_status || "";
  const task = p.task_id ? `<span class="muted">任务 ID：${esc(p.task_id)}</span>` : "";
  const bar = isFirstFrame && !pct
    ? `<div class="progress-bar progress-bar-indeterminate"><div class="progress-fill"></div></div>`
    : `<div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>`;
  return `
    <div class="seedance-progress seedance-progress-active">
      <div class="seedance-progress-head">
        <strong>${esc(title)}</strong>
        <span>${esc(phase)}${isFirstFrame && !pct ? "" : ` · ${pct}%`}${apiStatus && !isFirstFrame ? " · " + esc(apiStatus) : ""}</span>
      </div>
      ${bar}
      ${task}
      <p class="muted" style="margin-top:6px">${esc(p.message || defaultMsg)}</p>
    </div>`;
}

function renderVideoSegments(v) {
  if (isManualVideo(v)) return "";
  const seg = parseSegmentJson(v);
  const status = displayVideoStatus(v);
  const busy = status === "生成中";
  const rows = [];
  if (seg.part_a) {
    rows.push(`
      <div class="segment-row">
        <a href="${esc(seg.part_a)}" target="_blank" style="color:var(--accent)">Part A (0-15s)</a>
        <button class="btn ghost btn-sm" ${busy ? "disabled" : ""} onclick="regenerateSegment('${v.id}','part_a')">重新生成</button>
      </div>`);
  }
  if (seg.part_b) {
    rows.push(`
      <div class="segment-row">
        <a href="${esc(seg.part_b)}" target="_blank" style="color:var(--accent)">Part B (15-30s)</a>
        <button class="btn ghost btn-sm" ${busy ? "disabled" : ""} onclick="regenerateSegment('${v.id}','part_b')">重新生成</button>
      </div>`);
  }
  if (!rows.length) return "";
  return `<div class="video-segments"><p class="muted" style="margin-bottom:6px">分段预览</p>${rows.join("")}</div>`;
}

function renderVideoDeleteAction(v) {
  const status = displayVideoStatus(v);
  if (status === "生成中") return "";
  return `<button class="btn danger btn-sm" onclick="deleteVideo('${v.id}')">删除</button>`;
}

function shotsTable(shots) {
  if (!shots?.length) return "<p class='muted'>无分镜</p>";
  const rows = shots
    .map(
      (s) =>
        `<tr><td>${esc(s.time)}</td><td>${esc(s.visual)}</td><td>${esc(s.audio)}</td><td>${esc(s.overlay)}</td></tr>`
    )
    .join("");
  return `<table class="shots-table"><thead><tr><th>时长</th><th>画面</th><th>口播</th><th>花字</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

/** 各步骤卡片统一展示：ID / 产品 / 方向 / 账号 */
function workflowIdentity(item, stepId) {
  const id = stepId ?? item?.id ?? item?.script_id ?? "-";
  return `
    <div class="workflow-identity">
      <div class="wf-row"><span class="wf-k">ID</span><code class="wf-v">${esc(id)}</code></div>
      <div class="wf-row"><span class="wf-k">产品</span><span class="wf-v">${esc(item?.product || "-")}</span></div>
      <div class="wf-row"><span class="wf-k">方向</span><span class="wf-v">${esc(item?.direction || "-")}</span></div>
      <div class="wf-row"><span class="wf-k">账号</span><span class="wf-v">${esc(item?.account_name || "通用")}</span></div>
    </div>`;
}

async function loadScripts() {
  const pendingOnly = $("#script-pending-only").checked;
  const batchId = $("#script-batch-filter").value;
  const [allScripts, batches] = await Promise.all([
    api(batchId ? `/api/scripts?batch_id=${batchId}` : "/api/scripts"),
    api("/api/batches"),
  ]);
  let scripts = pendingOnly ? allScripts.filter(scriptNeedsAttention) : allScripts;
  scripts = [...scripts].sort((a, b) => scriptSortKey(a) - scriptSortKey(b));
  const list = $("#scripts-list");
  const batchCards = pendingOnly
    ? renderBatchGeneratingCards(batches, allScripts) + renderFailedBatchCards(batches)
    : "";
  if (!batchCards && !scripts.length) {
    list.innerHTML = '<div class="empty">暂无脚本</div>';
    return;
  }
  list.innerHTML =
    batchCards +
    scripts
      .map((s) => {
        const generating = isScriptGenerating(s);
        const failed = s.review_status === "失败";
        const canReview = s.review_status === "待审核" && !generating;
        return `
    <article class="item-card${generating ? " is-generating" : ""}${failed ? " is-failed" : ""}" data-type="script" data-id="${s.id}">
      <header>
        <div>
          ${workflowIdentity(s, s.id)}
        </div>
        <div class="header-actions">
          ${statusTag(displayScriptStatus(s))}
          ${
            canReview
              ? `
            <button class="btn success btn-sm" onclick="submitReview('script','${s.id}','通过')">✓ 通过</button>
            <button class="btn danger btn-sm" onclick="submitReview('script','${s.id}','不通过-废弃')">废弃</button>
            <button class="btn ghost btn-sm" onclick="toggleRejectPanel('script-${s.id}')">更多</button>`
              : ""
          }
        </div>
      </header>
      ${generating ? renderGeneratingBanner("script", s) : ""}
      ${
        failed
          ? `<div class="fail-reason"><strong>生成失败</strong>${s.review_note ? ` · ${esc(s.review_note)}` : " · 可点上方批次「重新生成脚本」或新建批次重试"}</div>`
          : ""
      }
      ${
        canReview
          ? `<div id="reject-script-${s.id}" class="reject-panel hidden">
          <textarea id="note-script-${s.id}" rows="2" placeholder="不通过备注（重生成时必填）"></textarea>
          <div class="card-actions" style="margin-top:0">
            <button class="btn warn btn-sm" onclick="submitReview('script','${s.id}','不通过-重生成')">按备注重生成</button>
            <button class="btn warn btn-sm" onclick="submitReview('script','${s.id}','不通过-人工剪辑')">人工剪辑</button>
          </div>
        </div>`
          : s.review_note
            ? `<p class="muted">备注：${esc(s.review_note)}</p>`
            : ""
      }
      ${
        generating
          ? ""
          : `<details class="card-details" open>
        <summary>分镜详情</summary>
        <p><strong>Hook：</strong>${esc(s.hook)}</p>
        <p class="muted">${esc(s.outline)}</p>
        ${shotsTable(s.shots)}
        <p><strong>CTA：</strong>${esc(s.cta)}</p>
      </details>`
      }
    </article>`;
      })
      .join("");
}

window.submitReview = (type, id, status) => {
  const key = `${type}:${id}`;
  if (processingKeys.has(key)) return;
  const needsNote = status.includes("重生成") || status.includes("调Prompt");
  const noteEl = document.getElementById(`note-${type}-${id}`);
  const note = noteEl?.value?.trim() || "";
  if (needsNote && !note) {
    toggleRejectPanel(`${type}-${id}`);
    if (noteEl) noteEl.focus();
    toast("请先填写备注");
    return;
  }
  const reviewer = getDefaultReviewer();
  saveDefaultReviewer();
  const labels = {
    通过: type === "script" ? "脚本通过·生成Prompt" : "Prompt通过·出片",
    "不通过-废弃": "已废弃",
    "不通过-重生成": "脚本重生成",
    "不通过-人工剪辑": "转人工剪辑",
    "不通过-调Prompt": "Prompt重生成",
    "不通过-改人工剪": "转人工剪辑",
  };
  const panel =
    type === "script" ? "scripts" : status === "通过" && type === "prompt" ? "videos" : "prompts";
  markCardProcessing(type, id, true);
  runInBackground(labels[status] || status, panel, async () => {
    const result =
      type === "script"
        ? await api(`/api/scripts/${id}/review`, {
            method: "POST",
            body: JSON.stringify({ status, note, reviewer }),
          })
        : await api(`/api/prompts/${id}/review`, {
            method: "POST",
            body: JSON.stringify({ status, note }),
          });
    markCardProcessing(type, id, false);
    loadPanel(panel);
    if (status === "通过" && type === "prompt") {
      switchTab("videos");
      await loadVideos();
    }
    return result;
  });
};

// --- prompts ---
async function loadPrompts() {
  const pendingOnly = $("#prompt-pending-only").checked;
  const allPrompts = await api("/api/prompts");
  let prompts = pendingOnly ? allPrompts.filter(promptNeedsAttention) : allPrompts;
  prompts = [...prompts].sort((a, b) => promptSortKey(a) - promptSortKey(b));
  const list = $("#prompts-list");
  if (!prompts.length) {
    list.innerHTML = '<div class="empty">暂无 Prompt</div>';
    return;
  }
  list.innerHTML = prompts
    .map((p) => {
      const generating = isPromptGenerating(p);
      const canReview = p.review_status === "待审核" && !generating;
      return `
    <article class="item-card${generating ? " is-generating" : ""}" data-type="prompt" data-id="${p.id}">
      <header>
        <div>
          ${workflowIdentity(p, p.id)}
        </div>
        <div class="header-actions">
          ${statusTag(displayPromptStatus(p))}
          ${
            canReview
              ? `
            <button class="btn success btn-sm" onclick="submitReview('prompt','${p.id}','通过')">✓ 通过出片</button>
            <button class="btn danger btn-sm" onclick="submitReview('prompt','${p.id}','不通过-废弃')">废弃</button>
            <button class="btn ghost btn-sm" onclick="toggleRejectPanel('prompt-${p.id}')">更多</button>`
              : ""
          }
        </div>
      </header>
      ${generating ? renderGeneratingBanner("prompt", p) : ""}
      ${
        canReview
          ? `<div id="reject-prompt-${p.id}" class="reject-panel hidden">
          <textarea id="note-prompt-${p.id}" rows="2" placeholder="调 Prompt 备注（必填）"></textarea>
          <div class="card-actions" style="margin-top:0">
            <button class="btn warn btn-sm" onclick="submitReview('prompt','${p.id}','不通过-调Prompt')">调 Prompt 重出</button>
            <button class="btn warn btn-sm" onclick="submitReview('prompt','${p.id}','不通过-改人工剪')">改人工剪辑</button>
          </div>
        </div>`
          : ""
      }
      ${
        generating
          ? ""
          : `<details class="card-details">
        <summary>Prompt 全文</summary>
        <p class="muted">Part A（0-15s）</p>
        <div class="prompt-box">${esc(p.prompt_text)}</div>
        ${p.prompt_part_b ? `<p class="muted">Part B（15-30s）</p><div class="prompt-box">${esc(p.prompt_part_b)}</div>` : ""}
        ${formatProductSpec(p.product_spec_json)}
        ${p.negative_prompt ? `<p class="muted">负面：${esc(p.negative_prompt)}</p>` : ""}
      </details>`
      }
    </article>`;
    })
    .join("");
}

// --- videos ---
function renderSubtitleAlignLine(v) {
  const status = v.subtitle_align_status || "";
  if (!status) return "";
  const ok = status === "口播对齐" || status === "节奏对齐" || status === "TTS对齐";
  const fail = status.includes("失败");
  const color = ok ? "var(--success)" : fail ? "var(--warn)" : "var(--muted)";
  const detail = v.subtitle_align_detail ? ` — ${v.subtitle_align_detail}` : "";
  return `<p class="muted" style="color:${color}">口播对齐：${esc(status)}${esc(detail)}</p>`;
}

async function loadVideos() {
  const videos = await api("/api/videos");
  refreshCredits();
  const list = $("#videos-list");
  if (!videos.length) {
    list.innerHTML = '<div class="empty">暂无视频产出</div>';
    return;
  }
  list.innerHTML = videos
    .map(
      (v) => `
    <article class="item-card" data-type="video" data-id="${v.id}">
      <header>
        <div>
          ${workflowIdentity(v, v.id)}
        </div>
        <div class="header-actions">${videoStatusTag(displayVideoStatus(v))}</div>
      </header>
      ${renderSeedanceProgress(v)}
      ${renderFirstFramePreview(v)}
      ${renderVideoSegments(v)}
      ${v.video_url ? `<p><a href="${esc(v.video_url)}" target="_blank" style="color:var(--accent)">查看 30s 成片</a></p>` : ""}
      ${
        v.output_status === "失败" && (v.fail_reason || v.note)
          ? `<div class="fail-reason"><strong>失败原因：</strong>${esc(v.fail_reason || v.note)}</div>`
          : ""
      }
      <p class="muted">字幕：${esc(v.subtitle_status || "未开始")}（底部居中偏上 · 白字黑边 · 品牌黄字大一号）${v.note && v.output_status !== "失败" ? " · " + esc(v.note) : ""}</p>
      ${renderSubtitleAlignLine(v)}
      ${
        v.subtitle_align_status && v.subtitle_align_status.includes("失败")
          ? `<p class="muted" style="color:var(--warn);font-size:12px">${
              (v.subtitle_align_detail || "").toLowerCase().includes("no audio")
                ? "提示：<strong>Edge TTS</strong> 未返回音频（音色服务偶发故障）。请点「重烧字幕」重试；系统会自动换备用音色。"
                : "提示：识别服务暂不可用时，系统会尝试<strong>节奏对齐</strong>（静音检测）；最佳效果需下载本地 Whisper 或配置 OpenAI Whisper API。"
            }</p>`
          : v.subtitle_align_status === "节奏对齐"
          ? `<p class="muted" style="font-size:12px">已用音频口播段落对齐；若仍不准，可下载本地 Whisper 后重烧。</p>`
          : ""
      }
      ${
        displayVideoStatus(v) === "失败" && !isManualVideo(v)
          ? `<div class="card-actions">
          <button class="btn warn" onclick="retryVideo('${v.id}')">重试出片</button>
          ${renderVideoDeleteAction(v)}
        </div>`
          : isManualVideo(v) && ["待剪辑", "排队中", "剪辑中"].includes(displayVideoStatus(v))
          ? `<div class="card-actions">
          <button class="btn ghost" onclick="updateVideo('${v.id}','剪辑中')">标记剪辑中</button>
          <button class="btn success" onclick="updateVideo('${v.id}','已交付')">标记已交付</button>
          ${renderVideoDeleteAction(v)}
        </div>`
          : displayVideoStatus(v) === "待交付"
          ? `<div class="card-actions">
          <button class="btn success" onclick="updateVideo('${v.id}','已交付')">标记已交付</button>
          ${!isManualVideo(v) ? `<button class="btn ghost btn-sm" onclick="burnSubtitles('${v.id}', ${v.subtitle_status === "已完成"})">${v.subtitle_status === "已完成" ? "重烧字幕" : "补烧字幕"}</button>` : ""}
          ${renderVideoDeleteAction(v)}
        </div>`
          : displayVideoStatus(v) === "生成中"
          ? `<div class="card-actions">
          <button class="btn warn" onclick="recoverVideo('${v.id}')">续跑（服务重启后）</button>
        </div>
        <p class="muted" style="color:var(--warn)">进度按轮询估算，5% 左右可能仍在正常生成；若长时间不动可点续跑</p>`
          : displayVideoStatus(v) === "已交付"
          ? `<div class="card-actions">
          ${!isManualVideo(v) && v.video_url ? `<button class="btn ghost btn-sm" onclick="burnSubtitles('${v.id}', true)">重烧字幕</button>` : ""}
          ${renderVideoDeleteAction(v)}
        </div>`
          : `<div class="card-actions">${renderVideoDeleteAction(v)}</div>`
      }
    </article>`
    )
    .join("");
}

window.recoverVideo = (id) => {
  markCardProcessing("video", id, true);
  runInBackground("续跑 Seedance", "videos", async () => {
    const res = await api(`/api/videos/${id}/recover`, { method: "POST" });
    markCardProcessing("video", id, false);
    loadVideos();
    return res;
  });
};

window.retryVideo = (id) => {
  if (!confirm("确认重新调用 Seedance 生成该视频？")) return;
  markCardProcessing("video", id, true);
  runInBackground("视频重试出片", "videos", async () => {
    const res = await api(`/api/videos/${id}/retry`, { method: "POST" });
    markCardProcessing("video", id, false);
    loadVideos();
    return res;
  });
};

window.updateVideo = (id, status) => {
  const body = status === "已交付"
    ? { output_status: "已交付", subtitle_status: "已完成" }
    : { output_status: "剪辑中", subtitle_status: "剪辑中" };
  runInBackground("更新视频状态", "videos", async () => {
    await api(`/api/videos/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    loadVideos();
  });
};

window.regenerateSegment = (id, segment) => {
  const label = segment === "part_a" ? "Part A (0-15s)" : "Part B (15-30s)";
  if (!confirm(`确认重新生成 ${label}？完成后将自动重新拼接 30s 成片（若两段齐全）。`)) return;
  markCardProcessing("video", id, true);
  runInBackground(`重生成 ${label}`, "videos", async () => {
    const res = await api(`/api/videos/${id}/segments/${segment}/regenerate`, { method: "POST" });
    markCardProcessing("video", id, false);
    loadVideos();
    return res;
  });
};

window.deleteVideo = (id) => {
  if (!confirm("确认删除该视频记录？分段与成片链接将一并移除。")) return;
  runInBackground("删除视频", "videos", async () => {
    await api(`/api/videos/${id}`, { method: "DELETE" });
    loadVideos();
    refreshBadges();
    return { ok: true };
  });
};

window.burnSubtitles = (id, isReburn = false) => {
  const msg = isReburn
    ? "将用无字幕原片重新烧录（正文白字 · 品牌黄字）。完成后请 Ctrl+F5 强刷页面再预览。"
    : "确认烧录英文字幕？";
  if (!confirm(msg)) return;
  runInBackground(isReburn ? "重烧字幕" : "烧录字幕", "videos", async () => {
    await api(`/api/videos/${id}/burn-subtitles`, { method: "POST" });
    loadVideos();
    return { ok: true };
  });
};

// --- batches ---
async function loadBatches() {
  const batches = await api("/api/batches");
  const list = $("#batches-list");
  const filter = $("#script-batch-filter");
  const current = filter.value;
  filter.innerHTML = '<option value="">全部批次</option>';
  batches.forEach((b) => filter.add(new Option(b.id, b.id)));

  if (current) filter.value = current;

  if (!batches.length) {
    list.innerHTML = '<div class="empty">暂无批次</div>';
    return;
  }
  list.innerHTML = batches
    .map(
      (b) => `
    <article class="item-card">
      <header>
        <div>
          ${workflowIdentity({ product: b.product, direction: b.direction, account_name: "见各脚本" }, b.id)}
        </div>
        <span class="tag">${statusTag(b.status)}</span>
      </header>
      <p class="muted">${b.count} 条 · 待审脚本 ${b.script_pending} / ${b.script_total} · 创建人 ${esc(b.creator || "-")}</p>
    </article>`
    )
    .join("");
}

// --- production board ---
let boardBrowseScriptId = null;
let boardBrowsePackage = null;

function renderBrowsePackage(pkg) {
  const { script: s, prompt: p, video: v } = pkg;
  let html = `<section>${workflowIdentity(s, s.id)}<details class="card-details" open style="margin-top:10px">
    <summary>脚本正文</summary>
    <p class="muted">Hook：${esc(s.hook)}</p>
    ${shotsTable(s.shots)}
    <p class="muted">CTA：${esc(s.cta)}</p></details></section>`;
  if (p) {
    html += `<section>${workflowIdentity(
      { product: s.product, direction: s.direction, account_name: pkg.account_name },
      p.id
    )}<details class="card-details" open style="margin-top:10px">
      <summary>Prompt 全文</summary>
      <p class="muted">Part A</p><div class="prompt-box">${esc(p.prompt_text)}</div>
      ${p.prompt_part_b ? `<p class="muted">Part B</p><div class="prompt-box">${esc(p.prompt_part_b)}</div>` : ""}
      ${formatProductSpec(p.product_spec_json)}</details></section>`;
  }
  if (v) {
    html += `<section>${workflowIdentity(
      { product: s.product, direction: s.direction, account_name: pkg.account_name },
      v.id
    )}<details class="card-details" open style="margin-top:10px">
      <summary>成片 · ${esc(v.output_status || "")}</summary>`;
    if (v.video_url) {
      html += `<p><a href="${esc(v.video_url)}" target="_blank" style="color:var(--accent)">在新标签页播放</a></p>`;
      if (v.video_url.startsWith("/")) {
        html += `<video controls style="max-width:100%;border-radius:8px;margin-top:8px" src="${esc(v.video_url)}"></video>`;
      }
    } else {
      html += `<p class="muted">暂无成片链接（${esc(v.output_status || "未生成")}）</p>`;
    }
    if (v.fail_reason) {
      html += `<div class="fail-reason">${esc(v.fail_reason)}</div>`;
    }
    html += `</details></section>`;
  }
  const assets = pkg.download_assets || [];
  if (assets.length) {
    html += `<section><h4>下载包内容</h4><ul class="beats-list">${assets
      .map(
        (a) =>
          `<li>${esc(a.label)} <span class="muted">· ${a.available ? "可下载" : "暂无"}</span></li>`
      )
      .join("")}</ul></section>`;
  }
  return html;
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function resolvePackageDownloadNames(pkg) {
  const names = pkg?.download_filenames;
  if (names?.video && names?.package) {
    return names;
  }
  const base =
    pkg?.download_basename ||
    [pkg?.script?.product, pkg?.script?.direction, pkg?.account_name || "通用"]
      .filter(Boolean)
      .join("-") ||
    pkg?.script?.id ||
    "VidAU-Flow";
  return {
    package: `${base}-素材包.json`,
    script: `${base}-脚本.json`,
    video: `${base}-完整视频.mp4`,
    part_a: `${base}-PartA-无字幕.mp4`,
    part_b: `${base}-PartB-无字幕.mp4`,
    audio: `${base}-口播.wav`,
    zip: `${base}-素材包.zip`,
  };
}

async function downloadBlobFile(filename, blob) {
  const obj = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = obj;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(obj);
}

async function downloadApiFile(apiPath, filename) {
  const resp = await fetch(API + apiPath);
  if (!resp.ok) {
    const err = await resp.text();
    throw new Error(err || "下载失败");
  }
  const blob = await resp.blob();
  await downloadBlobFile(filename, blob);
}

async function downloadVideoFile(url, filename) {
  if (!url) throw new Error("无可下载的成片");
  if (url.startsWith("/")) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    return;
  }
  const resp = await fetch(url);
  if (!resp.ok) throw new Error("成片下载失败");
  const blob = await resp.blob();
  const obj = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = obj;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(obj);
}

window.browseBoardItem = async (scriptId) => {
  try {
    const pkg = await api(`/api/scripts/${scriptId}/package`);
    boardBrowseScriptId = scriptId;
    boardBrowsePackage = pkg;
    const s = pkg.script;
    $("#board-browse-title").textContent = "素材详情";
    $("#board-browse-meta").innerHTML = workflowIdentity(
      {
        product: s.product,
        direction: s.direction,
        account_name: pkg.account_name,
      },
      s.id
    );
    $("#board-browse-body").innerHTML = renderBrowsePackage(pkg);
    $("#board-browse-dialog").showModal();
  } catch (err) {
    toast("加载失败: " + err.message);
  }
};

let boardZipDownloading = false;

window.downloadBoardItem = async (scriptId) => {
  if (boardZipDownloading) return;
  boardZipDownloading = true;
  try {
    toast("正在服务器打包 ZIP，请稍候（约 10–30 秒）…");
    const pkg = boardBrowsePackage?.script?.id === scriptId
      ? boardBrowsePackage
      : await api(`/api/scripts/${scriptId}/package`);
    const zipName = pkg.download_filenames?.zip || `${pkg.download_basename || scriptId}-素材包.zip`;
    await downloadApiFile(`/api/scripts/${scriptId}/download/zip`, zipName);
    toast(`已下载 ZIP：${zipName}`);
  } catch (err) {
    toast("ZIP 下载失败: " + err.message);
  } finally {
    boardZipDownloading = false;
  }
};

$("#board-browse-download")?.addEventListener("click", () => {
  if (boardBrowseScriptId) downloadBoardItem(boardBrowseScriptId);
});

$("#board-browse-close")?.addEventListener("click", () => $("#board-browse-dialog").close());

async function loadProductionBoard() {
  const rows = await api("/api/production-board");
  const tbody = $("#production-board tbody");
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty">暂无生产任务</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((r) => {
    const delivery = r.delivery_status || r.output_status || "";
    const feedback = r.delivery_feedback || r.video_feedback || "";
    const fa = r.fa_flag === "1" || r.video_fa === "1";
    const account = r.account_name ? `${r.account_name}` : "-";
    const hasVideo = !!r.video_url;
    return `<tr>
      <td><code style="font-size:0.8rem">${esc(r.id)}</code></td>
      <td>${esc(r.product)}</td>
      <td>${esc(r.direction)}</td>
      <td>${esc(account)}</td>
      <td>${esc(r.language || "英语")}</td>
      <td>${esc(r.producer || r.video_producer || "")}</td>
      <td>${statusTag(r.review_status)}</td>
      <td>${esc(delivery)}</td>
      <td>${esc(feedback)}</td>
      <td>${fa ? "✓" : ""}</td>
      <td>
        <div class="board-actions">
          <button class="btn ghost btn-sm" onclick="browseBoardItem('${r.id}')">浏览</button>
          <button class="btn ghost btn-sm" onclick="downloadBoardItem('${r.id}')">下载 ZIP</button>
          <button class="btn ghost btn-sm" onclick="openDeliveryEdit('${r.id}')">交付</button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

let deliveryScriptId = null;

window.openDeliveryEdit = async (scriptId) => {
  const s = await api(`/api/scripts/${scriptId}`);
  deliveryScriptId = scriptId;
  const target = $("#delivery-target");
  if (target) {
    target.innerHTML = workflowIdentity(s, s.id);
  }
  const form = $("#delivery-form");
  form.elements.namedItem("delivery_status").value = s.delivery_status || "";
  form.elements.namedItem("delivery_feedback").value = s.delivery_feedback || "";
  form.elements.namedItem("producer").value = s.producer || "";
  form.elements.namedItem("fa_flag").checked = s.fa_flag === "1";
  $("#delivery-dialog").showModal();
};

$("#delivery-form").onsubmit = async (e) => {
  e.preventDefault();
  if (!deliveryScriptId) return;
  const fd = new FormData(e.target);
  runInBackground("更新交付信息", "board", async () => {
    await api(`/api/scripts/${deliveryScriptId}/delivery`, {
      method: "PATCH",
      body: JSON.stringify({
        delivery_status: fd.get("delivery_status") || "",
        delivery_feedback: fd.get("delivery_feedback") || "",
        producer: fd.get("producer") || "",
        fa_flag: fd.get("fa_flag") ? "1" : "0",
      }),
    });
    $("#delivery-dialog").close();
    loadProductionBoard();
  });
};

$("#delivery-cancel").onclick = () => $("#delivery-dialog").close();

$("#refresh-board")?.addEventListener("click", loadProductionBoard);

function getConfigSubTab() {
  return localStorage.getItem("configSubTab") || "products";
}

function switchConfigSubTab(name) {
  localStorage.setItem("configSubTab", name);
  $$("#config-subtabs .sub-tab").forEach((t) => {
    t.classList.toggle("active", t.dataset.config === name);
  });
  $$(".config-subpanel").forEach((p) => p.classList.remove("active"));
  $(`#config-subpanel-${name}`)?.classList.add("active");
  if (name === "products") loadProducts();
  if (name === "accounts") loadAccounts();
  if (name === "directions") loadDirections();
}

function reloadConfigPanel() {
  if (getActiveTab() === "config") switchConfigSubTab(getConfigSubTab());
}

function updateConfigSyncButtons(user) {
  const show = !window.appMeta?.auth_enabled || user?.role === "admin";
  $("#config-export-btn")?.classList.toggle("hidden", !show);
  $("#config-import-btn")?.classList.toggle("hidden", !show);
}

$$("#config-subtabs .sub-tab").forEach((tab) => {
  tab.addEventListener("click", () => switchConfigSubTab(tab.dataset.config));
});

$("#config-export-btn")?.addEventListener("click", async () => {
  try {
    const bundle = await api("/api/config/export");
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `fixed-config-${stamp}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
    toast("配置已导出");
  } catch (err) {
    toast("导出失败: " + err.message);
  }
});

$("#config-import-btn")?.addEventListener("click", () => $("#config-import-file")?.click());

$("#config-import-file")?.addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  e.target.value = "";
  if (!file) return;
  if (!confirm("将按名称/序号合并导入产品、账号、方向（含产品图），是否继续？")) return;
  try {
    const text = await file.text();
    const bundle = JSON.parse(text);
    const res = await api("/api/config/import", {
      method: "POST",
      body: JSON.stringify({ bundle }),
    });
    const s = res.stats || {};
    toast(
      `导入完成：产品 +${s.products_created || 0}/~${s.products_updated || 0}，账号 +${s.accounts_created || 0}/~${s.accounts_updated || 0}，方向 +${s.directions_created || 0}/~${s.directions_updated || 0}`
    );
    loadMeta();
    reloadConfigPanel();
  } catch (err) {
    toast("导入失败: " + err.message);
  }
});

async function importConfigCsv(kind, file) {
  if (!file) return;
  const labels = { accounts: "账号人设", directions: "内容方向", products: "产品" };
  if (!confirm(`将合并导入${labels[kind] || kind} CSV（按序号/名称更新已有项），是否继续？`)) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await api(`/api/config/import-csv/${kind}`, { method: "POST", body: fd });
    const s = res.stats || {};
    toast(
      `${labels[kind]} CSV：新增 ${s.created || 0}，更新 ${s.updated || 0}${s.skipped ? `，跳过 ${s.skipped}` : ""}`
    );
    if (kind === "products" || kind === "directions") loadMeta();
    reloadConfigPanel();
  } catch (err) {
    toast("CSV 导入失败: " + err.message);
  }
}

$("#import-accounts-csv-btn")?.addEventListener("click", () => $("#import-accounts-csv-file")?.click());
$("#import-accounts-csv-file")?.addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  importConfigCsv("accounts", f);
});
$("#import-directions-csv-btn")?.addEventListener("click", () => $("#import-directions-csv-file")?.click());
$("#import-directions-csv-file")?.addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  importConfigCsv("directions", f);
});
$("#import-products-csv-btn")?.addEventListener("click", () => $("#import-products-csv-file")?.click());
$("#import-products-csv-file")?.addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  importConfigCsv("products", f);
});

// --- accounts ---
async function loadAccounts() {
  const accounts = await api("/api/accounts");
  const list = $("#accounts-list");
  list.innerHTML = accounts.map((a) => `
    <article class="item-card">
      <header>
        <div>
          <h3>账号${a.no} · ${esc(a.display_name)}</h3>
          <div class="meta">${esc(a.username)} · ${esc(a.language)} · ${esc(a.blogger_type)}</div>
        </div>
        <div class="card-actions">
          <button class="btn ghost" onclick="openMgmt('account', '${a.id}')">编辑</button>
          <button class="btn danger" onclick="deleteItem('account', '${a.id}')">删除</button>
        </div>
      </header>
      <p class="muted"><strong>定位：</strong>${esc(a.positioning)}</p>
      <p class="muted"><strong>方向：</strong>${esc((a.content_directions || "").replace(/\n/g, " / "))}</p>
      <p class="muted"><strong>主推产品：</strong>${esc(a.main_products)}</p>
      <p class="muted"><strong>Bio：</strong>${esc(a.bio)}</p>
    </article>
  `).join("") || '<div class="empty">暂无账号，已从 Excel 导入或手动添加</div>';
}

$("#add-account-btn")?.addEventListener("click", () => openMgmt("account"));

// --- products & directions mgmt ---
let mgmtContext = null;

async function loadProducts() {
  const products = await api("/api/products");
  const list = $("#products-list");
  list.innerHTML = products.map(p => `
    <article class="item-card">
      <header>
        <h3>${esc(p.name)}</h3>
        <div class="card-actions">
          <button class="btn ghost" onclick="openMgmt('product', '${p.id}')">编辑</button>
          <button class="btn danger" onclick="deleteItem('product', '${p.id}')">删除</button>
        </div>
      </header>
      ${
        productImageUrls(p).length
          ? `<div class="product-images-row">${productImageUrls(p)
              .map((url) => `<img src="${esc(url)}" alt="产品图" />`)
              .join("")}</div>
             <p class="muted">共 ${productImageUrls(p).length} 张产品图</p>`
          : `<p class="muted" style="color:var(--warn)">未上传产品图，无法用于出片</p>`
      }
      <p class="muted"><strong>价格：</strong>${esc(p.daily_price) || "-"} / 活动 ${esc(p.promo_price) || "-"}</p>
      <p class="muted"><strong>转化方式：</strong>${esc(p.conversion_method || "视频挂链")}</p>
      <p class="muted"><strong>外观说明：</strong>${
        p.specs_confirmed
          ? "已确认"
          : '<span style="color:var(--warn)">待确认（AI识别后需人工确认）</span>'
      }</p>
      <p class="muted"><strong>卖点：</strong>${esc(p.selling_points) || "未填写"}</p>
      ${p.purchase_link ? `<p class="muted"><a href="${esc(p.purchase_link)}" target="_blank" style="color:var(--accent)">购买链接</a></p>` : ""}
    </article>
  `).join("") || '<div class="empty">暂无产品</div>';
}

async function loadDirections() {
  const directions = await api("/api/directions");
  const list = $("#directions-list");
  list.innerHTML = directions.map(d => `
    <article class="item-card">
      <header>
        <h3>${esc(d.name)}</h3>
        <div class="card-actions">
          <button class="btn ghost" onclick="openMgmt('direction', '${d.id}')">编辑</button>
          <button class="btn danger" onclick="deleteItem('direction', '${d.id}')">删除</button>
        </div>
      </header>
      <p class="muted"><strong>短码：</strong>${esc(d.short_code) || "未填写"}</p>
      <p class="muted"><strong>说明：</strong>${esc(d.description) || "未填写"}</p>
    </article>
  `).join("") || '<div class="empty">暂无方向</div>';
}

const MGMT_LABELS = { product: "产品", direction: "内容方向", account: "账号人设" };

window.openMgmt = async (type, id = null) => {
  mgmtContext = { type, id };
  $("#mgmt-title").textContent = (id ? "编辑" : "添加") + (MGMT_LABELS[type] || type);
  const fields = $("#mgmt-fields");

  let item = {};
  if (id) {
    item = await api(`/api/${type}s/${id}`);
  }

  if (type === "account") {
    fields.innerHTML = `
      <label>序号 <input type="number" name="no" value="${esc(item.no || "")}" /></label>
      <label class="full">账号名称 <input type="text" name="display_name" value="${esc(item.display_name || "")}" required /></label>
      <label class="full">Username <input type="text" name="username" value="${esc(item.username || "")}" /></label>
      <label>语言 <input type="text" name="language" value="${esc(item.language || "英语")}" /></label>
      <label class="full">博主类型 <input type="text" name="blogger_type" value="${esc(item.blogger_type || "")}" /></label>
      <label class="full">账号定位 <textarea name="positioning" rows="2">${esc(item.positioning || "")}</textarea></label>
      <label class="full">内容方向（多行） <textarea name="content_directions" rows="3">${esc(item.content_directions || "")}</textarea></label>
      <label class="full">主页包装 <textarea name="page_packaging" rows="2">${esc(item.page_packaging || "")}</textarea></label>
      <label class="full">主推产品 <input type="text" name="main_products" value="${esc(item.main_products || "")}" /></label>
      <label class="full">人设风格 <textarea name="persona_style" rows="3">${esc(item.persona_style || "")}</textarea></label>
      <label class="full">头像/视觉描述 <textarea name="avatar_desc" rows="2">${esc(item.avatar_desc || "")}</textarea></label>
      <label class="full">Bio <textarea name="bio" rows="2">${esc(item.bio || "")}</textarea></label>
    `;
  } else if (type === "product") {
    mgmtContext.imageUrls = productImageUrls(item);
    mgmtContext.pendingFiles = [];
    fields.innerHTML = `
      <label class="full">名称 <input type="text" name="name" value="${esc(item.name)}" required /></label>
      <label class="full">
        产品图（1-9 张）
        <input type="file" name="image_files" accept="image/jpeg,image/png,image/webp,image/bmp,image/tiff,image/gif,image/heic,image/heif,.heic,.heif" multiple />
        <span class="muted" style="display:block;margin-top:6px">支持 JPEG / PNG / WEBP / BMP / TIFF / GIF / HEIC / HEIF，单张最大 30MB，共 1-9 张。第一张建议纯产品图（无人物），细节图可后续追加</span>
      </label>
      <div id="product-image-preview" class="image-preview-grid hidden"></div>
      <label>日常价 <input type="text" name="daily_price" value="${esc(item.daily_price || "")}" /></label>
      <label>活动价 <input type="text" name="promo_price" value="${esc(item.promo_price || "")}" /></label>
      <label class="full">购买链接 <input type="text" name="purchase_link" value="${esc(item.purchase_link || "")}" /></label>
      <label class="full">上架状态 <input type="text" name="listing_status" value="${esc(item.listing_status || "")}" placeholder="如：不挂车，bio放众筹链接" /></label>
      <label class="full">转化方式
        <select name="conversion_method">
          <option value=""${!item.conversion_method ? " selected" : ""}>自动（根据名称/上架状态推断）</option>
          ${["视频挂链", "Bio引流", "橱窗商品卡"].map(
            (m) =>
              `<option value="${m}"${item.conversion_method === m ? " selected" : ""}>${m}</option>`
          ).join("")}
        </select>
      </label>
      <label class="full">产品外观与交互说明
        <textarea name="product_specs" rows="5" placeholder="上传产品图后点击「AI 识别」，核对后勾选确认。描述外观、按键、屏幕、可演示动作；禁止插电/插口特写。">${esc(item.product_specs || item.product_specs_draft || "")}</textarea>
      </label>
      <div class="vision-actions" style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 12px">
        <button type="button" class="btn ghost" id="product-vision-btn">AI 识别产品特点</button>
        <button type="button" class="btn ghost hidden" id="product-vision-apply-specs-btn">采用外观说明</button>
        <button type="button" class="btn ghost hidden" id="product-vision-apply-selling-btn">采用建议卖点</button>
      </div>
      <div id="product-vision-status" class="hidden" style="margin-bottom:12px"></div>
      <div id="product-vision-draft" class="prompt-box hidden" style="margin-bottom:12px"></div>
      <label class="full" style="flex-direction:row;align-items:center;gap:8px">
        <input type="checkbox" name="product_specs_confirmed" id="product-specs-confirmed" ${item.specs_confirmed ? "checked" : ""} />
        已人工核对外观说明（确认后才可用于新建批次）
      </label>
      <label class="full">产品卖点 <textarea name="selling_points" rows="4">${esc(item.selling_points || item.selling_points_draft || "")}</textarea></label>
    `;
    mgmtContext.visionDraft = null;
    const visionBtn = fields.querySelector("#product-vision-btn");
    const visionApplySpecsBtn = fields.querySelector("#product-vision-apply-specs-btn");
    const visionApplySellingBtn = fields.querySelector("#product-vision-apply-selling-btn");
    const visionDraftEl = fields.querySelector("#product-vision-draft");
    const visionStatusEl = fields.querySelector("#product-vision-status");
    const setVisionApplyButtons = (draft) => {
      const hasSpecs = Boolean((draft?.product_specs_draft || "").trim());
      const hasSelling = Boolean((draft?.selling_points_draft || "").trim());
      visionApplySpecsBtn.classList.toggle("hidden", !hasSpecs);
      visionApplySellingBtn.classList.toggle("hidden", !hasSelling);
    };
    const renderVisionDraft = (draft) => {
      if (!draft) {
        visionDraftEl.classList.add("hidden");
        setVisionApplyButtons(null);
        return;
      }
      clearVisionStatus(visionStatusEl);
      const notes = draft.vision?.confidence_notes || "";
      visionDraftEl.classList.remove("hidden");
      setVisionApplyButtons(draft);
      visionDraftEl.innerHTML = `
        <p class="muted"><strong>AI 识别草稿（需人工核对）</strong></p>
        <pre style="white-space:pre-wrap;margin:8px 0">${esc(draft.product_specs_draft || "")}</pre>
        ${draft.selling_points_draft ? `<p class="muted"><strong>建议卖点</strong></p><pre style="white-space:pre-wrap">${esc(draft.selling_points_draft)}</pre>` : ""}
        ${notes ? `<p class="muted" style="color:var(--warn)"><strong>请重点确认：</strong>${esc(notes)}</p>` : ""}
      `;
    };
    visionBtn.onclick = async () => {
      visionBtn.disabled = true;
      const visionBtnDefault = visionBtn.textContent;
      visionApplySpecsBtn.classList.add("hidden");
      visionApplySellingBtn.classList.add("hidden");
      clearVisionStatus(visionStatusEl);
      const analyzeStartedAt = Date.now();
      try {
        const urls = [...(mgmtContext.imageUrls || [])];
        const pending = [...(mgmtContext.pendingFiles || [])];
        if (pending.length) {
          for (let i = 0; i < pending.length; i++) {
            const file = pending[i];
            renderVisionStatus(visionStatusEl, "uploading", {
              done: i,
              total: pending.length,
              name: file.name,
            });
            const uploaded = await uploadProductImage(file);
            urls.push(uploaded.url);
            mgmtContext.imageUrls = urls;
            mgmtContext.pendingFiles = mgmtContext.pendingFiles.filter((f) => f !== file);
            refreshPreview();
          }
        }
        if (urls.length < 1) {
          renderVisionStatus(visionStatusEl, "error", { error: "请先上传至少 1 张产品图" });
          toast("请先上传至少 1 张产品图");
          return;
        }
        const imageCount = Math.min(urls.length, 4);
        renderVisionStatus(visionStatusEl, "analyzing", { imageCount, startedAt: analyzeStartedAt });
        visionBtn.textContent = "AI 识别中…";
        const name = fields.querySelector('input[name="name"]')?.value?.trim() || item.name || "";
        const existing_specs = fields.querySelector('textarea[name="product_specs"]')?.value || "";
        const existing_selling_points = fields.querySelector('textarea[name="selling_points"]')?.value || "";
        let draft;
        if (id) {
          draft = await api(`/api/products/${id}/analyze-images`, { method: "POST" });
        } else {
          draft = await api("/api/products/analyze-images", {
            method: "POST",
            body: JSON.stringify({
              product_name: name,
              image_urls: urls,
              existing_specs,
              existing_selling_points,
            }),
          });
        }
        mgmtContext.visionDraft = draft;
        renderVisionDraft(draft);
        fields.querySelector("#product-specs-confirmed").checked = false;
        const elapsed = Math.max(1, Math.round((Date.now() - analyzeStartedAt) / 1000));
        toast(`识别完成（${elapsed}s），请核对后分别采用外观说明/卖点`);
      } catch (err) {
        renderVisionStatus(visionStatusEl, "error", { error: err });
        toast("识别失败: " + formatVisionError(err));
      } finally {
        visionBtn.disabled = false;
        visionBtn.textContent = visionBtnDefault;
      }
    };
    visionApplySpecsBtn.onclick = () => {
      const draft = mgmtContext.visionDraft;
      if (!draft?.product_specs_draft) return;
      fields.querySelector('textarea[name="product_specs"]').value = draft.product_specs_draft;
      fields.querySelector("#product-specs-confirmed").checked = false;
      toast("已填入外观说明，请核对后勾选确认");
    };
    visionApplySellingBtn.onclick = () => {
      const draft = mgmtContext.visionDraft;
      if (!draft?.selling_points_draft) return;
      fields.querySelector('textarea[name="selling_points"]').value = draft.selling_points_draft;
      toast("已填入建议卖点，可按需修改");
    };
    if (item.product_specs_draft && !item.specs_confirmed) {
      renderVisionDraft({
        product_specs_draft: item.product_specs_draft,
        selling_points_draft: item.selling_points_draft,
        vision: { confidence_notes: "上次识别结果，换图后请重新识别" },
      });
    }
    const fileInput = fields.querySelector('input[type="file"]');
    const preview = $("#product-image-preview");
    const refreshPreview = () => {
      renderProductImageGrid(preview, {
        serverUrls: mgmtContext.imageUrls,
        pendingFiles: mgmtContext.pendingFiles,
        onRemoveServer: (index) => {
          mgmtContext.imageUrls.splice(index, 1);
          refreshPreview();
        },
        onRemovePending: (index) => {
          mgmtContext.pendingFiles.splice(index, 1);
          refreshPreview();
        },
      });
    };
    fileInput.onchange = () => {
      const files = [...(fileInput.files || [])];
      fileInput.value = "";
      for (const file of files) {
        if (file.size > MAX_IMAGE_BYTES) {
          toast("单张图片不能超过 30MB");
          continue;
        }
        const total = mgmtContext.imageUrls.length + mgmtContext.pendingFiles.length;
        if (total >= MAX_PRODUCT_IMAGES) {
          toast(`产品图最多 ${MAX_PRODUCT_IMAGES} 张`);
          break;
        }
        mgmtContext.pendingFiles.push(file);
      }
      refreshPreview();
    };
    refreshPreview();
  } else {
    fields.innerHTML = `
      <label class="full">方向名称 <input type="text" name="name" value="${esc(item.name)}" required /></label>
      <label>短码 <input type="text" name="short_code" value="${esc(item.short_code || "")}" placeholder="方向1" /></label>
      <label class="full">方向说明 <textarea name="description" rows="4">${esc(item.description)}</textarea></label>
    `;
  }
  $("#mgmt-dialog").showModal();
};

$("#mgmt-form").onsubmit = async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const data = Object.fromEntries(
    [...fd.entries()].filter(([key]) => key !== "image_files" && key !== "product_specs_confirmed")
  );
  const { type, id } = mgmtContext;
  try {
    if (type === "product") {
      const urls = [...(mgmtContext.imageUrls || [])];
      for (const file of mgmtContext.pendingFiles || []) {
        const uploaded = await uploadProductImage(file);
        urls.push(uploaded.url);
      }
      if (urls.length < 1) {
        toast("请至少上传 1 张产品图");
        return;
      }
      if (urls.length > MAX_PRODUCT_IMAGES) {
        toast(`产品图最多 ${MAX_PRODUCT_IMAGES} 张`);
        return;
      }
      data.image_urls = urls;
      data.product_specs_confirmed = !!fd.get("product_specs_confirmed");
      if (!data.product_specs?.trim()) {
        toast("请填写产品外观说明，或先 AI 识别");
        return;
      }
      if (!data.product_specs_confirmed) {
        toast("请勾选「已人工核对外观说明」后再保存");
        return;
      }
    }
    const method = id ? "PATCH" : "POST";
    const url = `/api/${type}s` + (id ? `/${id}` : "");
    await api(url, { method, body: JSON.stringify(data) });
    $("#mgmt-dialog").close();
    toast("保存成功");
    reloadConfigPanel();
    loadMeta();
  } catch (err) {
    toast("保存失败: " + err.message);
  }
};

$("#mgmt-cancel").onclick = () => $("#mgmt-dialog").close();

window.deleteItem = async (type, id) => {
  if (!confirm("确定要删除吗？")) return;
  try {
    await api(`/api/${type}s/${id}`, { method: "DELETE" });
    toast("已删除");
    reloadConfigPanel();
    loadMeta();
  } catch (err) {
    toast("删除失败: " + err.message);
  }
};

$("#add-product-btn").onclick = () => openMgmt("product");
$("#add-direction-btn").onclick = () => openMgmt("direction");

// --- panel loader ---
function loadPanel(name) {
  if (name === "board") loadProductionBoard();
  if (name === "scripts") loadScripts();
  if (name === "prompts") loadPrompts();
  if (name === "videos") loadVideos();
  if (name === "batches") loadBatches();
  if (name === "config") switchConfigSubTab(getConfigSubTab());
}

$("#refresh-scripts").onclick = () => { loadScripts(); refreshBadges(); };
$("#refresh-prompts").onclick = () => { loadPrompts(); refreshBadges(); };
$("#refresh-videos").onclick = loadVideos;
$("#script-pending-only").onchange = loadScripts;
$("#prompt-pending-only").onchange = loadPrompts;
$("#script-batch-filter").onchange = loadScripts;

const BATCH_ACTIVE_STATUSES = new Set(["生成中", "自动审核中", "视频生成中", "待脚本审核"]);

async function maybePollPanels() {
  const bg = { background: true };
  const tab = getActiveTab();
  try {
    if (tab === "videos" && $("#video-auto-refresh")?.checked) {
      const videos = await api("/api/videos", bg);
      const generating = videos.some(
        (v) => displayVideoStatus(v) === "生成中" || parseSegmentJson(v).progress?.seedance_status === "running"
      );
      if (generating) loadVideos();
    }
    if (tab === "scripts" && $("#script-auto-refresh")?.checked) {
      const [scripts, batches] = await Promise.all([
        api("/api/scripts", bg),
        api("/api/batches", bg),
      ]);
      if (scripts.some(isScriptGenerating) || batches.some((b) => BATCH_ACTIVE_STATUSES.has(b.status))) {
        loadScripts();
      }
    }
    if (tab === "prompts" && $("#prompt-auto-refresh")?.checked) {
      const prompts = await api("/api/prompts", bg);
      if (prompts.some(isPromptGenerating)) loadPrompts();
    }
    refreshBadges();
  } catch {
    /* ignore */
  }
}

function startPanelPolling() {
  if (videoPollTimer) clearInterval(videoPollTimer);
  videoPollTimer = setInterval(maybePollPanels, 4000);
}

// init
const savedReviewer = localStorage.getItem("reviewer");
if (savedReviewer && $("#default-reviewer")) $("#default-reviewer").value = savedReviewer;
$("#default-reviewer")?.addEventListener("change", saveDefaultReviewer);
$("#default-reviewer")?.addEventListener("blur", saveDefaultReviewer);

(async function boot() {
  await loadMeta();
  if (!isLoggedIn()) return;
  refreshBadges();
  setInterval(refreshBadges, 30000);
  startPanelPolling();
})();
