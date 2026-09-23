const state = {
  config: null,
  service: null,
  authenticated: false,
  authSessionId: null,
  authTimer: null,
};

const els = {
  connectionState: document.querySelector("#connectionState"),
  workerState: document.querySelector("#workerState"),
  workerPid: document.querySelector("#workerPid"),
  workerUptime: document.querySelector("#workerUptime"),
  workerMode: document.querySelector("#workerMode"),
  cacheUsage: document.querySelector("#cacheUsage"),
  maxCacheGb: document.querySelector("#maxCacheGb"),
  visibilityState: document.querySelector("#visibilityState"),
  targetCount: document.querySelector("#targetCount"),
  servicePulse: document.querySelector("#servicePulse"),
  startButton: document.querySelector("#startButton"),
  stopButton: document.querySelector("#stopButton"),
  restartButton: document.querySelector("#restartButton"),
  saveButton: document.querySelector("#saveButton"),
  refreshButton: document.querySelector("#refreshButton"),
  autoRestart: document.querySelector("#autoRestart"),
  deleteAfterUpload: document.querySelector("#deleteAfterUpload"),
  visibilityControl: document.querySelector("#visibilityControl"),
  targetList: document.querySelector("#targetList"),
  targetEmpty: document.querySelector("#targetEmpty"),
  targetForm: document.querySelector("#targetForm"),
  targetName: document.querySelector("#targetName"),
  targetUrl: document.querySelector("#targetUrl"),
  logView: document.querySelector("#logView"),
  clearLogButton: document.querySelector("#clearLogButton"),
  loginButton: document.querySelector("#loginButton"),
  loginLabel: document.querySelector("#loginLabel"),
  loginModal: document.querySelector("#loginModal"),
  closeLoginButton: document.querySelector("#closeLoginButton"),
  qrImage: document.querySelector("#qrImage"),
  qrLoading: document.querySelector("#qrLoading"),
  loginMessage: document.querySelector("#loginMessage"),
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
  window.setTimeout(() => node.remove(), 3600);
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
    state.service = await api("/api/state").then((payload) => payload.service);
    renderService();
  } catch (_error) {
    els.connectionState.classList.remove("online");
  }
}

