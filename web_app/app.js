const tokenInput = document.getElementById("tokenInput");
const saveTokenBtn = document.getElementById("saveTokenBtn");
const createTaskBtn = document.getElementById("createTaskBtn");
const saveConfigBtn = document.getElementById("saveConfigBtn");
const refreshBtn = document.getElementById("refreshBtn");
const taskList = document.getElementById("taskList");
const taskTableBody = document.getElementById("taskTableBody");
const taskSummaryCount = document.getElementById("taskSummaryCount");
const taskSummarySize = document.getElementById("taskSummarySize");
const selectAllTasks = document.getElementById("selectAllTasks");
const deleteSelectedTasksBtn = document.getElementById("deleteSelectedTasksBtn");
const taskPrevBtn = document.getElementById("taskPrevBtn");
const taskNextBtn = document.getElementById("taskNextBtn");
const taskPageInfo = document.getElementById("taskPageInfo");
const formMsg = document.getElementById("formMsg");
const loginMsg = document.getElementById("loginMsg");
const loginStatus = document.getElementById("loginStatus");
const logModal = document.getElementById("logModal");
const logContent = document.getElementById("logContent");
const closeLogBtn = document.getElementById("closeLogBtn");
const serverBaseHint = document.getElementById("serverBaseHint");
const mediaModal = document.getElementById("mediaModal");
const mediaContainer = document.getElementById("mediaContainer");
const mediaContent = document.getElementById("mediaContent");
const closeMediaBtn = document.getElementById("closeMediaBtn");
const mediaPrevBtn = document.getElementById("mediaPrevBtn");
const mediaNextBtn = document.getElementById("mediaNextBtn");

const channelInput = document.getElementById("channelInput");
const selectedCountText = document.getElementById("selectedCountText");
const outputDirInput = document.getElementById("outputDirInput");
const autoUploadInput = document.getElementById("autoUploadInput");
const uploadMetaInput = document.getElementById("uploadMetaInput");
const serverBaseInput = document.getElementById("serverBaseInput");
const apiIdInput = document.getElementById("apiIdInput");
const apiHashInput = document.getElementById("apiHashInput");
const sshUserInput = document.getElementById("sshUserInput");
const pemPathInput = document.getElementById("pemPathInput");
const downloadRootInput = document.getElementById("downloadRootInput");
const shortThresholdInput = document.getElementById("shortThresholdInput");
const concurrencyInput = document.getElementById("concurrencyInput");
const countryCodeInput = document.getElementById("countryCodeInput");
const phoneNumberInput = document.getElementById("phoneNumberInput");
const codeInput = document.getElementById("codeInput");
const passwordInput = document.getElementById("passwordInput");
const previewLimitInput = document.getElementById("previewLimitInput");
const sendCodeBtn = document.getElementById("sendCodeBtn");
const loginBtn = document.getElementById("loginBtn");
const previewBtn = document.getElementById("previewBtn");
const previewList = document.getElementById("previewList");
const previewPrevBtn = document.getElementById("previewPrevBtn");
const previewNextBtn = document.getElementById("previewNextBtn");
const previewPageInfo = document.getElementById("previewPageInfo");
const previewStatus = document.getElementById("previewStatus");
const selectAllBtn = document.getElementById("selectAllBtn");
const clearSelectionBtn = document.getElementById("clearSelectionBtn");
const deleteSelectedBtn = document.getElementById("deleteSelectedBtn");
const taskBadge = document.getElementById("taskBadge");

const storageKey = "tg_downloader_token";
const configKey = "tg_downloader_form";
const previewKey = "tg_downloader_preview";
const selectedKey = "tg_downloader_selected";
let previewPage = 1;
let previewHasMore = false;
let previewCursors = { 1: null };
const previewCache = {};
let galleryItems = [];
let galleryIndex = 0;
const selectedIds = new Set();
const deletedIds = new Set();
const groupActiveMap = new Map();
let previewGroupMap = {};
let loginAuthorized = false;
let tasksLoading = false;
let currentTaskId = null;
let currentTaskIds = [];
let currentTaskPageIds = [];
let taskFilePage = 1;
const taskFilePageSize = 20;
let lastTaskItems = [];
const selectedTaskIds = new Set();
let lastTasksSignature = "";

const getToken = () => tokenInput.value.trim();
const getBaseUrl = () =>
  (serverBaseInput.value.trim() || window.location.origin).replace(/\/+$/, "");

const updateServerBaseHint = () => {
  if (serverBaseHint) {
    serverBaseHint.textContent = getBaseUrl();
  }
};

const authHeaders = () => {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
};

const setMessage = (msg, isError = false) => {
  formMsg.textContent = msg;
  formMsg.style.color = isError ? "#c0392b" : "#888";
};

const setLoginMessage = (msg, isError = false) => {
  loginMsg.textContent = msg;
  loginMsg.style.color = isError ? "#c0392b" : "#888";
};

const parseMessageIds = (text) =>
  text
    .split(",")
    .map((id) => id.trim())
    .filter(Boolean)
    .map((id) => Number(id))
    .filter((id) => Number.isFinite(id));

const fetchJSON = async (url, options = {}) => {
  const baseUrl = getBaseUrl();
  const fullUrl = baseUrl ? `${baseUrl}${url}` : url;
  const { timeoutMs = 20000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  let resp;
  try {
    resp = await fetch(fullUrl, {
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(fetchOptions.headers || {}),
      },
      ...fetchOptions,
      signal: controller.signal,
    });
  } catch (err) {
    if (err && err.name === "AbortError") {
      throw new Error("请求超时");
    }
    throw err;
  } finally {
    clearTimeout(timeoutId);
  }
  if (!resp) {
    throw new Error("请求超时或网络错误");
  }
  if (!resp.ok) {
    const timeoutMessage =
      "\u9884\u89c8\u8bf7\u6c42\u8d85\u65f6\uff0c\u8bf7\u964d\u4f4e\u68c0\u6d4b\u6570\u91cf\u540e\u91cd\u8bd5";
    if (resp.status === 524) {
      throw new Error(timeoutMessage);
    }
    if (resp.status === 504) {
      try {
        const data = await resp.json();
        throw new Error(data.detail || timeoutMessage);
      } catch (err) {
        if (err instanceof Error && err.message) {
          throw err;
        }
        throw new Error(timeoutMessage);
      }
    }
    const contentType = resp.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      const data = await resp.json();
      throw new Error(data.detail || data.message || resp.statusText);
    }
    const text = await resp.text();
    throw new Error(text || resp.statusText);
  }
  return resp.json();
};

const buildPreviewUrl = (relPath) =>
  `${getBaseUrl()}/preview/image?output_dir=${encodeURIComponent(
    outputDirInput.value.trim()
  )}&path=${encodeURIComponent(relPath)}`;

const buildVideoUrl = (relPath) =>
  `${getBaseUrl()}/preview/video?output_dir=${encodeURIComponent(
    outputDirInput.value.trim()
  )}&path=${encodeURIComponent(relPath)}`;

