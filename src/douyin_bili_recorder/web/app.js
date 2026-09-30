const state = {
  config: null,
  service: null,
  authenticated: false,
  authSessionId: null,
  authTimer: null,
  library: null,
  analyticsTarget: "",
  submissions: null,
  reportTarget: "",
  dirty: false,
  uploadSignature: "",
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
  cloudRcloneBin: document.querySelector("#cloudRcloneBin"),
  lateThreshold: document.querySelector("#lateThreshold"),
  reconnectGrace: document.querySelector("#reconnectGrace"),
  pollInterval: document.querySelector("#pollInterval"),
  quality: document.querySelector("#quality"),
  frameRate: document.querySelector("#frameRate"),
  encodingEstimate: document.querySelector("#encodingEstimate"),
  encodingHint: document.querySelector("#encodingHint"),
  uploadPanel: document.querySelector("#uploadPanel"),
  uploadTitle: document.querySelector("#uploadTitle"),
  uploadMeta: document.querySelector("#uploadMeta"),
  uploadPercent: document.querySelector("#uploadPercent"),
  uploadBar: document.querySelector("#uploadBar"),
  uploadBytes: document.querySelector("#uploadBytes"),
  uploadSpeed: document.querySelector("#uploadSpeed"),
  uploadEta: document.querySelector("#uploadEta"),
  uploadList: document.querySelector("#uploadList"),
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
  discardButton: document.querySelector("#discardButton"),
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
  reportModal: document.querySelector("#reportModal"),
  closeReport: document.querySelector("#closeReport"),
  reportTitle: document.querySelector("#reportTitle"),
  reportNote: document.querySelector("#reportNote"),
  reportPeriodNote: document.querySelector("#reportPeriodNote"),
  currentWeekReportButton: document.querySelector("#currentWeekReportButton"),
  previousWeekReportButton: document.querySelector("#previousWeekReportButton"),
  monthlyReportButton: document.querySelector("#monthlyReportButton"),
  submissionsButton: document.querySelector("#submissionsButton"),
  submissionsModal: document.querySelector("#submissionsModal"),
  closeSubmissions: document.querySelector("#closeSubmissions"),
  submissionNote: document.querySelector("#submissionNote"),
  submissionList: document.querySelector("#submissionList"),
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

function markDirty() {
  state.dirty = true;
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
    if (!state.dirty) state.config = payload.config;
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
    const configChanged = !state.dirty && JSON.stringify(state.config) !== JSON.stringify(payload.config);
    state.service = payload.service;
    if (!state.dirty) state.config = payload.config;
    state.authenticated = payload.authenticated;
    renderService();
    if (configChanged) {
      renderSettings();
      renderTargets();
    } else {
      updateTargetRuntime();
    }
  } catch (_error) {
    els.connectionState.classList.remove("online");
  }
}

const TARGET_STATE_META = {
  service_stopped: { label: "服务停止", tone: "muted" },
  paused: { label: "已暂停", tone: "muted" },
  scheduled: { label: "等待排班", tone: "muted" },
  manual: { label: "手动待机", tone: "muted" },
  checking: { label: "检测中", tone: "checking" },
  starting: { label: "连接中", tone: "checking" },
  connecting: { label: "连接中", tone: "checking" },
  reconnecting: { label: "重连检测", tone: "checking" },
  waiting_space: { label: "等待空间", tone: "checking" },
  rate_limited: { label: "限流等待", tone: "checking" },
  canceled: { label: "上传已停止", tone: "muted" },
  offline: { label: "未开播", tone: "offline" },
  recording: { label: "录制中", tone: "recording" },
  recording_uploading: { label: "录制中 / 上传中", tone: "uploading" },
  monitoring: { label: "仅监视", tone: "recording" },
  uploading: { label: "上传中", tone: "uploading" },
  uploaded: { label: "上传完成", tone: "success" },
  recorded: { label: "已录制", tone: "success" },
  error: { label: "异常", tone: "error" },
};

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
  renderUploadProgress(service.upload_progresses || [], service.upload_progress || {});
  els.servicePulse.classList.toggle("online", running);
  els.startButton.disabled = running;
  els.stopButton.disabled = !running;
  els.restartButton.disabled = !running;
}