async function refreshLogs() {
  try {
    const payload = await api("/api/logs?lines=220");
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
  els.cacheUsage.textContent = `${service.cache_used_gb ?? "--"} / ${service.cache_limit_gb ?? "--"} GB`;
  els.servicePulse.classList.toggle("online", running);
  els.startButton.disabled = running;
  els.stopButton.disabled = !running;
  els.restartButton.disabled = !running;
  els.startButton.classList.toggle("disabled", running);
  els.stopButton.classList.toggle("disabled", !running);
  els.restartButton.classList.toggle("disabled", !running);
}

function renderSettings() {
  if (!state.config) return;
  els.visibilityState.textContent = state.config.public ? "公开投稿" : "仅自己可见";
  els.targetCount.textContent = `${state.config.targets.length} 个主播`;
  els.autoRestart.checked = Boolean(state.config.auto_restart);
  els.deleteAfterUpload.checked = Boolean(state.config.delete_after_upload);
  els.maxCacheGb.value = state.config.max_cache_gb ?? 10;
  for (const button of els.visibilityControl.querySelectorAll("button")) {
    const wanted = button.dataset.value === (state.config.public ? "public" : "private");
    button.classList.toggle("active", wanted);
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

  for (const target of targets) {
    const row = document.createElement("div");
    row.className = "target-row";

    const identity = document.createElement("div");
    identity.className = "target-controls";
    const enableLabel = document.createElement("label");
    enableLabel.className = "switch-row compact-switch";
    const status = document.createElement("span");
    status.className = `target-status ${target.enabled ? "enabled" : "disabled"}`;
    const dot = document.createElement("span");
    dot.className = "status-dot";
    const statusText = document.createElement("span");
    const latest = latestByTarget.get(target.name);
    statusText.textContent = target.enabled ? latest?.status || "待机" : "已暂停";
    status.append(dot, statusText);
    enableLabel.append(status);

    const enabledInput = document.createElement("input");
    enabledInput.type = "checkbox";
    enabledInput.checked = target.enabled;
    enabledInput.addEventListener("change", () => {
      target.enabled = enabledInput.checked;
      status.className = `target-status ${target.enabled ? "enabled" : "disabled"}`;
      statusText.textContent = target.enabled ? "待保存" : "已暂停";
    });
    const switchTrack = document.createElement("span");
    switchTrack.className = "switch-track";
    enableLabel.append(enabledInput, switchTrack);
    identity.append(enableLabel);

    const fields = document.createElement("div");
    fields.className = "target-controls target-fields";
    const nameInput = document.createElement("input");
    nameInput.value = target.name;
    nameInput.setAttribute("aria-label", "主播名称");
    nameInput.addEventListener("input", () => {
      target.name = nameInput.value;
    });
    const urlInput = document.createElement("input");
    urlInput.value = target.url;
    urlInput.setAttribute("aria-label", "直播间或主页链接");
    urlInput.addEventListener("input", () => {
      target.url = urlInput.value;
    });
    fields.append(nameInput, urlInput);

    const actions = document.createElement("div");
    actions.className = "target-controls";
    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "icon-button target-delete";
    deleteButton.title = "删除主播";
    deleteButton.append(icon("trash-2"));
    deleteButton.addEventListener("click", () => {
      state.config.targets = state.config.targets.filter((item) => item.id !== target.id);
      renderTargets();
      renderIcons();
    });
    actions.append(deleteButton);

    row.append(identity, fields, actions);
    els.targetList.append(row);
  }
  renderIcons();
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  return [hours, minutes, secs].map((part) => String(part).padStart(2, "0")).join(":");
}

async function saveState() {
  if (!state.config) return;
  if (!state.config.targets.length) {
    toast("至少添加一个监视主播", "error");
    return;
  }
  try {
    const payload = await api("/api/state", {
      method: "PUT",
      body: JSON.stringify(state.config),
    });
    state.config = payload.config;
    render();
    toast("设置已保存");
  } catch (error) {
    toast(`保存失败：${error.message}`, "error");
  }
}

async function serviceAction(action) {
  try {
    state.service = await api(`/api/service/${action}`, { method: "POST" });
    renderService();
    toast(action === "start" ? "录制服务已启动" : action === "stop" ? "录制服务已停止" : "录制服务已重启");
    window.setTimeout(refreshLogs, 700);
  } catch (error) {
    toast(`操作失败：${error.message}`, "error");
  }
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
    els.loginMessage.textContent = "请使用 B 站手机客户端扫码";
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
      state.authenticated = true;
      renderSettings();
      toast("B站登录成功");
      window.setTimeout(closeLogin, 900);
    }
    if (payload.state === "expired") {
      window.clearInterval(state.authTimer);
      state.authTimer = null;
      els.loginMessage.textContent = "二维码已过期，请重新打开登录窗口";
    }
  } catch (error) {
    els.loginMessage.textContent = `登录状态检查失败：${error.message}`;
  }
}

els.startButton.addEventListener("click", () => serviceAction("start"));
els.stopButton.addEventListener("click", () => serviceAction("stop"));
els.restartButton.addEventListener("click", () => serviceAction("restart"));
els.saveButton.addEventListener("click", saveState);
els.refreshButton.addEventListener("click", async () => {
  els.refreshButton.firstElementChild?.classList.add("spin");
  await loadState(true);
  window.setTimeout(() => els.refreshButton.firstElementChild?.classList.remove("spin"), 400);
});
els.clearLogButton.addEventListener("click", refreshLogs);
els.autoRestart.addEventListener("change", () => {
  state.config.auto_restart = els.autoRestart.checked;
});
els.deleteAfterUpload.addEventListener("change", () => {
  state.config.delete_after_upload = els.deleteAfterUpload.checked;
});
els.maxCacheGb.addEventListener("change", () => {
  const value = Math.max(1, Number(els.maxCacheGb.value) || 10);
  state.config.max_cache_gb = value;
  els.maxCacheGb.value = value;
});
els.visibilityControl.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-value]");
  if (!button) return;
  state.config.public = button.dataset.value === "public";
  renderSettings();
});
els.targetForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const name = els.targetName.value.trim();
  const url = els.targetUrl.value.trim();
  if (!name || !url) return;
  state.config.targets.push({
    id: Math.random().toString(16).slice(2, 12),
    name,
    url,
    enabled: true,
    title_template: "{name}｜{start_date} {start_time} 开播｜{room_title}",
    tags: ["直播录像", "抖音"],
    tid: 171,
    copyright: 2,
    source: "",
  });
  els.targetForm.reset();
  renderTargets();
  renderSettings();
  toast("已添加，保存后生效");
});
els.loginButton.addEventListener("click", openLogin);
els.closeLoginButton.addEventListener("click", closeLogin);
els.loginModal.addEventListener("click", (event) => {
  if (event.target === els.loginModal) closeLogin();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.loginModal.hidden) closeLogin();
});

loadState(true);
refreshLogs();
window.setInterval(refreshService, 3000);
window.setInterval(refreshLogs, 3500);
renderIcons();