const buildStreamUrl = (channel, messageId) => {
  const token = getToken();
  const tokenParam = token ? `&token=${encodeURIComponent(token)}` : "";
  return `${getBaseUrl()}/preview/stream?api_id=${encodeURIComponent(
    apiIdInput.value.trim()
  )}&api_hash=${encodeURIComponent(
    apiHashInput.value.trim()
  )}&output_dir=${encodeURIComponent(
    outputDirInput.value.trim()
  )}&channel=${encodeURIComponent(channel)}&message_id=${encodeURIComponent(
    messageId
  )}${tokenParam}`;
};

const formatSpeed = (bps) => {
  const value = Number(bps);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const kb = value / 1024;
  if (kb < 1024) return `${kb.toFixed(1)}KB/s`;
  const mb = kb / 1024;
  return `${mb.toFixed(1)}MB/s`;
};

const formatBytesAuto = (bytes) => {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value < 0) return "--";
  if (value < 1024) return `${value.toFixed(0)}B`;
  const kb = value / 1024;
  if (kb < 1024) return `${kb.toFixed(1)}KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb.toFixed(2)}MB`;
  const gb = mb / 1024;
  if (gb < 1024) return `${gb.toFixed(2)}GB`;
  const tb = gb / 1024;
  return `${tb.toFixed(2)}TB`;
};

const getTaskSpeed = (task) => {
  if (!task.progress_json) return "--";
  let data = task.progress_json;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return "--";
    }
  }
  const stage = data.stage || "download";
  if (stage === "upload") {
    const uploadVideo = data.upload_video || {};
    const upload = Object.keys(uploadVideo).length ? uploadVideo : data.upload || {};
    return formatSpeed(upload.speed_bps);
  }
  const download = data.download || {};
  return formatSpeed(download.speed_bps);
};

const getTaskBytes = (task) => {
  if (!task.progress_json) return "--";
  let data = task.progress_json;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return "--";
    }
  }
  const stage = data.stage || "download";
  if (stage === "upload") {
    const uploadVideo = data.upload_video || {};
    const upload = Object.keys(uploadVideo).length ? uploadVideo : data.upload || {};
    const fileName = String(upload.file_name || "");
    const isVideo = upload.is_video === true || /\.(mp4|mov|mkv|avi|webm)$/i.test(fileName);
    if (!isVideo) return "--";
    const sent = upload.sent;
    const total = upload.total;
    if (!Number.isFinite(sent) && !Number.isFinite(total)) return "--";
    return `${formatBytesAuto(sent)}/${formatBytesAuto(total)}`;
  }
  const download = data.download || {};
  const downloaded = download.task_bytes_downloaded;
  const total = download.task_bytes_total;
  if (!Number.isFinite(downloaded) && !Number.isFinite(total)) return "--";
  return `${formatBytesAuto(downloaded)}/${formatBytesAuto(total)}`;
};

const formatProgress = (task, options = {}) => {
  const { full = false } = options;
  if (!task.progress_json) return "--";
  let data = task.progress_json;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return "--";
    }
  }
  const rawStatus = data.status || "";
  const status = translateStatus(rawStatus, !full);
  const stage = data.stage || "download";
  const count = stage === "upload" ? data.upload_count : data.download_count;
  const downloadBytes = data.download || {};
  let suffix = "";
  if (
    Number.isFinite(downloadBytes.bytes_downloaded) &&
    Number.isFinite(downloadBytes.bytes_total) &&
    downloadBytes.bytes_total > 0
  ) {
    const percent = Math.floor(
      (downloadBytes.bytes_downloaded / downloadBytes.bytes_total) * 100
    );
    suffix = ` ${percent}%`;
  }
  if (count && Number.isFinite(count.done) && Number.isFinite(count.total)) {
    suffix = ` (${count.done}/${count.total})`;
  } else if (task.status === "done") {
    let total = 1;
    try {
      const ids = JSON.parse(task.message_ids || "[]");
      if (Array.isArray(ids) && ids.length) total = ids.length;
    } catch {
      total = 1;
    }
    suffix = ` (${total}/${total})`;
  }
  return `${status}${suffix}`;
};

const truncateText = (text, maxLen = 20) => {
  if (typeof text !== "string") return "";
  if (text.length <= maxLen) return text;
  return `${text.slice(0, maxLen)}...`;
};

const translateStatus = (text, truncate = true) => {
  if (!text) return "";
  const cut = (value) => (truncate ? truncateText(value) : value);
  if (text.startsWith("下载失败：")) {
    return `失败：${cut(text.slice("下载失败：".length))}`;
  }
  if (text.startsWith("上传失败：")) {
    return `失败：${cut(text.slice("上传失败：".length))}`;
  }
  if (text.startsWith("下载中：")) {
    return `进行中：${cut(text.slice("下载中：".length))}`;
  }
  if (text.startsWith("分片下载中：")) {
    return `进行中：${cut(text.slice("分片下载中：".length))}`;
  }
  if (text.startsWith("上传中：")) {
    return `进行中：${cut(text.slice("上传中：".length))}`;
  }
  if (text === "下载完成") return "完成";
  if (text === "上传完成") return "完成";
  if (text === "下载中") return "进行中";
  if (text === "上传中") return "进行中";
  if (text.startsWith("Skipped (already in manifest)")) {
    return text.replace("Skipped (already in manifest)", "已存在，跳过");
  }
  if (text.startsWith("Done:")) {
    return text.replace("Done:", "完成:");
  }
  if (text.startsWith("Downloading")) {
    return text.replace("Downloading", "下载中");
  }
  if (text.startsWith("Uploading")) {
    return text.replace("Uploading", "上传中");
  }
  if (text.startsWith("Paused")) {
    return text.replace("Paused", "已暂停");
  }
  if (text.startsWith("Failed")) {
    return text.replace("Failed", "失败");
  }
  return text;
};

const formatStatus = (status) => {
  const mapping = {
    done: "已完成",
    failed: "失败",
    running: "下载中",
    pending: "等待中",
    cancelled: "已取消",
    cancel_requested: "已取消",
  };
  return mapping[status] || status || "--";
};

const formatDateTime = (value) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
};

const formatLogLine = (line) => {
  if (typeof line !== "string") return line;
  const match = line.match(/^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*(.*)$/);
  if (!match) return line;
  const utc = new Date(`${match[1].replace(" ", "T")}Z`);
  if (Number.isNaN(utc.getTime())) return line;
  return `[${utc.toLocaleString()}] ${match[2]}`;
};