function renderEncodingEstimate() {
  const quality = els.quality.value || "origin";
  const frameRate = els.frameRate.value || "source";
  const base = { origin: 8.4, "1080p": 2.59, "720p": 1.75, "480p": 0.77 }[quality] || 8.4;
  const factor = quality === "origin"
    ? frameRate === "60" ? 1.2 : frameRate === "30" ? 0.9 : 1
    : frameRate === "60" ? 1.45 : frameRate === "30" && quality === "1080p" ? 0.9 : 1;
  const estimate = quality === "origin" && frameRate === "source" ? 8.4 : base * factor;
  const transcode = quality !== "origin" || frameRate !== "source";
  els.encodingEstimate.textContent = `预计 ${estimate.toFixed(2)} GB / 小时`;
  els.encodingHint.textContent = transcode
    ? `原文件加转码文件峰值约 ${((8.4 + estimate) * 1.08).toFixed(1)} GB；空间不足会暂停下一段`
    : `原画直传，峰值约 ${(estimate * 1.1).toFixed(1)} GB，不额外生成第二份 MP4`;
}

function renderUploadProgress(progressesArg, fallback = {}) {
  const progresses = Array.isArray(progressesArg) ? progressesArg : [];
  const signature = JSON.stringify([progresses, fallback]);
  if (state.uploadSignature === signature) return;
  state.uploadSignature = signature;
  const progress = progresses[0] || fallback || {};
  const available = Boolean(progress.available);
  const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
  els.uploadPanel.classList.toggle("active", available || progresses.length > 0);
  els.uploadTitle.textContent = available ? progress.title || "正在上传" : "当前没有上传";
  els.uploadMeta.textContent = available
    ? `${progress.target || "主播"} · P${String(progress.part || 1).padStart(2, "0")} · ${progress.message || "上传中"}`
    : "等待分段完成";
  els.uploadPercent.textContent = available ? `${percent.toFixed(2)}%` : "--";
  els.uploadBar.style.width = available ? `${percent}%` : "0%";
  els.uploadBytes.textContent = available
    ? `${formatBytes(progress.uploaded_bytes)} / ${formatBytes(progress.total_bytes)}`
    : "-- / --";
  els.uploadSpeed.textContent = available && progress.speed_bytes
    ? `${(Number(progress.speed_bytes) / 1048576).toFixed(2)} MB/s`
    : "--";
  els.uploadEta.textContent = available && progress.eta_seconds != null
    ? `剩余 ${formatDuration(progress.eta_seconds)}`
    : available && progress.bvid ? `BVID ${progress.bvid}` : "--";
  const visible = progresses.filter((item) => item.available).slice(0, 8);
  els.uploadList.replaceChildren(...visible.map((item) => {
    const row = document.createElement("div");
    row.className = "upload-row";
    const info = document.createElement("div");
    const title = document.createElement("span");
    title.textContent = `${item.target || "主播"} · P${String(item.part || 1).padStart(2, "0")}`;
    const meta = document.createElement("small");
    meta.textContent = `${item.message || "上传中"} · ${formatBytes(item.uploaded_bytes)} / ${formatBytes(item.total_bytes)}${item.bvid ? ` · ${item.bvid}` : ""}`;
    info.append(title, meta);
    const itemPercent = document.createElement("strong");
    const itemPercentValue = Math.max(0, Math.min(100, Number(item.percent || 0)));
    itemPercent.textContent = `${itemPercentValue.toFixed(1)}%`;
    const actions = document.createElement("div");
    actions.className = "upload-row-actions";
    actions.append(itemPercent);
    const message = String(item.message || "");
    const uploadState = String(item.state || "");
    const completed = Boolean(item.bvid) || itemPercentValue >= 100 || message === "上传完成";
    const paused = uploadState === "paused" || message === "已暂停";
    const stopped = uploadState === "stopped" || message === "已停止";
    const failed = uploadState === "failed" || message.includes("失败");
    if (!completed) {
      if (paused || stopped || failed) {
        actions.append(uploadControlButton("rotate-cw", "重试", "retry-upload-button", () => retryUpload(item.key)));
      } else {
        actions.append(uploadControlButton("pause", "暂停", "pause-upload-button", () => pauseUpload(item.key)));
        actions.append(uploadControlButton("square", "停止", "stop-upload-button", () => stopUpload(item.key)));
      }
    }
    row.append(info, actions);
    return row;
  }));
}

function uploadControlButton(iconName, label, className, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.title = label;
  button.append(icon(iconName), document.createTextNode(label));
  button.addEventListener("click", handler);
  return button;
}

async function uploadControl(action, key, successMessage, failureMessage) {
  const match = String(key || "").match(/^(.*):(\d+)$/);
  if (!match) return;
  try {
    await api(`/api/uploads/${encodeURIComponent(match[1])}/${match[2]}/${action}`, { method: "POST" });
    toast(successMessage);
    await refreshService();
  } catch (error) {
    toast(`${failureMessage}：${error.message}`, "error");
  }
}

