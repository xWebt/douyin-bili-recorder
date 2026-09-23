const state = {
  config: null,
  service: null,
  authenticated: false,
  authSessionId: null,
  authTimer: null,
  library: null,
  analyticsTarget: "",
};

const els = {
  connectionState: document.querySelector("#connectionState"),
  workerState: document.querySelector("#workerState"),
  workerPid: document.querySelector("#workerPid"),
  workerUptime: document.querySelector("#workerUptime"),
  workerMode: document.querySelector("#workerMode"),
  cacheUsage: document.querySelector("#cacheUsage"),
  activeCache: document.querySelector("#activeCache"),
  cacheBar: document.querySelector("#cacheBar"),
  maxCacheGb: document.querySelector("#maxCacheGb"),
  cacheSettingHint: document.querySelector("#cacheSettingHint"),
  targetCount: document.querySelector("#targetCount"),
  collectionState: document.querySelector("#collectionState"),
  servicePulse: document.querySelector("#servicePulse"),
  startButton: document.querySelector("#startButton"),
  stopButton: document.querySelector("#stopButton"),
  restartButton: document.querySelector("#restartButton"),
  saveButton: document.querySelector("#saveButton"),
  refreshButton: document.querySelector("#refreshButton"),
  autoRestart: document.querySelector("#autoRestart"),
  deleteAfterUpload: document.querySelector("#deleteAfterUpload"),
  defaultVisibility: document.querySelector("#defaultVisibility"),
  videoDir: document.querySelector("#videoDir"),
  lateThreshold: document.querySelector("#lateThreshold"),
  reconnectGrace: document.querySelector("#reconnectGrace"),
  targetList: document.querySelector("#targetList"),
  targetEmpty: document.querySelector("#targetEmpty"),
  targetForm: document.querySelector("#targetForm"),
  targetName: document.querySelector("#targetName"),
  targetUrl: document.querySelector("#targetUrl"),
  resolveButton: document.querySelector("#resolveButton"),
  logView: document.querySelector("#logView"),
  clearLogButton: document.querySelector("#clearLogButton"),
  loginButton: document.querySelector("#loginButton"),
  loginLabel: document.querySelector("#loginLabel"),
  loginModal: document.querySelector("#loginModal"),
  closeLoginButton: document.querySelector("#closeLoginButton"),
  qrImage: document.querySelector("#qrImage"),
  qrLoading: document.querySelector("#qrLoading"),
  loginMessage: document.querySelector("#loginMessage"),
  stopModal: document.querySelector("#stopModal"),
  pauseUploadButton: document.querySelector("#pauseUploadButton"),
  pauseKeepButton: document.querySelector("#pauseKeepButton"),
  pauseCancelButton: document.querySelector("#pauseCancelButton"),
  videoLibraryButton: document.querySelector("#videoLibraryButton"),
  videoLibraryModal: document.querySelector("#videoLibraryModal"),
  closeVideoLibrary: document.querySelector("#closeVideoLibrary"),
  videoRootPath: document.querySelector("#videoRootPath"),
  openRootButton: document.querySelector("#openRootButton"),
  libraryList: document.querySelector("#libraryList"),
  analyticsModal: document.querySelector("#analyticsModal"),
  closeAnalytics: document.querySelector("#closeAnalytics"),
  analyticsTitle: document.querySelector("#analyticsTitle"),
  analyticsMetrics: document.querySelector("#analyticsMetrics"),
  analyticsRows: document.querySelector("#analyticsRows"),
  delayChart: document.querySelector("#delayChart"),
  durationChart: document.querySelector("#durationChart"),
  toastRegion: document.querySelector("#toastRegion"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function icon(name) {
  const element = document.createElement("i");
  element.dataset.lucide = name;
  return element;
}

function renderIcons() {
  if (window.lucide) window.lucide.createIcons();
}

function toast(message, type = "info") {
  const node = document.createElement("div");
  node.className = `toast ${type}`;
  node.textContent = message;
  els.toastRegion.append(node);
  window.setTimeout(() => node.remove(), 4200);
}

async function loadState(showErrors = false) {
  try {
    const payload = await api("/api/state");
    state.config = payload.config;
    state.service = payload.service;
    state.authenticated = payload.authenticated;
    render();
  } catch (error) {
    els.connectionState.classList.remove("online");
    els.connectionState.lastElementChild.textContent = "连接失败";
    if (showErrors) toast(error.message, "error");
  }
}

async function refreshService() {
  try {
    const payload = await api("/api/state");
    state.config = payload.config;
    state.service = payload.service;
    state.authenticated = payload.authenticated;
    renderService();
    renderSettings();
  } catch (_error) {
    els.connectionState.classList.remove("online");
  }
}

async function refreshLogs() {
  try {
    const payload = await api("/api/logs?lines=260");
    els.logView.textContent = payload.lines.length ? payload.lines.join("\n") : "等待录制进程输出...";
    els.logView.scrollTop = els.logView.scrollHeight;
  } catch (_error) {
    els.logView.textContent = "日志暂时不可用";
  }
}

function render() {
  renderService();
  renderSettings();
  renderTargets();
  renderIcons();
}

function renderService() {
  const service = state.service || {};
  const running = Boolean(service.running);
  els.connectionState.classList.toggle("online", running);
  els.connectionState.lastElementChild.textContent = running ? "录制服务运行中" : "录制服务已停止";
  els.workerState.textContent = running ? "运行中" : "已停止";
  els.workerPid.textContent = running ? `PID ${service.pid}` : "PID -";
  els.workerUptime.textContent = formatDuration(service.uptime_seconds || 0);
  els.workerMode.textContent = running ? "后台守护 / 自动恢复" : "后台守护待命";
  const used = Number(service.cache_used_gb || 0);
  const limit = Number(service.cache_limit_gb || 10);
  const active = Number(service.active_cache_limit_gb || limit);
  els.cacheUsage.textContent = `${used.toFixed(2)} / ${limit} GB`;
  els.activeCache.textContent = `当前运行实例 ${active} GB`;
  els.cacheBar.style.width = `${Math.min(100, limit ? (used / limit) * 100 : 0)}%`;
  els.servicePulse.classList.toggle("online", running);
  els.startButton.disabled = running;
  els.stopButton.disabled = !running;
  els.restartButton.disabled = !running;
}

function renderSettings() {
  if (!state.config) return;
  els.targetCount.textContent = `${state.config.targets.length} 个主播`;
  const bound = state.config.targets.filter((target) => target.collection_id).length;
  els.collectionState.textContent = `${bound} 个合集已绑定`;
  els.autoRestart.checked = Boolean(state.config.auto_restart);
  els.deleteAfterUpload.checked = Boolean(state.config.delete_after_upload);
  els.maxCacheGb.value = state.config.max_cache_gb ?? 10;
  els.cacheSettingHint.textContent = `已保存分配 ${state.config.max_cache_gb ?? 10} GB`;
  els.videoDir.value = state.config.video_dir || "~/Movies/DouyinBiliRecorder";
  els.lateThreshold.value = state.config.late_threshold_minutes ?? 5;
  els.reconnectGrace.value = state.config.reconnect_grace_minutes ?? 15;
  for (const button of els.defaultVisibility.querySelectorAll("button")) {
    button.classList.toggle("active", button.dataset.value === (state.config.public ? "public" : "private"));
  }
  els.loginLabel.textContent = state.authenticated ? "B站已登录" : "B站登录";
}

function renderTargets() {
  els.targetList.replaceChildren();
  const targets = state.config?.targets || [];
  els.targetEmpty.hidden = targets.length > 0;
  const latestByTarget = new Map();
  for (const session of state.service?.sessions || []) {
    if (!latestByTarget.has(session.target_name)) latestByTarget.set(session.target_name, session);
  }
  for (const target of targets) els.targetList.append(buildTargetRow(target, latestByTarget.get(target.name)));
  renderIcons();
}

function buildTargetRow(target, latest) {
  const row = document.createElement("article");
  row.className = "target-row";
  row.dataset.targetId = target.id;
  const header = document.createElement("div");
  header.className = "target-header";
  const identity = document.createElement("div");
  identity.className = "target-identity";
  const status = document.createElement("span");
  status.className = `target-status ${target.enabled ? "enabled" : "disabled"}`;
  status.append(makeDot(), document.createTextNode(target.enabled ? latest?.status || "待机" : "已暂停"));
  const name = document.createElement("strong");
  name.textContent = target.name || "未命名主播";
  const url = document.createElement("small");
  url.textContent = target.url;
  identity.append(status, name, url);

  const actions = document.createElement("div");
  actions.className = "target-actions";
  const enabled = checkbox(target.enabled);
  enabled.title = "启用/暂停";
  enabled.addEventListener("change", () => { target.enabled = enabled.checked; renderTargets(); });
  actions.append(
    enabled,
    actionButton("bar-chart-3", "数据详情", () => openAnalytics(target.name)),
    actionButton("folder-open", "打开目录", () => openFolder("anchor", target.name)),
    actionButton("trash-2", "删除主播", () => {
      state.config.targets = state.config.targets.filter((item) => item.id !== target.id);
      renderTargets();
    }),
  );
  header.append(identity, actions);

  const main = document.createElement("div");
  main.className = "target-main-grid";
  const nameField = labelledInput("主播名称", target.name, (value) => { target.name = value; });
  const urlField = labelledInput("链接", target.url, (value) => { target.url = value; }, "url-field");
  const collectionField = labelledInput("合集名称", target.collection_name || target.name, (value) => {
    target.collection_name = value;
  });
  nameField.querySelector("input").dataset.field = "name";
  urlField.querySelector("input").dataset.field = "url";
  collectionField.querySelector("input").dataset.field = "collection_name";
  main.append(nameField, urlField, collectionField);

  const controls = document.createElement("div");
  controls.className = "target-option-grid";
  controls.append(
    segmentedControl("稿件权限", target.public ? "public" : "private", [
      ["private", "仅自己"], ["public", "公开"],
    ], (value) => { target.public = value === "public"; }),
    segmentedControl("监控模式", target.record_mode || "record", [
      ["record", "录制视频"], ["monitor", "仅数据"],
    ], (value) => { target.record_mode = value; }),
  );
  const collection = document.createElement("div");
  collection.className = "collection-state";
  collection.innerHTML = `<span>合集 ID</span><code>${target.collection_id || "保存后自动创建"}</code>`;
  controls.append(collection);

  const schedule = document.createElement("details");
  schedule.className = "schedule-editor";
  const summary = document.createElement("summary");
  summary.textContent = `直播排班 · ${(target.schedule || []).length} 个时段`;
  schedule.append(summary, buildScheduleList(target));
  const saveBar = document.createElement("div");
  saveBar.className = "target-save-bar";
  const saveTarget = document.createElement("button");
  saveTarget.type = "button";
  saveTarget.className = "save-button compact-save";
  saveTarget.append(icon("save"), document.createTextNode("保存主播设置"));
  saveTarget.addEventListener("click", () => saveState(`${target.name} 的设置已保存`));
  const saveHint = document.createElement("small");
  saveHint.textContent = "排班、权限、合集和监控模式会一起保存";
  saveBar.append(saveTarget, saveHint);
  row.append(header, main, controls, schedule, saveBar);
  return row;
}

function buildScheduleList(target) {
  const wrapper = document.createElement("div");
  wrapper.className = "schedule-list";
  const slots = target.schedule || (target.schedule = []);
  if (!slots.length) slots.push({ days: [1, 3, 5], start: "20:00", end: "23:00", enabled: true });
  slots.forEach((slot, index) => {
    const line = document.createElement("div");
    line.className = "schedule-row";
    line.dataset.slotIndex = String(index);
    const daysField = labelledInput("星期（1-7，逗号分隔）", (slot.days || []).join(","), (value) => {
        slot.days = value.split(",").map(Number).filter((day) => day >= 1 && day <= 7);
      });
    const startField = labelledInput("预计开播", slot.start || "20:00", (value) => { slot.start = value; }, "", "time");
    const endField = labelledInput("预计结束", slot.end || "23:00", (value) => { slot.end = value; }, "", "time");
    daysField.querySelector("input").dataset.scheduleField = "days";
    startField.querySelector("input").dataset.scheduleField = "start";
    endField.querySelector("input").dataset.scheduleField = "end";
    line.append(daysField, startField, endField);
    const remove = actionButton("minus", "删除时段", () => { slots.splice(index, 1); renderTargets(); });
    line.append(remove);
    wrapper.append(line);
  });
  wrapper.append(actionButton("plus", "添加时段", () => {
    slots.push({ days: [1, 3, 5], start: "20:00", end: "23:00", enabled: true });
    renderTargets();
  }));
  return wrapper;
}

function labelledInput(label, value, onChange, className = "", type = "text") {
  const wrapper = document.createElement("label");
  if (className) wrapper.className = className;
  const span = document.createElement("span");
  span.textContent = label;
  const input = document.createElement("input");
  input.type = type;
  input.value = value || "";
  input.addEventListener("input", () => onChange(input.value));
  wrapper.append(span, input);
  return wrapper;
}

function segmentedControl(label, value, options, onChange) {
  const wrapper = document.createElement("div");
  wrapper.className = "compact-control";
  const title = document.createElement("span");
  title.textContent = label;
  const group = document.createElement("div");
  group.className = "segmented compact";
  for (const [key, text] of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.classList.toggle("active", key === value);
    button.addEventListener("click", () => { onChange(key); renderTargets(); });
    group.append(button);
  }
  wrapper.append(title, group);
  return wrapper;
}

function actionButton(iconName, title, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button";
  button.title = title;
  button.append(icon(iconName));
  button.addEventListener("click", handler);
  return button;
}

function makeDot() {
  const dot = document.createElement("span");
  dot.className = "status-dot";
  return dot;
}

function checkbox(checked) {
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.className = "row-checkbox";
  return input;
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
}

async function saveState(message = "") {
  if (!state.config) return;
  if (!state.config.targets.length) {
    toast("至少添加一个监视主播", "error");
    return false;
  }
  try {
    syncStateFromDom();
    const payload = await api("/api/state", { method: "PUT", body: JSON.stringify(state.config) });
    state.config = payload.config;
    render();
    toast(message || (payload.restart_required ? "设置已保存；缓存将在下一分段或重启后生效" : "设置已保存"));
    return true;
  } catch (error) {
    toast(`保存失败：${error.message}`, "error");
    return false;
  }
}

function syncStateFromDom() {
  if (!state.config) return;
  for (const row of els.targetList.querySelectorAll(".target-row[data-target-id]")) {
    const target = state.config.targets.find((item) => item.id === row.dataset.targetId);
    if (!target) continue;
    for (const input of row.querySelectorAll("input[data-field]")) {
      target[input.dataset.field] = input.value;
    }
    const scheduleRows = [...row.querySelectorAll(".schedule-row[data-slot-index]")];
    if (scheduleRows.length) {
      target.schedule = scheduleRows.map((scheduleRow) => {
        const slot = {
          days: [],
          start: "20:00",
          end: "23:00",
          enabled: true,
        };
        for (const input of scheduleRow.querySelectorAll("input[data-schedule-field]")) {
          if (input.dataset.scheduleField === "days") {
            slot.days = input.value.split(",").map(Number).filter((day) => day >= 1 && day <= 7);
          } else {
            slot[input.dataset.scheduleField] = input.value;
          }
        }
        return slot;
      });
    }
  }
}

async function serviceAction(action, mode = "upload") {
  try {
    state.service = await api(`/api/service/${action}?mode=${encodeURIComponent(mode)}`, { method: "POST" });
    renderService();
    closeStopDialog();
    toast(action === "start" ? "录制服务已启动" : action === "stop" ? (mode === "upload" ? "正在收尾并上传当前内容" : "已暂停并保留本地内容") : "录制服务已重启");
    window.setTimeout(refreshLogs, 800);
  } catch (error) {
    toast(`操作失败：${error.message}`, "error");
  }
}

function openStopDialog() { els.stopModal.hidden = false; }
function closeStopDialog() { els.stopModal.hidden = true; }

async function resolveTargetUrl() {
  const url = els.targetUrl.value.trim();
  if (!url) return toast("先输入抖音链接", "error");
  els.resolveButton.disabled = true;
  try {
    const result = await api("/api/targets/resolve", { method: "POST", body: JSON.stringify({ url }) });
    const resolvedUrl = result.canonical_url || url;
    const resolvedName = els.targetName.value.trim() || result.anchor_name || `主播-${state.config.targets.length + 1}`;
    let target = state.config.targets.find((item) => item.url === resolvedUrl || item.url === url);
    if (!target) {
      target = {
        id: Math.random().toString(16).slice(2, 12),
        name: resolvedName,
        url: resolvedUrl,
        enabled: true,
        public: Boolean(state.config.public),
        record_mode: "record",
        collection_name: resolvedName,
        collection_id: "",
        title_template: "{name}｜{start_date} {start_time} 开播｜{room_title}",
        tags: ["直播录像", "抖音"],
        tid: 171,
        copyright: 2,
        source: "",
        schedule: [{ days: [1, 3, 5], start: "20:00", end: "23:00", enabled: true }],
      };
      state.config.targets.push(target);
    } else {
      target.url = resolvedUrl;
      if (!target.name && result.anchor_name) target.name = result.anchor_name;
      if (!target.collection_name) target.collection_name = target.name;
    }
    const saved = await saveState(`${target.name} 已解析并自动保存`);
    if (saved) {
      els.targetForm.reset();
      renderTargets();
      renderSettings();
    }
  } catch (error) {
    toast(`解析失败：${error.message}`, "error");
  } finally {
    els.resolveButton.disabled = false;
  }
}

async function openAnalytics(name) {
  state.analyticsTarget = name;
  els.analyticsTitle.textContent = `${name} · 本月数据`;
  els.analyticsModal.hidden = false;
  try {
    const data = await api(`/api/targets/${encodeURIComponent(name)}/analytics`);
    renderAnalytics(data);
  } catch (error) {
    toast(`统计数据读取失败：${error.message}`, "error");
  }
}

function renderAnalytics(data) {
  const metrics = [
    ["直播天数", data.live_days || 0], ["直播场次", data.sessions || 0],
    ["迟到日", data.late_days || 0], ["迟到场次", data.late_sessions || 0],
    ["总时长", formatHours(data.total_duration_seconds || 0)], ["按时率", `${data.on_time_rate || 100}%`],
  ];
  els.analyticsMetrics.replaceChildren(...metrics.map(([label, value]) => {
    const card = document.createElement("div"); card.className = "metric-card";
    card.innerHTML = `<span>${label}</span><strong>${value}</strong>`; return card;
  }));
  els.analyticsRows.replaceChildren(...(data.sessions_detail || []).slice().reverse().map((item) => {
    const row = document.createElement("tr");
    row.innerHTML = `<td>${item.date || "-"}</td><td>${shortTime(item.detected_start_iso)}</td><td>${formatHours(item.duration_seconds || 0)}</td><td>${item.late ? `迟到 ${item.late_minutes} 分钟` : "正常"}</td><td>${item.reconnect_count || 0}</td><td>${item.bvid || "-"}</td>`;
    return row;
  }));
  drawLineChart(els.delayChart, (data.sessions_detail || []).map((item) => Number(item.late_minutes || 0)), "#f3b85c");
  drawBarChart(els.durationChart, (data.sessions_detail || []).map((item) => Number(item.duration_seconds || 0)), "#74e5a5");
}

function drawLineChart(svg, values, color) {
  const width = 520, height = 180, pad = 20, max = Math.max(1, ...values);
  const points = values.map((value, index) => {
    const x = values.length <= 1 ? width / 2 : pad + (index / (values.length - 1)) * (width - pad * 2);
    const y = height - pad - (value / max) * (height - pad * 2);
    return `${x},${y}`;
  }).join(" ");
  svg.innerHTML = `<line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}" stroke="#2b3a34"/><polyline points="${points}" fill="none" stroke="${color}" stroke-width="3"/>`;
}

function drawBarChart(svg, values, color) {
  const width = 520, height = 180, pad = 20, max = Math.max(1, ...values);
  const barWidth = values.length ? Math.max(3, (width - pad * 2) / values.length - 5) : 10;
  svg.innerHTML = values.map((value, index) => {
    const barHeight = (value / max) * (height - pad * 2);
    const x = pad + index * ((width - pad * 2) / Math.max(1, values.length));
    return `<rect x="${x}" y="${height-pad-barHeight}" width="${barWidth}" height="${barHeight}" fill="${color}" rx="2"/>`;
  }).join("");
}

function formatHours(seconds) {
  const hours = Number(seconds || 0) / 3600;
  return hours >= 10 ? `${hours.toFixed(1)} h` : `${hours.toFixed(2)} h`;
}

function shortTime(iso) { return iso ? String(iso).slice(11, 16) : "-"; }

async function openVideoLibrary() {
  els.videoLibraryModal.hidden = false;
  try {
    state.library = await api("/api/videos");
    els.videoRootPath.textContent = state.library.root;
    els.libraryList.replaceChildren(...(state.library.anchors || []).map((anchor) => {
      const row = document.createElement("div"); row.className = "library-row";
      const info = document.createElement("div"); info.innerHTML = `<strong>${anchor.name}</strong><small>${anchor.path}</small>`;
      row.append(info, actionButton("folder-open", "打开主播目录", () => openFolder("anchor", anchor.name))); return row;
    }));
  } catch (error) { toast(`视频库读取失败：${error.message}`, "error"); }
}

async function openFolder(kind, name = "") {
  try { await api("/api/open-folder", { method: "POST", body: JSON.stringify({ kind, name }) }); }
  catch (error) { toast(`打开目录失败：${error.message}`, "error"); }
}

function openLogin() {
  els.loginModal.hidden = false;
  els.qrImage.removeAttribute("src");
  els.qrLoading.hidden = false;
  els.loginMessage.textContent = "正在生成二维码";
  beginLogin();
}

function closeLogin() {
  els.loginModal.hidden = true;
  if (state.authTimer) window.clearInterval(state.authTimer);
  state.authTimer = null;
}

async function beginLogin() {
  try {
    const payload = await api("/api/auth/qrcode", { method: "POST" });
    state.authSessionId = payload.session_id;
    els.qrImage.src = `data:image/png;base64,${payload.image_base64}`;
    els.qrLoading.hidden = true;
    els.loginMessage.textContent = "请使用 B站手机客户端扫码";
    if (state.authTimer) window.clearInterval(state.authTimer);
    state.authTimer = window.setInterval(pollLogin, 1800);
  } catch (error) {
    els.qrLoading.hidden = true;
    els.loginMessage.textContent = `二维码生成失败：${error.message}`;
  }
}

async function pollLogin() {
  if (!state.authSessionId) return;
  try {
    const payload = await api(`/api/auth/poll?session_id=${encodeURIComponent(state.authSessionId)}`);
    els.loginMessage.textContent = payload.message;
    if (payload.state === "authenticated") {
      state.authenticated = true; renderSettings(); toast("B站登录成功"); window.setTimeout(closeLogin, 900);
    }
    if (payload.state === "expired") { window.clearInterval(state.authTimer); state.authTimer = null; }
  } catch (error) { els.loginMessage.textContent = `登录状态检查失败：${error.message}`; }
}

els.startButton.addEventListener("click", () => serviceAction("start"));
els.stopButton.addEventListener("click", openStopDialog);
els.pauseUploadButton.addEventListener("click", () => serviceAction("stop", "upload"));
els.pauseKeepButton.addEventListener("click", () => serviceAction("stop", "keep"));
els.pauseCancelButton.addEventListener("click", closeStopDialog);
els.restartButton.addEventListener("click", () => serviceAction("restart"));
els.saveButton.addEventListener("click", saveState);
els.resolveButton.addEventListener("click", resolveTargetUrl);
els.refreshButton.addEventListener("click", () => loadState(true));
els.clearLogButton.addEventListener("click", refreshLogs);
els.autoRestart.addEventListener("change", () => { state.config.auto_restart = els.autoRestart.checked; });
els.deleteAfterUpload.addEventListener("change", () => { state.config.delete_after_upload = els.deleteAfterUpload.checked; });
els.maxCacheGb.addEventListener("input", () => { state.config.max_cache_gb = Math.max(1, Number(els.maxCacheGb.value) || 10); });
els.videoDir.addEventListener("input", () => { state.config.video_dir = els.videoDir.value; });
els.lateThreshold.addEventListener("input", () => { state.config.late_threshold_minutes = Math.max(0, Number(els.lateThreshold.value) || 0); });
els.reconnectGrace.addEventListener("input", () => { state.config.reconnect_grace_minutes = Math.max(0, Number(els.reconnectGrace.value) || 0); });
els.defaultVisibility.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-value]"); if (!button) return;
  state.config.public = button.dataset.value === "public"; renderSettings();
});
els.targetForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const url = els.targetUrl.value.trim();
  const name = els.targetName.value.trim() || `主播-${state.config.targets.length + 1}`;
  if (!url) return;
  state.config.targets.push({
    id: Math.random().toString(16).slice(2, 12), name, url, enabled: true,
    public: Boolean(state.config.public), record_mode: "record", collection_name: name, collection_id: "",
    title_template: "{name}｜{start_date} {start_time} 开播｜{room_title}",
    tags: ["直播录像", "抖音"], tid: 171, copyright: 2, source: "",
    schedule: [{ days: [1, 3, 5], start: "20:00", end: "23:00", enabled: true }],
  });
  saveState(`${name} 已添加并保存`).then((saved) => {
    if (saved) {
      els.targetForm.reset();
      renderTargets();
      renderSettings();
    }
  });
});
els.loginButton.addEventListener("click", openLogin);
els.closeLoginButton.addEventListener("click", closeLogin);
els.videoLibraryButton.addEventListener("click", openVideoLibrary);
els.closeVideoLibrary.addEventListener("click", () => { els.videoLibraryModal.hidden = true; });
els.openRootButton.addEventListener("click", () => openFolder("root"));
els.closeAnalytics.addEventListener("click", () => { els.analyticsModal.hidden = true; });

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const modal of [els.loginModal, els.stopModal, els.videoLibraryModal, els.analyticsModal]) modal.hidden = true;
});

loadState(true);
refreshLogs();
window.setInterval(refreshService, 3000);
window.setInterval(refreshLogs, 3500);
renderIcons();