const formatElapsed = (start, end) => {
  if (!start) return "--";
  const startDate = new Date(start);
  const endDate = end ? new Date(end) : new Date();
  if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) {
    return "--";
  }
  const diffMs = Math.max(0, endDate - startDate);
  const totalSeconds = Math.floor(diffMs / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}小时${minutes}分${seconds}秒`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
};

const buildPreviewMap = () => {
  const map = new Map();
  Object.values(previewCache).forEach((page) => {
    (page?.items || []).forEach((item) => {
      if (item && Number.isFinite(item.message_id)) {
        map.set(Number(item.message_id), item);
      }
    });
  });
  return map;
};

const formatBytesPair = (done, total) => {
  if (!Number.isFinite(done) && !Number.isFinite(total)) return "--";
  const left = Number.isFinite(done) ? formatBytesAuto(done) : "--";
  const right = Number.isFinite(total) ? formatBytesAuto(total) : "--";
  return `${left}/${right}`;
};

const UI_VERSION = "20260223";

const renderTasks = (items) => {
  if (!taskTableBody) return;
  const signature = JSON.stringify({
    v: UI_VERSION,
    page: taskFilePage,
    pageSize: taskFilePageSize,
    items: (items || []).map((t) => {
      let data = t.progress_json || {};
      if (typeof data === "string") {
        try {
          data = JSON.parse(data);
        } catch {
          data = {};
        }
      }
      const download = (data && data.download) || {};
      const bytes = download.task_bytes_downloaded;
      const speed = download.speed_bps;
      return [t.id, t.updated_at, t.status, bytes, speed];
    }),
  });
  if (signature === lastTasksSignature) {
    return;
  }
  lastTasksSignature = signature;
  lastTaskItems = items;
  taskTableBody.innerHTML = "";
  if (!items.length) {
    taskTableBody.innerHTML =
      "<tr><td colspan='9' class='hint'>暂无任务</td></tr>";
    if (taskBadge) taskBadge.classList.add("hidden");
    if (taskSummaryCount) taskSummaryCount.textContent = "下载数: --";
    if (taskSummarySize) taskSummarySize.textContent = "大小: --";
    currentTaskId = null;
    currentTaskIds = [];
    currentTaskPageIds = [];
    selectedTaskIds.clear();
    if (selectAllTasks) selectAllTasks.checked = false;
    if (taskPrevBtn) taskPrevBtn.disabled = true;
    if (taskNextBtn) taskNextBtn.disabled = true;
    if (taskPageInfo) taskPageInfo.textContent = "\u7b2c 1/1 \u9875";
    return;
  }
  const activeTasks = items.filter((task) =>
    ["pending", "running", "cancel_requested"].includes(task.status)
  );
  if (taskBadge) {
    let remainingTotal = 0;
    activeTasks.forEach((task) => {
      let data = task.progress_json || {};
      if (typeof data === "string") {
        try {
          data = JSON.parse(data);
        } catch {
          data = {};
        }
      }
      const files = (data && data.files) || {};
      let ids = [];
      try {
        const raw = JSON.parse(task.message_ids || "[]");
        if (Array.isArray(raw) && raw.length) ids = raw.map(Number);
      } catch {}
      if (!ids.length) {
        ids = Object.keys(files).map((id) => Number(id));
      }
      const total = ids.length;
      let done = 0;
      if (data && data.download_count && Number.isFinite(data.download_count.done)) {
        done = Number(data.download_count.done);
      } else {
        ids.forEach((id) => {
          if (files[String(id)]?.status === "done") done += 1;
        });
      }
      const remaining = Math.max(0, total - done);
      remainingTotal += remaining;
    });
    if (remainingTotal > 0) {
      taskBadge.textContent = String(remainingTotal);
      taskBadge.classList.remove("hidden");
    } else {
      taskBadge.classList.add("hidden");
    }
  }

  const pickLatest = (list) =>
    list.reduce((latest, current) => {
      if (!latest) return current;
      const latestTime = Date.parse(latest.updated_at || "");
      const currentTime = Date.parse(current.updated_at || "");
      if (Number.isFinite(currentTime) && Number.isFinite(latestTime)) {
        return currentTime > latestTime ? current : latest;
      }
      const latestId = Number(latest.id);
      const currentId = Number(current.id);
      if (Number.isFinite(currentId) && Number.isFinite(latestId)) {
        return currentId > latestId ? current : latest;
      }
      return currentId ? current : latest;
    }, null);

  const task = activeTasks.length ? pickLatest(activeTasks) : pickLatest(items);
  if (!task) {
    taskTableBody.innerHTML =
      "<tr><td colspan='9' class='hint'>暂无任务</td></tr>";
    return;
  }
  if (currentTaskId !== task.id) {
    selectedTaskIds.clear();
    taskFilePage = 1;
  }
  currentTaskId = task.id;
  let data = task.progress_json || {};
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      data = {};
    }
  }
  const files = (data && data.files) || {};
  const ids = (() => {
    try {
      const raw = JSON.parse(task.message_ids || "[]");
      if (Array.isArray(raw) && raw.length) return raw.map(Number);
    } catch {}
    return Object.keys(files).map((id) => Number(id));
  })();
  currentTaskIds = ids;
  const totalPages = Math.max(1, Math.ceil(ids.length / taskFilePageSize));
  if (taskFilePage > totalPages) {
    taskFilePage = totalPages;
    lastTasksSignature = "";
    renderTasks(items);
    return;
  }
  const pageStart = (taskFilePage - 1) * taskFilePageSize;
  const pageIds = ids.slice(pageStart, pageStart + taskFilePageSize);
  currentTaskPageIds = pageIds;
  const previewMap = buildPreviewMap();

  let totalBytes = 0;
  let downloadedBytes = 0;
  let doneCount = 0;
  ids.forEach((id) => {
    const state = files[String(id)] || {};
    const preview = previewMap.get(id);
    const bytesTotal =
      state.bytes_total ?? (preview ? Number(preview.file_size) : undefined);
    const bytesDownloaded = Number(state.bytes_downloaded);
    if (Number.isFinite(bytesTotal)) totalBytes += bytesTotal;
    if (Number.isFinite(bytesDownloaded)) downloadedBytes += bytesDownloaded;
    if (
      state.status === "done" ||
      (Number.isFinite(bytesTotal) &&
        Number.isFinite(bytesDownloaded) &&
        bytesDownloaded >= bytesTotal * 0.98)
    ) {
      doneCount += 1;
    }
  });
  const count = data.download_count || {};
  const totalCount = ids.length || count.total || "--";
  const doneDisplay = Number.isFinite(count.done)
    ? Math.max(count.done, doneCount)
    : doneCount;
  if (taskSummaryCount) {
    taskSummaryCount.textContent = `下载数: ${doneDisplay}/${totalCount}`;
  }
  if (taskSummarySize) {
    taskSummarySize.textContent = `大小: ${formatBytesPair(
      downloadedBytes,
      totalBytes
    )}`;
  }

  if (!ids.length) {
    currentTaskPageIds = [];
    if (taskPrevBtn) taskPrevBtn.disabled = true;
    if (taskNextBtn) taskNextBtn.disabled = true;
    if (taskPageInfo) taskPageInfo.textContent = "\u7b2c 1/1 \u9875";
    taskTableBody.innerHTML =
      "<tr><td colspan='9' class='hint'>暂无任务</td></tr>";
    return;
  }

  pageIds.forEach((id) => {
    const state = files[String(id)] || {};
    const preview = previewMap.get(id);
    const name = preview?.file_name || state.file_name || `消息 ${id}`;
    const duration = preview?.duration;
    const type = getVideoType(duration);
    const bytesTotal =
      state.bytes_total ?? (preview ? Number(preview.file_size) : undefined);
    const bytesDownloaded = Number(state.bytes_downloaded);
    const speed = Number(state.speed_bps);
    const isPaused = state.status === "paused";
    const isDownloading =
      state.status === "downloading" ||
      (Number.isFinite(bytesDownloaded) &&
        bytesDownloaded > 0 &&
        state.status !== "done" &&
        !isPaused);
    const status = isPaused
      ? "已暂停"
      : state.status === "done"
      ? "完成"
      : isDownloading
      ? "下载中"
      : "准备下载";
    const statusClass =
      status === "完成"
        ? "success"
        : status === "失败"
        ? "danger"
        : status === "已暂停"
        ? "paused"
        : "";
    const actionBtn = isPaused
      ? `<button class="btn ghost btn-mini task-pause-btn" data-action="resume" data-id="${id}">开始</button>`
      : isDownloading
      ? `<button class="btn ghost btn-mini task-pause-btn" data-action="pause" data-id="${id}">暂停</button>`
      : "";
    const timeText =
      state.finished_at || state.started_at || task.updated_at || "--";
    const row = document.createElement("tr");
    row.className = "task-row";
    row.innerHTML = `
      <td class="col-check">
        <input class="task-select" type="checkbox" data-id="${id}" ${
          selectedTaskIds.has(id) ? "checked" : ""
        } />
      </td>
      <td class="col-id">${id}</td>
      <td class="col-name task-name" title="${name}">${name}</td>
      <td class="col-type">${type}</td>
      <td class="col-speed">${Number.isFinite(speed) ? formatSpeed(speed) : "--"}</td>
      <td class="col-size">${formatBytesPair(bytesDownloaded, bytesTotal)}</td>
      <td class="col-status">
        <span class="task-status ${statusClass}">${status}</span>
      </td>
      <td class="col-action">
        ${actionBtn || "--"}
      </td>
      <td class="col-time">${formatDateTime(timeText)}</td>
    `;
    taskTableBody.appendChild(row);
  });

  if (selectAllTasks) {
    const selectedCount = pageIds.filter((id) => selectedTaskIds.has(id)).length;
    selectAllTasks.indeterminate =
      selectedCount > 0 && selectedCount < pageIds.length;
    selectAllTasks.checked = pageIds.length > 0 && selectedCount === pageIds.length;
  }
  if (taskPrevBtn) taskPrevBtn.disabled = taskFilePage <= 1;
  if (taskNextBtn) taskNextBtn.disabled = taskFilePage >= totalPages;
  if (taskPageInfo) {
    const from = pageStart + 1;
    const to = Math.min(pageStart + pageIds.length, ids.length);
    taskPageInfo.textContent = `\u7b2c ${taskFilePage}/${totalPages} \u9875 · ${from}-${to}/${ids.length}`;
  }
};

const loadTasks = async () => {
  if (tasksLoading) return;
  tasksLoading = true;
  try {
    const data = await fetchJSON(
      "/tasks?limit=50&sort_by=updated_at&sort_order=desc&cache=1"
    );
    renderTasks(data.items || []);
  } catch (err) {
    setMessage(`加载任务失败: ${err.message}`, true);
  } finally {
    tasksLoading = false;
  }
};

const refreshLoginStatus = async () => {
  try {
    const data = await fetchJSON(
      `/auth/status?api_id=${encodeURIComponent(apiIdInput.value.trim())}&api_hash=${encodeURIComponent(apiHashInput.value.trim())}&output_dir=${encodeURIComponent(outputDirInput.value.trim())}`
    );
    const authorized = Boolean(data.authorized);
    loginAuthorized = authorized;
    loginStatus.textContent = authorized ? "已登录" : "未登录";
    loginStatus.classList.toggle("success", authorized);
    loginStatus.classList.toggle("danger", !authorized);
    [
      countryCodeInput,
      phoneNumberInput,
      codeInput,
      passwordInput,
      sendCodeBtn,
    ].forEach((el) => {
      if (el) el.disabled = authorized;
    });
    if (loginBtn) {
      loginBtn.textContent = authorized ? "退出" : "登录";
      loginBtn.disabled = false;
    }
  } catch (err) {
    loginStatus.textContent = "未知";
    loginStatus.classList.remove("success", "danger");
  }
};

const sendCode = async () => {
  const phone = `${countryCodeInput.value.trim()}${phoneNumberInput.value.trim()}`;
  if (!countryCodeInput.value.trim() || !phoneNumberInput.value.trim()) {
    setLoginMessage("请填写区号和手机号", true);
    return;
  }
  try {
    setLoginMessage("验证码发送中...");
    const data = await fetchJSON("/auth/send_code", {
      method: "POST",
      body: JSON.stringify({
        api_id: apiIdInput.value.trim(),
        api_hash: apiHashInput.value.trim(),
        output_dir: outputDirInput.value.trim(),
        phone,
      }),
    });
    setLoginMessage(`验证码已发送 (${data.status})`);
    await refreshLoginStatus();
  } catch (err) {
    setLoginMessage(`发送失败: ${err.message}`, true);
  }
};

const login = async () => {
  const phone = `${countryCodeInput.value.trim()}${phoneNumberInput.value.trim()}`;
  const code = codeInput.value.trim();
  if (!phone || !code) {
    setLoginMessage("请填写手机号和验证码", true);
    return;
  }
  try {
    await fetchJSON("/auth/verify_code", {
      method: "POST",
      body: JSON.stringify({
        api_id: apiIdInput.value.trim(),
        api_hash: apiHashInput.value.trim(),
        output_dir: outputDirInput.value.trim(),
        phone,
        code,
        password: passwordInput.value.trim() || undefined,
      }),
    });
    setLoginMessage("登录成功");
    await refreshLoginStatus();
  } catch (err) {
    setLoginMessage(`登录失败: ${err.message}`, true);
  }
};

const logout = async () => {
  const confirmed = window.confirm("确定要退出登录吗？");
  if (!confirmed) return;
  try {
    await fetchJSON(
      `/auth/logout?api_id=${encodeURIComponent(apiIdInput.value.trim())}&api_hash=${encodeURIComponent(apiHashInput.value.trim())}&output_dir=${encodeURIComponent(outputDirInput.value.trim())}`,
      { method: "POST" }
    );
    window.location.reload();
  } catch (err) {
    setLoginMessage(`退出失败: ${err.message}`, true);
  }
};

const formatFileSize = (bytes) => {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const mb = value / (1024 * 1024);
  return `${mb.toFixed(2)} MB`;
};

const formatDuration = (seconds) => {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const mins = Math.floor(value / 60);
  const secs = Math.floor(value % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
};

const getVideoType = (durationSeconds) => {
  const value = Number(durationSeconds);
  if (!Number.isFinite(value) || value <= 0) return "--";
  const thresholdMin = Number(shortThresholdInput.value);
  const thresholdSec = Number.isFinite(thresholdMin) ? thresholdMin * 60 : 0;
  if (thresholdSec <= 0) return "--";
  return value > thresholdSec ? "长视频" : "短视频";
};

const buildPreviewRow = (item) => {
  const previewImg = item.preview_image
    ? `<div class="preview-image-wrap">
        <img class="preview-image" data-media="video" src="${buildPreviewUrl(
          item.preview_image
        )}" alt="preview" data-src="${item.preview_image}" />
        <span class="play-badge">▶</span>
      </div>`
    : `<div class="preview-image placeholder">无预览</div>`;
  const extraImages = Array.isArray(item.extra_images)
    ? item.extra_images
        .map(
          (img) =>
            `<img class="preview-thumb extra-thumb" src="${buildPreviewUrl(
              img
            )}" alt="extra" data-media="image" data-src="${img}" />`
        )
        .join("")
    : "";
  const extraImagesMedia = extraImages
    ? `<div class="extra-images">${extraImages}</div>`
    : "";
  const videoAttr = item.video_path ? `data-video="${item.video_path}"` : "";
  const streamAttr =
    item.channel && item.message_id
      ? `data-channel="${item.channel}" data-message-id="${item.message_id}"`
      : "";
  const galleryAttr = extraImages
    ? `data-gallery='${JSON.stringify(item.extra_images || [])}'`
    : `data-gallery='[]'`;
  return `
    <div class="preview-row" ${videoAttr} ${streamAttr} ${galleryAttr}>
      <div class="preview-media">
        ${previewImg}
        ${extraImagesMedia}
      </div>
      <div class="preview-content">
        <label class="preview-select">
          <input type="checkbox" data-select-id="${item.message_id}" ${
            selectedIds.has(item.message_id) ? "checked" : ""
          } />
          选择该视频
        </label>
        <div class="preview-type-badge ${getVideoType(item.duration) === "长视频" ? "long" : "short"}">
          ${getVideoType(item.duration)}
        </div>
        <div class="preview-title">${item.file_name || item.title || "--"}</div>
        <div class="preview-meta">
          <span>消息ID: ${item.message_id}</span>
          <span>大小: ${formatFileSize(item.file_size)}</span>
          <span>时长: ${formatDuration(item.duration)}</span>
          <span>标签: ${(item.tags || []).join(", ")}</span>
        </div>
        <div class="preview-caption" title="${(item.caption || "").replace(
          /"/g,
          "&quot;"
        )}">
          ${item.caption || ""}
        </div>
      </div>
    </div>
  `;
};