function pauseUpload(key) {
  return uploadControl("pause", key, "已暂停该视频上传", "暂停上传失败");
}

function retryUpload(key) {
  return uploadControl("retry", key, "已重新加入上传队列", "重试上传失败");
}

function stopUpload(key) {
  return uploadControl("stop", key, "已停止该视频上传", "停止上传失败");
}

async function clearTargetCache(name) {
  if (!window.confirm(`清除“${name}”已上传、已停止或已丢弃片段的本地缓存？不会删除正在录制或待上传的文件。`)) return;
  try {
    const result = await api(`/api/targets/${encodeURIComponent(name)}/clear-cache`, { method: "POST" });
    toast(`已释放 ${formatBytes(result.freed_bytes || 0)}`);
    await refreshService();
  } catch (error) {
    toast(`清除缓存失败：${error.message}`, "error");
  }
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
  els.cloudRcloneBin.value = state.config.cloud_rclone_bin || "rclone";
  els.lateThreshold.value = state.config.late_threshold_minutes ?? 5;
  els.reconnectGrace.value = state.config.reconnect_grace_minutes ?? 15;
  els.pollInterval.value = state.config.poll_interval_seconds ?? 30;
  els.quality.value = state.config.quality || "origin";
  els.frameRate.value = state.config.frame_rate || "source";
  renderEncodingEstimate();
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
  const runtimeByTarget = state.service?.target_statuses || {};
  const recordingTargets = new Set(
    (state.service?.sessions || [])
      .filter((session) => String(session.status || "").toUpperCase() === "RECORDING")
      .map((session) => session.target_name),
  );
  const usageByTarget = state.service?.target_usage_bytes || {};
  const uploadByTarget = new Map();
  for (const upload of state.service?.upload_progresses || []) {
    if (!upload.target || Number(upload.percent || 0) >= 100) continue;
    const current = uploadByTarget.get(upload.target);
    if (!current || Number(upload.updated_at || 0) > Number(current.updated_at || 0)) uploadByTarget.set(upload.target, upload);
  }
  for (const target of targets) {
    els.targetList.append(buildTargetRow(
      target,
      latestByTarget.get(target.name),
      runtimeByTarget[target.name],
      uploadByTarget.get(target.name),
      recordingTargets.has(target.name),
      usageByTarget[target.name] || 0,
    ));
  }
  renderIcons();
}

function updateTargetRuntime() {
  const targets = state.config?.targets || [];
  const targetById = new Map(targets.map((target) => [target.id, target]));
  const latestByTarget = new Map();
  for (const session of state.service?.sessions || []) {
    if (!latestByTarget.has(session.target_name)) latestByTarget.set(session.target_name, session);
  }
  const runtimeByTarget = state.service?.target_statuses || {};
  const recordingTargets = new Set(
    (state.service?.sessions || [])
      .filter((session) => String(session.status || "").toUpperCase() === "RECORDING")
      .map((session) => session.target_name),
  );
  const usageByTarget = state.service?.target_usage_bytes || {};
  const uploadByTarget = new Map();
  for (const upload of state.service?.upload_progresses || []) {
    if (!upload.target || Number(upload.percent || 0) >= 100) continue;
    const current = uploadByTarget.get(upload.target);
    if (!current || Number(upload.updated_at || 0) > Number(current.updated_at || 0)) uploadByTarget.set(upload.target, upload);
  }

  for (const row of els.targetList.querySelectorAll(".target-row")) {
    const target = targetById.get(row.dataset.targetId);
    if (!target) continue;
    const runtime = resolveTargetRuntime(
      target,
      latestByTarget.get(target.name),
      runtimeByTarget[target.name],
      uploadByTarget.get(target.name),
      recordingTargets.has(target.name),
    );
    const status = row.querySelector(".target-status");
    if (status) {
      status.className = `target-status ${runtime.meta.tone}`;
      status.replaceChildren(makeDot(), document.createTextNode(runtime.meta.label));
    }
    const detail = row.querySelector(".target-runtime-message");
    if (detail) {
      detail.textContent = runtime.detail;
      detail.title = runtime.detail;
    }
    const upload = row.querySelector(".target-upload-progress");
    if (upload) {
      upload.textContent = runtime.uploadDetail;
      upload.hidden = !runtime.uploadDetail;
    }
    const cloud = row.querySelector(".target-cloud-progress");
    if (cloud) {
      cloud.textContent = runtime.cloudDetail;
      cloud.hidden = !runtime.cloudDetail;
    }
    const usage = row.querySelector(".target-usage");
    if (usage) usage.textContent = `空间占用 ${formatBytes(usageByTarget[target.name] || 0)}`;
  }
  renderIcons();
}

