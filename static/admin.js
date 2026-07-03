function qs(id) {
  return document.getElementById(id);
}

async function fetchJson(url, options = {}) {
  const resolvedUrl = window.VIT?.withMakeQuery ? window.VIT.withMakeQuery(url) : url;
  const res = await fetch(resolvedUrl, {
    credentials: "same-origin",
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return body;
}

function formatDurationSec(sec) {
  if (sec == null || sec === "") return "—";
  const value = Number(sec);
  if (!Number.isFinite(value) || value < 0) return "—";
  if (value < 60) return `${value.toFixed(1)}s`;
  const mins = Math.floor(value / 60);
  const rem = Math.round(value % 60);
  if (mins < 60) return rem ? `${mins}m ${rem}s` : `${mins}m`;
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return remMins ? `${hours}h ${remMins}m` : `${hours}h`;
}

function formatStartedAt(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function formatJobType(jobType) {
  return (
    {
      ingest: "Ingest",
      geocode: "Geocode",
      catalog_sync: "Catalog sync",
      dealer_sync: "Dealer sync",
      dealer_vehicle_refresh: "Dealer ZIP refresh",
    }[jobType] || jobType
  );
}

function formatWorkerState(state) {
  const normalized = String(state || "unknown").toLowerCase();
  return (
    {
      idle: "Idle",
      busy: "Busy",
      suspended: "Suspended",
      started: "Busy",
    }[normalized] || normalized
  );
}

function formatWorkerJobType(jobType) {
  return formatJobType(jobType || "task");
}

function formatWorkerHeartbeat(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const ageSec = Math.max(0, Math.round((Date.now() - date.getTime()) / 1000));
  if (ageSec < 60) return `${ageSec}s ago`;
  const mins = Math.floor(ageSec / 60);
  if (mins < 60) return `${mins}m ago`;
  return date.toLocaleString();
}

function isUnsafeJobDescription(desc) {
  const text = String(desc || "");
  return (
    text.includes("run_ingest_task") ||
    text.includes("run_geocode_task") ||
    text.includes("run_catalog_sync_task") ||
    text.includes("run_dealer_vehicle_refresh_task") ||
    text.includes("mysql+pymysql://") ||
    text.includes("mysql://") ||
    text.length > 160
  );
}

function formatWorkerJobDetail(job) {
  if (!job) return "Running…";
  const parts = [
    job.message,
    job.detail,
    job.percent != null && Number.isFinite(Number(job.percent))
      ? `Progress ${Math.round(Number(job.percent))}%`
      : "",
  ].filter(Boolean);
  if (parts.length) {
    return parts.join(" · ");
  }
  const desc = String(job.description || "").trim();
  if (desc && !isUnsafeJobDescription(desc)) {
    return desc;
  }
  return "Running…";
}

function formatModelCodesValue(codes) {
  if (!Array.isArray(codes) || !codes.length) return "";
  if (codes.length <= 12) return codes.join(", ");
  return `${codes.length} models: ${codes.slice(0, 10).join(", ")}, …`;
}

function renderWorkersPanel(workersPayload) {
  const panel = qs("admin-workers-panel");
  const summaryEl = qs("admin-workers-summary");
  const queuesEl = qs("admin-workers-queues");
  const failedEl = qs("admin-workers-failed");
  if (!panel) return;

  const payload = workersPayload || {};
  const summary = payload.summary || {};
  const queues = payload.queues || [];
  const workerRows = payload.workers || [];
  const failedJobs = payload.failed_jobs || [];

  if (summaryEl) {
    if (!payload.enabled) {
      summaryEl.textContent = payload.message || "Redis jobs disabled";
    } else {
      const total = Number(summary.total || 0);
      const expected = Number(payload.expected_workers || 0);
      const onlineText =
        expected > 0 && total < expected ? `${total}/${expected} online` : `${total} online`;
      summaryEl.textContent = `${onlineText} · ${summary.busy || 0} busy · ${summary.idle || 0} idle`;
    }
  }

  if (queuesEl) {
    if (!payload.enabled || !queues.length) {
      queuesEl.innerHTML = payload.message
        ? `<p class="admin-muted">${escapeHtml(payload.message)}</p>`
        : "";
    } else {
      queuesEl.innerHTML = queues
        .map(
          (queue) =>
            `<span class="admin-workers-queue-chip"><strong>${escapeHtml(queue.name)}</strong>: ${Number(queue.queued || 0).toLocaleString()} queued · ${Number(queue.intermediate || 0).toLocaleString()} stuck · ${Number(queue.started || 0).toLocaleString()} started · ${Number(queue.failed || 0).toLocaleString()} failed</span>`
        )
        .join("");
    }
  }

  if (failedEl) {
    if (!payload.enabled) {
      failedEl.innerHTML = "";
    } else {
      const parts = [];
      if (payload.message) {
        parts.push(`<p class="admin-muted">${escapeHtml(payload.message)}</p>`);
      }
      if (failedJobs.length) {
        parts.push(`<div class="admin-workers-failed-list">
          <div class="admin-muted">Recent failed queue jobs</div>
          ${failedJobs
            .map(
              (job) =>
                `<div class="admin-workers-failed-item"><strong>${escapeHtml(job.queue || "queue")}</strong> · ${escapeHtml(job.id || "job")}<div class="admin-muted">${escapeHtml(job.error || "Unknown error")}</div></div>`
            )
            .join("")}
        </div>`);
      }
      failedEl.innerHTML = parts.join("");
    }
  }

  if (!payload.enabled) {
    panel.innerHTML = `<p class="admin-muted">${escapeHtml(payload.message || "Background workers are not available.")}</p>`;
    return;
  }

  if (!workerRows.length) {
    panel.innerHTML = `<p class="admin-muted">${escapeHtml(payload.message || "No workers connected.")}</p>`;
    return;
  }

  panel.innerHTML = workerRows
    .map((worker) => {
      const state = String(worker.state || "unknown").toLowerCase();
      const job = worker.current_job || null;
      const makeLabel = job?.make ? String(job.make).toUpperCase() : "";
      const jobType = job?.job_type ? formatWorkerJobType(job.job_type) : "";
      const jobRunId = job?.job_run_id != null ? `#${job.job_run_id}` : "";
      const currentJobHtml = job
        ? `<div class="admin-worker-job">
            <div class="admin-worker-job-title">${escapeHtml([makeLabel, jobType, jobRunId].filter(Boolean).join(" · ") || job.task_label || "Current job")}</div>
            <div class="admin-worker-job-detail">${escapeHtml(formatWorkerJobDetail(job))}</div>
          </div>`
        : `<div class="admin-worker-job admin-worker-job-idle">Waiting for work</div>`;
      const queueLabels = (worker.queues || []).map((name) => escapeHtml(name)).join(", ") || "—";
      return `<article class="admin-worker-card">
        <div class="admin-worker-card-head">
          <div>
            <strong>${escapeHtml(worker.name || "worker")}</strong>
            <div class="admin-muted admin-worker-meta">PID ${escapeHtml(worker.pid ?? "—")} · ${escapeHtml(worker.hostname || "host")}</div>
          </div>
          <span class="job-run-status ${escapeHtml(state)}">${escapeHtml(formatWorkerState(state))}</span>
        </div>
        ${currentJobHtml}
        <div class="admin-worker-foot">
          <span>Queues: ${queueLabels}</span>
          <span>Heartbeat: ${escapeHtml(formatWorkerHeartbeat(worker.last_heartbeat))}</span>
        </div>
      </article>`;
    })
    .join("");
}

function isWorkersActive(workersPayload) {
  const summary = workersPayload?.summary || {};
  const queues = workersPayload?.queues || [];
  const queuedTotal = queues.reduce((sum, queue) => sum + Number(queue.queued || 0), 0);
  return Boolean(
    workersPayload?.enabled &&
      ((summary.busy || 0) > 0 || queuedTotal > 0)
  );
}

function summarizeParams(run) {
  const params = run.params || {};
  if (run.job_type === "ingest") {
    const models = params.all_models
      ? "all models"
      : `${(params.model_codes || []).length} model(s)`;
    const scope = params.nationwide
      ? "nationwide"
      : `ZIP ${params.zip_code ?? "—"}, ${params.distance ?? "—"} mi`;
    return `${scope}, ${models}`;
  }
  if (run.job_type === "geocode") {
    const limit = params.limit == null ? "all remaining" : `${params.limit} max`;
    return `${limit}, ${params.workers || 1} worker(s)${params.force ? ", force" : ""}`;
  }
  if (run.job_type === "catalog_sync") {
    const parts = [`ZIP ${params.zip_code ?? "—"}`];
    if (params.distance != null) parts.push(`${params.distance} mi`);
    return parts.join(", ");
  }
  if (run.job_type === "dealer_sync") {
    return params.make ? `${params.make} nationwide` : "Nationwide dealer discovery";
  }
  if (run.job_type === "dealer_vehicle_refresh") {
    const models = params.all_models
      ? "all models"
      : `${(params.model_codes || []).length} model(s)`;
    return `${params.distance ?? 1} mi per dealer ZIP, ${models}`;
  }
  return JSON.stringify(params);
}

function formatParamsDetail(run) {
  const params = run.params || {};
  const rows = [];

  function addRow(label, value, className = "") {
    if (value == null || value === "") return;
    const classAttr = className ? ` class="${className}"` : "";
    rows.push(
      `<div class="job-run-param-row"><dt>${escapeHtml(label)}</dt><dd${classAttr}>${escapeHtml(String(value))}</dd></div>`
    );
  }

  if (run.job_type === "ingest") {
    addRow("Make", params.make);
    addRow("ZIP code", params.zip_code);
    addRow("Radius (mi)", params.distance);
    addRow("Page size", params.page_size);
    addRow("All models", params.all_models ? "yes" : "no");
    if (!params.all_models && Array.isArray(params.model_codes) && params.model_codes.length) {
      addRow("Model codes", formatModelCodesValue(params.model_codes), "job-run-model-codes");
    }
    addRow("Series code", params.series_code);
    addRow("Lead ID", params.lead_id);
  } else if (run.job_type === "geocode") {
    addRow("Limit", params.limit == null ? "all remaining" : params.limit);
    addRow("Workers", params.workers);
    addRow("Delay (sec)", params.delay_sec);
    addRow("Force re-geocode", params.force ? "yes" : "no");
  } else if (run.job_type === "catalog_sync") {
    addRow("Make", params.make);
    addRow("ZIP code", params.zip_code);
    addRow("Radius (mi)", params.distance);
  } else if (run.job_type === "dealer_sync") {
    addRow("Make", params.make);
  } else if (run.job_type === "dealer_vehicle_refresh") {
    addRow("Make", params.make);
    addRow("Radius (mi)", params.distance);
    addRow("Page size", params.page_size);
    addRow("All models", params.all_models ? "yes" : "no");
    if (!params.all_models && Array.isArray(params.model_codes) && params.model_codes.length) {
      addRow("Model codes", formatModelCodesValue(params.model_codes), "job-run-model-codes");
    }
  }

  const summary = summarizeParams(run);
  const pretty = JSON.stringify(params, null, 2);
  const dl = rows.length
    ? `<dl class="job-run-params-dl">${rows.join("")}</dl>`
    : `<p class="job-run-params-empty muted">No parameters recorded.</p>`;

  return `
    <div class="job-run-detail-section">
      <h4>Parameters</h4>
      <p class="job-run-params-summary">${escapeHtml(summary)}</p>
      ${dl}
      <details class="job-run-params-raw">
        <summary>Raw JSON</summary>
        <pre>${escapeHtml(pretty)}</pre>
      </details>
    </div>
  `;
}

function jobRunProgressData(run, liveProgress) {
  const status = String(run.status || "unknown").toLowerCase();
  const source = liveProgress || run.result || {};
  let pct = null;

  if (source.percent != null && Number.isFinite(Number(source.percent))) {
    pct = Math.max(0, Math.min(100, Number(source.percent)));
  } else if (run.job_type === "geocode" && Number(source.total) > 0) {
    pct = Math.max(0, Math.min(100, (Number(source.processed || 0) / Number(source.total)) * 100));
  } else if (run.job_type === "ingest" && Number(source.total_pages) > 0) {
    pct = Math.max(
      0,
      Math.min(100, (Number(source.current_page || 0) / Number(source.total_pages)) * 100)
    );
  } else if (run.job_type === "ingest" && Number(source.total_models) > 0) {
    const index = Number(source.model_index || 0);
    pct = Math.max(0, Math.min(100, (index / Number(source.total_models)) * 100));
  } else if (run.job_type === "dealer_vehicle_refresh" && Number(source.total_models) > 0) {
    const index = Number(source.model_index || 0);
    pct = Math.max(0, Math.min(100, (index / Number(source.total_models)) * 100));
  } else if (run.job_type === "dealer_vehicle_refresh" && source.percent != null) {
    pct = Math.max(0, Math.min(100, Number(source.percent)));
  }

  if (status === "completed") {
    return { pct: 100, label: "100%", state: "complete", indeterminate: false };
  }
  if (status === "cancelled") {
    return {
      pct: pct ?? 0,
      label: pct != null ? `${Math.round(pct)}%` : "Cancelled",
      state: "cancelled",
      indeterminate: false,
    };
  }
  if (status === "failed") {
    return {
      pct: pct ?? 0,
      label: pct != null ? `${Math.round(pct)}%` : "Failed",
      state: "failed",
      indeterminate: false,
    };
  }
  if (status === "queued") {
    return {
      pct: 0,
      label: "Queued",
      state: "queued",
      indeterminate: true,
    };
  }
  if (status === "running") {
    const indeterminate = pct == null;
    return {
      pct: indeterminate ? 0 : pct,
      label: indeterminate ? "Running…" : `${Math.round(pct)}%`,
      state: "running",
      indeterminate,
    };
  }
  return { pct: 0, label: "—", state: "idle", indeterminate: false };
}

function renderJobRunProgressBar(progress) {
  const fillClass = [
    "job-run-progress-mini-fill",
    progress.state === "complete" ? "is-complete" : "",
    progress.state === "failed" ? "is-failed" : "",
    progress.state === "cancelled" ? "is-cancelled" : "",
    progress.state === "queued" ? "is-queued" : "",
    progress.indeterminate ? "is-indeterminate" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const width = progress.indeterminate ? 40 : Math.max(0, Math.min(100, progress.pct || 0));
  return `
    <div class="job-run-progress-wrap" title="${escapeHtml(progress.label)}">
      <div class="job-run-progress-mini" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.indeterminate ? 0 : Math.round(width)}">
        <div class="${fillClass}" style="width: ${width}%"></div>
      </div>
      <span class="job-run-progress-label">${escapeHtml(progress.label)}</span>
    </div>
  `;
}

function buildLiveProgressMap(payload) {
  const map = {};
  const ingest = payload?.ingest || {};
  if (ingest.job_run_id && window.VIT?.isJobStatusActive?.(ingest.status)) {
    map[ingest.job_run_id] = ingest;
  }
  const geocode = payload?.geocode?.job || {};
  if (geocode.job_run_id && window.VIT?.isJobStatusActive?.(geocode.status)) {
    map[geocode.job_run_id] = geocode;
  }
  for (const run of payload?.recent_runs || []) {
    if (!run?.job_run_id || !window.VIT?.isJobStatusActive?.(run.status)) {
      continue;
    }
    if (map[run.job_run_id]) {
      continue;
    }
    map[run.job_run_id] = {
      ...(run.result || {}),
      status: run.status,
      job_run_id: run.job_run_id,
      job_type: run.job_type,
      message: run.message || "",
    };
  }
  return map;
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function summarizeResult(run) {
  const result = run.result || {};
  const error = run.error
    ? `<div class="job-run-error">${escapeHtml(run.error)}</div>`
    : "";
  const logs = Array.isArray(result.logs) ? result.logs : [];
  const logBlock = logs.length
    ? `<details class="job-run-logs"><summary>${logs.length} log line(s)</summary><pre>${escapeHtml(logs.join("\n"))}</pre></details>`
    : "";
  if (run.job_type === "ingest") {
    const parts = [];
    if (result.vehicles_persisted != null) {
      parts.push(`${Number(result.vehicles_persisted).toLocaleString()} saved`);
    }
    if (result.completed_models?.length != null) {
      parts.push(`${result.completed_models.length} model(s)`);
    }
    const summary = parts.join(", ") || run.message || "—";
    return `${error}${escapeHtml(summary)}${logBlock}`;
  }
  if (run.job_type === "geocode") {
    const parts = [];
    if (result.geocoded != null) parts.push(`${Number(result.geocoded).toLocaleString()} geocoded`);
    if (result.failed != null && Number(result.failed) > 0) {
      parts.push(`${Number(result.failed).toLocaleString()} failed`);
    }
    if (result.remaining != null) parts.push(`${Number(result.remaining).toLocaleString()} left`);
    const summary = parts.join(", ") || run.message || "—";
    return `${error}${escapeHtml(summary)}${logBlock}`;
  }
  if (run.job_type === "catalog_sync" && result.count != null) {
    return `${error}${Number(result.count).toLocaleString()} model(s)${logBlock}`;
  }
  if (run.job_type === "dealer_sync") {
    const parts = [];
    if (result.count != null) parts.push(`${Number(result.count).toLocaleString()} dealer(s)`);
    if (result.seed_zips != null) parts.push(`${Number(result.seed_zips).toLocaleString()} seed ZIPs`);
    const summary = parts.join(", ") || run.message || "—";
    return `${error}${escapeHtml(summary)}${logBlock}`;
  }
  if (run.job_type === "dealer_vehicle_refresh") {
    const parts = [];
    if (result.vehicles_persisted != null) {
      parts.push(`${Number(result.vehicles_persisted).toLocaleString()} saved`);
    }
    if (result.completed_models?.length != null) {
      parts.push(`${result.completed_models.length} model(s)`);
    }
    const summary = parts.join(", ") || run.message || "—";
    return `${error}${escapeHtml(summary)}${logBlock}`;
  }
  return `${error}${escapeHtml(run.message || run.error || "—")}${logBlock}`;
}

function renderStatusBlock(container, title, status, lines) {
  const statusClass = String(status || "unknown").toLowerCase();
  container.innerHTML = `
    <div class="admin-status-row">
      <span class="job-run-status ${statusClass}">${status || "unknown"}</span>
      <strong>${title}</strong>
    </div>
    <ul class="admin-status-lines">
      ${lines.map((line) => `<li>${line}</li>`).join("")}
    </ul>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

let catalogModels = [];
let adminPollTimer = null;
let adminPollInFlight = false;
let lastIngestStatus = "idle";
let lastJobRuns = [];
let lastLiveProgressMap = {};
const expandedJobRunIds = new Set();
const POLL_IDLE_MS = 15000;
const POLL_ACTIVE_MS = 5000;
const POLL_HIDDEN_MS = 60000;
const ingestUiState = {
  running: false,
  selectedModelCodes: new Set(),
};

function setIngestPanelLoading(active) {
  const overlay = qs("ingest-loading");
  const panel = qs("ingest-panel");
  if (overlay) {
    overlay.classList.toggle("hidden", !active);
    overlay.setAttribute("aria-hidden", active ? "false" : "true");
  }
  if (panel) {
    panel.classList.toggle("is-loading", active);
  }
}

function getIngestSettingsPayload(options) {
  if (window.VIT?.getIngestSettingsPayload) {
    return window.VIT.getIngestSettingsPayload(options);
  }
  const defaults = window.VIT?.getIngestDefaults?.(window.VIT?.currentMake) || {
    zip: "95132",
    distance: 500,
    pageSize: 250,
  };
  return {
    zip_code: qs("ingest-zip-code")?.value?.trim() || defaults.zip,
    distance: Number(qs("ingest-distance")?.value || defaults.distance),
    page_size: defaults.pageSize,
    nationwide: defaults.nationwide !== false,
  };
}

function applyMakeUi() {
  const info = window.VIT?.currentMakeInfo;
  if (!info) return;

  const title = qs("admin-ingest-title");
  if (title) {
    title.textContent = `Refresh ${info.display_name} inventory`;
  }

  const subtitle = qs("admin-ingest-subtitle");
  if (subtitle) {
    subtitle.textContent =
      info.slug === "mazda"
        ? "Sync dealers nationwide, then refresh inventory by model or per dealer ZIP (1 mi radius)."
        : info.supports_catalog_sync
          ? "Sync the model catalog, then ingest selected models or the full catalog."
          : "Run ingest to refresh inventory for this make.";
  }

  window.VIT?.hydrateIngestLocationFields?.();
  const defaults = window.VIT.getIngestDefaults(info.slug);
  const zipEl = qs("ingest-zip-code");
  const distEl = qs("ingest-distance");
  if (zipEl && !zipEl.value.trim()) zipEl.value = defaults.zip;
  if (distEl && !distEl.value.trim()) distEl.value = String(defaults.distance);

  const showCatalogSync = Boolean(info.supports_catalog_sync);
  const showModelSelection = Boolean(info.requires_model_selection);
  for (const id of [
    "ingest-refresh-catalog-btn",
    "catalog-select-all-btn",
    "catalog-select-missing-btn",
    "catalog-select-none-btn",
    "catalog-selection-count",
  ]) {
    qs(id)?.classList.toggle("hidden", !showCatalogSync);
  }
  qs("ingest-selected-btn")?.classList.toggle("hidden", !showModelSelection);
  qs("ingest-sync-dealers-btn")?.classList.toggle("hidden", info.slug !== "mazda");
  qs("ingest-dealer-refresh-selected-btn")?.classList.toggle("hidden", info.slug !== "mazda");
  qs("ingest-dealer-refresh-all-btn")?.classList.toggle("hidden", info.slug !== "mazda");
  if (!showCatalogSync) {
    qs("ingest-all-btn")?.classList.remove("hidden");
  }
}

function emptyCatalogMessage() {
  const info = window.VIT?.currentMakeInfo;
  if (info?.supports_catalog_sync) {
    return 'No model catalog in the database yet. Click “Sync Model Catalog” to fetch available models.';
  }
  return "No models in the database yet. Run ingest to populate inventory.";
}

function updateCatalogSelectionUi() {
  const count = ingestUiState.selectedModelCodes.size;
  const countEl = qs("catalog-selection-count");
  if (countEl) {
    countEl.textContent =
      count === 1 ? "1 model selected" : `${count.toLocaleString()} models selected`;
  }
  const selectedBtn = qs("ingest-selected-btn");
  if (selectedBtn) {
    selectedBtn.disabled = count === 0;
  }
  const dealerRefreshSelectedBtn = qs("ingest-dealer-refresh-selected-btn");
  if (dealerRefreshSelectedBtn) {
    dealerRefreshSelectedBtn.disabled = count === 0;
  }
}

function catalogModelHasNoData(model) {
  return Number(model.active_vehicle_count || 0) === 0;
}

function selectAllCatalogModels() {
  ingestUiState.selectedModelCodes = new Set(catalogModels.map((model) => model.model_code));
  renderCatalogModels();
}

function selectMissingDataCatalogModels() {
  ingestUiState.selectedModelCodes = new Set(
    catalogModels.filter(catalogModelHasNoData).map((model) => model.model_code)
  );
  renderCatalogModels();
}

function selectNoneCatalogModels() {
  ingestUiState.selectedModelCodes.clear();
  renderCatalogModels();
}

function formatCatalogInventoryCount(count) {
  const value = Number(count || 0);
  if (value === 0) {
    return "No cars in database";
  }
  return `${value.toLocaleString()} ${value === 1 ? "car" : "cars"} in database`;
}

function sortCatalogModelsForDisplay(models) {
  return [...models].sort((a, b) => {
    const aCount = Number(a.active_vehicle_count || 0);
    const bCount = Number(b.active_vehicle_count || 0);
    if (aCount === 0 && bCount > 0) return -1;
    if (bCount === 0 && aCount > 0) return 1;
    if (aCount !== bCount) return aCount - bCount;
    const aTitle = String(a.title || a.series || a.model_code || "");
    const bTitle = String(b.title || b.series || b.model_code || "");
    return aTitle.localeCompare(bTitle);
  });
}

function renderCatalogModels() {
  const container = qs("catalog-model-list");
  if (!container) return;

  if (!catalogModels.length) {
    container.innerHTML = `<div class="muted">${escapeHtml(emptyCatalogMessage())}</div>`;
    return;
  }

  container.innerHTML = sortCatalogModelsForDisplay(catalogModels)
    .map((model) => {
      const code = model.model_code;
      const selected = ingestUiState.selectedModelCodes.has(code);
      const title = escapeHtml(model.title || model.series || code);
      const inventoryCount = Number(model.active_vehicle_count || 0);
      const hasNoData = catalogModelHasNoData(model);
      const meta = [
        model.year ? `${model.year}` : "",
        model.msrp ? `$${Number(model.msrp).toLocaleString()} MSRP` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      const image = model.image
        ? (window.VIT?.cachedImgTag ? VIT.cachedImgTag(model.image, title) : `<img src="${escapeHtml(model.image)}" alt="" loading="lazy" />`)
        : '<div class="catalog-model-thumb catalog-model-thumb-empty"><span>No image</span></div>';
      const alert = hasNoData
        ? '<span class="catalog-model-alert" title="No inventory in database">⚠</span>'
        : "";
      return `
        <label class="catalog-model-item ${selected ? "selected" : ""} ${hasNoData ? "no-data" : ""}" data-model-code="${escapeHtml(code)}">
          <input type="checkbox" ${selected ? "checked" : ""} data-model-code="${escapeHtml(code)}" />
          ${image}
          <div class="catalog-model-copy">
            <div class="catalog-model-title-row">
              <strong>${title}</strong>
              ${alert}
            </div>
            <span>${escapeHtml(code)}</span>
            <span class="catalog-model-count ${hasNoData ? "is-empty" : ""}">${escapeHtml(formatCatalogInventoryCount(inventoryCount))}</span>
            ${meta ? `<span class="catalog-model-meta">${escapeHtml(meta)}</span>` : ""}
          </div>
        </label>
      `;
    })
    .join("");

  container.querySelectorAll(".catalog-model-item").forEach((item) => {
    item.addEventListener("click", (event) => {
      if (event.target instanceof HTMLInputElement) return;
      const checkbox = item.querySelector('input[type="checkbox"]');
      if (!checkbox) return;
      checkbox.checked = !checkbox.checked;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  container.querySelectorAll('input[type="checkbox"][data-model-code]').forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const code = checkbox.getAttribute("data-model-code");
      if (!code) return;
      if (checkbox.checked) {
        ingestUiState.selectedModelCodes.add(code);
      } else {
        ingestUiState.selectedModelCodes.delete(code);
      }
      const label = checkbox.closest(".catalog-model-item");
      if (label) {
        label.classList.toggle("selected", checkbox.checked);
      }
      updateCatalogSelectionUi();
    });
  });

  updateCatalogSelectionUi();
  if (window.VIT?.hydrateImages) {
    VIT.hydrateImages(container);
  }
  if (window.VIT?.primeImageUrls) {
    VIT.primeImageUrls(catalogModels.map((model) => model.image).filter(Boolean));
  }
}

async function loadCatalogModels() {
  setIngestPanelLoading(true);
  try {
    const data = await fetchJson("/api/catalog/models");
    catalogModels = data.models || [];
    renderCatalogModels();
  } finally {
    setIngestPanelLoading(false);
  }
}

function setIngestUiRunning(running) {
  ingestUiState.running = running;
  updateCatalogSelectionUi();
  const dealerRefreshSelectedBtn = qs("ingest-dealer-refresh-selected-btn");
  if (dealerRefreshSelectedBtn) {
    dealerRefreshSelectedBtn.disabled = ingestUiState.selectedModelCodes.size === 0;
  }
}

function renderIngestProgress(status) {
  const wrap = qs("ingest-progress-wrap");
  const label = qs("ingest-progress-label");
  const percent = qs("ingest-progress-percent");
  const bar = qs("ingest-progress-bar");
  const detail = qs("ingest-progress-detail");
  if (!wrap || !label || !percent || !bar || !detail) return;

  const isActive = window.VIT?.isJobStatusActive?.(status.status);
  wrap.classList.toggle(
    "hidden",
    !isActive && status.status !== "failed" && status.status !== "completed"
  );

  const pct =
    status.status === "queued"
      ? 0
      : Math.max(0, Math.min(100, Number(status.percent || 0)));
  label.textContent =
    status.status === "queued"
      ? status.message || "Queued — waiting for worker..."
      : status.message || status.status || "Idle";
  percent.textContent = `${pct.toFixed(0)}%`;
  bar.value = pct;

  const parts = [];
  const scope = window.VIT?.formatIngestScope?.(status);
  if (scope) parts.push(scope);
  if (status.current_model_title || status.current_model) {
    const isDealerZipRefresh = /^\d{5}$/.test(String(status.current_model || ""));
    if (isDealerZipRefresh) {
      parts.push(
        `ZIP ${status.current_model} (${status.model_index || 0}/${status.total_models || 0})`
      );
      if (status.current_model_title) {
        parts.push(String(status.current_model_title));
      }
    } else {
      parts.push(
        `Model ${status.model_index || 0}/${status.total_models || 0}: ${status.current_model_title || status.current_model}`
      );
    }
  }
  if (status.total_pages) {
    parts.push(`Page ${status.current_page || 0}/${status.total_pages}`);
  }
  if (status.vehicles_fetched) {
    parts.push(`${Number(status.vehicles_fetched).toLocaleString()} vehicles fetched`);
  }
  if (status.vehicles_persisted) {
    parts.push(`${Number(status.vehicles_persisted).toLocaleString()} saved to database`);
  }
  if (status.completed_models?.length) {
    parts.push(`${status.completed_models.length} model(s) done`);
  }
  if (status.error) {
    parts.push(`Error: ${status.error}`);
  }
  detail.textContent = parts.join(" · ");

  if (status.status === "failed") {
    label.textContent = status.error ? `Failed: ${status.error}` : "Ingest failed";
  }

  renderIngestLogs(status);
}

function renderIngestLogs(status) {
  const panel = qs("ingest-log-panel");
  const output = qs("ingest-log-output");
  if (!panel || !output) return;

  const logs = Array.isArray(status.logs) ? status.logs : [];
  const show =
    logs.length > 0 ||
    window.VIT?.isJobStatusActive?.(status.status) ||
    status.status === "failed" ||
    status.status === "completed";
  panel.classList.toggle("hidden", !show);

  const text = logs.length ? logs.join("\n") : status.message || "";
  const stickToBottom =
    output.scrollHeight - output.clientHeight - output.scrollTop < 48;
  output.textContent = text;
  if (stickToBottom || window.VIT?.isJobStatusActive?.(status.status)) {
    output.scrollTop = output.scrollHeight;
  }
}

function isAdminJobActive(payload) {
  if (typeof payload?.jobs_active === "boolean") {
    return payload.jobs_active || isWorkersActive(payload.workers);
  }
  const ingestStatus = payload?.ingest?.status;
  const geocodeStatus = payload?.geocode?.job?.status;
  return (
    window.VIT?.isJobStatusActive?.(ingestStatus) ||
    window.VIT?.isJobStatusActive?.(geocodeStatus) ||
    isWorkersActive(payload?.workers)
  );
}

function scheduleAdminPoll(delayMs) {
  if (adminPollTimer !== null) {
    clearTimeout(adminPollTimer);
  }
  const interval = document.hidden ? POLL_HIDDEN_MS : delayMs;
  adminPollTimer = window.setTimeout(() => {
    adminPollTimer = null;
    pollAdminState().catch((err) => console.error(err));
  }, interval);
}

async function pollAdminState() {
  if (adminPollInFlight) {
    return;
  }
  adminPollInFlight = true;
  try {
    const payload = await fetchJson("/api/admin/overview");
    const ingest = payload.ingest || {};
    const previousIngestStatus = lastIngestStatus;
    lastIngestStatus = ingest.status || "idle";

    renderOverview(payload);

    if (
      window.VIT?.isJobStatusActive?.(previousIngestStatus) &&
      lastIngestStatus === "completed"
    ) {
      await loadCatalogModels();
    }

    setIngestUiRunning(window.VIT?.isJobStatusActive?.(ingest.status));
    scheduleAdminPoll(isAdminJobActive(payload) ? POLL_ACTIVE_MS : POLL_IDLE_MS);
  } catch (err) {
    console.error(err);
    scheduleAdminPoll(POLL_IDLE_MS);
  } finally {
    adminPollInFlight = false;
  }
}

async function syncNationwideDealers() {
  setIngestUiRunning(true);
  const syncBtn = qs("ingest-sync-dealers-btn");
  const originalText = syncBtn?.textContent || "Sync Dealers (Nationwide)";
  if (syncBtn) syncBtn.textContent = "Syncing dealers...";
  try {
    await fetchJson("/api/dealers/sync", { method: "POST", body: "{}" });
    await pollAdminState();
  } finally {
    if (syncBtn) syncBtn.textContent = originalText;
    setIngestUiRunning(false);
  }
}

async function syncModelCatalog() {
  setIngestUiRunning(true);
  const syncBtn = qs("ingest-refresh-catalog-btn");
  const originalText = syncBtn?.textContent || "Sync Model Catalog";
  if (syncBtn) syncBtn.textContent = "Syncing catalog...";
  try {
    await fetchJson("/api/catalog/sync", {
      method: "POST",
      body: JSON.stringify(getIngestSettingsPayload({ forCatalogSync: true })),
    });
    await loadCatalogModels();
    await pollAdminState();
  } finally {
    if (syncBtn) syncBtn.textContent = originalText;
    setIngestUiRunning(false);
  }
}

async function startDealerVehicleRefresh({ allModels = false } = {}) {
  const payload = getIngestSettingsPayload();
  payload.all_models = allModels;
  payload.distance = 1;
  if (!allModels) {
    payload.model_codes = Array.from(ingestUiState.selectedModelCodes);
    if (!payload.model_codes.length) {
      return;
    }
  }

  setIngestUiRunning(true);
  qs("ingest-progress-wrap")?.classList.remove("hidden");
  renderIngestProgress({
    status: "queued",
    job_type: "dealer_vehicle_refresh",
    message: "Starting dealer ZIP vehicle refresh...",
    percent: 0,
  });

  await fetchJson("/api/dealers/refresh-vehicles", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  scheduleAdminPoll(POLL_ACTIVE_MS);
}

async function startIngest({ allModels = false } = {}) {
  const payload = getIngestSettingsPayload();
  payload.all_models = allModels;
  if (!allModels) {
    payload.model_codes = Array.from(ingestUiState.selectedModelCodes);
    if (!payload.model_codes.length) {
      return;
    }
  }

  window.VIT?.persistSearchLocation?.(payload.zip_code, payload.distance);
  setIngestUiRunning(true);
  qs("ingest-progress-wrap")?.classList.remove("hidden");
  renderIngestProgress({
    status: "queued",
    job_type: "ingest",
    zip_code: payload.zip_code,
    distance: payload.distance,
    message: `Queued ingest near ZIP ${payload.zip_code} (${payload.distance} mi)...`,
    percent: 0,
  });

  await fetchJson("/api/ingest/start", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  scheduleAdminPoll(POLL_ACTIVE_MS);
}

function setupIngestHandlers() {
  qs("ingest-refresh-catalog-btn")?.addEventListener("click", () => {
    syncModelCatalog().catch((err) => alert(err.message));
  });
  qs("ingest-sync-dealers-btn")?.addEventListener("click", () => {
    syncNationwideDealers().catch((err) => alert(err.message));
  });
  qs("catalog-select-all-btn")?.addEventListener("click", selectAllCatalogModels);
  qs("catalog-select-missing-btn")?.addEventListener("click", selectMissingDataCatalogModels);
  qs("catalog-select-none-btn")?.addEventListener("click", selectNoneCatalogModels);
  qs("ingest-selected-btn")?.addEventListener("click", () => {
    if (ingestUiState.selectedModelCodes.size === 0) return;
    startIngest({ allModels: false }).catch((err) => alert(err.message));
  });
  qs("ingest-all-btn")?.addEventListener("click", () => {
    startIngest({ allModels: true }).catch((err) => alert(err.message));
  });
  qs("ingest-dealer-refresh-selected-btn")?.addEventListener("click", () => {
    if (ingestUiState.selectedModelCodes.size === 0) return;
    startDealerVehicleRefresh({ allModels: false }).catch((err) => alert(err.message));
  });
  qs("ingest-dealer-refresh-all-btn")?.addEventListener("click", () => {
    startDealerVehicleRefresh({ allModels: true }).catch((err) => alert(err.message));
  });
}

function renderOverview(payload) {
  const ingest = payload.ingest || {};
  renderIngestProgress(ingest);
  if (window.VIT?.isJobStatusActive?.(ingest.status)) {
    setIngestUiRunning(true);
  }

  renderWorkersPanel(payload.workers);

  const geocode = payload.geocode?.job || {};
  const geoStats = payload.geocode || {};
  renderStatusBlock(qs("admin-geocode-status"), "Dealer geocoding", geocode.status, [
    geocode.message || geoStats.remaining != null
      ? `${Number(geoStats.remaining || 0).toLocaleString()} dealer(s) remaining`
      : "No message",
    geoStats.geocoded != null && geoStats.dealers_in_inventory != null
      ? `${Number(geoStats.geocoded).toLocaleString()}/${Number(geoStats.dealers_in_inventory).toLocaleString()} fully geocoded`
      : null,
    geoStats.oem_provisional > 0
      ? `${Number(geoStats.oem_provisional).toLocaleString()} with OEM coords only (pending full geocode)`
      : null,
    geocode.processed > 0 && geocode.total > 0
      ? `${Number(geocode.processed).toLocaleString()}/${Number(geocode.total).toLocaleString()} processed this run`
      : null,
    geocode.current_dealer_cd ? `Current: ${geocode.current_dealer_cd}` : null,
    geocode.error ? `Error: ${geocode.error}` : null,
  ].filter(Boolean));

  const startBtn = qs("admin-geocode-start-btn");
  const cancelBtn = qs("admin-geocode-cancel-btn");
  const geocodeRunning = window.VIT?.isJobStatusActive?.(geocode.status);
  if (startBtn) {
    startBtn.disabled = false;
    startBtn.title = "";
  }
  if (cancelBtn) {
    cancelBtn.disabled = !geocodeRunning;
  }

  renderFailedGeocodeDealers(geoStats.failed_dealers || []);

  renderJobSummary(payload.summary || {});
  lastJobRuns = payload.recent_runs || [];
  lastLiveProgressMap = buildLiveProgressMap(payload);
  renderJobRuns(lastJobRuns, lastLiveProgressMap);
  const updated = qs("admin-last-updated");
  if (updated) {
    updated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }
}

function formatFailedGeocodeQuery(raw) {
  if (!raw) return "<em class=\"muted\">no queries recorded</em>";
  const parts = String(raw)
    .split("|")
    .map((s) => s.trim())
    .filter(Boolean);
  if (!parts.length) return "<em class=\"muted\">no queries recorded</em>";
  return parts.map((q) => `<code>${escapeHtml(q)}</code>`).join("<br>");
}

function renderFailedGeocodeDealers(rows) {
  const container = qs("admin-geocode-failed");
  if (!container) return;
  if (!Array.isArray(rows) || rows.length === 0) {
    container.innerHTML = "";
    return;
  }
  const bodyRows = rows
    .map((row) => {
      const website = row.dealer_website
        ? `<a href="${escapeHtml(row.dealer_website)}" target="_blank" rel="noreferrer noopener">${escapeHtml(row.dealer_website)}</a>`
        : "<span class=\"muted\">—</span>";
      const when = row.geocoded_at
        ? escapeHtml(row.geocoded_at)
        : "<span class=\"muted\">—</span>";
      return `<tr>
          <td>${escapeHtml(row.dealer_cd)}</td>
          <td>${escapeHtml(row.dealer_name)}</td>
          <td>${website}</td>
          <td class="admin-geocode-failed-query">${formatFailedGeocodeQuery(row.query_text)}</td>
          <td>${when}</td>
        </tr>`;
    })
    .join("");
  container.innerHTML = `
    <details class="admin-geocode-failed-details" open>
      <summary>Failed geocode attempts (${rows.length.toLocaleString()})</summary>
      <table class="admin-geocode-failed-table">
        <thead>
          <tr>
            <th>Dealer code</th>
            <th>Name</th>
            <th>Website</th>
            <th>Queries tried</th>
            <th>Last attempt</th>
          </tr>
        </thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </details>
  `;
}

function renderJobSummary(summary) {
  const container = qs("admin-job-summary");
  if (!container) return;
  const entries = Object.entries(summary);
  if (!entries.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = entries
    .map(([jobType, stats]) => {
      const avg =
        stats.avg_duration_sec != null ? formatDurationSec(stats.avg_duration_sec) : "—";
      return `<span class="job-runs-summary-chip"><strong>${formatJobType(jobType)}</strong>: ${stats.count} run(s), avg ${avg}</span>`;
    })
    .join("");
}

function bindJobRunExpandHandlers() {
  const tbody = qs("admin-job-runs-tbody");
  if (!tbody) return;
  tbody.querySelectorAll(".job-run-expand-btn").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.stopPropagation();
      const id = Number(btn.dataset.jobRunId);
      if (!Number.isFinite(id)) return;
      if (expandedJobRunIds.has(id)) {
        expandedJobRunIds.delete(id);
      } else {
        expandedJobRunIds.add(id);
      }
      renderJobRuns(lastJobRuns, lastLiveProgressMap);
    });
  });
}

function renderJobRuns(runs, liveProgressMap = {}) {
  const tbody = qs("admin-job-runs-tbody");
  if (!tbody) return;
  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="job-runs-empty">No job runs yet.</td></tr>';
    return;
  }
  tbody.innerHTML = runs
    .flatMap((run) => {
      const statusClass = String(run.status || "unknown").toLowerCase();
      const id = run.job_run_id;
      const expanded = expandedJobRunIds.has(id);
      const progress = jobRunProgressData(run, liveProgressMap[id]);
      const expandLabel = expanded ? "Collapse job details" : "Expand job details";
      const mainRow = `
        <tr class="job-run-row ${expanded ? "is-expanded" : ""}" data-job-run-id="${id}">
          <td class="job-run-id-cell">
            <button
              type="button"
              class="job-run-expand-btn"
              data-job-run-id="${id}"
              aria-expanded="${expanded ? "true" : "false"}"
              aria-label="${expandLabel}"
              title="${expandLabel}"
            >${expanded ? "▾" : "▸"}</button>
            ${id}
          </td>
          <td>${formatJobType(run.job_type)}</td>
          <td><span class="job-run-status ${statusClass}">${run.status || "unknown"}</span></td>
          <td>${renderJobRunProgressBar(progress)}</td>
          <td>${formatStartedAt(run.started_at)}</td>
          <td>${formatDurationSec(run.duration_sec)}</td>
          <td>${run.trigger_source || "—"}</td>
          <td>${summarizeResult(run)}</td>
        </tr>
      `;
      if (!expanded) {
        return [mainRow];
      }
      return [
        mainRow,
        `
        <tr class="job-run-detail-row" data-job-run-id="${id}">
          <td colspan="8">
            <div class="job-run-detail-panel">
              ${formatParamsDetail(run)}
            </div>
          </td>
        </tr>
      `,
      ];
    })
    .join("");
  bindJobRunExpandHandlers();
}

async function refreshOverview() {
  const payload = await fetchJson("/api/admin/overview");
  renderOverview(payload);
}

async function repairWorkerQueues() {
  const btn = qs("admin-workers-repair-btn");
  if (btn) btn.disabled = true;
  try {
    const payload = await fetchJson("/api/admin/workers/repair", { method: "POST", body: "{}" });
    if (payload.workers) {
      renderWorkersPanel(payload.workers);
    }
    const removed = Number(payload.repair?.removed_workers || 0);
    const reclaimed = Number(payload.repair?.reclaimed_jobs || 0);
    if (removed || reclaimed) {
      alert(`Repaired queues: removed ${removed} stale worker registration(s), reclaimed ${reclaimed} stuck job(s).`);
    }
    await refreshOverview();
  } catch (err) {
    alert(err.message || "Failed to repair worker queues.");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function startGeocodeJob() {
  const btn = qs("admin-geocode-start-btn");
  if (btn) btn.disabled = true;
  try {
    await fetchJson("/api/admin/geocode/start", { method: "POST", body: "{}" });
    await refreshOverview();
  } catch (err) {
    alert(err.message || "Failed to start geocode job.");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function cancelGeocodeJob() {
  const btn = qs("admin-geocode-cancel-btn");
  if (btn) btn.disabled = true;
  try {
    await fetchJson("/api/admin/geocode/cancel", { method: "POST", body: "{}" });
    await refreshOverview();
  } catch (err) {
    alert(err.message || "Failed to cancel geocode job.");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function resetOemGeocode() {
  const confirmed = confirm(
    "Delete all OEM-provisional dealer coordinates?\n\n" +
      "Bulk geocoding will replace them with real coordinates from website / Photon / Nominatim.",
  );
  if (!confirmed) return;
  const btn = qs("admin-geocode-reset-oem-btn");
  if (btn) btn.disabled = true;
  try {
    const payload = await fetchJson("/api/admin/geocode/reset-oem", { method: "POST", body: "{}" });
    const removed = Number(payload?.removed || 0);
    alert(`Removed ${removed} OEM-provisional coord row(s). Run "Start geocode" to re-populate.`);
    await refreshOverview();
  } catch (err) {
    alert(err.message || "Failed to reset OEM coords.");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function clearGeoCache() {
  const confirmed = confirm(
    "Wipe the ENTIRE dealer_geo_cache table?\n\n" +
      "Every dealer coordinate will be removed. Run \"Start geocode\" afterwards to re-populate.",
  );
  if (!confirmed) return;
  const btn = qs("admin-geocode-clear-cache-btn");
  if (btn) btn.disabled = true;
  try {
    const payload = await fetchJson("/api/admin/geocode/clear-cache", { method: "POST", body: "{}" });
    const removed = Number(payload?.removed || 0);
    alert(`Cleared ${removed} dealer_geo_cache row(s). Run "Start geocode" to re-populate.`);
    await refreshOverview();
  } catch (err) {
    alert(err.message || "Failed to clear geo cache.");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function setupAdmin() {
  if (window.VIT?.initMakeSwitcher) {
    try {
      await window.VIT.initMakeSwitcher("make-select");
      applyMakeUi();
    } catch (err) {
      console.warn("[make]", err);
    }
  }
  setupIngestHandlers();
  qs("admin-geocode-start-btn")?.addEventListener("click", () => {
    startGeocodeJob().catch((err) => console.error(err));
  });
  qs("admin-geocode-cancel-btn")?.addEventListener("click", () => {
    cancelGeocodeJob().catch((err) => console.error(err));
  });
  qs("admin-geocode-reset-oem-btn")?.addEventListener("click", () => {
    resetOemGeocode().catch((err) => console.error(err));
  });
  qs("admin-geocode-clear-cache-btn")?.addEventListener("click", () => {
    clearGeoCache().catch((err) => console.error(err));
  });
  qs("admin-workers-repair-btn")?.addEventListener("click", () => {
    repairWorkerQueues().catch((err) => console.error(err));
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      scheduleAdminPoll(POLL_IDLE_MS);
    }
  });

  try {
    await loadCatalogModels();
    await pollAdminState();
  } catch (err) {
    console.error(err);
    alert(err.message || "Failed to load admin page.");
  }
}

window.addEventListener("load", () => {
  setupAdmin().catch((err) => console.error(err));
});