const renderPreview = (items) => {
  previewList.innerHTML = "";
  previewGroupMap = {};
  const visibleItems = (items || []).filter(
    (item) => !deletedIds.has(item.message_id)
  );
  if (!visibleItems.length) {
    previewList.innerHTML = items.length
      ? "<div class='hint'>本页暂无可显示内容</div>"
      : "<div class='hint'>暂无视频</div>";
    return;
  }
  const groups = new Map();
  visibleItems.forEach((item) => {
    const key = item.grouped_id ? `g-${item.grouped_id}` : `m-${item.message_id}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  groups.forEach((groupItems, key) => {
    if (groupItems.length <= 1) {
      const item = groupItems[0];
      const node = document.createElement("div");
      node.className = "preview-item";
      if (selectedIds.has(item.message_id)) {
        node.classList.add("selected");
      }
      node.innerHTML = buildPreviewRow(item);
      previewList.appendChild(node);
      return;
    }
    previewGroupMap[key] = groupItems;
    const activeId = groupActiveMap.get(key);
    const activeItem =
      groupItems.find((item) => item.message_id === activeId) || groupItems[0];
    groupActiveMap.set(key, activeItem.message_id);
    const groupNode = document.createElement("div");
    groupNode.className = "preview-group";
    groupNode.dataset.groupKey = key;
    const mainNode = document.createElement("div");
    mainNode.className = "preview-item preview-group-main";
    if (selectedIds.has(activeItem.message_id)) {
      mainNode.classList.add("selected");
    }
    mainNode.innerHTML = buildPreviewRow(activeItem);
    const thumbs = document.createElement("div");
    thumbs.className = "preview-group-thumbs";
    thumbs.innerHTML = groupItems
      .map((item) => {
        const activeClass = item.message_id === activeItem.message_id ? " active" : "";
        const title = item.file_name || item.title || "";
        const thumbImg = item.preview_image
          ? `<img class="group-thumb-img" src="${buildPreviewUrl(
              item.preview_image
            )}" alt="thumb" />`
          : `<div class="group-thumb-placeholder">无预览</div>`;
        return `<button type="button" class="group-thumb${activeClass}" data-group-key="${key}" data-message-id="${item.message_id}" title="${title}">
          ${thumbImg}
          <span class="play-badge small">▶</span>
        </button>`;
      })
      .join("");
    groupNode.appendChild(mainNode);
    groupNode.appendChild(thumbs);
    previewList.appendChild(groupNode);
  });
};