function resolveTargetRuntime(target, latest, runtimeStatus, activeUpload, isRecordingTarget) {
  if (!target.enabled) return { meta: TARGET_STATE_META.paused, detail: "已暂停监控" };
  if (!state.service?.running) return { meta: TARGET_STATE_META.service_stopped, detail: "录制服务未运行" };

  const latestState = String(latest?.status || "").toUpperCase();
  const runtime = runtimeStatus || {};
  let stateName = String(runtime.state || "");
  let message = String(runtime.message || "");
  const isRecording = Boolean(isRecordingTarget) || stateName === "recording" || stateName === "recording_uploading" || latestState === "RECORDING";
  if (activeUpload) {
    const percent = Math.max(0, Math.min(100, Number(activeUpload.percent || 0)));
    const eta = activeUpload.eta_seconds != null ? ` · 剩余 ${formatDuration(activeUpload.eta_seconds)}` : "";
    stateName = isRecording ? "recording_uploading" : "uploading";
    message = `P${String(activeUpload.part || 1).padStart(2, "0")} · ${percent.toFixed(1)}%${eta}`;
  }
  if (!stateName) {
    if (latestState === "RECORDING") stateName = target.record_mode === "monitor" ? "monitoring" : "recording";
    else if (latestState === "UPLOADING") stateName = "uploading";
    else if (latestState === "UPLOADED") stateName = "uploaded";
    else if (latestState === "UPLOAD_FAILED" || latestState === "FAILED") stateName = "error";
    else if (latestState === "RECORDED") stateName = "recorded";
    else if (target.watch_mode === "manual") stateName = "manual";
    else if (target.watch_mode === "scheduled") stateName = "scheduled";
    else stateName = "checking";
  }

  const meta = TARGET_STATE_META[stateName] || TARGET_STATE_META.checking;
  let detail = message || `${meta.label} · 等待下一次状态更新`;
  const updatedAt = Number(runtime.updated_at || 0);
  if (updatedAt && ["recording", "recording_uploading", "monitoring"].includes(stateName)) {
    detail += ` · 已持续 ${formatDuration(Date.now() / 1000 - updatedAt)}`;
  } else if (updatedAt && stateName !== "uploading") {
    detail += ` · ${formatClock(updatedAt)}`;
  }
  const uploadDetail = activeUpload
    ? `上传进度：P${String(activeUpload.part || 1).padStart(2, "0")} · ${Math.max(0, Math.min(100, Number(activeUpload.percent || 0))).toFixed(1)}%${activeUpload.eta_seconds != null ? ` · 剩余 ${formatDuration(activeUpload.eta_seconds)}` : ""}`
    : "";
  const cloudState = String(runtime.cloud_state || latest?.cloud_status || "").toLowerCase();
  const cloudMessage = String(runtime.cloud_message || "");
  let cloudDetail = "";
  if (target.cloud_backup) {
    if (cloudMessage) cloudDetail = cloudMessage;
    else if (cloudState === "uploaded") cloudDetail = "网盘备份已完成";
    else if (cloudState === "failed") cloudDetail = "网盘备份失败，本地文件已保留";
    else if (cloudState === "pending" || cloudState === "uploading") cloudDetail = "网盘备份排队中";
    else if (Number(latest?.cloud_pending_parts || 0) > 0) cloudDetail = `网盘待备份 ${latest.cloud_pending_parts} 个分段`;
  }
  return { meta, detail, uploadDetail, cloudDetail, isRecording };
}

