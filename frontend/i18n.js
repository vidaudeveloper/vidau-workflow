/** Ad Flow Agent UI i18n (zh / en) */
(function () {
  const STORAGE_KEY = "ui_locale";

  const STRINGS = {
    zh: {
      brand: "Ad Flow Agent",
      login: "登录",
      buyCredits: "购买积分",
      newProject: "新建广告",
      runWorkflow: "运行工作流",
      assistantRole: "Copilot",
      youRole: "你",
      chatTitle: "AI Copilot",
      chatSub: "对话式搭建工作流",
      chatWelcome:
        "用对话描述需求即可；有资料可点 **+ 上传文件**，纯文字也可以。",
      chatPlaceholder: "描述广告需求；可选上传素材或粘贴链接，不是必须。",
      chatSend: "发送",
      canvasTitle: "Workflow Canvas",
      chatRunStarted: "已创建运行批次：{id}，正在执行脚本→分镜→出片。",
      chatNodeQueued: "已提交节点重跑：{node}",
      chatHintHook: "我已切到脚本节点，你可以编辑 Hook 后创建分支重跑。",
      chatHintStoryboard: "我已切到分镜节点，可输入调整说明并重调。",
      chatHintVideo: "我已切到视频节点，可只重跑视频不动脚本/分镜。",
      chatApplyInput: "我已把需求写入 Input 节点，点击“运行工作流”即可执行。",
      chatGuideGreeting:
        "你好！直接说想做什么广告就行。\n\n可选：**+ 上传文件** 附 PDF、表格、对标视频或产品图（最多 8 个）。纯文字也完全可以。",
      chatGuideVague:
        "我还不太确定具体需求。你可以这样说：\n「为 @Elite 300 做 15 秒 TikTok 广告，露营场景，前 2 秒要强钩子」\n\n也可以点下方模板快速开始。",
      chatGuideProduct: "好的。请补充产品名称（如 Elite 300、Apex 300）。",
      chatGuideBrief:
        "产品已记下。请补充广告目标：时长、投放场景、受众，以及想强调的核心卖点或钩子风格。",
      chatGuideDuration: "还差时长：默认按 15 秒竖屏生成。若要改时长，直接告诉我（如「改成 30 秒」）。",
      chatGuideScenario:
        "请补充场景或受众（如 TikTok、露营、家庭应急），或 @ 选一个风格方向，脚本会更准。",
      chatBriefReady:
        "需求已同步到 Input 节点，你可以在左侧 Inspector 继续改。\n满意后点 Run all，或回复「开始运行」。",
      chatBriefPartial: "已记下：{snippet}\n\n{next}",
      chatGuideRunFirst: "要操作脚本/分镜/视频节点，先运行一次工作流生成节点结果。先把 Input 补全后回复「开始运行」。",
      chatGuideHookMissing: "请先告诉我要改成什么 Hook。例如：把 Hook 改成“前 2 秒直接抛出停电焦虑问题”。",
      chatGuideScriptHookApplied: "已把 Hook 写入脚本节点。需要我现在重跑脚本吗？你可以说“重跑脚本”或“分支重跑脚本”。",
      chatGuideScriptSaved: "脚本节点已保存。要继续生成分镜的话，可以说“重跑分镜”或“开始运行”。",
      chatGuideStoryboardMissing: "请先给我分镜调整说明。例如：分镜改成“前三镜头更快切，产品特写更近”。",
      chatGuideStoryboardApplied: "已记录分镜调整说明。需要我现在重跑分镜吗？可说“重跑分镜”或“分支重跑分镜”。",
      tplQuickUgc: "UGC 快速起量",
      tplDemo: "产品讲解",
      tplBenefit: "痛点钩子",
      heroTitle: "你想做什么广告？",
      heroLead: "让 Agent 用对话帮你搭建并执行完整工作流",
      tabBrief: "描述需求",
      tabUrl: "产品链接",
      briefPlaceholder: "例如：Elite 300，15 秒竖屏广告，露营场景，强调轻便与长续航…",
      urlPlaceholder: "https://your-store.com/product/…",
      urlHint: "支持 URL + 补充需求，Agent 会自动转成 Input 节点参数。",
      urlBriefPlaceholder: "可选：补充人群、风格、CTA",
      mentionHint: "输入 @ 选择产品/风格",
      chip1: "户外电源 · TikTok",
      chip2: "家用储能 · 应急",
      chip3: "充电宝 · 快充",
      ex1: "为户外电源做 15 秒 TikTok 广告，露营场景，强调轻便与长续航",
      ex2: "家用储能产品，停电应急场景，温馨家庭风格，英语口播",
      ex3: "便携充电宝，通勤场景，快节奏剪辑，突出快充",
      optVoice: "口播语言",
      optCount: "数量",
      optRatio: "画幅",
      count1: "1 条",
      count2: "2 条",
      count3: "3 条",
      ratio916: "9:16 竖屏",
      legacyRatioLocked: "画幅由系统固定为 9:16",
      generate: "生成广告",
      generating: "正在创建…",
      guestHint: "登录后即可生成广告并保存项目",
      previewTitle: "预览",
      previewEmpty: "视频出片后将在此播放",
      previewWaiting: "分镜完成后将自动开始出片",
      previewRendering: "视频生成中，请稍候…",
      previewReady: "视频已生成，可预览或下载",
      previewNotStarted: "尚未开始生成",
      previewRenderingStatus: "出片中…",
      previewWaitingStatus: "等待视频节点",
      downloadVideo: "下载视频",
      downloadZip: "下载素材包",
      branchCompare: "分支对比",
      compareEmpty: "暂无分支版本",
      compareLeft: "左侧版本",
      compareRight: "右侧版本",
      compareHook: "Hook",
      compareStoryboard: "分镜文案",
      compareVideoStatus: "视频状态",
      diffSame: "一致",
      diffChanged: "有差异",
      compareOnlyDiff: "仅看差异",
      compareNoDiff: "当前两版本无差异",
      setActiveLeft: "左侧设为当前版本",
      setActiveRight: "右侧设为当前版本",
      nodeProductInfo: "Input",
      nodeProductAssets: "产品素材",
      nodeBenchmark: "对标视频",
      nodeBrief: "策略简报",
      nodeInput: "Input",
      nodeInputHint: "等待输入需求",
      stepScript: "脚本",
      stepStoryboard: "分镜",
      stepRender: "出片",
      stepQA: "质检打包",
      stepVideo: "视频",
      statusPending: "待开始",
      statusRunning: "进行中",
      statusDone: "已完成",
      statusFail: "失败",
      scriptWait: "点击节点可编辑 Hook，等待任务创建",
      storyWait: "脚本完成后自动生成分镜，点击节点可重调",
      videoWait: "分镜通过后自动出片，点击节点可仅重跑出片",
      productInfoHint: "Input 节点填写产品名与产品页链接；规格表可通过上传解析。",
      productAssetsHint: "上传产品图/产品视频后，素材分析会同步到这里。",
      productAssetsReady: "已收到素材分析，可进入策略节点。",
      benchmarkHint: "填写对标视频链接或上传对标视频文件。",
      qaWaitHint: "等待出片完成后自动进入质检。",
      qaRunningHint: "质检中：检查视频状态与素材包。",
      qaDoneHint: "质检通过，可下载视频与素材包。",
      qaFailHint: "质检失败，请回到出片或分镜节点重跑。",
      branchMain: "主版本",
      branchFrom: "分支",
      inspectorTitle: "Inspector",
      inspectorEmpty: "暂无可编辑节点",
      fieldBrief: "Brief",
      fieldRefVideo: "对标视频链接",
      fieldRefVideoPh: "https://tiktok.com/... 或 YouTube 链接",
      fieldMaterialCtx: "素材分析（自动）",
      fieldUrl: "产品 URL",
      fieldProduct: "产品",
      fieldDirection: "风格",
      fieldNote: "调整说明",
      notePlaceholderScript: "例如：Hook 更直接，强调停电焦虑",
      notePlaceholderStoryboard: "例如：镜头更近，产品占画面更大",
      storyPromptPreview: "分镜 Prompt 预览",
      saveOnly: "仅保存",
      branchRunStoryboard: "创建分支并重跑分镜",
      rerunCurrentStoryboard: "当前版本重跑分镜",
      branchRunVideo: "创建分支并重跑视频",
      rerunCurrentVideo: "当前版本重跑视频",
      videoNodeHint: "只重跑视频节点，不改脚本与分镜。",
      impactNone: "未检测到待重算节点",
      impactPending: "待重算链路：{nodes}",
      impactedBy: "受影响原因：{reason}",
      authChecking: "正在验证登录状态…",
      authPopup: "请在弹窗中完成登录…",
      authConnecting: "正在连接账号…",
      loginRequired: "请先登录后再操作。",
      estimateCredits: "预计消耗 {range} credits{fallback}",
      estimateFallback: "（区间估算）",
      errBrief: "请先描述你想做的广告。",
      errInsufficient: "积分不足：余额 {coin}，需要 {needed}。",
      errCreate: "创建失败：{msg}",
      errSync: "同步失败：{msg}",
      errInit: "初始化失败：{msg}",
      inputNeedProduct: "请在 Input 节点填写产品名称。",
      errProductInvalid: "所选产品不存在：{name}。请在 Input 节点改为有效产品名。",
      inputReadyHint: "输入完整，可直接运行工作流。",
      mentionProduct: "产品",
      mentionStyle: "风格",
      hookRequired: "Hook 不能为空",
      actionFailed: "操作失败：{msg}",
      errEdgeInvalid: "连线无效：会产生循环或重复连接。",
      batchLabel: "批次 {id}",
      chatTplApplied: "模板已写入 Input 节点，可直接运行。",
      vipBannerText: "升级 VIP 解锁更多积分、优先生成与高级模板",
      vipBannerCta: "立即充值",
      projectUntitled: "Untitled Flow",
      runAll: "Run all",
      upgrade: "Upgrade",
      addProduct: "+ Product",
      mentionBtn: "@ 提及",
      addFiles: "+ 上传文件",
      addFilesTitle: "PDF、Word、表格、视频、产品图等，最多 8 个",
      dropFilesHere: "松手上传文件",
      mentionTitle: "选择要 @ 的产品或风格",
      mentionProducts: "产品",
      mentionStyles: "风格",
      mentionEmpty: "暂无选项，请先在后台配置产品/风格",
      attachPdf: "PDF",
      attachDocx: "Word",
      attachCsv: "CSV",
      attachXlsx: "Excel",
      attachVideo: "对标视频",
      attachImage: "产品图",
      attachText: "文本",
      attachTooMany: "单次最多上传 {max} 个文件",
      chatAttachOnly: "（已上传参考素材）",
      chatIntakeDone: "已解析素材并写入 Input 节点（产品：{product}）。可在 Inspector 查看 Brief 与对标风格摘要。",
      chatIntakeFailed: "素材解析失败：{msg}",
      aiBuilding: "AI 正在构建 — 画布编辑已暂停",
      copilotStatePlanning: "Planning…",
      copilotStateReady: "Ready",
      copilotStateThinking: "Thinking…",
      copilotStateBuilding: "Building…",
      copilotStateError: "Error",
      copilotThinking: "Thinking…",
      chatStop: "停止",
    },
    en: {
      brand: "Ad Flow Agent",
      login: "Log in",
      buyCredits: "Buy credits",
      newProject: "New run",
      runWorkflow: "Run workflow",
      assistantRole: "Copilot",
      youRole: "You",
      chatTitle: "AI Copilot",
      chatSub: "Build workflow by chat",
      chatWelcome:
        "Describe your ad in chat; use **+ Upload** for files when needed.",
      chatPlaceholder: "Describe your ad — files and links are optional.",
      chatSend: "Send",
      canvasTitle: "Workflow Canvas",
      chatRunStarted: "Run created: {id}. Executing script → storyboard → video.",
      chatNodeQueued: "Node rerun queued: {node}",
      chatHintHook: "Switched to Script node. Edit hook and branch rerun.",
      chatHintStoryboard: "Switched to Storyboard node. Add notes and rerun.",
      chatHintVideo: "Switched to Video node. Rerun only video.",
      chatApplyInput: "Your request is written to Input node. Click Run workflow.",
      chatGuideGreeting:
        "Hi! Just tell me what ad you want.\n\nOptional: **+ Upload** for PDFs, tables, videos, images (up to 8). Text-only is fine.",
      chatGuideVague:
        "I need a bit more detail. Try:\n\"15s TikTok ad for @Elite 300, camping scene, strong 2s hook\"\n\nOr pick a template below.",
      chatGuideProduct: "Got it. Please provide the product name (e.g. Elite 300).",
      chatGuideBrief:
        "Product noted. Add goals: duration, scene, audience, and key selling points or hook style.",
      chatGuideDuration: "Almost there. Default is 15s vertical. Tell me if you want another length.",
      chatGuideScenario:
        "Add scene or audience (e.g. TikTok, camping, home backup), or @ a style direction.",
      chatBriefReady:
        "Synced to Input node — edit in Inspector if needed.\nRun all when ready, or say \"run\".",
      chatBriefPartial: "Noted: {snippet}\n\n{next}",
      chatGuideRunFirst:
        "To control script/storyboard/video nodes, run the workflow once first so those nodes have outputs. Complete Input, then say \"run\".",
      chatGuideHookMissing:
        "Tell me the hook text first. Example: \"change hook to: Start with a blackout anxiety question in the first 2 seconds.\"",
      chatGuideScriptHookApplied:
        "Hook is written to Script node. Want me to rerun script now? Say \"rerun script\" or \"branch rerun script\".",
      chatGuideScriptSaved:
        "Script node is saved. To continue, say \"rerun storyboard\" or \"run\".",
      chatGuideStoryboardMissing:
        "Please provide storyboard adjustment notes first. Example: \"faster first three shots, closer product close-up.\"",
      chatGuideStoryboardApplied:
        "Storyboard note is recorded. Want me to rerun storyboard now? Say \"rerun storyboard\" or \"branch rerun storyboard\".",
      tplQuickUgc: "UGC quick scale",
      tplDemo: "Product demo",
      tplBenefit: "Pain-point hook",
      heroTitle: "What ad do you want to create?",
      heroLead: "Let Agent build and execute the workflow through chat",
      tabBrief: "Describe",
      tabUrl: "Product URL",
      briefPlaceholder: "e.g. Elite 300, 15s vertical ad, camping scene, strong portability + long runtime…",
      urlPlaceholder: "https://your-store.com/product/…",
      urlHint: "Use URL + notes. Agent maps them to Input node parameters.",
      urlBriefPlaceholder: "Optional: audience, style, CTA",
      mentionHint: "Type @ to insert product/style",
      chip1: "Outdoor power · TikTok",
      chip2: "Home backup · Emergency",
      chip3: "Power bank · Fast charge",
      ex1: "15s TikTok ad for portable power, camping scene, lightweight & long runtime",
      ex2: "Home backup battery, outage scenario, warm family tone, English VO",
      ex3: "Compact power bank, commute scene, fast cuts, highlight fast charging",
      optVoice: "Voiceover",
      optCount: "Variants",
      optRatio: "Aspect",
      count1: "1",
      count2: "2",
      count3: "3",
      ratio916: "9:16 vertical",
      legacyRatioLocked: "Aspect ratio is locked to 9:16",
      generate: "Generate",
      generating: "Creating…",
      guestHint: "Log in to run and save workflows",
      previewTitle: "Preview",
      previewEmpty: "Video preview appears here",
      previewWaiting: "Video starts after storyboard",
      previewRendering: "Rendering video…",
      previewReady: "Video ready",
      previewNotStarted: "Not started",
      previewRenderingStatus: "Rendering…",
      previewWaitingStatus: "Waiting video",
      downloadVideo: "Download video",
      downloadZip: "Download ZIP",
      branchCompare: "Branch compare",
      compareEmpty: "No branch versions yet",
      compareLeft: "Left branch",
      compareRight: "Right branch",
      compareHook: "Hook",
      compareStoryboard: "Storyboard text",
      compareVideoStatus: "Video status",
      diffSame: "Same",
      diffChanged: "Changed",
      compareOnlyDiff: "Only differences",
      compareNoDiff: "No differences between selected branches",
      setActiveLeft: "Set left as active",
      setActiveRight: "Set right as active",
      nodeProductInfo: "Input",
      nodeProductAssets: "Product Assets",
      nodeBenchmark: "Benchmark",
      nodeBrief: "Creative Brief",
      nodeInput: "Input",
      nodeInputHint: "Waiting for prompt",
      stepScript: "Script",
      stepStoryboard: "Storyboard",
      stepRender: "Render",
      stepQA: "QA Pack",
      stepVideo: "Video",
      statusPending: "Pending",
      statusRunning: "Running",
      statusDone: "Done",
      statusFail: "Failed",
      scriptWait: "Edit hook on node, waiting for run",
      storyWait: "Storyboard starts after script",
      videoWait: "Video starts after storyboard",
      productInfoHint: "Fill product name and product URL in Input node; spec tables can be uploaded and parsed.",
      productAssetsHint: "Upload product images/videos; parsed asset summary appears here.",
      productAssetsReady: "Asset analysis is ready for brief strategy.",
      benchmarkHint: "Provide benchmark video URL or upload a benchmark video file.",
      qaWaitHint: "Waiting for render output before QA.",
      qaRunningHint: "QA running: checking video output and package files.",
      qaDoneHint: "QA passed. Video and package are ready.",
      qaFailHint: "QA failed. Rerun render/storyboard to fix.",
      branchMain: "Main",
      branchFrom: "Branch",
      inspectorTitle: "Inspector",
      inspectorEmpty: "No editable node yet",
      fieldBrief: "Brief",
      fieldRefVideo: "Reference video URL",
      fieldRefVideoPh: "https://tiktok.com/... or YouTube link",
      fieldMaterialCtx: "Material analysis (auto)",
      fieldUrl: "Product URL",
      fieldProduct: "Product",
      fieldDirection: "Style",
      fieldNote: "Adjustment note",
      notePlaceholderScript: "e.g. stronger direct hook",
      notePlaceholderStoryboard: "e.g. closer camera, bigger product framing",
      storyPromptPreview: "Storyboard prompt preview",
      saveOnly: "Save only",
      branchRunStoryboard: "Branch + rerun storyboard",
      rerunCurrentStoryboard: "Rerun current storyboard",
      branchRunVideo: "Branch + rerun video",
      rerunCurrentVideo: "Rerun current video",
      videoNodeHint: "Only reruns video, script/storyboard unchanged.",
      impactNone: "No pending recalculation nodes",
      impactPending: "Pending recalculation path: {nodes}",
      impactedBy: "Impacted by: {reason}",
      authChecking: "Checking sign-in…",
      authPopup: "Complete sign-in in popup…",
      authConnecting: "Connecting account…",
      loginRequired: "Please sign in first.",
      estimateCredits: "Est. {range} credits{fallback}",
      estimateFallback: " (estimate)",
      errBrief: "Please describe your ad request.",
      errInsufficient: "Insufficient credits: {coin} balance, {needed} required.",
      errCreate: "Failed: {msg}",
      errSync: "Sync failed: {msg}",
      errInit: "Init failed: {msg}",
      inputNeedProduct: "Please fill product name in Input node.",
      errProductInvalid: "Selected product does not exist: {name}. Update it in Input node.",
      inputReadyHint: "Input looks valid and ready to run.",
      mentionProduct: "Product",
      mentionStyle: "Style",
      hookRequired: "Hook cannot be empty",
      actionFailed: "Action failed: {msg}",
      errEdgeInvalid: "Invalid link: duplicate or cyclic dependency.",
      batchLabel: "Batch {id}",
      chatTplApplied: "Template applied to Input node. Run workflow now.",
      vipBannerText: "Upgrade to VIP for more credits, priority rendering, and premium templates",
      vipBannerCta: "Upgrade now",
      projectUntitled: "Untitled Flow",
      runAll: "Run all",
      upgrade: "Upgrade",
      addProduct: "+ Product",
      mentionBtn: "@ Mention",
      addFiles: "+ Upload",
      addFilesTitle: "PDF, Word, spreadsheets, video, images — up to 8",
      dropFilesHere: "Drop files to upload",
      mentionTitle: "Pick a product or style to @mention",
      mentionProducts: "Products",
      mentionStyles: "Styles",
      mentionEmpty: "No products or styles configured yet",
      attachPdf: "PDF",
      attachDocx: "Word",
      attachCsv: "CSV",
      attachXlsx: "Excel",
      attachVideo: "Ref video",
      attachImage: "Image",
      attachText: "Text",
      attachTooMany: "Up to {max} files per upload",
      chatAttachOnly: "(uploaded reference materials)",
      chatIntakeDone: "Materials parsed into Input node (product: {product}). Check Brief and style summary in Inspector.",
      chatIntakeFailed: "Material analysis failed: {msg}",
      aiBuilding: "AI is building — canvas editing paused",
      copilotStatePlanning: "Planning…",
      copilotStateReady: "Ready",
      copilotStateThinking: "Thinking…",
      copilotStateBuilding: "Building…",
      copilotStateError: "Error",
      copilotThinking: "Thinking…",
      chatStop: "Stop",
    },
  };

  let locale = "zh";

  function t(key, vars = {}) {
    let s = STRINGS[locale]?.[key] ?? STRINGS.zh[key] ?? key;
    Object.entries(vars).forEach(([k, v]) => {
      s = s.replace(new RegExp(`\\{${k}\\}`, "g"), String(v));
    });
    return s;
  }

  function hasKey(key) {
    return !!(STRINGS[locale]?.[key] ?? STRINGS.zh[key]);
  }

  function applyI18n() {
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
    document.title = hasKey("brand") ? t("brand") : document.title;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.dataset.i18n;
      if (!key || !hasKey(key)) return;
      el.textContent = t(key);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.dataset.i18nPlaceholder;
      if (!key || !hasKey(key)) return;
      el.placeholder = t(key);
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const key = el.dataset.i18nTitle;
      if (!key || !hasKey(key)) return;
      el.title = t(key);
    });
    document.querySelectorAll("[data-i18n-example]").forEach((el) => {
      el.dataset.example = t(el.dataset.i18nExample);
      if (el.dataset.i18n) el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-ui-locale]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.uiLocale === locale);
      btn.setAttribute("aria-pressed", btn.dataset.uiLocale === locale ? "true" : "false");
    });
  }

  function setLocale(next) {
    if (next !== "zh" && next !== "en") return;
    locale = next;
    localStorage.setItem(STORAGE_KEY, locale);
    applyI18n();
    window.dispatchEvent(new CustomEvent("ui-locale-change", { detail: { locale } }));
  }

  async function initLocale() {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "zh" || saved === "en") {
      locale = saved;
      applyI18n();
      return { locale, source: "storage" };
    }
    try {
      const res = await fetch("/api/toc/locale", { credentials: "include" });
      const data = await res.json();
      locale = data.locale === "en" ? "en" : "zh";
      applyI18n();
      return data;
    } catch {
      locale = "zh";
      applyI18n();
      return { locale: "zh", source: "fallback" };
    }
  }

  window.FlowI18n = { t, initLocale, setLocale, applyI18n, getLocale: () => locale };
})();