const openMediaModal = (type, src, fallback) => {
  stopMediaPlayback();
  mediaContent.innerHTML = "";
  galleryItems = [];
  mediaPrevBtn.disabled = true;
  mediaNextBtn.disabled = true;
  if (type === "video") {
    const video = document.createElement("video");
    video.src = buildVideoUrl(src);
    video.controls = true;
    video.autoplay = true;
    video.onerror = () => {
      if (fallback) {
        openMediaModal("stream", fallback);
      }
    };
    mediaContent.appendChild(video);
  } else if (type === "stream") {
    const video = document.createElement("video");
    video.src = src;
    video.controls = true;
    video.autoplay = true;
    mediaContent.appendChild(video);
  } else {
    const img = document.createElement("img");
    img.src = buildPreviewUrl(src);
    img.alt = "preview";
    mediaContent.appendChild(img);
  }
  mediaModal.classList.remove("hidden");
};

const openImageGallery = (items, startIndex) => {
  galleryItems = items || [];
  galleryIndex = Math.min(
    Math.max(startIndex || 0, 0),
    Math.max(galleryItems.length - 1, 0)
  );
  if (!galleryItems.length) return;
  const img = galleryItems[galleryIndex];
  mediaContent.innerHTML = "";
  const image = document.createElement("img");
  image.src = buildPreviewUrl(img);
  image.alt = "preview";
  mediaContent.appendChild(image);
  mediaModal.classList.remove("hidden");
  mediaPrevBtn.disabled = galleryIndex <= 0;
  mediaNextBtn.disabled = galleryIndex >= galleryItems.length - 1;
};

const moveGallery = (step) => {
  if (!galleryItems.length) return;
  galleryIndex = Math.min(
    Math.max(galleryIndex + step, 0),
    galleryItems.length - 1
  );
  const img = galleryItems[galleryIndex];
  mediaContent.innerHTML = "";
  const image = document.createElement("img");
  image.src = buildPreviewUrl(img);
  image.alt = "preview";
  mediaContent.appendChild(image);
  mediaPrevBtn.disabled = galleryIndex <= 0;
  mediaNextBtn.disabled = galleryIndex >= galleryItems.length - 1;
};