function formatClock(epochSeconds) {
  return new Date(Number(epochSeconds) * 1000).toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function buildTargetRow(target, latest, runtimeStatus, activeUpload, isRecordingTarget, usageBytes) {
  const row = document.createElement("article");
  row.className = "target-row";
  row.dataset.targetId = target.id;
  const header = document.createElement("div");
  header.className = "target-header";
  const identity = document.createElement("div");
  identity.className = "target-identity";
  const runtime = resolveTargetRuntime(target, latest, runtimeStatus, activeUpload, isRecordingTarget);
  const status = document.createElement("span");
  status.className = `target-status ${runtime.meta.tone}`;
  status.append(makeDot(), document.createTextNode(runtime.meta.label));
  const name = document.createElement("strong");
  name.textContent = target.name || "未命名主播";
  const url = document.createElement("small");
  url.textContent = target.url;
  const runtimeMessage = document.createElement("small");
  runtimeMessage.className = "target-runtime-message";
  runtimeMessage.textContent = runtime.detail;
  runtimeMessage.title = runtime.detail;
  const usage = document.createElement("small");
  usage.className = "target-usage";
  usage.textContent = `空间占用 ${formatBytes(usageBytes)}`;
  const uploadMessage = document.createElement("small");
  uploadMessage.className = "target-upload-progress";
  uploadMessage.textContent = runtime.uploadDetail;
  uploadMessage.hidden = !runtime.uploadDetail;
  const cloudMessage = document.createElement("small");
  cloudMessage.className = "target-cloud-progress";
  cloudMessage.textContent = runtime.cloudDetail;
  cloudMessage.hidden = !runtime.cloudDetail;
  identity.append(status, name, url, runtimeMessage, uploadMessage, cloudMessage, usage);

  const actions = document.createElement("div");
  actions.className = "target-actions";
  const enabled = checkbox(target.enabled);
  enabled.title = "启用/暂停";
  enabled.addEventListener("change", () => { target.enabled = enabled.checked; markDirty(); renderTargets(); });
  actions.append(
    enabled,
    actionButton("play-circle", "单独开始", () => manualStartTarget(target.name)),
    actionButton("pause", "单独暂停", () => pauseTarget(target)),
    actionButton("file-text", "生成报告", () => openReportDialog(target.name)),
    actionButton("bar-chart-3", "数据详情", () => openAnalytics(target.name)),
    actionButton("folder-open", "打开目录", () => openFolder("anchor", target.name)),
    actionButton("eraser", "清除缓存", () => clearTargetCache(target.name)),
    actionButton("trash-2", "删除主播", () => {
      const removedName = target.name;
      state.config.targets = state.config.targets.filter((item) => item.id !== target.id);
      renderTargets();
      saveState(`${removedName} 已删除`).then((saved) => {
        if (!saved) loadState(true);
      });
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
    ], (value) => { target.public = value === "public"; }, "public"),
    segmentedControl("监控模式", target.record_mode || "record", [
      ["record", "录制视频"], ["monitor", "仅数据"],
    ], (value) => { target.record_mode = value; }, "record_mode"),
    segmentedControl("监控方式", target.watch_mode || "all_day", [
      ["scheduled", "固定排班"], ["all_day", "全天轮询"], ["manual", "手动开启"],
    ], (value) => { target.watch_mode = value; }, "watch_mode"),
    segmentedControl("弹幕录制", target.record_danmaku ? "on" : "off", [
      ["off", "不录制"], ["on", "录制并烧录"],
    ], (value) => { target.record_danmaku = value === "on"; }, "record_danmaku"),
  );
  const collection = document.createElement("label");
  collection.className = "collection-state";
  const collectionLabel = document.createElement("span");
  collectionLabel.textContent = "合集 ID";
  const collectionInput = document.createElement("input");
  collectionInput.type = "text";
  collectionInput.value = target.collection_id || "";
  collectionInput.placeholder = "粘贴 B站合集 ID";
  collectionInput.dataset.field = "collection_id";
  collectionInput.addEventListener("input", () => { target.collection_id = collectionInput.value.trim(); });
  const collectionHint = document.createElement("small");
  collectionHint.textContent = "填写后，新稿件会直接进入该主播合集";
  collection.append(collectionLabel, collectionInput, collectionHint);
  controls.append(collection);

  const cloud = document.createElement("div");
  cloud.className = "cloud-state";
  const cloudTitle = document.createElement("span");
  cloudTitle.textContent = "网盘备份";
  const cloudToggle = segmentedControl("备份方式", target.cloud_backup ? "on" : "off", [
    ["off", "不备份"], ["on", "独立备份"],
  ], (value) => {
    target.cloud_backup = value === "on";
    if (target.cloud_backup && !target.cloud_remote) {
      target.cloud_remote = cloudProviderDefault(target.cloud_provider || "baidu");
    }
  }, "cloud_backup");
  const provider = document.createElement("select");
  provider.className = "cloud-provider";
  provider.dataset.field = "cloud_provider";
  for (const [value, label] of [["baidu", "百度网盘（OpenList）"], ["quark", "夸克网盘（OpenList）"], ["custom", "其他 rclone remote"]]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    provider.append(option);
  }
  provider.value = target.cloud_provider || "baidu";
  const remote = document.createElement("input");
  remote.type = "text";
  remote.dataset.field = "cloud_remote";
  remote.value = target.cloud_remote || "";
  remote.placeholder = "baidu:/baidu/DouyinBiliRecorder";
  provider.addEventListener("change", () => {
    const previousDefault = cloudProviderDefault(target.cloud_provider);
    target.cloud_provider = provider.value;
    if (!target.cloud_remote || target.cloud_remote === previousDefault) {
      remote.value = cloudProviderDefault(provider.value);
      target.cloud_remote = remote.value;
    }
  });
  remote.addEventListener("input", () => { target.cloud_remote = remote.value.trim(); });
  const cloudHint = document.createElement("small");
  cloudHint.textContent = "保存时会创建该主播目录；如果 remote 指向 OpenList 的 /dav 根，路径需包含挂载名，例如 quark:/quark/DouyinBiliRecorder。";
  const testButton = document.createElement("button");
  testButton.type = "button";
  testButton.className = "secondary-button compact-action";
  testButton.append(icon("cloud-upload"), document.createTextNode("测试网盘"));
  testButton.addEventListener("click", () => testCloudTarget(target));
  cloud.append(cloudTitle, cloudToggle, provider, remote, testButton, cloudHint);
  controls.append(cloud);

  const saveBar = document.createElement("div");
  saveBar.className = "target-save-bar";
  const saveTarget = document.createElement("button");
  saveTarget.type = "button";
  saveTarget.className = "save-button compact-save";
  saveTarget.append(icon("save"), document.createTextNode("保存主播设置"));
  saveTarget.addEventListener("click", () => saveState(`${target.name} 的设置已保存`));
  const modePanel = document.createElement("div");
  modePanel.className = "watch-mode-panel";
  if (target.watch_mode === "scheduled") {
    const schedule = document.createElement("details");
    schedule.className = "schedule-editor";
    const summary = document.createElement("summary");
    summary.textContent = `固定排班 · ${(target.schedule || []).length} 个时段`;
    schedule.append(summary, buildScheduleList(target));
    modePanel.append(schedule);
  } else {
    const modeHint = document.createElement("div");
    modeHint.className = "watch-mode-hint";
    modeHint.textContent = target.watch_mode === "manual"
      ? "手动开启：不会自动轮询，只有点击“手动开始”后才检查。"
      : `全天轮询：每 ${state.config?.poll_interval_seconds || 30} 秒自动检查一次。`;
    modePanel.append(modeHint);
  }
  const saveHint = document.createElement("small");
  saveHint.textContent = target.watch_mode === "scheduled"
    ? "排班、权限、合集、监控模式、弹幕和网盘设置会一起保存"
    : "监控方式、权限、合集、弹幕和网盘设置会一起保存";
  saveBar.append(saveTarget, saveHint);
  row.append(header, main, controls, modePanel, saveBar);
  row.addEventListener("input", markDirty);
  row.addEventListener("change", markDirty);
  return row;
}

async function manualStartTarget(name) {
  try {
    await api(`/api/targets/${encodeURIComponent(name)}/manual-start`, { method: "POST" });
    toast(`${name} 已单独启动`);
    await loadState(true);
    window.setTimeout(refreshLogs, 800);
  } catch (error) {
    toast(`手动开始失败：${error.message}`, "error");
  }
}

async function pauseTarget(target) {
  try {
    await api(`/api/targets/${encodeURIComponent(target.name)}/pause`, { method: "POST" });
    await loadState(true);
    toast(`${target.name} 已单独暂停`);
    window.setTimeout(refreshLogs, 800);
  } catch (error) {
    toast(`暂停失败：${error.message}`, "error");
  }
}

function cloudProviderDefault(provider) {
  if (provider === "quark") return "quark:/quark/DouyinBiliRecorder";
  if (provider === "custom") return "openlist:/DouyinBiliRecorder";
  return "baidu:/baidu/DouyinBiliRecorder";
}

async function testCloudTarget(target) {
  const remote = String(target.cloud_remote || "").trim();
  if (!remote) return toast("先填写网盘远端路径", "error");
  try {
    const result = await api("/api/cloud/test", {
      method: "POST",
      body: JSON.stringify({ remote }),
    });
    toast(result.message || "网盘远端可访问");
  } catch (error) {
    toast(`网盘测试失败：${error.message}`, "error");
  }
}

function buildScheduleList(target) {
  const wrapper = document.createElement("div");
  wrapper.className = "schedule-list";
  const precheck = document.createElement("p");
  precheck.className = "schedule-precheck";
  precheck.textContent = "固定排班会在预计开播前 10 分钟开始预检，离线探测会立即返回并继续轮询。";
  wrapper.append(precheck);
  const slots = target.schedule || (target.schedule = []);
  if (!slots.length) {
    const empty = document.createElement("p");
    empty.className = "schedule-empty";
    empty.textContent = "尚未设置固定时段。点击“添加时段”后再保存。";
    wrapper.append(empty);
  }
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
    const remove = actionButton("minus", "删除时段", () => { slots.splice(index, 1); markDirty(); renderTargets(); });
    line.append(remove);
    wrapper.append(line);
  });
  wrapper.append(actionButton("plus", "添加时段", () => {
    slots.push({ days: [1, 2, 3, 4, 5, 6, 7], start: "20:00", end: "23:00", enabled: true });
    markDirty();
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

function segmentedControl(label, value, options, onChange, field = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "compact-control";
  const title = document.createElement("span");
  title.textContent = label;
  const group = document.createElement("div");
  group.className = "segmented compact";
  if (field) group.dataset.segmentedField = field;
  for (const [key, text] of options) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.dataset.value = key;
    button.classList.toggle("active", key === value);
    button.addEventListener("click", () => {
      onChange(key);
      markDirty();
      renderTargets();
    });
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

function formatBytes(value) {
  let number = Math.max(0, Number(value) || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let index = 0;
  while (number >= 1024 && index < units.length - 1) { number /= 1024; index += 1; }
  return `${number.toFixed(index > 2 ? 2 : 1)} ${units[index]}`;
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
    state.dirty = false;
    state.config = payload.config;
    render();
    let saveMessage = message || (payload.restart_required ? "设置已保存；缓存将在下一分段或重启后生效" : "设置已保存");
    const folders = Array.isArray(payload.cloud_folders) ? payload.cloud_folders : [];
    const warnings = Array.isArray(payload.cloud_warnings) ? payload.cloud_warnings : [];
    if (folders.length) saveMessage += `；已同步 ${folders.length} 个云盘主播目录`;
    if (warnings.length) {
      saveMessage += `；云盘目录失败：${warnings.map((item) => `${item.target} ${item.message}`).join("；")}`;
      toast(saveMessage, "error");
    } else {
      toast(saveMessage);
    }
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
    for (const select of row.querySelectorAll("select[data-field]")) {
      target[select.dataset.field] = select.value;
    }
    for (const group of row.querySelectorAll("[data-segmented-field]")) {
      const active = group.querySelector("button.active");
      if (!active) continue;
      const field = group.dataset.segmentedField;
      if (field === "public") target[field] = active.dataset.value === "public";
      else if (field === "record_danmaku") target[field] = active.dataset.value === "on";
      else if (field === "cloud_backup") target[field] = active.dataset.value === "on";
      else target[field] = active.dataset.value;
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
  state.config.quality = els.quality.value || "origin";
  state.config.frame_rate = els.frameRate.value || "source";
  state.config.cloud_rclone_bin = els.cloudRcloneBin.value.trim() || "rclone";
}

async function serviceAction(action, mode = "upload") {
  try {
    state.service = await api(`/api/service/${action}?mode=${encodeURIComponent(mode)}`, { method: "POST" });
    renderService();
    closeStopDialog();
    const stopMessage = mode === "upload"
      ? "正在收尾并上传当前内容"
      : mode === "discard"
        ? "已停止全部任务，正在删除当前录像"
        : "已暂停并保留本地内容";
    toast(action === "start" ? "录制服务已启动" : action === "stop" ? stopMessage : "录制服务已重启");
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
        record_danmaku: false,
        watch_mode: "manual",
        collection_name: resolvedName,
        collection_id: "",
        cloud_backup: false,
        cloud_provider: "baidu",
        cloud_remote: "",
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

function localDateISO(value) {
  const date = new Date(value);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function previousWeekAnchor() {
  const today = new Date();
  const anchor = new Date(today);
  anchor.setDate(today.getDate() - 7);
  return localDateISO(anchor);
}

function previousMonthAnchor() {
  const today = new Date();
  return localDateISO(new Date(today.getFullYear(), today.getMonth() - 1, 1));
}

function openReportDialog(name) {
  state.reportTarget = name;
  els.reportTitle.textContent = `${name} · 生成完整周期报告`;
  els.reportNote.textContent = "本周周报可生成截至今天；上周和月报只使用已经结束的完整周期，不会自动生成。";
  els.reportPeriodNote.textContent = `上周报表锚点：${previousWeekAnchor()}；上月报表锚点：${previousMonthAnchor()}`;
  els.reportModal.hidden = false;
}

async function openSubmissions() {
  els.submissionsModal.hidden = false;
  els.submissionNote.textContent = "正在读取 B站稿件状态。";
  els.submissionList.replaceChildren();
  try {
    state.submissions = await api("/api/bilibili/submissions");
    renderSubmissions(state.submissions);
  } catch (error) {
    els.submissionNote.textContent = `稿件状态读取失败：${error.message}`;
  }
}

function renderSubmissions(payload) {
  const submissions = payload?.submissions || [];
  els.submissionNote.textContent = payload?.available
    ? (payload.message || `共 ${submissions.length} 个已投稿稿件；状态由 B站接口实时返回。`)
    : `暂不可用：${payload?.message || "未登录或网络不可用"}`;
  if (!submissions.length) {
    const empty = document.createElement("div");
    empty.className = "submission-empty";
    empty.textContent = payload?.available ? "暂无匹配到本机投稿记录的稿件。" : "登录B站后刷新。";
    els.submissionList.append(empty);
    return;
  }
  els.submissionList.replaceChildren(...submissions.map((item) => {
    const row = document.createElement("div");
    row.className = "submission-row";
    const info = document.createElement("div");
    info.className = "submission-info";
    const name = document.createElement("strong");
    name.textContent = (item.targets || []).join("、") || "未知主播";
    const title = document.createElement("small");
    title.textContent = item.session_title || item.title || item.bvid;
    info.append(name, title);
    const meta = document.createElement("div");
    meta.className = "submission-meta";
    const badge = document.createElement("span");
    badge.className = `submission-badge ${submissionStateClass(`${item.state || ""} ${item.state_desc || ""}`)}`;
    badge.textContent = item.state_desc || "状态未知";
    const bvid = document.createElement("code");
    bvid.textContent = item.bvid || "-";
    const duration = document.createElement("span");
    duration.textContent = formatDuration(item.duration_seconds || 0);
    meta.append(badge, bvid, duration);
    row.append(info, meta);
    return row;
  }));
}

function submissionStateClass(value) {
  const state = String(value || "").toLowerCase();
  if (state.includes("pubed") || state.includes("开放")) return "published";
  if (state.includes("pubing") || state.includes("审核")) return "review";
  if (state.includes("not") || state.includes("失败")) return "failed";
  return "neutral";
}

async function downloadReport(period, allowPartial = false) {
  const target = state.reportTarget || state.analyticsTarget;
  if (!target) return;
  const anchor = period === "week" && allowPartial
    ? localDateISO(new Date())
    : period === "week" ? previousWeekAnchor() : previousMonthAnchor();
  const url = `/api/targets/${encodeURIComponent(target)}/reports/${period}?anchor_date=${anchor}&allow_partial=${allowPartial}`;
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(await response.text());
    const blob = await response.blob();
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = objectUrl;
    link.download = response.headers.get("content-disposition")?.match(/filename="?([^";]+)"?/)?.[1] || `${target}-${period}.pdf`;
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(objectUrl);
    toast(period === "week" ? (allowPartial ? "本周周报已生成" : "上周周报已生成") : "上月月报已生成");
  } catch (error) {
    toast(`报告生成失败：${error.message}`, "error");
  }
}

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
els.discardButton.addEventListener("click", () => serviceAction("stop", "discard"));
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
els.pollInterval.addEventListener("input", () => { state.config.poll_interval_seconds = Math.max(5, Number(els.pollInterval.value) || 30); });
els.quality.addEventListener("change", () => { state.config.quality = els.quality.value; renderEncodingEstimate(); });
els.frameRate.addEventListener("change", () => { state.config.frame_rate = els.frameRate.value; renderEncodingEstimate(); });
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
    record_danmaku: false,
    watch_mode: "manual",
    cloud_backup: false,
    cloud_provider: "baidu",
    cloud_remote: "",
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
els.closeReport.addEventListener("click", () => { els.reportModal.hidden = true; });
els.currentWeekReportButton.addEventListener("click", () => downloadReport("week", true));
els.previousWeekReportButton.addEventListener("click", () => downloadReport("week", false));
els.monthlyReportButton.addEventListener("click", () => downloadReport("month"));
els.submissionsButton.addEventListener("click", openSubmissions);
els.closeSubmissions.addEventListener("click", () => { els.submissionsModal.hidden = true; });

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  for (const modal of [els.loginModal, els.stopModal, els.videoLibraryModal, els.analyticsModal, els.submissionsModal, els.reportModal]) modal.hidden = true;
});

window.setInterval(() => {
  if (!els.submissionsModal.hidden) openSubmissions();
}, 20000);

const globalControlRail = document.querySelector(".control-rail");
if (globalControlRail) {
  globalControlRail.addEventListener("input", markDirty);
  globalControlRail.addEventListener("change", markDirty);
  globalControlRail.addEventListener("click", (event) => {
    if (event.target.closest(".segmented button")) markDirty();
  });
}

loadState(true);
refreshLogs();
window.setInterval(refreshService, 3000);
window.setInterval(refreshLogs, 3500);
renderIcons();