const stopMediaPlayback = () => {
  const video = mediaContent.querySelector("video");
  if (video) {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  mediaContent.innerHTML = "";
};

const savePreviewState = (items) => {
  localStorage.setItem(
    previewKey,
    JSON.stringify({
      items,
      page: previewPage,
      hasMore: previewHasMore,
      cursors: previewCursors,
      cache: previewCache,
    })
  );
};

const saveSelectedState = () => {
  localStorage.setItem(selectedKey, JSON.stringify(Array.from(selectedIds)));
};

const loadSelectedState = () => {
  const raw = localStorage.getItem(selectedKey);
  if (!raw) return;
  try {
    const ids = JSON.parse(raw);
    if (Array.isArray(ids)) {
      ids.forEach((id) => {
        const value = Number(id);
        if (Number.isFinite(value)) selectedIds.add(value);
      });
    }
  } catch {
    localStorage.removeItem(selectedKey);
  }
};

const loadPreviewState = () => {
  const raw = localStorage.getItem(previewKey);
  if (!raw) return;
  try {
    const data = JSON.parse(raw);
    previewPage = data.page || 1;
    previewHasMore = Boolean(data.hasMore);
    previewCursors = data.cursors || { 1: null };
    if (data.cache && typeof data.cache === "object") {
      Object.keys(previewCache).forEach((key) => delete previewCache[key]);
      Object.entries(data.cache).forEach(([key, value]) => {
        previewCache[key] = value;
      });
    }
    renderPreview(data.items || []);
    updatePreviewPagination();
    if (previewStatus) {
      previewStatus.textContent = data.items?.length
        ? `已保留上次检测结果（第 ${previewPage} 页）`
        : "暂无检测结果";
    }
  } catch {
    localStorage.removeItem(previewKey);
  }
};

const updatePreviewPagination = () => {
  previewPrevBtn.disabled = previewPage <= 1;
  previewNextBtn.disabled = !previewHasMore;
  previewPageInfo.textContent = `第 ${previewPage} 页`;
};

const loadPreviewPage = async (page) => {
  try {
    if (previewStatus) previewStatus.textContent = "检测中...";
    const limit = Number(previewLimitInput.value) || 50;
    const targetPage = Math.max(1, page || 1);
    if (previewCache[targetPage]) {
      previewPage = targetPage;
      previewHasMore = previewCache[targetPage].hasMore;
      renderPreview(previewCache[targetPage].items || []);
      updatePreviewPagination();
      if (previewStatus) {
        previewStatus.textContent = `已缓存第 ${targetPage} 页`;
      }
      return;
    }
    const offsetId = previewCursors[targetPage] ?? null;
    const data = await fetchJSON("/preview", {
      method: "POST",
      body: JSON.stringify({
        api_id: apiIdInput.value.trim(),
        api_hash: apiHashInput.value.trim(),
        output_dir: outputDirInput.value.trim(),
        channel: channelInput.value.trim(),
        limit,
        offset_id: offsetId,
      }),
      timeoutMs: 60000,
    });
    previewPage = targetPage;
    previewHasMore = Boolean(data.has_more);
    if (data.next_offset_id) {
      previewCursors[targetPage + 1] = data.next_offset_id;
    } else if (!previewHasMore) {
      previewCursors[targetPage + 1] = null;
    }
    previewCache[targetPage] = {
      items: data.items || [],
      hasMore: previewHasMore,
    };
    renderPreview(data.items || []);
    updatePreviewPagination();
    savePreviewState(data.items || []);
    if (previewStatus) {
      previewStatus.textContent = data.items?.length
        ? `检测完成，当前页 ${data.items.length} 条`
        : "检测完成，暂无视频";
    }
  if (previewHasMore && previewCursors[targetPage + 1]) {
    prefetchPreviewPage(targetPage + 1);
  }
  } catch (err) {
    setLoginMessage(`检测失败: ${err.message}`, true);
    if (previewStatus) previewStatus.textContent = `检测失败: ${err.message}`;
  }
};

const previewVideos = async () => {
  Object.keys(previewCache).forEach((key) => delete previewCache[key]);
  previewCursors = { 1: null };
  selectedIds.clear();
  deletedIds.clear();
  updateSelectedCount();
  localStorage.removeItem(previewKey);
  localStorage.removeItem(selectedKey);
  if (previewStatus) previewStatus.textContent = "检测中...";
  previewList.innerHTML = "";
  await loadPreviewPage(1);
};

const prefetchPreviewPage = async (page) => {
  const limit = Number(previewLimitInput.value) || 50;
  const offsetId = previewCursors[page] ?? null;
  if (!offsetId || previewCache[page]) return;
  try {
    const data = await fetchJSON("/preview", {
      method: "POST",
      body: JSON.stringify({
        api_id: apiIdInput.value.trim(),
        api_hash: apiHashInput.value.trim(),
        output_dir: outputDirInput.value.trim(),
        channel: channelInput.value.trim(),
        limit,
        offset_id: offsetId,
      }),
      timeoutMs: 60000,
    });
    previewCache[page] = {
      items: data.items || [],
      hasMore: Boolean(data.has_more),
    };
    if (data.next_offset_id) {
      previewCursors[page + 1] = data.next_offset_id;
    }
  } catch {
    // Prefetch failures should not block the UI
  }
};

const createTask = async () => {
  await submitSelected();
};

const updateSelectedCount = () => {
  if (selectedCountText) {
    selectedCountText.textContent = `已选: ${selectedIds.size}`;
  }
  saveSelectedState();
};

const submitSelected = async () => {
  const channel = channelInput.value.trim();
  if (!channel) {
    setMessage("请填写频道", true);
    return;
  }
  if (!selectedIds.size) {
    setMessage("请先选择需要下载的视频", true);
    return;
  }
  const payload = {
    channel,
    message_ids: Array.from(selectedIds),
    output_dir: outputDirInput.value.trim() || undefined,
  };
  if (autoUploadInput.value) payload.auto_upload = autoUploadInput.value === "true";
  if (uploadMetaInput.value) payload.upload_meta = uploadMetaInput.value === "true";
  try {
    const data = await fetchJSON("/tasks", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setMessage(`任务已创建 #${data.id}`);
    await loadTasks();
    selectedIds.clear();
    updateSelectedCount();
    const items = previewCache[previewPage]?.items || [];
    renderPreview(items);
  } catch (err) {
    setMessage(`创建失败: ${err.message}`, true);
  }
};

const openLog = async (taskId) => {
  try {
    const data = await fetchJSON(`/tasks/${taskId}/log?limit=200`, {
      timeoutMs: 60000,
    });
    const lines = (data.items || [])
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item.message === "string") return item.message;
        return "";
      })
      .filter((line) => line.trim())
      .map(formatLogLine)
      .join("\n");
    logContent.textContent = lines && lines.trim() ? lines : "暂无日志";
    logModal.classList.remove("hidden");
  } catch (err) {
    const msg = `加载日志失败: ${err.message}`;
    setMessage(msg, true);
    logContent.textContent = msg;
    logModal.classList.remove("hidden");
  }
};

const handleTaskAction = async (event) => {
  const btn = event.target.closest("button");
  if (!btn) return;
  const action = btn.dataset.action;
  const taskId = btn.dataset.id;
  if (!action || !taskId) return;
  try {
    if (action === "log") {
      await openLog(taskId);
      return;
    }
    if (action === "retry") {
      if (!window.confirm("确定重试该任务吗？")) return;
      const status = btn.closest(".task-card")?.dataset.status || "";
      if (["running", "pending", "cancel_requested"].includes(status)) {
        if (!window.confirm("任务运行中，是否先取消再重试？")) return;
        await fetchJSON(`/tasks/${taskId}/cancel`, { method: "POST" });
        setMessage("已提交取消，准备重试...");
      }
      let retried = false;
      let lastErr = null;
      for (let i = 0; i < 10; i += 1) {
        try {
          await fetchJSON(`/tasks/${taskId}/retry`, { method: "POST" });
          retried = true;
          break;
        } catch (err) {
          const msg = err?.message || "";
          lastErr = err;
          if (!msg.includes("任务运行中")) throw err;
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
      if (!retried && lastErr) throw lastErr;
      setMessage("已提交重试");
    } else if (action === "cancel") {
      const status = btn.closest(".task-card")?.dataset.status || "";
      if (["failed", "done", "cancelled"].includes(status)) {
        setMessage("任务已结束，无法取消", true);
        return;
      }
      if (!window.confirm("确定取消该任务吗？")) return;
      await fetchJSON(`/tasks/${taskId}/cancel`, { method: "POST" });
      const card = btn.closest(".task-card");
      const statusPill = card?.querySelector(".status-pill");
      if (statusPill) {
        statusPill.textContent = "已取消";
      }
      setMessage("已提交取消");
    } else if (action === "delete") {
      if (!window.confirm("确定删除该任务吗？删除后不可恢复。")) return;
      await fetchJSON(`/tasks/${taskId}`, { method: "DELETE" });
      setMessage("已删除任务");
    }
    await loadTasks();
  } catch (err) {
    setMessage(`操作失败: ${err.message}`, true);
  }
};

const connectWs = () => {
  const baseUrl = getBaseUrl() || window.location.origin;
  let url = `${baseUrl.replace("http", "ws")}/ws/tasks`;
  const token = getToken();
  if (token) {
    url += `?token=${encodeURIComponent(token)}`;
  }
  try {
    const ws = new WebSocket(url);
    ws.onmessage = () => loadTasks();
    ws.onclose = () => setTimeout(connectWs, 2000);
  } catch {
    setTimeout(connectWs, 2000);
  }
};

const loadServerConfig = async () => {
  try {
    const data = await fetchJSON("/config");
    const value = Number(data?.telegram_download_concurrency);
    if (Number.isFinite(value) && value > 0) {
      concurrencyInput.value = String(value);
      persistForm();
    }
  } catch {
    // Ignore if token missing or server not ready
  }
};

saveTokenBtn.addEventListener("click", () => {
  localStorage.setItem(storageKey, getToken());
  setMessage("Token 已保存");
});

createTaskBtn.addEventListener("click", createTask);
saveConfigBtn.addEventListener("click", async () => {
  persistForm();
  try {
    const concurrency = Number(concurrencyInput.value);
    if (Number.isFinite(concurrency) && concurrency > 0) {
      await fetchJSON("/config", {
        method: "POST",
        body: JSON.stringify({ telegram_download_concurrency: concurrency }),
      });
    }
    setMessage("配置已保存");
  } catch (err) {
    setMessage(`配置保存失败: ${err.message}`, true);
  }
});
taskBadge?.addEventListener("click", async () => {
  await loadTasks();
  document.getElementById("taskList")?.scrollIntoView({ behavior: "smooth" });
});
selectAllTasks?.addEventListener("change", (event) => {
  if (!currentTaskPageIds.length) return;
  if (event.target.checked) {
    currentTaskPageIds.forEach((id) => selectedTaskIds.add(id));
  } else {
    currentTaskPageIds.forEach((id) => selectedTaskIds.delete(id));
  }
  if (lastTaskItems.length) renderTasks(lastTaskItems);
});
deleteSelectedTasksBtn?.addEventListener("click", async () => {
  if (!currentTaskId) return;
  const ids = Array.from(selectedTaskIds);
  if (!ids.length) {
    setMessage("请先选择需要删除的视频", true);
    return;
  }
  const warn = `确定删除已选视频（${ids.length} 个）吗？正在下载或已完成的条目也会从列表中移除。`;
  if (!window.confirm(warn)) return;
  try {
    await fetchJSON(`/tasks/${currentTaskId}/remove`, {
      method: "POST",
      body: JSON.stringify({ message_ids: ids }),
    });
    selectedTaskIds.clear();
    setMessage("已删除所选视频");
    await loadTasks();
  } catch (err) {
    setMessage(`删除失败: ${err.message}`, true);
  }
});
refreshBtn.addEventListener("click", loadTasks);
taskList.addEventListener("click", handleTaskAction);
taskTableBody?.addEventListener("click", async (event) => {
  const btn = event.target.closest(".task-pause-btn");
  if (!btn) return;
  if (!currentTaskId) return;
  const msgId = Number(btn.dataset.id);
  if (!Number.isFinite(msgId)) return;
  const action = btn.dataset.action;
  const pause = action === "pause";
  try {
    await fetchJSON(`/tasks/${currentTaskId}/pause`, {
      method: "POST",
      body: JSON.stringify({ message_id: msgId, pause }),
    });
    setMessage(pause ? "已暂停当前视频" : "已继续当前视频");
    await loadTasks();
  } catch (err) {
    setMessage(`操作失败: ${err.message}`, true);
  }
});
taskTableBody?.addEventListener("change", (event) => {
  const checkbox = event.target.closest(".task-select");
  if (!checkbox) return;
  const id = Number(checkbox.dataset.id);
  if (!Number.isFinite(id)) return;
  if (checkbox.checked) {
    selectedTaskIds.add(id);
  } else {
    selectedTaskIds.delete(id);
  }
  if (selectAllTasks && currentTaskPageIds.length) {
    const selectedCount = currentTaskPageIds.filter((v) =>
      selectedTaskIds.has(v)
    ).length;
    selectAllTasks.indeterminate =
      selectedCount > 0 && selectedCount < currentTaskPageIds.length;
    selectAllTasks.checked =
      currentTaskPageIds.length > 0 && selectedCount === currentTaskPageIds.length;
  }
});
closeLogBtn.addEventListener("click", () => logModal.classList.add("hidden"));
closeMediaBtn.addEventListener("click", () => {
  stopMediaPlayback();
  mediaModal.classList.add("hidden");
});
mediaPrevBtn.addEventListener("click", () => moveGallery(-1));
mediaNextBtn.addEventListener("click", () => moveGallery(1));
sendCodeBtn.addEventListener("click", sendCode);
loginBtn.addEventListener("click", () => {
  if (loginAuthorized) {
    logout();
  } else {
    login();
  }
});
previewBtn.addEventListener("click", previewVideos);
previewPrevBtn.addEventListener("click", () =>
  loadPreviewPage(Math.max(1, previewPage - 1))
);
previewNextBtn.addEventListener("click", () =>
  loadPreviewPage(previewPage + 1)
);
taskPrevBtn?.addEventListener("click", () => {
  taskFilePage = Math.max(1, taskFilePage - 1);
  lastTasksSignature = "";
  renderTasks(lastTaskItems);
});
taskNextBtn?.addEventListener("click", () => {
  taskFilePage += 1;
  lastTasksSignature = "";
  renderTasks(lastTaskItems);
});
previewList.addEventListener(
  "error",
  (event) => {
    const img = event.target;
    if (!(img instanceof HTMLImageElement)) return;
    if (!img.classList.contains("preview-image") && !img.classList.contains("extra-thumb")) {
      return;
    }
    const placeholder = document.createElement("div");
    placeholder.className = img.classList.contains("preview-image")
      ? "preview-image placeholder"
      : "preview-thumb placeholder";
    placeholder.textContent = "\u65e0\u5c01\u9762";
    placeholder.dataset.src = img.dataset.src || "";
    img.replaceWith(placeholder);
  },
  true
);
previewList.addEventListener("click", (event) => {
  const groupBtn = event.target.closest(".group-thumb");
  if (groupBtn) {
    const groupKey = groupBtn.dataset.groupKey;
    const messageId = Number(groupBtn.dataset.messageId);
    const groupItems = previewGroupMap[groupKey] || [];
    const item = groupItems.find((entry) => entry.message_id === messageId);
    if (!item) return;
    groupActiveMap.set(groupKey, messageId);
    const groupEl = groupBtn.closest(".preview-group");
    const mainEl = groupEl?.querySelector(".preview-group-main");
    if (mainEl) {
      mainEl.innerHTML = buildPreviewRow(item);
      mainEl.classList.toggle("selected", selectedIds.has(item.message_id));
    }
    groupEl?.querySelectorAll(".group-thumb").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.messageId === String(messageId));
    });
    return;
  }
  const img = event.target.closest("img, .preview-image");
  const row = event.target.closest(".preview-row");
  if (!img || !row) return;
  if (img.classList.contains("preview-image")) {
    const fallback =
      row.dataset.channel && row.dataset.messageId
        ? buildStreamUrl(row.dataset.channel, row.dataset.messageId)
        : null;
    if (row.dataset.video) {
      openMediaModal("video", row.dataset.video, fallback);
    } else if (fallback) {
      openMediaModal("stream", fallback);
    }
    return;
  }
  if (img.classList.contains("extra-thumb") && img.dataset.src) {
    const items = JSON.parse(row.dataset.gallery || "[]");
    const index = items.indexOf(img.dataset.src);
    openImageGallery(items, index >= 0 ? index : 0);
  }
});

previewList.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-select-id]");
  if (!checkbox) return;
  const id = Number(checkbox.dataset.selectId);
  if (checkbox.checked) {
    selectedIds.add(id);
  } else {
    selectedIds.delete(id);
  }
  updateSelectedCount();
  const items = previewCache[previewPage]?.items || [];
  renderPreview(items);
});

selectAllBtn.addEventListener("click", () => {
  const items = previewCache[previewPage]?.items || [];
  items.forEach((item) => selectedIds.add(item.message_id));
  renderPreview(items);
  updateSelectedCount();
});

clearSelectionBtn.addEventListener("click", () => {
  selectedIds.clear();
  const items = previewCache[previewPage]?.items || [];
  renderPreview(items);
  updateSelectedCount();
  if (previewStatus) previewStatus.textContent = "已取消选择";
});

deleteSelectedBtn.addEventListener("click", () => {
  if (!selectedIds.size) {
    setMessage("请先选择需要删除的内容", true);
    return;
  }
  selectedIds.forEach((id) => deletedIds.add(id));
  Object.keys(previewCache).forEach((page) => {
    const items = previewCache[page]?.items || [];
    previewCache[page] = {
      ...previewCache[page],
      items: items.filter((item) => !deletedIds.has(item.message_id)),
    };
  });
  selectedIds.clear();
  updateSelectedCount();
  const items = previewCache[previewPage]?.items || [];
  renderPreview(items);
  savePreviewState(items);
});

tokenInput.value = localStorage.getItem(storageKey) || "";
const savedForm = JSON.parse(localStorage.getItem(configKey) || "{}");
const FIXED_OUTPUT_DIR = "/data/telegram_downloads";
serverBaseInput.value = window.location.origin;
apiIdInput.value = savedForm.apiId || "30535444";
apiHashInput.value = savedForm.apiHash || "";
channelInput.value = savedForm.channel || "@sosocw";
outputDirInput.value = FIXED_OUTPUT_DIR;
autoUploadInput.value = savedForm.autoUpload ?? "true";
uploadMetaInput.value = savedForm.uploadMeta ?? "true";
sshUserInput.value = savedForm.sshUser || "ubuntu";
pemPathInput.value =
  savedForm.pemPath || "/Users/huangjin/Desktop/工具源码/telegramDownload.pem";
downloadRootInput.value = savedForm.downloadRoot || "/data/telegram_downloads";
shortThresholdInput.value = savedForm.shortThreshold ?? "1";
concurrencyInput.value = savedForm.concurrency ?? "2";
countryCodeInput.value = savedForm.countryCode || "+86";
phoneNumberInput.value = savedForm.phoneNumber || "";
previewLimitInput.value = savedForm.previewLimit || "50";

const persistForm = () => {
  localStorage.setItem(
    configKey,
    JSON.stringify({
      serverBase: window.location.origin,
      apiId: apiIdInput.value.trim(),
      apiHash: apiHashInput.value.trim(),
      channel: channelInput.value.trim(),
      outputDir: FIXED_OUTPUT_DIR,
      autoUpload: autoUploadInput.value,
      uploadMeta: uploadMetaInput.value,
      sshUser: sshUserInput.value.trim(),
      pemPath: pemPathInput.value.trim(),
      downloadRoot: downloadRootInput.value.trim(),
      shortThreshold: shortThresholdInput.value.trim(),
      concurrency: concurrencyInput.value.trim(),
      countryCode: countryCodeInput.value.trim(),
      phoneNumber: phoneNumberInput.value.trim(),
      previewLimit: previewLimitInput.value.trim(),
    })
  );
};

[
  serverBaseInput,
  apiIdInput,
  apiHashInput,
  channelInput,
  outputDirInput,
  autoUploadInput,
  uploadMetaInput,
  sshUserInput,
  pemPathInput,
  downloadRootInput,
  shortThresholdInput,
  concurrencyInput,
  countryCodeInput,
  phoneNumberInput,
  previewLimitInput,
].forEach((el) => el.addEventListener("change", persistForm));

loadTasks();
connectWs();
refreshLoginStatus();
updateServerBaseHint();
loadPreviewState();
loadSelectedState();
updateSelectedCount();
loadServerConfig();
setInterval(refreshLoginStatus, 15000);
setInterval(loadTasks, 15000);
