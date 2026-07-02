const qs = (id) => document.getElementById(id);

const DEFAULT_SEARCH_ZIP = "95132";
const DEFAULT_SEARCH_RADIUS_MILES = 50;

function searchZipStorageKey() {
  const make = window.VIT?.currentMake || "toyota";
  return `vit-search-zip:${make}`;
}

function searchRadiusStorageKey() {
  const make = window.VIT?.currentMake || "toyota";
  return `vit-search-radius:${make}`;
}

function readStoredSearchZip() {
  try {
    const make = window.VIT?.currentMake || "toyota";
    const key = searchZipStorageKey();
    let value = localStorage.getItem(key);
    if (!value && make === "toyota") {
      value = localStorage.getItem("toyota-search-zip");
    }
    return value;
  } catch (_err) {
    return null;
  }
}

function readStoredSearchRadius() {
  try {
    return localStorage.getItem(searchRadiusStorageKey());
  } catch (_err) {
    return null;
  }
}

function defaultSearchZip() {
  return window.VIT?.getIngestDefaults?.(window.VIT?.currentMake)?.zip || DEFAULT_SEARCH_ZIP;
}
let userReferenceCoords = null;
let userLocationRequestStarted = false;

function getUserReferenceCoords() {
  return userReferenceCoords;
}

function startUserLocationWatch() {
  if (userLocationRequestStarted || !navigator.geolocation) {
    return;
  }
  userLocationRequestStarted = true;
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      userReferenceCoords = {
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
      };
      loadFilters({ silent: true }).catch((err) => console.warn("[location]", err.message));
    },
    () => {},
    { enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }
  );
}

function normalizeZipCode(value) {
  const digits = String(value || "").replace(/\D/g, "");
  return digits.length >= 5 ? digits.slice(0, 5) : "";
}

function clearZipRadiusFilters() {
  const zipEl = qs("search-zip-code");
  const distanceEl = qs("distance-max-miles");
  if (zipEl) zipEl.value = "";
  if (distanceEl) distanceEl.value = "";
  try {
    localStorage.removeItem(searchZipStorageKey());
    localStorage.removeItem(searchRadiusStorageKey());
  } catch (_err) {
    // Ignore storage failures.
  }
}

function hasStateFilterSelected() {
  return selectedMultiValues(qs("state-codes")).length > 0;
}

function getLocationFilterParams() {
  const stateCodes = selectedMultiValues(qs("state-codes")).join(",");
  if (hasStateFilterSelected()) {
    return { stateCodes, searchZip: "", distanceMax: "" };
  }
  return {
    stateCodes,
    searchZip: normalizeZipCode(qs("search-zip-code")?.value.trim() || ""),
    distanceMax: qs("distance-max-miles")?.value.trim() || "",
  };
}

function applySearchLocation(zip, radiusMiles) {
  const zipEl = qs("search-zip-code");
  const distanceEl = qs("distance-max-miles");
  const ingestZipEl = qs("ingest-zip-code");
  const normalizedZip = normalizeZipCode(zip) || defaultSearchZip();
  const radius = Number(radiusMiles) > 0 ? Number(radiusMiles) : DEFAULT_SEARCH_RADIUS_MILES;
  if (zipEl) zipEl.value = normalizedZip;
  if (distanceEl) distanceEl.value = String(radius);
  if (ingestZipEl) ingestZipEl.value = normalizedZip;
  try {
    localStorage.setItem(searchZipStorageKey(), normalizedZip);
    localStorage.setItem(searchRadiusStorageKey(), String(radius));
  } catch (_err) {
    // Ignore storage failures (private mode, quota, etc.).
  }
}

function filtersStorageKey() {
  const make = window.VIT?.currentMake || document.body?.dataset?.make || "toyota";
  return `vit-filters:v1:${make}`;
}

function collectFilterState() {
  const state = {
    version: 1,
    series: getSeriesSelectedValues(),
    states: getStateSelectedValues(),
    facets: {},
    vinQuery: qs("vin-query")?.value.trim() || "",
    stockQuery: qs("stock-query")?.value.trim() || "",
    activeOnly: qs("active-only")?.checked !== false,
    searchZip: normalizeZipCode(qs("search-zip-code")?.value.trim() || ""),
    searchRadius: qs("distance-max-miles")?.value.trim() || "",
    histogram:
      histogramState.metric != null &&
      histogramState.min != null &&
      histogramState.max != null
        ? {
            metric: histogramState.metric,
            min: histogramState.min,
            max: histogramState.max,
          }
        : null,
    sort: { key: sortState.key, dir: sortState.dir },
  };
  for (const id of FILTER_MULTI_SELECT_IDS) {
    if (id === "state-codes") continue;
    state.facets[id] = [...getFacetSelectionSet(id)];
  }
  return state;
}

function applyStoredFilterState(saved) {
  if (!saved || saved.version !== 1) return false;

  seriesSelectedValues.clear();
  for (const value of saved.series || []) {
    if (value) seriesSelectedValues.add(String(value));
  }

  stateSelectedValues.clear();
  for (const value of saved.states || []) {
    if (value) stateSelectedValues.add(String(value));
  }

  for (const id of FILTER_MULTI_SELECT_IDS) {
    if (id === "state-codes") continue;
    const values = (saved.facets && saved.facets[id]) || [];
    facetSelectedValues.set(id, new Set(values.map(String).filter(Boolean)));
  }

  const vinQueryEl = qs("vin-query");
  const stockQueryEl = qs("stock-query");
  const activeOnlyEl = qs("active-only");
  if (vinQueryEl) vinQueryEl.value = saved.vinQuery || "";
  if (stockQueryEl) stockQueryEl.value = saved.stockQuery || "";
  if (activeOnlyEl) activeOnlyEl.checked = saved.activeOnly !== false;

  const hasStates = (saved.states || []).length > 0;
  if (hasStates) {
    const zipEl = qs("search-zip-code");
    const distanceEl = qs("distance-max-miles");
    if (zipEl) zipEl.value = "";
    if (distanceEl) distanceEl.value = "";
  } else if (saved.searchZip || readStoredSearchZip()) {
    const zip = saved.searchZip || readStoredSearchZip() || "";
    const radius =
      saved.searchRadius ||
      readStoredSearchRadius() ||
      String(DEFAULT_SEARCH_RADIUS_MILES);
    applySearchLocation(zip, radius);
  } else {
    clearZipRadiusFilters();
  }

  if (
    saved.histogram &&
    saved.histogram.metric != null &&
    saved.histogram.min != null &&
    saved.histogram.max != null
  ) {
    histogramState.metric = saved.histogram.metric;
    histogramState.min = saved.histogram.min;
    histogramState.max = saved.histogram.max;
  } else {
    histogramState.metric = null;
    histogramState.min = null;
    histogramState.max = null;
  }

  if (saved.sort && saved.sort.key) {
    sortState.key = saved.sort.key;
    sortState.dir = saved.sort.dir === "desc" ? "desc" : "asc";
  }
  return true;
}

let filterSaveTimer = null;
function scheduleFilterStateSave() {
  if (filterSaveTimer) clearTimeout(filterSaveTimer);
  filterSaveTimer = setTimeout(saveFilterState, 300);
}

function saveFilterState() {
  try {
    localStorage.setItem(filtersStorageKey(), JSON.stringify(collectFilterState()));
  } catch (_err) {
    // Ignore storage failures.
  }
}

function restoreFilterState() {
  try {
    const raw = localStorage.getItem(filtersStorageKey());
    if (!raw) {
      const zip = readStoredSearchZip();
      if (zip) {
        applySearchLocation(
          zip,
          readStoredSearchRadius() || DEFAULT_SEARCH_RADIUS_MILES
        );
      }
      return false;
    }
    return applyStoredFilterState(JSON.parse(raw));
  } catch (_err) {
    return false;
  }
}

window.VIT = window.VIT || {};
window.VIT.saveFilterState = saveFilterState;

async function initializeSearchLocation() {
  const restored = restoreFilterState();
  if (typeof renderInventoryTableHeader === "function") {
    renderInventoryTableHeader();
  }
  const locationMetaEl = qs("location-filter-meta");
  if (locationMetaEl && !restored) {
    locationMetaEl.textContent =
      "No location filter applied. Set ZIP + distance or pick states to narrow results.";
  }
}

const loadingState = {
  table: 0,
  analytics: 0,
};

const LOADING_PANELS = {
  table: {
    overlayId: "table-loading",
    panelSelector: ".inventory-table-scroll",
  },
  analytics: {
    overlayId: "analytics-loading",
    panelId: "analytics-panel",
  },
  filters: {
    overlayId: "filters-loading",
    panelSelector: ".filters",
  },
  ingest: {
    overlayId: "ingest-loading",
    panelId: "ingest-panel",
  },
};

function setPanelLoading(kind, active) {
  if (active) {
    loadingState[kind] += 1;
  } else {
    loadingState[kind] = Math.max(0, loadingState[kind] - 1);
  }

  const config = LOADING_PANELS[kind];
  if (!config) return;

  const overlay = qs(config.overlayId);
  const panel = config.panelId ? qs(config.panelId) : document.querySelector(config.panelSelector);
  const isLoading = loadingState[kind] > 0;

  if (overlay) {
    overlay.classList.toggle("hidden", !isLoading);
    overlay.setAttribute("aria-hidden", isLoading ? "false" : "true");
  }
  if (panel) {
    panel.classList.toggle("is-loading", isLoading);
  }
}

async function withPanelLoading(kind, task) {
  setPanelLoading(kind, true);
  try {
    return await task();
  } finally {
    setPanelLoading(kind, false);
  }
}

let currentItems = [];
let analyticsState = null;
let filterLoadToken = 0;
let inventoryLoadToken = 0;
let filterReloadTimer = null;
const paginationState = {
  page: 1,
  pageSize: 20,
  totalCount: 0,
  pageCount: 0,
};
const sortState = {
  key: "advertized_price",
  dir: "asc",
};
const histogramState = {
  metric: null,
  min: null,
  max: null,
};
const FILTER_MULTI_SELECT_IDS = [
  "model-values",
  "exterior-color-values",
  "interior-color-values",
  "drivetrain-codes",
  "stage-codes",
  "option-codes",
  "dealer-values",
  "state-codes",
];
const FILTER_PILL_IDS = {
  "series-values": "series-selected-pills",
  "dealer-values": "dealer-selected-pills",
  "state-codes": "state-selected-pills",
  "model-values": "model-selected-pills",
  "exterior-color-values": "exterior-color-selected-pills",
  "interior-color-values": "interior-color-selected-pills",
  "drivetrain-codes": "drivetrain-selected-pills",
  "stage-codes": "stage-selected-pills",
  "option-codes": "option-selected-pills",
};
const FILTER_FACET_STYLES = {
  "model-values": "default",
  "drivetrain-codes": "drivetrain",
  "stage-codes": "stage",
  "option-codes": "option",
};
const FACET_BUTTON_LIST_IDS = new Set([
  "model-values",
  "drivetrain-codes",
  "stage-codes",
  "option-codes",
]);
let dealerFilterItems = [];
let seriesFilterItems = [];
const seriesSelectedValues = new Set();
let stateFilterItems = [];
const stateSelectedValues = new Set();
const facetSelectedValues = new Map();
const facetFilterItems = new Map();
const facetItemCache = {};
let catalogModels = [];
let ingestPollTimer = null;
const ingestUiState = {
  running: false,
  selectedModelCodes: new Set(),
  lastPersistedRefresh: 0,
  watchedIngestSession: false,
};

let geocodePollTimer = null;
const geocodeUiState = {
  lastGeocodedRefresh: 0,
};

function isIngestRunning() {
  return ingestUiState.running;
}

function renderAnalyticsPaused() {
  const message = "Analytics paused while inventory ingest is running.";
  const statsEl = qs("selection-stats");
  if (statsEl) {
    statsEl.innerHTML = `
      <div class="stat-chip stat-chip-paused">
        <div class="label">Analytics</div>
        <div class="value">Paused during ingest</div>
      </div>
    `;
  }

  const distributionEl = qs("price-distribution");
  if (distributionEl) {
    distributionEl.innerHTML = `<h3>Price Distribution</h3><div class="chart-empty">${escapeHtml(message)}</div>`;
  }

  const insightsEl = qs("pricing-insights");
  if (insightsEl) {
    insightsEl.innerHTML = `<h3>Pricing Insights</h3><div class="chart-empty">${escapeHtml(message)}</div>`;
  }

  const geoEl = qs("inventory-geo-map");
  if (geoEl) {
    geoEl.innerHTML = `<h3>Geography &amp; MSRP Analytics</h3><div class="chart-empty">${escapeHtml(message)}</div>`;
  }
}

function hydrateImages(root) {
  if (window.VIT?.hydrateImages) {
    VIT.hydrateImages(root);
    return;
  }
  if (window.VitImageCache?.hydrate) {
    VitImageCache.hydrate(root);
  }
}

function scheduleHydrateImages(root) {
  if (window.VIT?.scheduleHydrateImages) {
    VIT.scheduleHydrateImages(root);
    return;
  }
  if (!root) return;
  const run = () => hydrateImages(root);
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 2500 });
  } else {
    setTimeout(run, 16);
  }
}

let analyticsRefreshTimer = null;
let analyticsRefreshToken = 0;

function scheduleAnalyticsRefresh({ delayMs = 2000 } = {}) {
  if (analyticsRefreshTimer) {
    clearTimeout(analyticsRefreshTimer);
  }
  showAnalyticsLoadingPlaceholder();
  analyticsRefreshTimer = setTimeout(() => {
    analyticsRefreshTimer = null;
    refreshAnalyticsPanels().catch((err) => console.warn("[analytics]", err.message));
  }, delayMs);
}

function showAnalyticsLoadingPlaceholder() {
  if (analyticsState || isIngestRunning()) {
    return;
  }
  const statsEl = qs("selection-stats");
  if (statsEl && !statsEl.textContent.trim()) {
    statsEl.innerHTML = `
      <div class="stat-chip stat-chip-paused">
        <div class="label">Analytics</div>
        <div class="value">Loading…</div>
      </div>
    `;
  }
  const geoEl = qs("inventory-geo-map");
  if (geoEl && !geoEl.querySelector(".geo-insights-grid") && !geoEl.querySelector(".chart-empty")) {
    geoEl.innerHTML = `
      <h3>Geography &amp; MSRP Analytics</h3>
      <div class="chart-empty">Loading geography…</div>
    `;
  }
}

async function refreshAnalyticsPanels() {
  if (isIngestRunning()) {
    renderAnalyticsPaused();
    return;
  }
  const token = ++analyticsRefreshToken;
  await Promise.all([loadAnalytics(), loadGeoMap()]);
  if (token !== analyticsRefreshToken) {
    return;
  }
}

function cachedImgTag(url, alt = "", className = "") {
  if (!url) return "";
  if (window.VIT?.cachedImgTag) {
    return VIT.cachedImgTag(url, alt, className);
  }
  if (window.VitImageCache?.imgTag) {
    return VitImageCache.imgTag(url, alt, className);
  }
  const cls = className ? ` class="${escapeHtml(className)}"` : "";
  return `<img src="${escapeHtml(url)}" alt="${escapeHtml(alt)}" loading="lazy" decoding="async"${cls} />`;
}

function setOptions(selectEl, values, includeAll = true) {
  selectEl.innerHTML = "";
  if (includeAll) {
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "All";
    selectEl.appendChild(all);
  }
  values.forEach((value) => {
    const opt = document.createElement("option");
    if (typeof value === "string") {
      opt.value = value;
      opt.textContent = value;
    } else {
      const code =
        value.option_cd ||
        value.allocation_stage_code ||
        value.exterior_color_name ||
        value.interior_color_name ||
        value.value ||
        "";
      const name = plainTextFromHtml(
        value.marketing_name ||
          value.allocation_stage_label ||
          value.label ||
          value.exterior_color_name ||
          value.interior_color_name ||
          ""
      );
      const count = value.vehicle_count ?? "";
      opt.value = code;
      const textBase = value.option_cd || value.allocation_stage_code ? `${code}${name ? " - " + name : ""}` : name;
      opt.textContent = `${textBase}${count !== "" ? ` (${count})` : ""}`;
    }
    selectEl.appendChild(opt);
  });
}

function formatFacetLabel(item, style = "default") {
  const count =
    item.vehicle_count != null && item.vehicle_count !== ""
      ? ` (${Number(item.vehicle_count).toLocaleString()})`
      : "";
  if (style === "stage") {
    const code = item.value || item.allocation_stage_code || "";
    const name = item.label || item.allocation_stage_label || "";
    return `${code}${name ? " - " + name : ""}${count}`;
  }
  if (style === "drivetrain") {
    const code = item.value || item.drivetrain_code || "";
    const name = item.label || item.drivetrain_title || "";
    return `${code}${name ? " - " + name : ""}${count}`;
  }
  if (style === "option") {
    const code = item.value || item.option_cd || "";
    const name = plainTextFromHtml(item.label || item.marketing_name || "");
    return `${code}${name ? " — " + name : ""}${count}`;
  }
  return `${item.label || item.value || ""}${count}`;
}

function sortDealerFilterItems(items) {
  return [...(items || [])].sort((a, b) => {
    const aAvailable = a.available !== false ? 0 : 1;
    const bAvailable = b.available !== false ? 0 : 1;
    if (aAvailable !== bAvailable) return aAvailable - bAvailable;

    const aDist = Number(a.distance_miles);
    const bDist = Number(b.distance_miles);
    const aHasDist = Number.isFinite(aDist);
    const bHasDist = Number.isFinite(bDist);
    if (aHasDist && bHasDist && aDist !== bDist) {
      return aDist - bDist;
    }
    if (aHasDist !== bHasDist) {
      return aHasDist ? -1 : 1;
    }

    const aLabel = String(a.label || a.value || "");
    const bLabel = String(b.label || b.value || "");
    return aLabel.localeCompare(bLabel);
  });
}

function sortFacetItems(items) {
  return [...(items || [])].sort((a, b) => {
    const aAvailable = a.available !== false ? 0 : 1;
    const bAvailable = b.available !== false ? 0 : 1;
    if (aAvailable !== bAvailable) return aAvailable - bAvailable;
    const aCount = Number(a.vehicle_count ?? 0);
    const bCount = Number(b.vehicle_count ?? 0);
    if (bCount !== aCount) return bCount - aCount;
    const aLabel = String(a.label || a.value || "");
    const bLabel = String(b.label || b.value || "");
    return aLabel.localeCompare(bLabel);
  });
}

function getFacetItemValue(item) {
  return (
    item.value ||
    item.series_code ||
    item.dealer_cd ||
    item.model_marketing_name ||
    item.exterior_color_name ||
    item.interior_color_name ||
    item.option_cd ||
    ""
  );
}

function resolveFilterLabel(filterId, value) {
  if (filterId === "series-values") {
    const item = seriesFilterItems.find((entry) => getFacetItemValue(entry) === value);
    return seriesItemLabel(item || { series_code: value, series_name: value });
  }
  if (filterId === "state-codes") {
    const item = stateFilterItems.find((entry) => getFacetItemValue(entry) === value);
    return stateItemLabel(item || { value, label: value });
  }
  if (filterId === "dealer-values") {
    const item = dealerFilterItems.find((entry) => getFacetItemValue(entry) === value);
    const name = item?.label || item?.dealer_marketing_name || value;
    return name === value ? value : `${name} (${value})`;
  }
  const cached = facetItemCache[filterId] || [];
  const item = cached.find((entry) => getFacetItemValue(entry) === value);
  if (item) {
    return formatFacetLabel(item, FILTER_FACET_STYLES[filterId] || "default");
  }
  return value;
}

function renderFilterSelectedPills(filterId) {
  const pillsId = FILTER_PILL_IDS[filterId];
  const container = qs(filterId);
  const pillsEl = pillsId ? qs(pillsId) : null;
  if (!container || !pillsEl) return;

  const selected = selectedMultiValues(container);
  pillsEl.innerHTML = "";
  if (!selected.length) {
    pillsEl.classList.add("hidden");
    return;
  }
  pillsEl.classList.remove("hidden");

  for (const value of selected) {
    const label = resolveFilterLabel(filterId, value);
    const pill = document.createElement("span");
    pill.className = "filter-pill";
    pill.dataset.value = value;

    const labelEl = document.createElement("span");
    labelEl.className = "filter-pill-label";
    const swatchInfo = facetColorSwatchInfo(filterId, value);
    if (swatchInfo) {
      labelEl.innerHTML = `${colorPreview(swatchInfo.hex, swatchInfo.swatchUrl)}<span>${escapeHtml(label)}</span>`;
    } else {
      labelEl.textContent = label;
    }

    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "filter-pill-remove";
    removeBtn.setAttribute("aria-label", `Remove ${label}`);
    removeBtn.textContent = "×";
    removeBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      deselectFilterValue(filterId, value);
    });

    pill.appendChild(labelEl);
    pill.appendChild(removeBtn);
    pillsEl.appendChild(pill);
  }
  if (filterId === "exterior-color-values" || filterId === "interior-color-values") {
    scheduleHydrateImages(pillsEl);
  }
}

function rerenderFilterList(filterId) {
  if (filterId === "series-values") {
    renderSeriesFilterList();
    return;
  }
  if (filterId === "state-codes") {
    renderStateFilterList();
    return;
  }
  if (filterId === "dealer-values") {
    renderDealerFilterList();
    return;
  }
  if (filterId === "exterior-color-values" || filterId === "interior-color-values") {
    const kind = filterId.includes("exterior") ? "exterior" : "interior";
    populateFacetedColorList(qs(filterId), facetItemCache[filterId] || [], kind);
    return;
  }
  if (FACET_BUTTON_LIST_IDS.has(filterId)) {
    renderFacetButtonList(filterId);
    return;
  }
  renderFilterSelectedPills(filterId);
}

function deselectFilterValue(filterId, value) {
  const container = qs(filterId);
  if (!container) return;

  if (filterId === "series-values") {
    seriesSelectedValues.delete(value);
  } else if (filterId === "state-codes") {
    stateSelectedValues.delete(value);
  } else {
    getFacetSelectionSet(filterId).delete(value);
  }

  rerenderFilterList(filterId);
  container.dispatchEvent(new Event("change"));
}

function getFacetSelectionSet(selectId) {
  if (!selectId) return new Set();
  if (!facetSelectedValues.has(selectId)) {
    facetSelectedValues.set(selectId, new Set());
  }
  return facetSelectedValues.get(selectId);
}

function clearFacetSelectionSet(selectId) {
  facetSelectedValues.set(selectId, new Set());
}

function populateFacetButtonList(filterId, items) {
  facetFilterItems.set(filterId, items || []);
  facetItemCache[filterId] = items || [];
  renderFacetButtonList(filterId);
}

function renderFacetButtonList(filterId) {
  const container = qs(filterId);
  if (!container) return;
  const style = FILTER_FACET_STYLES[filterId] || "default";
  ensureFacetButtonListReady(filterId, container);
  const preserved = getFacetSelectionSet(filterId);
  const items = facetFilterItems.get(filterId) || [];
  const filtered = sortFacetItems([...items]);
  const itemValues = new Set();

  container.innerHTML = "";
  if (!filtered.length && preserved.size === 0) {
    container.innerHTML = `<div class="series-filter-empty">No options available.</div>`;
  } else {
    for (const item of filtered) {
      const value = getFacetItemValue(item);
      if (!value) continue;
      itemValues.add(value);
      appendFacetButtonOption(container, {
        value,
        label: formatFacetLabel(item, style),
        isSelected: preserved.has(value),
        isAvailable: item.available !== false,
        count: item.vehicle_count,
      });
    }
    for (const value of preserved) {
      if (itemValues.has(value)) continue;
      appendFacetButtonOption(container, {
        value,
        label: resolveFilterLabel(filterId, value),
        isSelected: true,
        isAvailable: true,
        count: null,
      });
    }
  }

  updateFilterLabelState(container, items);
  renderFilterSelectedPills(filterId);
}

function appendFacetButtonOption(container, { value, label, isSelected, isAvailable, count }) {
  const countText =
    count != null ? ` · ${Number(count).toLocaleString()}` : "";
  const option = document.createElement("button");
  option.type = "button";
  option.className = "series-filter-option";
  option.dataset.value = value;
  option.setAttribute("role", "option");
  option.setAttribute("aria-selected", isSelected ? "true" : "false");
  if (isSelected) {
    option.classList.add("is-selected");
  }
  if (!isAvailable && !isSelected) {
    option.classList.add("is-unavailable");
    option.disabled = true;
  }
  option.innerHTML = `<span class="series-filter-label">${escapeHtml(label)}${escapeHtml(countText)}${!isAvailable && !isSelected ? " — unavailable" : ""}</span>`;
  container.appendChild(option);
}

function ensureFacetButtonListReady(filterId, containerEl) {
  if (!containerEl || containerEl.dataset.facetButtonReady === "1") {
    return;
  }
  containerEl.dataset.facetButtonReady = "1";
  containerEl.addEventListener("click", (event) => {
    const option = event.target.closest(".series-filter-option");
    if (!option || !containerEl.contains(option) || option.disabled) {
      return;
    }
    option.classList.toggle("is-selected");
    option.setAttribute("aria-selected", option.classList.contains("is-selected") ? "true" : "false");
    const value = option.dataset.value;
    const selected = getFacetSelectionSet(filterId);
    if (value) {
      if (option.classList.contains("is-selected")) {
        selected.add(value);
      } else {
        selected.delete(value);
      }
    }
    renderFacetButtonList(filterId);
    containerEl.dispatchEvent(new Event("change"));
  });
}

function isFacetedFilterList(el) {
  return Boolean(
    el?.classList?.contains("color-filter-list") ||
      el?.classList?.contains("dealer-filter-list") ||
      el?.classList?.contains("series-filter-list") ||
      el?.classList?.contains("facet-filter-list")
  );
}

function isColorFilterList(el) {
  return isFacetedFilterList(el);
}

function populateFacetedColorList(containerEl, items, kind = "exterior") {
  if (!containerEl) return;
  if (containerEl.id) {
    facetItemCache[containerEl.id] = items || [];
  }
  ensureColorFilterListReady(containerEl);
  const preserved = getFacetSelectionSet(containerEl.id);
  containerEl.innerHTML = "";

  for (const item of sortFacetItems(items)) {
    const value = item.value || item.exterior_color_name || item.interior_color_name || "";
    if (!value) continue;
    const isSelected = preserved.has(value);
    const isAvailable = item.available !== false;
    const option = document.createElement("button");
    option.type = "button";
    option.className = "color-filter-option";
    option.dataset.value = value;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", isSelected ? "true" : "false");
    if (isSelected) {
      option.classList.add("is-selected");
    }
    if (!isAvailable && !isSelected) {
      option.classList.add("is-unavailable");
      option.disabled = true;
    }

    const hex = kind === "exterior" ? item.exterior_color_hex : null;
    const swatch =
      kind === "exterior" ? item.exterior_color_swatch : item.interior_color_swatch;
    const label = formatFacetLabel(item, "default");
    option.innerHTML = `${colorPreview(hex, swatch)}<span class="color-filter-label">${escapeHtml(label)}${!isAvailable && !isSelected ? " — unavailable" : ""}</span>`;
    containerEl.appendChild(option);
  }

  for (const value of preserved) {
    if (items.some((item) => getFacetItemValue(item) === value)) continue;
    const option = document.createElement("button");
    option.type = "button";
    option.className = "color-filter-option is-selected";
    option.dataset.value = value;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", "true");
    option.innerHTML = `<span class="color-filter-label">${escapeHtml(resolveFilterLabel(containerEl.id, value))}</span>`;
    containerEl.appendChild(option);
  }

  updateFilterLabelState(containerEl, items || []);
  if (containerEl.id) {
    renderFilterSelectedPills(containerEl.id);
  }
  scheduleHydrateImages(containerEl);
}

function ensureColorFilterListReady(containerEl) {
  if (!containerEl || containerEl.dataset.colorFilterReady === "1") {
    return;
  }
  containerEl.dataset.colorFilterReady = "1";
  containerEl.addEventListener("click", (event) => {
    const option = event.target.closest(".color-filter-option");
    if (!option || !containerEl.contains(option) || option.disabled) {
      return;
    }
    option.classList.toggle("is-selected");
    option.setAttribute("aria-selected", option.classList.contains("is-selected") ? "true" : "false");
    const value = option.dataset.value;
    const selected = getFacetSelectionSet(containerEl.id);
    if (value) {
      if (option.classList.contains("is-selected")) {
        selected.add(value);
      } else {
        selected.delete(value);
      }
    }
    renderFilterSelectedPills(containerEl.id);
    containerEl.dispatchEvent(new Event("change"));
  });
}

function dealerMatchesSearch(item, query) {
  if (!query) return true;
  const needle = query.toLowerCase();
  const label = String(item.label || item.dealer_marketing_name || "").toLowerCase();
  const code = String(item.value || item.dealer_cd || "").toLowerCase();
  return label.includes(needle) || code.includes(needle);
}

function seriesMatchesSearch(item, query) {
  if (!query) return true;
  const needle = query.toLowerCase();
  const name = String(item.series_name || item.label || "").toLowerCase();
  const code = String(item.series_code || item.value || "").toLowerCase();
  return name.includes(needle) || code.includes(needle);
}

function getSeriesSelectedValues() {
  return [...seriesSelectedValues];
}

function seriesItemLabel(item) {
  const code = item.series_code || item.value || "";
  const name = item.series_name || item.label || code;
  return name === code ? code : `${name} (${code})`;
}

function populateSeriesFilterList(items) {
  seriesFilterItems = (items || []).map((item) => ({
    value: item.series_code,
    series_code: item.series_code,
    series_name: item.series_name,
    label: item.series_name,
    vehicle_count: item.vehicle_count,
    available: item.available,
  }));
  renderSeriesFilterList();
}

function renderSeriesFilterList() {
  const container = qs("series-values");
  if (!container) return;
  ensureSeriesFilterListReady(container);
  const preserved = new Set(seriesSelectedValues);
  const query = qs("series-search")?.value.trim() || "";
  const filtered = sortFacetItems(
    [...seriesFilterItems].filter((item) => seriesMatchesSearch(item, query))
  );

  container.innerHTML = "";
  if (!filtered.length) {
    container.innerHTML = `<div class="series-filter-empty">${query ? "No series match your search." : "No series available."}</div>`;
  } else {
    for (const item of filtered) {
      const value = item.series_code || item.value || "";
      if (!value) continue;
      const isSelected = preserved.has(value);
      const isAvailable = item.available !== false;
      const count =
        item.vehicle_count != null
          ? ` · ${Number(item.vehicle_count).toLocaleString()}`
          : "";
      const option = document.createElement("button");
      option.type = "button";
      option.className = "series-filter-option";
      option.dataset.value = value;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", isSelected ? "true" : "false");
      if (isSelected) {
        option.classList.add("is-selected");
      }
      if (!isAvailable && !isSelected) {
        option.classList.add("is-unavailable");
        option.disabled = true;
      }
      option.innerHTML = `<span class="series-filter-label">${escapeHtml(seriesItemLabel(item))}${escapeHtml(count)}${!isAvailable && !isSelected ? " — unavailable" : ""}</span>`;
      container.appendChild(option);
    }
  }

  const meta = qs("series-filter-meta");
  if (meta) {
    const selectedCount = preserved.size;
    const total = seriesFilterItems.length;
    const availableCount = seriesFilterItems.filter((item) => item.available !== false).length;
    if (selectedCount > 0) {
      meta.textContent = `${selectedCount} selected · ${filtered.length} shown of ${total}`;
    } else if (availableCount > 0 && availableCount < total) {
      meta.textContent = `${availableCount} of ${total} series match other filters`;
    } else {
      meta.textContent = `${total} series`;
    }
  }

  renderFilterSelectedPills("series-values");
  updateFilterLabelState(container, seriesFilterItems);
}

function ensureSeriesFilterListReady(containerEl) {
  if (!containerEl || containerEl.dataset.seriesFilterReady === "1") {
    return;
  }
  containerEl.dataset.seriesFilterReady = "1";
  containerEl.addEventListener("click", (event) => {
    const option = event.target.closest(".series-filter-option");
    if (!option || !containerEl.contains(option) || option.disabled) {
      return;
    }
    option.classList.toggle("is-selected");
    option.setAttribute("aria-selected", option.classList.contains("is-selected") ? "true" : "false");
    const value = option.dataset.value;
    if (value) {
      if (option.classList.contains("is-selected")) {
        seriesSelectedValues.add(value);
      } else {
        seriesSelectedValues.delete(value);
      }
    }
    renderSeriesFilterList();
    containerEl.dispatchEvent(new Event("change"));
  });
}

function getStateSelectedValues() {
  return [...stateSelectedValues];
}

function stateItemLabel(item) {
  const code = item.value || "";
  const name = item.label || code;
  return name === code ? code : `${name} (${code})`;
}

function populateStateFilterList(items) {
  stateFilterItems = (items || []).map((item) => ({
    value: item.value,
    label: item.label || item.value,
    vehicle_count: item.vehicle_count,
    available: item.available,
  }));
  facetItemCache["state-codes"] = stateFilterItems;
  renderStateFilterList();
}

function renderStateFilterList() {
  const container = qs("state-codes");
  if (!container) return;
  ensureStateFilterListReady(container);
  const preserved = new Set(stateSelectedValues);
  const filtered = sortFacetItems([...stateFilterItems]);
  const itemValues = new Set();

  container.innerHTML = "";
  if (!filtered.length && preserved.size === 0) {
    container.innerHTML = `<div class="series-filter-empty">No states available.</div>`;
  } else {
    for (const item of filtered) {
      const value = item.value || "";
      if (!value) continue;
      const isSelected = preserved.has(value);
      const isAvailable = item.available !== false;
      const count =
        item.vehicle_count != null
          ? ` · ${Number(item.vehicle_count).toLocaleString()}`
          : "";
      const option = document.createElement("button");
      option.type = "button";
      option.className = "series-filter-option";
      option.dataset.value = value;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", isSelected ? "true" : "false");
      if (isSelected) {
        option.classList.add("is-selected");
      }
      if (!isAvailable && !isSelected) {
        option.classList.add("is-unavailable");
        option.disabled = true;
      }
      option.innerHTML = `<span class="series-filter-label">${escapeHtml(stateItemLabel(item))}${escapeHtml(count)}${!isAvailable && !isSelected ? " — unavailable" : ""}</span>`;
      container.appendChild(option);
      itemValues.add(value);
    }
    for (const value of preserved) {
      if (itemValues.has(value)) continue;
      appendFacetButtonOption(container, {
        value,
        label: resolveFilterLabel("state-codes", value),
        isSelected: true,
        isAvailable: true,
        count: null,
      });
    }
  }

  const meta = qs("state-filter-meta");
  if (meta) {
    const selectedCount = preserved.size;
    const total = stateFilterItems.length;
    const availableCount = stateFilterItems.filter((item) => item.available !== false).length;
    if (selectedCount > 0) {
      meta.textContent = `${selectedCount} selected · ${filtered.length} shown of ${total}`;
    } else if (availableCount > 0 && availableCount < total) {
      meta.textContent = `${availableCount} of ${total} states match other filters`;
    } else {
      meta.textContent = `${total} states`;
    }
  }

  renderFilterSelectedPills("state-codes");
  updateFilterLabelState(container, stateFilterItems);
}

function ensureStateFilterListReady(containerEl) {
  if (!containerEl || containerEl.dataset.stateFilterReady === "1") {
    return;
  }
  containerEl.dataset.stateFilterReady = "1";
  containerEl.addEventListener("click", (event) => {
    const option = event.target.closest(".series-filter-option");
    if (!option || !containerEl.contains(option) || option.disabled) {
      return;
    }
    option.classList.toggle("is-selected");
    option.setAttribute("aria-selected", option.classList.contains("is-selected") ? "true" : "false");
    const value = option.dataset.value;
    if (value) {
      if (option.classList.contains("is-selected")) {
        stateSelectedValues.add(value);
      } else {
        stateSelectedValues.delete(value);
      }
    }
    renderStateFilterList();
    containerEl.dispatchEvent(new Event("change"));
  });
}

function populateDealerFilterList(items) {
  dealerFilterItems = items || [];
  renderDealerFilterList();
}

function renderDealerFilterList() {
  const container = qs("dealer-values");
  if (!container) return;
  ensureDealerFilterListReady(container);
  const preserved = getFacetSelectionSet("dealer-values");
  const query = qs("dealer-search")?.value.trim() || "";
  const filtered = sortDealerFilterItems(dealerFilterItems.filter((item) => dealerMatchesSearch(item, query)));
  const itemValues = new Set();

  container.innerHTML = "";
  if (!filtered.length && preserved.size === 0) {
    container.innerHTML = `<div class="dealer-filter-empty">${query ? "No dealers match your search." : "No dealers in the current selection."}</div>`;
  } else {
    for (const item of filtered) {
      const value = item.value || item.dealer_cd || "";
      if (!value) continue;
      itemValues.add(value);
      const isSelected = preserved.has(value);
      const isAvailable = item.available !== false;
      const option = document.createElement("button");
      option.type = "button";
      option.className = "dealer-filter-option";
      option.dataset.value = value;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", isSelected ? "true" : "false");
      if (isSelected) {
        option.classList.add("is-selected");
      }
      if (!isAvailable && !isSelected) {
        option.classList.add("is-unavailable");
        option.disabled = true;
      }
      const count =
        item.vehicle_count != null && item.vehicle_count !== ""
          ? ` (${Number(item.vehicle_count).toLocaleString()})`
          : "";
      const distance =
        item.distance_miles != null && Number.isFinite(Number(item.distance_miles))
          ? ` · ${Math.round(Number(item.distance_miles)).toLocaleString()} mi`
          : "";
      const name = item.label || value;
      option.innerHTML = `<span class="dealer-filter-label">${escapeHtml(`${name} (${value})${count}${distance}`)}${!isAvailable && !isSelected ? " — unavailable" : ""}</span>`;
      container.appendChild(option);
    }
    for (const value of preserved) {
      if (itemValues.has(value)) continue;
      const option = document.createElement("button");
      option.type = "button";
      option.className = "dealer-filter-option is-selected";
      option.dataset.value = value;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "true");
      option.innerHTML = `<span class="dealer-filter-label">${escapeHtml(resolveFilterLabel("dealer-values", value))}</span>`;
      container.appendChild(option);
    }
  }

  const meta = qs("dealer-filter-meta");
  if (meta) {
    const selectedCount = preserved.size;
    const visible = filtered.length;
    const total = dealerFilterItems.length;
    meta.textContent =
      query || selectedCount
        ? `${visible} shown of ${total}${selectedCount ? ` · ${selectedCount} selected` : ""}`
        : `${total} dealers`;
  }

  updateFilterLabelState(container, dealerFilterItems);
  renderFilterSelectedPills("dealer-values");
}

function ensureDealerFilterListReady(containerEl) {
  if (!containerEl || containerEl.dataset.dealerFilterReady === "1") {
    return;
  }
  containerEl.dataset.dealerFilterReady = "1";
  containerEl.addEventListener("click", (event) => {
    const option = event.target.closest(".dealer-filter-option");
    if (!option || !containerEl.contains(option) || option.disabled) {
      return;
    }
    option.classList.toggle("is-selected");
    option.setAttribute("aria-selected", option.classList.contains("is-selected") ? "true" : "false");
    const value = option.dataset.value;
    const selected = getFacetSelectionSet("dealer-values");
    if (value) {
      if (option.classList.contains("is-selected")) {
        selected.add(value);
      } else {
        selected.delete(value);
      }
    }
    renderDealerFilterList();
    containerEl.dispatchEvent(new Event("change"));
  });
}

function updateFilterLabelState(selectEl, items) {
  const label = selectEl?.closest("label");
  if (!label) return;
  label.classList.remove("filter-partial", "filter-empty");
  if (!items.length) {
    label.classList.add("filter-empty");
    return;
  }
  const availableCount = items.filter((item) => item.available !== false).length;
  if (availableCount === 0) {
    label.classList.add("filter-empty");
  } else if (availableCount < items.length) {
    label.classList.add("filter-partial");
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function plainTextFromHtml(value) {
  if (value == null || value === "") return "";
  const str = String(value);
  if (!/[<>]/.test(str)) return str.trim();
  try {
    const doc = new DOMParser().parseFromString(str, "text/html");
    const listItems = [...doc.querySelectorAll("li")];
    if (listItems.length) {
      return listItems
        .map((node) => (node.textContent || "").replace(/\s+/g, " ").trim())
        .filter(Boolean)
        .join("; ");
    }
    return (doc.body.textContent || "").replace(/\s+/g, " ").trim();
  } catch (_err) {
    return str.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  }
}

function formatOptionDetailBody(value) {
  if (!value) return "";
  const str = String(value);
  if (!/[<>]/.test(str)) return escapeHtml(str);
  try {
    const doc = new DOMParser().parseFromString(str, "text/html");
    const listItems = [...doc.querySelectorAll("li")]
      .map((node) => (node.textContent || "").replace(/\s+/g, " ").trim())
      .filter(Boolean);
    if (listItems.length) {
      return `<ul class="option-text-list">${listItems.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
    }
  } catch (_err) {
    /* fall through */
  }
  return escapeHtml(plainTextFromHtml(str));
}

function formatOptionLabel(code, name) {
  const cleanName = plainTextFromHtml(name);
  return cleanName ? `${code} — ${cleanName}` : code;
}

function formatDate(value) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMoney(value) {
  if (value == null) return "-";
  return `$${Number(value).toLocaleString()}`;
}

function computeNumericStats(items, field) {
  const values = items
    .map((item) => item[field])
    .filter((value) => value != null && !Number.isNaN(Number(value)))
    .map((value) => Number(value));
  if (!values.length) {
    return null;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const avg = values.reduce((acc, value) => acc + value, 0) / values.length;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  const median =
    sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
  return { min, max, avg, median, count: values.length };
}

function renderSelectionStats(analytics) {
  const statsEl = qs("selection-stats");
  if (!statsEl) return;

  const advertised = analytics?.advertized_price || null;
  const msrp = analytics?.total_msrp || null;
  const msrpComparison = analytics?.insights?.msrp_comparison || null;
  const msrpSummary = msrpComparison?.summary || null;
  const activeCount = analytics?.total_count ?? 0;

  const chips = [
    {
      label: "Vehicles In Selection",
      value: Number(activeCount).toLocaleString(),
    },
    {
      label: "Advertised Price (Min / Avg / Max)",
      value: advertised
        ? `${formatMoney(advertised.min)} / ${formatMoney(advertised.avg)} / ${formatMoney(advertised.max)}`
        : "-",
    },
    {
      label: "Advertised Price Median",
      value: advertised ? formatMoney(advertised.median) : "-",
    },
    {
      label: "MSRP (Min / Avg / Max)",
      value: msrp ? `${formatMoney(msrp.min)} / ${formatMoney(msrp.avg)} / ${formatMoney(msrp.max)}` : "-",
    },
    {
      label: "Avg Sale vs MSRP",
      value: msrpSummary
        ? `${formatDelta(msrpSummary.avg_delta)} (${formatDeltaPct(msrpSummary.avg_delta_pct).replace(/<[^>]+>/g, "")})`
        : "-",
      rawHtml: msrpSummary
        ? `${formatDelta(msrpSummary.avg_delta)} (${formatDeltaPct(msrpSummary.avg_delta_pct)})`
        : "-",
    },
    {
      label: "Below MSRP",
      value: msrpSummary
        ? `${Number(msrpSummary.below_msrp_count).toLocaleString()} (${Number(msrpSummary.below_msrp_pct).toFixed(0)}%)`
        : "-",
    },
    {
      label: "Rows With Advertised Price",
      value: advertised ? Number(advertised.count).toLocaleString() : "0",
    },
  ];

  statsEl.innerHTML = chips
    .map(
      (chip) => `
      <div class="stat-chip">
        <div class="label">${escapeHtml(chip.label)}</div>
        <div class="value">${chip.rawHtml ? chip.rawHtml : escapeHtml(chip.value)}</div>
      </div>
    `
    )
    .join("");
}

function renderDistributionChart(analytics) {
  const container = qs("price-distribution");
  if (!container) return;

  const histogram = analytics?.histogram;
  if (!histogram || !histogram.bins || histogram.bins.length < 3) {
    container.innerHTML = `
      <h3>Price Distribution</h3>
      <div class="chart-empty">Need at least 3 vehicles with price data in the current selection.</div>
    `;
    histogramState.metric = null;
    histogramState.min = null;
    histogramState.max = null;
    return;
  }

  const metricLabel = histogram.metric_label || "Advertised Price";
  const metricKey = histogram.metric || "advertized_price";
  if (histogramState.metric !== metricKey) {
    histogramState.metric = metricKey;
    histogramState.min = null;
    histogramState.max = null;
  }

  const min = histogram.min;
  const max = histogram.max;
  const mean = histogram.mean;
  const stdDev = histogram.std_dev || 1;
  const counts = histogram.bins.map((bin) => bin.count);
  const maxCount = histogram.max_bin_count || Math.max(...counts, 1);

  const width = 980;
  const height = 260;
  const left = 56;
  const right = 20;
  const top = 18;
  const bottom = 38;
  const plotW = width - left - right;
  const plotH = height - top - bottom;
  const barW = plotW / counts.length;
  const span = Math.max(max - min, 1);

  const bars = histogram.bins
    .map((bin, i) => {
      const isActive =
        histogramState.min != null &&
        histogramState.max != null &&
        Math.abs(histogramState.min - bin.start) < 1e-9 &&
        Math.abs(histogramState.max - bin.end) < 1e-9;
      const h = (bin.count / maxCount) * plotH;
      const x = left + i * barW + 1;
      const y = top + (plotH - h);
      const w = Math.max(barW - 2, 1);
      return `<rect class="hist-bar${isActive ? " active" : ""}" data-bin-start="${bin.start}" data-bin-end="${bin.end}" x="${x}" y="${y}" width="${w}" height="${h}" fill="#4f7f9f" opacity="0.75"></rect>`;
    })
    .join("");

  const normalPdf = (x) =>
    (1 / (stdDev * Math.sqrt(2 * Math.PI))) * Math.exp(-((x - mean) ** 2) / (2 * stdDev ** 2));
  const samples = 160;
  const points = [];
  const peak = normalPdf(mean);
  for (let i = 0; i <= samples; i += 1) {
    const t = i / samples;
    const xVal = min + span * t;
    const pdf = normalPdf(xVal);
    const scaled = peak > 0 ? pdf / peak : 0;
    const x = left + t * plotW;
    const y = top + (1 - scaled) * plotH;
    points.push(`${x},${y}`);
  }
  const curve = `<polyline fill="none" stroke="#cc7832" stroke-width="2.2" points="${points.join(" ")}"></polyline>`;

  const hasActiveFilter = histogramState.min != null && histogramState.max != null;
  const activeText = hasActiveFilter
    ? `Active bin: ${formatMoney(histogramState.min)} - ${formatMoney(histogramState.max)}`
    : "Click a histogram bar to filter the full selection by that bin.";

  container.innerHTML = `
    <h3>${escapeHtml(metricLabel)} Distribution (Full Selection)</h3>
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(metricLabel)} histogram with bell curve">
      <line x1="${left}" y1="${top + plotH}" x2="${width - right}" y2="${top + plotH}" stroke="#6a7076" stroke-width="1"></line>
      <line x1="${left}" y1="${top}" x2="${left}" y2="${top + plotH}" stroke="#6a7076" stroke-width="1"></line>
      ${bars}
      ${curve}
      <text x="${left}" y="${height - 14}" fill="#9aa6b2" font-size="11">${escapeHtml(formatMoney(min))}</text>
      <text x="${left + plotW / 2 - 38}" y="${height - 14}" fill="#9aa6b2" font-size="11">Mean ${escapeHtml(formatMoney(mean))}</text>
      <text x="${width - right - 72}" y="${height - 14}" fill="#9aa6b2" font-size="11">${escapeHtml(formatMoney(max))}</text>
      <text x="${left + 4}" y="${top + 12}" fill="#9aa6b2" font-size="11">${maxCount} max/bin</text>
    </svg>
    <div class="chart-caption">
      <span>Blue bars = histogram, orange line = bell-curve (${escapeHtml(metricLabel)}). ${escapeHtml(activeText)}</span>
      <span class="chart-actions">
        ${hasActiveFilter ? `<button id="clear-bin-filter" type="button">Clear Bin Filter</button>` : ""}
      </span>
    </div>
  `;

  container.querySelectorAll(".hist-bar").forEach((bar) => {
    bar.addEventListener("click", async () => {
      const start = Number(bar.getAttribute("data-bin-start"));
      const end = Number(bar.getAttribute("data-bin-end"));
      const same =
        histogramState.min != null &&
        histogramState.max != null &&
        Math.abs(histogramState.min - start) < 1e-9 &&
        Math.abs(histogramState.max - end) < 1e-9;
      if (same) {
        histogramState.min = null;
        histogramState.max = null;
      } else {
        histogramState.min = start;
        histogramState.max = end;
      }
      paginationState.page = 1;
      await refreshInventoryData();
      scheduleFilterStateSave();
    });
  });

  const clearBtn = qs("clear-bin-filter");
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      histogramState.min = null;
      histogramState.max = null;
      paginationState.page = 1;
      await refreshInventoryData();
      scheduleFilterStateSave();
    });
  }
}

function effectiveSalePrice(item) {
  for (const key of ["advertized_price", "non_sp_advertized_price"]) {
    const value = Number(item?.[key]);
    if (!Number.isNaN(value) && value > 0) return value;
  }
  return null;
}

function effectiveMsrp(item) {
  for (const key of ["total_msrp", "base_msrp"]) {
    const value = Number(item?.[key]);
    if (!Number.isNaN(value) && value > 0) return value;
  }
  return null;
}

function msrpDeltaValue(item) {
  if (item?.msrp_delta != null && !Number.isNaN(Number(item.msrp_delta))) {
    return Number(item.msrp_delta);
  }
  const price = effectiveSalePrice(item);
  const msrp = effectiveMsrp(item);
  if (price == null || msrp == null) return null;
  return price - msrp;
}

function enrichInventoryItem(item) {
  const delta = msrpDeltaValue(item);
  return {
    ...item,
    msrp_delta: delta,
  };
}

function trimLabelForItem(item) {
  const model = item.model_marketing_name || "Unknown";
  const grade = item.grade || "-";
  const drive = item.drivetrain_code || "-";
  return `${grade} ${model} (${drive})`;
}

function buildMsrpComparisonFromItems(items) {
  const pricedRows = (items || [])
    .map((item) => {
      const price = effectiveSalePrice(item);
      const msrp = effectiveMsrp(item);
      if (price == null || msrp == null) return null;
      const delta = price - msrp;
      return {
        vin: item.vin || "",
        model_marketing_name: item.model_marketing_name || "Unknown",
        grade: item.grade || "-",
        drivetrain_code: item.drivetrain_code || "-",
        dealer_marketing_name: item.dealer_marketing_name || item.dealer_cd || "-",
        trim_label: trimLabelForItem(item),
        sale_price: price,
        msrp,
        delta,
        delta_pct: (delta / msrp) * 100,
      };
    })
    .filter(Boolean);

  if (!pricedRows.length) return null;

  const avg = (values) => values.reduce((sum, value) => sum + value, 0) / values.length;
  const deltas = pricedRows.map((row) => row.delta);
  const belowRows = pricedRows.filter((row) => row.delta < -1);
  const aboveRows = pricedRows.filter((row) => row.delta > 1);
  const atMsrpCount = pricedRows.length - belowRows.length - aboveRows.length;

  const trimBuckets = new Map();
  for (const row of pricedRows) {
    const key = `${row.model_marketing_name}|${row.grade}|${row.drivetrain_code}`;
    const bucket = trimBuckets.get(key) || {
      trim_label: row.trim_label,
      model_marketing_name: row.model_marketing_name,
      grade: row.grade,
      drivetrain_code: row.drivetrain_code,
      deltas: [],
      pcts: [],
      prices: [],
      msrps: [],
    };
    bucket.deltas.push(row.delta);
    bucket.pcts.push(row.delta_pct);
    bucket.prices.push(row.sale_price);
    bucket.msrps.push(row.msrp);
    trimBuckets.set(key, bucket);
  }

  const trimItems = [...trimBuckets.values()]
    .filter((bucket) => bucket.deltas.length >= 3)
    .map((bucket) => {
      const belowCount = bucket.deltas.filter((delta) => delta < -1).length;
      const aboveCount = bucket.deltas.filter((delta) => delta > 1).length;
      return {
        trim_label: bucket.trim_label,
        model_marketing_name: bucket.model_marketing_name,
        grade: bucket.grade,
        drivetrain_code: bucket.drivetrain_code,
        count: bucket.deltas.length,
        avg_sale_price: avg(bucket.prices),
        avg_msrp: avg(bucket.msrps),
        avg_delta: avg(bucket.deltas),
        avg_delta_pct: avg(bucket.pcts),
        median_delta: [...bucket.deltas].sort((a, b) => a - b)[Math.floor(bucket.deltas.length / 2)],
        below_msrp_count: belowCount,
        above_msrp_count: aboveCount,
        below_msrp_pct: (belowCount / bucket.deltas.length) * 100,
      };
    });

  return {
    summary: {
      vehicle_count: pricedRows.length,
      avg_sale_price: avg(pricedRows.map((row) => row.sale_price)),
      avg_msrp: avg(pricedRows.map((row) => row.msrp)),
      avg_delta: avg(deltas),
      median_delta: [...deltas].sort((a, b) => a - b)[Math.floor(deltas.length / 2)],
      avg_delta_pct: avg(pricedRows.map((row) => row.delta_pct)),
      below_msrp_count: belowRows.length,
      above_msrp_count: aboveRows.length,
      at_msrp_count: Math.max(0, atMsrpCount),
      below_msrp_pct: (belowRows.length / pricedRows.length) * 100,
    },
    trims_below_msrp: trimItems
      .filter((item) => item.avg_delta < 0)
      .sort((a, b) => a.avg_delta - b.avg_delta)
      .slice(0, 15),
    trims_above_msrp: trimItems
      .filter((item) => item.avg_delta > 0)
      .sort((a, b) => b.avg_delta - a.avg_delta)
      .slice(0, 15),
    vehicles_most_below: [...pricedRows]
      .filter((row) => row.delta < 0)
      .sort((a, b) => a.delta - b.delta)
      .slice(0, 8),
    vehicles_most_above: [...pricedRows]
      .filter((row) => row.delta > 0)
      .sort((a, b) => b.delta - a.delta)
      .slice(0, 8),
  };
}

async function ensureAnalyticsMsrpComparison(analytics) {
  const payload = analytics || {};
  payload.insights = payload.insights || {};
  if (payload.insights.msrp_comparison?.summary) {
    return payload;
  }

  const params = buildInventoryQueryParams(false);
  try {
    const msrp = await fetchJsonWithRetry(`/api/inventory/msrp-comparison?${params}`, { attempts: 2 });
    if (msrp?.summary) {
      payload.insights.msrp_comparison = msrp;
    }
  } catch (err) {
    console.warn("[analytics] MSRP comparison endpoint unavailable:", err.message);
  }

  return payload;
}

function formatMsrpDelta(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  const cls = num < 0 ? "msrp-delta-below" : num > 0 ? "msrp-delta-above" : "msrp-delta-even";
  const sign = num > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${formatMoney(num)}</span>`;
}

const INVENTORY_TABLE_COLUMNS = [
  {
    key: "vin",
    label: "VIN",
    width: "9%",
    sortable: true,
    cell: (item) =>
      `<td class="mono-cell" title="${escapeHtml(item.vin)}"><span class="mono">${escapeHtml(item.vin)}</span></td>`,
  },
  {
    key: "stock_num",
    label: "Stock #",
    width: "5%",
    sortable: true,
    cell: (item) => `<td class="wrap-cell">${escapeHtml(item.stock_num || "-")}</td>`,
  },
  {
    key: "year",
    label: "Year",
    width: "3%",
    sortable: true,
    cell: (item) => `<td class="compact-cell">${escapeHtml(item.year ?? "-")}</td>`,
  },
  {
    key: "marketing_series",
    label: "Series",
    width: "5%",
    sortable: true,
    cell: (item) => `<td class="wrap-cell">${escapeHtml(item.marketing_series ?? item.series_code ?? "-")}</td>`,
  },
  {
    key: "grade",
    label: "Grade",
    width: "4%",
    sortable: true,
    cell: (item) => `<td class="wrap-cell">${escapeHtml(item.grade ?? "-")}</td>`,
  },
  {
    key: "model_marketing_name",
    label: "Model",
    width: "8%",
    sortable: true,
    cell: (item) => `<td class="wrap-cell">${escapeHtml(item.model_marketing_name ?? "-")}</td>`,
  },
  {
    key: "drivetrain_code",
    label: "Drive",
    width: "3%",
    sortable: true,
    cell: (item) => {
      const drivetrain = item.drivetrain_code
        ? `<span title="${escapeHtml(item.drivetrain_title || item.drivetrain_code)}">${escapeHtml(item.drivetrain_code)}</span>`
        : escapeHtml(item.drivetrain_title || "-");
      return `<td class="compact-cell">${drivetrain}</td>`;
    },
  },
  {
    key: "dealer_marketing_name",
    label: "Dealer",
    width: "12%",
    sortable: true,
    cell: (item) => {
      const dealer = item.dealer_marketing_name || item.dealer_cd || "-";
      const dealerWithZip = item.dealer_postal_code ? `${dealer} (${item.dealer_postal_code})` : dealer;
      return `<td class="wrap-cell">${escapeHtml(dealerWithZip)}</td>`;
    },
  },
  {
    key: "allocation_stage_code",
    label: "Stage",
    width: "7%",
    sortable: true,
    cell: (item) => {
      const stage = item.allocation_stage_label || item.allocation_stage_code || "-";
      return `<td class="stage-cell"><span class="badge">${escapeHtml(stage)}</span></td>`;
    },
  },
  {
    key: "advertized_price",
    label: "Price",
    width: "5%",
    sortable: true,
    cell: (item) => `<td class="num">${formatMoney(effectiveSalePrice(item))}</td>`,
  },
  {
    key: "total_msrp",
    label: "MSRP",
    width: "5%",
    sortable: true,
    cell: (item) => `<td class="num">${formatMoney(effectiveMsrp(item))}</td>`,
  },
  {
    key: "msrp_delta",
    label: "vs MSRP",
    width: "5%",
    sortable: true,
    cell: (item) => `<td class="num">${formatMsrpDelta(msrpDeltaValue(item))}</td>`,
  },
  {
    key: "distance",
    label: "Dist",
    width: "4%",
    sortable: true,
    cell: (item) => `<td class="num">${item.distance != null ? Number(item.distance).toLocaleString() : "-"}</td>`,
  },
  {
    key: "links",
    label: "Links",
    width: "5%",
    sortable: false,
    cell: (item) => {
      const dealerUrl = item.dealer_website
        ? `<a href="${escapeHtml(item.dealer_website)}" target="_blank" rel="noreferrer">Dealer</a>`
        : "-";
      const listingUrl = item.vdp_url
        ? `<a href="${escapeHtml(item.vdp_url)}" target="_blank" rel="noreferrer">Listing</a>`
        : "";
      return `<td class="links-cell"><div class="link-stack">${listingUrl}${dealerUrl !== "-" ? dealerUrl : ""}</div></td>`;
    },
  },
  {
    key: "exterior_color_name",
    label: "Exterior",
    width: "10%",
    sortable: true,
    cell: (item) => {
      const exterior = `${colorPreview(item.exterior_color_hex, item.exterior_color_swatch)}<span>${escapeHtml(item.exterior_color_name || "-")}</span>`;
      return `<td><div class="color-cell">${exterior}</div></td>`;
    },
  },
  {
    key: "interior_color_name",
    label: "Interior",
    width: "10%",
    sortable: true,
    cell: (item) => {
      const interior = `${colorPreview(null, item.interior_color_swatch)}<span>${escapeHtml(item.interior_color_name || "-")}</span>`;
      return `<td><div class="color-cell">${interior}</div></td>`;
    },
  },
];

function renderInventoryTableHeader() {
  const table = document.querySelector(".inventory-table");
  const row = table?.querySelector("thead tr");
  if (!table || !row) return;

  const colgroup = table.querySelector("colgroup") || document.createElement("colgroup");
  colgroup.innerHTML = `<col style="width:2%" />${INVENTORY_TABLE_COLUMNS.map(
    (column) => `<col style="width:${escapeHtml(column.width || "auto")}" />`
  ).join("")}`;
  if (!colgroup.parentElement) {
    table.prepend(colgroup);
  }

  row.innerHTML = `<th scope="col" class="select-col"><input type="checkbox" id="inventory-select-page" title="Select all on this page" aria-label="Select all on this page" /></th>${INVENTORY_TABLE_COLUMNS.map((column) => {
    if (!column.sortable) {
      return `<th scope="col">${escapeHtml(column.label)}</th>`;
    }
    return `<th scope="col" class="sortable" data-sort-key="${escapeHtml(column.key)}">${escapeHtml(column.label)}</th>`;
  }).join("")}`;
  renderSortIndicators();
}

function formatDelta(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  const cls = num < 0 ? "delta-negative" : num > 0 ? "delta-positive" : "";
  const sign = num > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${formatMoney(num)}</span>`;
}

function renderInsightTable(headers, rows) {
  if (!rows.length) {
    return `<div class="chart-empty">Not enough data in the current selection.</div>`;
  }
  let sawText = false;
  const cols = headers
    .map((h) => {
      if (h.numeric) return `<col class="col-num" />`;
      if (!sawText) {
        sawText = true;
        return `<col class="col-primary" />`;
      }
      return `<col class="col-text" />`;
    })
    .join("");
  const head = headers
    .map((h) => `<th class="${h.numeric ? "num" : ""}">${escapeHtml(h.label)}</th>`)
    .join("");
  const body = rows
    .map((row) => {
      const cells = headers
        .map((h) => {
          const raw = h.render ? h.render(row) : row[h.key];
          const content = h.rawHtml ? raw : escapeHtml(String(raw ?? "-"));
          const cellClass = h.numeric ? "num" : "wrap-cell";
          return `<td class="${cellClass}">${content}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<table class="insight-table"><colgroup>${cols}</colgroup><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function formatDeltaPct(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  const cls = num < 0 ? "delta-negative" : num > 0 ? "delta-positive" : "";
  const sign = num > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${num.toFixed(1)}%</span>`;
}

function renderMsrpComparisonSection(msrpComparison) {
  if (!msrpComparison?.summary) {
    const pricedInTable = currentItems.filter(
      (item) => effectiveSalePrice(item) != null && effectiveMsrp(item) != null
    ).length;
    const hint =
      pricedInTable > 0
        ? `${pricedInTable} vehicles on this page have both prices — reload analytics after ingest finishes or re-apply filters.`
        : "No vehicles in the current selection have both a sale price and MSRP to compare.";
    return `
      <div class="pricing-insight-panel pricing-insight-panel-wide">
        <h4>Sale vs MSRP</h4>
        <div class="chart-empty">${escapeHtml(hint)}</div>
      </div>
    `;
  }

  const summary = msrpComparison.summary;
  const trimBelowTable = renderInsightTable(
    [
      { label: "Trim", key: "trim_label" },
      { label: "Count", key: "count", numeric: true },
      {
        label: "Avg Sale",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_sale_price),
      },
      {
        label: "Avg MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_msrp),
      },
      {
        label: "Avg vs MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.avg_delta),
      },
      {
        label: "Avg %",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDeltaPct(row.avg_delta_pct),
      },
      {
        label: "Below MSRP",
        numeric: true,
        render: (row) =>
          `${Number(row.below_msrp_count).toLocaleString()} (${Number(row.below_msrp_pct).toFixed(0)}%)`,
      },
    ],
    msrpComparison.trims_below_msrp || []
  );

  const trimAboveTable = renderInsightTable(
    [
      { label: "Trim", key: "trim_label" },
      { label: "Count", key: "count", numeric: true },
      {
        label: "Avg Sale",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_sale_price),
      },
      {
        label: "Avg MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_msrp),
      },
      {
        label: "Avg vs MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.avg_delta),
      },
      {
        label: "Avg %",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDeltaPct(row.avg_delta_pct),
      },
      {
        label: "Above MSRP",
        numeric: true,
        render: (row) => Number(row.above_msrp_count).toLocaleString(),
      },
    ],
    msrpComparison.trims_above_msrp || []
  );

  const vehiclesBelowTable = renderInsightTable(
    [
      { label: "Trim", key: "trim_label" },
      { label: "Dealer", key: "dealer_marketing_name" },
      {
        label: "Sale",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.sale_price),
      },
      {
        label: "MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.msrp),
      },
      {
        label: "vs MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta),
      },
      {
        label: "%",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDeltaPct(row.delta_pct),
      },
    ],
    msrpComparison.vehicles_most_below || []
  );

  const vehiclesAboveTable = renderInsightTable(
    [
      { label: "Trim", key: "trim_label" },
      { label: "Dealer", key: "dealer_marketing_name" },
      {
        label: "Sale",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.sale_price),
      },
      {
        label: "MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.msrp),
      },
      {
        label: "vs MSRP",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta),
      },
      {
        label: "%",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDeltaPct(row.delta_pct),
      },
    ],
    msrpComparison.vehicles_most_above || []
  );

  return `
    <div class="pricing-insight-panel pricing-insight-panel-wide">
      <h4>Sale vs MSRP Overview</h4>
      <p class="panel-caption">
        Based on ${Number(summary.vehicle_count).toLocaleString()} vehicles with both advertised price and MSRP.
        Green deltas are below MSRP; orange is above.
      </p>
      <div class="msrp-summary-grid">
        <div class="msrp-summary-chip">
          <span class="label">Avg Sale</span>
          <span class="value">${escapeHtml(formatMoney(summary.avg_sale_price))}</span>
        </div>
        <div class="msrp-summary-chip">
          <span class="label">Avg MSRP</span>
          <span class="value">${escapeHtml(formatMoney(summary.avg_msrp))}</span>
        </div>
        <div class="msrp-summary-chip">
          <span class="label">Avg vs MSRP</span>
          <span class="value">${formatDelta(summary.avg_delta)} (${formatDeltaPct(summary.avg_delta_pct)})</span>
        </div>
        <div class="msrp-summary-chip">
          <span class="label">Below MSRP</span>
          <span class="value">${Number(summary.below_msrp_count).toLocaleString()} (${Number(summary.below_msrp_pct).toFixed(0)}%)</span>
        </div>
        <div class="msrp-summary-chip">
          <span class="label">Above MSRP</span>
          <span class="value">${Number(summary.above_msrp_count).toLocaleString()}</span>
        </div>
        <div class="msrp-summary-chip">
          <span class="label">At MSRP</span>
          <span class="value">${Number(summary.at_msrp_count).toLocaleString()}</span>
        </div>
      </div>
    </div>
    <div class="pricing-insight-panel">
      <h4>Trims Below MSRP (Avg)</h4>
      <p class="panel-caption">Grouped by grade, model, and drivetrain. Sorted by largest average discount first.</p>
      ${trimBelowTable}
    </div>
    <div class="pricing-insight-panel">
      <h4>Trims Above MSRP (Avg)</h4>
      <p class="panel-caption">Grouped by grade, model, and drivetrain. Sorted by largest average markup first.</p>
      ${trimAboveTable}
    </div>
    <div class="pricing-insight-panel">
      <h4>Biggest Individual Discounts</h4>
      <p class="panel-caption">Single listings with the largest sale price below MSRP in the current selection.</p>
      ${vehiclesBelowTable}
    </div>
    <div class="pricing-insight-panel">
      <h4>Biggest Individual Markups</h4>
      <p class="panel-caption">Single listings with the largest sale price above MSRP in the current selection.</p>
      ${vehiclesAboveTable}
    </div>
  `;
}

function renderPricingInsights(analytics) {
  const container = qs("pricing-insights");
  if (!container) return;

  const insights = analytics?.insights;
  const msrpComparison = insights?.msrp_comparison;
  if (!insights || (!insights.baseline && !msrpComparison?.summary)) {
    container.innerHTML = `
      <h3>Pricing Insights</h3>
      <div class="chart-empty">Need more priced vehicles in the current selection to compute pricing insights.</div>
    `;
    return;
  }

  const metricLabel = insights.metric_label || "Price";
  const baselineMedian = insights.baseline?.median;
  const msrpSection = renderMsrpComparisonSection(msrpComparison);

  if (!insights.baseline) {
    container.innerHTML = `
      <h3>Pricing Insights</h3>
      <div class="pricing-insights-grid">
        ${msrpSection}
      </div>
      ${insights.notes?.length ? `<ul class="pricing-insights-notes">${insights.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>` : ""}
    `;
    return;
  }

  const modelsTable = renderInsightTable(
    [
      { label: "Model", key: "model_marketing_name" },
      { label: "Drive", key: "drivetrain_code" },
      { label: "Count", key: "count", numeric: true },
      {
        label: "Median",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.median_price),
      },
      {
        label: "vs Baseline",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta_vs_baseline),
      },
    ],
    insights.models || []
  );

  const optionsTable = renderInsightTable(
    [
      { label: "Option", render: (row) => formatOptionLabel(row.option_cd, row.marketing_name) },
      { label: "With", key: "count_with", numeric: true },
      {
        label: "Avg With",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_with),
      },
      {
        label: "Avg Without",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.avg_without),
      },
      {
        label: "Effect",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta_vs_without),
      },
    ],
    insights.options || []
  );

  const distanceTable = renderInsightTable(
    [
      { label: "Distance Band", key: "label" },
      { label: "Count", key: "count", numeric: true },
      {
        label: "Median",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.median_price),
      },
      {
        label: "vs Baseline",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta_vs_baseline),
      },
    ],
    insights.distance_bands || []
  );

  const dealersTable = renderInsightTable(
    [
      { label: "Dealer", key: "dealer_marketing_name" },
      { label: "Count", key: "count", numeric: true },
      {
        label: "Median",
        numeric: true,
        rawHtml: true,
        render: (row) => formatMoney(row.median_price),
      },
      {
        label: "vs Baseline",
        numeric: true,
        rawHtml: true,
        render: (row) => formatDelta(row.delta_vs_baseline),
      },
    ],
    insights.dealers_below_baseline || []
  );

  const notes = (insights.notes || [])
    .map((note) => `<li>${escapeHtml(note)}</li>`)
    .join("");

  container.innerHTML = `
    <h3>Pricing Insights (${escapeHtml(metricLabel)})</h3>
    <div class="pricing-insights-intro">Baseline median for current filters: ${escapeHtml(formatMoney(baselineMedian))}. Green deltas are below baseline; orange is above.</div>
    <div class="pricing-insights-grid">
      ${msrpSection}
      <div class="pricing-insight-panel">
        <h4>Cheapest Models / Trims</h4>
        <p class="panel-caption">Grouped by model and drivetrain. Sorted lowest median first.</p>
        ${modelsTable}
      </div>
      <div class="pricing-insight-panel">
        <h4>Option Price Correlations</h4>
        <p class="panel-caption">Average price with vs without each option. Negative effect often means the option appears on lower-priced trims.</p>
        ${optionsTable}
      </div>
      <div class="pricing-insight-panel">
        <h4>Distance From Search ZIP</h4>
        <p class="panel-caption">Miles from the ingestion search origin (run ZIP). Useful for spotting farther-away bargains.</p>
        ${distanceTable}
      </div>
      <div class="pricing-insight-panel">
        <h4>Dealers Below Baseline</h4>
        <p class="panel-caption">Dealers whose median price is under the filtered baseline (minimum 5 listings per dealer).</p>
        ${dealersTable}
      </div>
    </div>
    ${notes ? `<ul class="pricing-insights-notes">${notes}</ul>` : ""}
  `;
}

let imageLightboxHref = "";

function enlargedImageUrl(href) {
  if (!href) return href;
  try {
    const url = new URL(href, window.location.origin);
    if (url.searchParams.has("size")) {
      url.searchParams.set("size", "1200,663");
      return url.toString();
    }
  } catch (_err) {
    return href;
  }
  return href;
}

function openImageLightbox(href, title) {
  imageLightboxHref = href;
  const lightbox = qs("image-lightbox");
  const image = qs("image-lightbox-image");
  const titleEl = qs("image-lightbox-title");
  if (!lightbox || !image || !titleEl) return;

  titleEl.textContent = title || "Vehicle image";
  const displayUrl = enlargedImageUrl(href);
  image.src = displayUrl;
  image.alt = title || "Vehicle image";
  if (window.VitImageCache?.get) {
    VitImageCache.get(displayUrl).then((cachedUrl) => {
      if (cachedUrl && image.isConnected) {
        image.src = cachedUrl;
      }
    });
  }
  lightbox.classList.remove("hidden");
  lightbox.setAttribute("aria-hidden", "false");
}

function closeImageLightbox() {
  const lightbox = qs("image-lightbox");
  const image = qs("image-lightbox-image");
  if (!lightbox || !image) return;

  lightbox.classList.add("hidden");
  lightbox.setAttribute("aria-hidden", "true");
  image.removeAttribute("src");
  imageLightboxHref = "";
}

function openImageInNewTab() {
  if (!imageLightboxHref) return;
  window.open(imageLightboxHref, "_blank", "noopener,noreferrer");
}

function bindMediaCards() {
  document.querySelectorAll(".media-card[data-image-href]").forEach((card) => {
    const open = () => {
      const href = card.getAttribute("data-image-href");
      const title = card.getAttribute("data-image-title") || "Vehicle image";
      if (!href) return;
      if (card.classList.contains("media-card-360")) {
        window.VitPanoViewer?.openModal(href, title);
        return;
      }
      openImageLightbox(href, title);
    };
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
}

function getDetailPanoViewerEl() {
  return qs("detail-pano-viewer");
}

function scheduleDetailPanoViewer() {
  const container = getDetailPanoViewerEl();
  if (!container) return;
  const href = container.getAttribute("data-pano-href");
  if (!href) return;
  const mount = () => window.VitPanoViewer?.mountInline(container, href);
  if (typeof requestAnimationFrame === "function") {
    requestAnimationFrame(() => requestAnimationFrame(mount));
  } else {
    setTimeout(mount, 32);
  }
}

function bindPanoViewerControls() {
  const container = getDetailPanoViewerEl();
  const section = container?.closest(".media-section-360");
  if (!section) return;

  section.querySelectorAll(".pano-picker-btn").forEach((button) => {
    button.addEventListener("click", () => {
      const href = button.getAttribute("data-pano-href");
      const title = button.getAttribute("data-pano-title") || "360° View";
      if (!href || !container) return;
      container.setAttribute("data-pano-href", href);
      container.setAttribute("data-pano-title", title);
      section.querySelectorAll(".pano-picker-btn").forEach((item) => {
        item.classList.toggle("is-active", item === button);
      });
      window.VitPanoViewer?.mountInline(container, href);
    });
  });

  section.querySelectorAll("[data-pano-fullscreen]").forEach((button) => {
    button.addEventListener("click", () => {
      const href = container.getAttribute("data-pano-href");
      const title = container.getAttribute("data-pano-title") || "360° View";
      if (href) {
        window.VitPanoViewer?.openModal(href, title);
      }
    });
  });
}

function colorPreview(exteriorHex, swatchUrl) {
  if (swatchUrl) {
    return `<span class="color-dot">${cachedImgTag(swatchUrl, "swatch")}</span>`;
  }
  if (exteriorHex) {
    const hex = String(exteriorHex).startsWith("#") ? String(exteriorHex) : `#${String(exteriorHex)}`;
    return `<span class="color-dot" style="background:${escapeHtml(hex)}"></span>`;
  }
  return `<span class="color-dot color-dot-empty"></span>`;
}

async function fetchJson(url, options = {}) {
  const { optional = false, ...fetchOptions } = options;
  const resolvedUrl = window.VIT?.withMakeQuery ? window.VIT.withMakeQuery(url) : url;
  const res = await fetch(resolvedUrl, fetchOptions);
  if (!res.ok) {
    if (optional) {
      console.warn(`Optional request failed: ${url} (${res.status})`);
      return null;
    }
    let detail = "";
    try {
      const payload = await res.json();
      detail = payload.error ? `: ${payload.error}` : "";
    } catch (_err) {
      detail = "";
    }
    throw new Error(`HTTP ${res.status}${detail}`);
  }
  return res.json();
}

async function fetchJsonWithRetry(url, { attempts = 3, delayMs = 400 } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await fetchJson(url);
    } catch (err) {
      lastError = err;
      if (attempt >= attempts) break;
      await new Promise((resolve) => window.setTimeout(resolve, delayMs * attempt));
    }
  }
  throw lastError;
}

async function fetchJsonOptional(url, label) {
  try {
    return await fetchJson(url);
  } catch (err) {
    console.warn(`[inventory] ${label} unavailable:`, err.message);
    return null;
  }
}

async function loadSummary() {
  const data = await fetchJson("/api/summary");
  qs("latest-run").textContent = data.latest_run_id ?? "-";
  qs("latest-time").textContent = formatDate(data.latest_queried_at);
  qs("active-count").textContent = data.active_count ?? 0;
  qs("total-count").textContent = data.all_vehicle_count ?? 0;
}

function selectedMultiValues(selectEl) {
  if (!selectEl?.id) return [];
  if (selectEl.id === "series-values") return getSeriesSelectedValues();
  if (selectEl.id === "state-codes") return getStateSelectedValues();
  return [...getFacetSelectionSet(selectEl.id)];
}

function clearMultiSelect(id) {
  if (id === "series-values") {
    seriesSelectedValues.clear();
    renderSeriesFilterList();
    return;
  }
  if (id === "state-codes") {
    stateSelectedValues.clear();
    renderStateFilterList();
    return;
  }
  clearFacetSelectionSet(id);
  if (id === "dealer-values") {
    renderDealerFilterList();
    return;
  }
  if (id === "exterior-color-values" || id === "interior-color-values") {
    const kind = id.includes("exterior") ? "exterior" : "interior";
    populateFacetedColorList(qs(id), facetItemCache[id] || [], kind);
    return;
  }
  if (FACET_BUTTON_LIST_IDS.has(id)) {
    renderFacetButtonList(id);
  }
}

function buildFilterQueryParams() {
  const seriesCodes = selectedMultiValues(qs("series-values")).join(",");
  const modelValues = selectedMultiValues(qs("model-values")).join(",");
  const exteriorColors = selectedMultiValues(qs("exterior-color-values")).join(",");
  const interiorColors = selectedMultiValues(qs("interior-color-values")).join(",");
  const drivetrainCodes = selectedMultiValues(qs("drivetrain-codes")).join(",");
  const stageCodes = selectedMultiValues(qs("stage-codes")).join(",");
  const optionCodes = selectedMultiValues(qs("option-codes")).join(",");
  const dealerCodes = selectedMultiValues(qs("dealer-values")).join(",");
  const { stateCodes, searchZip, distanceMax } = getLocationFilterParams();
  const activeOnly = qs("active-only")?.checked ? "1" : "0";
  const ref = !hasStateFilterSelected() ? getUserReferenceCoords() : null;

  return (
    `series_codes=${encodeURIComponent(seriesCodes)}` +
    `&model_marketing_names=${encodeURIComponent(modelValues)}` +
    `&exterior_colors=${encodeURIComponent(exteriorColors)}` +
    `&interior_colors=${encodeURIComponent(interiorColors)}` +
    `&drivetrain_codes=${encodeURIComponent(drivetrainCodes)}` +
    `&stage_codes=${encodeURIComponent(stageCodes)}` +
    `&option_codes=${encodeURIComponent(optionCodes)}` +
    `&dealer_codes=${encodeURIComponent(dealerCodes)}` +
    `&state_codes=${encodeURIComponent(stateCodes)}` +
    (searchZip ? `&search_zip=${encodeURIComponent(searchZip)}` : "") +
    (distanceMax ? `&distance_max=${encodeURIComponent(distanceMax)}` : "") +
    (ref ? `&reference_lat=${encodeURIComponent(ref.lat)}&reference_lng=${encodeURIComponent(ref.lng)}` : "") +
    `&active_only=${activeOnly}`
  );
}

function clearDependentFilters() {
  const dealerSearch = qs("dealer-search");
  if (dealerSearch) dealerSearch.value = "";
  for (const id of FILTER_MULTI_SELECT_IDS) {
    clearMultiSelect(id);
  }
}

async function loadFilters({ clearDependents = false, silent = false } = {}) {
  const token = ++filterLoadToken;
  if (!silent) {
    setPanelLoading("filters", true);
  }
  try {
    if (clearDependents) {
      clearDependentFilters();
    }

    const query = buildFilterQueryParams();
    const data = await fetchJson(`/api/filters?${query}`);
    if (token !== filterLoadToken) {
      return;
    }

    populateSeriesFilterList(data.series || []);
    populateFacetButtonList("model-values", data.models || []);
    populateFacetedColorList(qs("exterior-color-values"), data.exterior_colors || [], "exterior");
    populateFacetedColorList(qs("interior-color-values"), data.interior_colors || [], "interior");
    populateDealerFilterList(data.dealers || []);
    populateStateFilterList(data.states || []);
    populateFacetButtonList("drivetrain-codes", data.drivetrains || []);
    populateFacetButtonList("stage-codes", data.stages || []);
    populateFacetButtonList("option-codes", data.options || []);

    const contextEl = qs("filter-context-meta");
    if (contextEl) {
      const count = Number(data.context_count || 0).toLocaleString();
      contextEl.textContent =
        data.context_count != null
          ? `${count} vehicles match the current filter selections (latest run ${data.latest_run_id ?? "-"})`
          : "";
    }
  } finally {
    if (!silent && token === filterLoadToken) {
      setPanelLoading("filters", false);
    }
  }
}

function isFilterBackgroundReloadBusy() {
  return loadingState.table > 0 || loadingState.filters > 0 || loadingState.analytics > 0;
}

async function refreshFiltersAndInventory({
  showTableLoading = false,
  silentFilters = true,
  reloadFilters = true,
  clearDependents = false,
} = {}) {
  if (filterReloadTimer) {
    clearTimeout(filterReloadTimer);
    filterReloadTimer = null;
  }
  if (clearDependents) {
    clearDependentFilters();
  }
  await refreshInventoryData({ showTableLoading });
  if (reloadFilters) {
    await loadFilters({ silent: silentFilters });
  }
}

function scheduleFilterReload() {
  if (filterReloadTimer) {
    clearTimeout(filterReloadTimer);
  }
  filterReloadTimer = setTimeout(() => {
    filterReloadTimer = null;
    if (isFilterBackgroundReloadBusy()) {
      scheduleFilterReload();
      return;
    }
    loadFilters({ silent: true }).catch((err) => console.warn("[filters]", err.message));
  }, 400);
}

async function onFacetFilterChange(event) {
  const targetId = event?.target?.id;
  if (targetId === "state-codes" && hasStateFilterSelected()) {
    clearZipRadiusFilters();
  }
  paginationState.page = 1;
  await refreshFiltersAndInventory({ showTableLoading: false, silentFilters: true });
  scheduleFilterStateSave();
}

function rowHtml(item) {
  const isSelected = inventorySelectedVins.has(item.vin);
  const selectCell = `<td class="select-cell"><input type="checkbox" class="inventory-row-select" data-vin="${escapeHtml(item.vin)}" ${isSelected ? "checked" : ""} aria-label="Select ${escapeHtml(item.vin)}" /></td>`;
  return `<tr class="clickable-row${isSelected ? " is-row-selected" : ""}" data-vin="${escapeHtml(item.vin)}">${selectCell}${INVENTORY_TABLE_COLUMNS.map((column) => column.cell(item)).join("")}</tr>`;
}

function buildInventoryQueryParams(includePagination = true) {
  const seriesCodes = selectedMultiValues(qs("series-values")).join(",");
  const modelValues = selectedMultiValues(qs("model-values")).join(",");
  const exteriorColors = selectedMultiValues(qs("exterior-color-values")).join(",");
  const interiorColors = selectedMultiValues(qs("interior-color-values")).join(",");
  const drivetrainCodes = selectedMultiValues(qs("drivetrain-codes")).join(",");
  const stageCodes = selectedMultiValues(qs("stage-codes")).join(",");
  const optionCodes = selectedMultiValues(qs("option-codes")).join(",");
  const dealerCodes = selectedMultiValues(qs("dealer-values")).join(",");
  const vinQuery = qs("vin-query")?.value.trim() || "";
  const stockQuery = qs("stock-query")?.value.trim() || "";
  const { stateCodes, searchZip, distanceMax } = getLocationFilterParams();
  const activeOnly = qs("active-only")?.checked ? "1" : "0";

  let params =
    `series_codes=${encodeURIComponent(seriesCodes)}` +
    `&filter_mode=model` +
    `&model_marketing_names=${encodeURIComponent(modelValues)}` +
    `&exterior_colors=${encodeURIComponent(exteriorColors)}` +
    `&interior_colors=${encodeURIComponent(interiorColors)}` +
    `&drivetrain_codes=${encodeURIComponent(drivetrainCodes)}` +
    `&stage_codes=${encodeURIComponent(stageCodes)}` +
    `&option_codes=${encodeURIComponent(optionCodes)}` +
    `&dealer_codes=${encodeURIComponent(dealerCodes)}` +
    `&state_codes=${encodeURIComponent(stateCodes)}` +
    `&vin_query=${encodeURIComponent(vinQuery)}` +
    `&stock_query=${encodeURIComponent(stockQuery)}` +
    (searchZip ? `&search_zip=${encodeURIComponent(searchZip)}` : "") +
    (distanceMax ? `&distance_max=${encodeURIComponent(distanceMax)}` : "") +
    `&active_only=${activeOnly}`;

  if (histogramState.min != null && histogramState.max != null && histogramState.metric) {
    params += `&price_min=${encodeURIComponent(String(histogramState.min))}`;
    params += `&price_max=${encodeURIComponent(String(histogramState.max))}`;
    params += `&price_metric=${encodeURIComponent(histogramState.metric)}`;
  }

  if (includePagination) {
    params += `&page=${encodeURIComponent(String(paginationState.page))}`;
    params += `&page_size=${encodeURIComponent(String(paginationState.pageSize))}`;
  }

  params += `&sort_key=${encodeURIComponent(sortState.key)}`;
  params += `&sort_dir=${encodeURIComponent(sortState.dir)}`;

  return params;
}

async function exportSelectionCsv() {
  const btn = qs("export-csv-btn");
  const originalText = btn?.textContent || "Export CSV";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Exporting...";
  }
  try {
    const res = await fetch(window.VIT?.withMakeQuery ? window.VIT.withMakeQuery(`/api/inventory/export?${buildInventoryQueryParams(false)}`) : `/api/inventory/export?${buildInventoryQueryParams(false)}`);
    if (!res.ok) {
      throw new Error(`Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename=\"?([^\";]+)/i);
    const filename = match?.[1] || "vehicle_inventory.csv";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (err) {
    console.error(err);
    alert(err.message || "Failed to export CSV.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

function renderPaginationControls() {
  const container = qs("pagination-controls");
  if (!container) return;

  const { page, pageCount, totalCount, pageSize } = paginationState;
  if (!totalCount) {
    container.innerHTML = "";
    return;
  }

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  const selectedCount = inventorySelectedVins.size;
  const pageVins = currentItems.map((item) => item.vin).filter(Boolean);
  const selectedOnPage = pageVins.filter((vin) => inventorySelectedVins.has(vin)).length;
  container.innerHTML = `
    <div class="pagination-summary">
      Showing ${start.toLocaleString()}-${end.toLocaleString()} of ${totalCount.toLocaleString()}
      ${selectedCount ? ` · ${selectedCount.toLocaleString()} selected` : ""}
    </div>
    <div class="pagination-actions">
      <button type="button" id="export-pdf-btn" ${selectedCount ? "" : "disabled"}>Export PDF${selectedCount ? ` (${selectedCount})` : ""}</button>
      <button type="button" id="clear-selection-btn" ${selectedCount ? "" : "disabled"}>Clear selection</button>
      <button type="button" data-page-action="first" ${page <= 1 ? "disabled" : ""}>First</button>
      <button type="button" data-page-action="prev" ${page <= 1 ? "disabled" : ""}>Previous</button>
      <span class="pagination-page">Page ${page} / ${pageCount}</span>
      <button type="button" data-page-action="next" ${page >= pageCount ? "disabled" : ""}>Next</button>
      <button type="button" data-page-action="last" ${page >= pageCount ? "disabled" : ""}>Last</button>
    </div>
  `;
  updateInventoryPageSelectCheckbox(pageVins, selectedOnPage);
}

function updateInventoryPageSelectCheckbox(pageVins, selectedOnPage) {
  const pageCheckbox = qs("inventory-select-page");
  if (!pageCheckbox) return;
  pageCheckbox.checked = pageVins.length > 0 && selectedOnPage === pageVins.length;
  pageCheckbox.indeterminate = selectedOnPage > 0 && selectedOnPage < pageVins.length;
  pageCheckbox.onchange = () => {
    if (pageCheckbox.checked) {
      pageVins.forEach((vin) => inventorySelectedVins.add(vin));
    } else {
      pageVins.forEach((vin) => inventorySelectedVins.delete(vin));
    }
    renderSortedInventory();
    renderPaginationControls();
  };
}

function setupPaginationControls() {
  const container = qs("pagination-controls");
  if (!container || container.dataset.ready === "1") return;
  container.dataset.ready = "1";
  container.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) return;
    if (target.id === "export-pdf-btn") {
      await exportSelectedVehiclesPdf();
      return;
    }
    if (target.id === "clear-selection-btn") {
      inventorySelectedVins.clear();
      renderSortedInventory();
      renderPaginationControls();
      return;
    }
    const action = target.getAttribute("data-page-action");
    if (!action || target.disabled) return;

    const { pageCount } = paginationState;
    if (action === "first") paginationState.page = 1;
    if (action === "prev") paginationState.page = Math.max(1, paginationState.page - 1);
    if (action === "next") paginationState.page = Math.min(pageCount, paginationState.page + 1);
    if (action === "last") paginationState.page = pageCount;
    await loadInventory();
  });
}

async function loadAnalytics() {
  if (isIngestRunning()) {
    renderAnalyticsPaused();
    return;
  }
  return withPanelLoading("analytics", async () => {
    let data = null;
    try {
      data = await fetchJsonWithRetry(`/api/inventory/analytics?${buildInventoryQueryParams(false)}`);
    } catch (err) {
      console.warn("[analytics] primary request failed:", err.message);
      data = {
        total_count: paginationState.totalCount || 0,
        advertized_price: null,
        total_msrp: null,
        histogram: null,
        insights: {},
      };
    }
    data = await ensureAnalyticsMsrpComparison(data);
    analyticsState = data;
    renderSelectionStats(analyticsState);
    renderDistributionChart(analyticsState);
    renderPricingInsights(analyticsState);
  });
}

async function loadGeoMap() {
  if (isIngestRunning()) {
    return;
  }
  const container = qs("inventory-geo-map");
  if (!container) {
    return;
  }
  try {
    const data = await fetchJson(`/api/inventory/geo-map?${buildInventoryQueryParams(false)}`, {
      optional: true,
    });
    if (!data) {
      container.innerHTML = `
        <h3>Geography &amp; MSRP Analytics</h3>
        <div class="chart-empty">Geo analytics unavailable.</div>
      `;
      return;
    }
    if (window.VitGeoMap?.renderGeoMapSectionAsync) {
      container.innerHTML = await VitGeoMap.renderGeoMapSectionAsync(data);
    } else if (window.VitGeoMap?.renderGeoMapSection) {
      container.innerHTML = VitGeoMap.renderGeoMapSection(data);
    }
  } catch (err) {
    console.warn("[geo-map]", err.message);
    container.innerHTML = `
      <h3>Geography &amp; MSRP Analytics</h3>
      <div class="chart-empty">Could not load geography data.</div>
    `;
  }
}

async function fetchAndRenderInventory(expectedToken) {
  const data = await fetchJson(`/api/inventory?${buildInventoryQueryParams(true)}`);
  if (expectedToken != null && expectedToken !== inventoryLoadToken) {
    return;
  }
  paginationState.page = data.page || 1;
  paginationState.pageSize = data.page_size || 20;
  paginationState.totalCount = data.total_count ?? data.count ?? 0;
  paginationState.pageCount =
    data.page_count ||
    (paginationState.totalCount
      ? Math.max(1, Math.ceil(paginationState.totalCount / paginationState.pageSize))
      : 0);

  qs("result-title").textContent =
    `Results (${Number(paginationState.totalCount).toLocaleString()}) - Latest Run ${data.latest_run_id ?? "-"}`;

  const locationMetaEl = qs("location-filter-meta");
  if (locationMetaEl) {
    const parts = [];
    const searchZipValue = normalizeZipCode(qs("search-zip-code")?.value.trim() || "");
    const distanceMaxValue = qs("distance-max-miles")?.value.trim();
    const selectedStates = selectedMultiValues(qs("state-codes"));
    if (selectedStates.length) {
      parts.push(`States: ${selectedStates.join(", ")}`);
    } else if (searchZipValue && distanceMaxValue) {
      parts.push(
        `Within ${Number(distanceMaxValue).toLocaleString()} mi of ZIP ${searchZipValue}`
      );
    } else if (distanceMaxValue) {
      parts.push(`Max distance: ${Number(distanceMaxValue).toLocaleString()} mi`);
    }
    locationMetaEl.textContent = parts.join(" · ");
  }

  let items = data.items || [];
  if (!data.page && items.length > paginationState.pageSize) {
    const offset = (paginationState.page - 1) * paginationState.pageSize;
    items = items.slice(offset, offset + paginationState.pageSize);
  }
  currentItems = items.map(enrichInventoryItem);
  renderSortedInventory();
  renderPaginationControls();
}

async function loadInventory({ showLoading = true } = {}) {
  const token = ++inventoryLoadToken;
  const useLoading = showLoading && !isIngestRunning();
  if (useLoading) {
    return withPanelLoading("table", () => fetchAndRenderInventory(token));
  }
  return fetchAndRenderInventory(token);
}

async function refreshInventoryData({ includeAnalytics = null, showTableLoading = null } = {}) {
  const shouldLoadAnalytics = includeAnalytics ?? !isIngestRunning();
  const useTableLoading = showTableLoading ?? !isIngestRunning();
  await loadInventory({ showLoading: useTableLoading });
  if (shouldLoadAnalytics) {
    scheduleAnalyticsRefresh();
  } else {
    renderAnalyticsPaused();
  }
}

function renderSortedInventory() {
  qs("results-body").innerHTML = currentItems.map(rowHtml).join("");
  bindRowClicks();
  bindInventoryRowSelection();
  renderSortIndicators();
  hydrateImages(qs("results-body"));
}

function bindInventoryRowSelection() {
  document.querySelectorAll(".inventory-row-select").forEach((checkbox) => {
    if (checkbox.dataset.ready === "1") return;
    checkbox.dataset.ready = "1";
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    checkbox.addEventListener("change", () => {
      const vin = checkbox.getAttribute("data-vin");
      if (!vin) return;
      if (checkbox.checked) {
        inventorySelectedVins.add(vin);
      } else {
        inventorySelectedVins.delete(vin);
      }
      const row = checkbox.closest("tr");
      if (row) {
        row.classList.toggle("is-row-selected", checkbox.checked);
      }
      renderPaginationControls();
    });
  });
}

function renderSortIndicators() {
  const headers = document.querySelectorAll(".inventory-table th.sortable");
  headers.forEach((header) => {
    header.classList.remove("sorted-asc", "sorted-desc");
    const key = header.getAttribute("data-sort-key");
    if (key === sortState.key) {
      header.classList.add(sortState.dir === "asc" ? "sorted-asc" : "sorted-desc");
    }
  });
}

function getIngestSettingsPayload() {
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

function updateCatalogSelectionUi() {
  const count = ingestUiState.selectedModelCodes.size;
  const countEl = qs("catalog-selection-count");
  if (countEl) {
    countEl.textContent =
      count === 1 ? "1 model selected" : `${count.toLocaleString()} models selected`;
  }
  const selectedBtn = qs("ingest-selected-btn");
  if (selectedBtn && !ingestUiState.running) {
    selectedBtn.disabled = count === 0;
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

function catalogAlertIcon(title) {
  return `<span class="catalog-model-alert" title="${escapeHtml(title)}" aria-label="${escapeHtml(title)}">
    <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <path fill="currentColor" d="M12 2 1 21h22L12 2zm0 4.5 7.4 13.5H4.6L12 6.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/>
    </svg>
  </span>`;
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
    container.innerHTML =
      '<div class="muted">No model catalog in the database yet. Click “Sync Model Catalog” to fetch available models.</div>';
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
        ? cachedImgTag(model.image, title)
        : '<div class="catalog-model-thumb catalog-model-thumb-empty"><span>No image</span></div>';
      const alert = hasNoData
        ? catalogAlertIcon("No inventory in database — prioritize refreshing this model")
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
  hydrateImages(container);
  window.VIT?.primeImageUrls?.(catalogModels.map((model) => model.image).filter(Boolean));
}

async function loadCatalogModels() {
  return withPanelLoading("ingest", async () => {
    const data = await fetchJson("/api/catalog/models");
    catalogModels = data.models || [];
    renderCatalogModels();
  });
}

function setIngestUiRunning(running) {
  ingestUiState.running = running;
  for (const id of [
    "ingest-refresh-catalog-btn",
    "ingest-selected-btn",
    "ingest-all-btn",
    "catalog-select-all-btn",
    "catalog-select-missing-btn",
    "catalog-select-none-btn",
  ]) {
    const btn = qs(id);
    if (!btn) continue;
    if (id === "ingest-selected-btn") {
      btn.disabled = running || ingestUiState.selectedModelCodes.size === 0;
    } else {
      btn.disabled = running;
    }
  }
}

function renderIngestProgress(status) {
  const wrap = qs("ingest-progress-wrap");
  const label = qs("ingest-progress-label");
  const percent = qs("ingest-progress-percent");
  const bar = qs("ingest-progress-bar");
  const detail = qs("ingest-progress-detail");
  if (!wrap || !label || !percent || !bar || !detail) return;

  const isActive = status.status === "running";
  wrap.classList.toggle("hidden", !isActive && status.status !== "failed" && status.status !== "completed");

  const pct = Math.max(0, Math.min(100, Number(status.percent || 0)));
  label.textContent = status.message || status.status || "Idle";
  percent.textContent = `${pct.toFixed(0)}%`;
  bar.value = pct;

  const parts = [];
  if (status.current_model_title || status.current_model) {
    parts.push(`Model ${status.model_index || 0}/${status.total_models || 0}: ${status.current_model_title || status.current_model}`);
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
}

async function pollIngestStatus() {
  const status = await fetchJson("/api/ingest/status");
  renderIngestProgress(status);
  if (status.status === "running") {
    setIngestUiRunning(true);
    renderAnalyticsPaused();
    const persisted = Number(status.vehicles_persisted || 0);
    if (persisted - ingestUiState.lastPersistedRefresh >= 250) {
      ingestUiState.lastPersistedRefresh = persisted;
      await loadSummary();
      await loadInventory({ showLoading: false });
      renderAnalyticsPaused();
    }
    return;
  }

  clearInterval(ingestPollTimer);
  ingestPollTimer = null;
  setIngestUiRunning(false);
  ingestUiState.lastPersistedRefresh = 0;

  if (status.status === "completed") {
    await refreshAll();
  }
}

function startIngestPolling() {
  if (ingestPollTimer) {
    clearInterval(ingestPollTimer);
  }
  ingestPollTimer = window.setInterval(() => {
    pollIngestStatus().catch((err) => {
      console.error(err);
    });
  }, 1500);
  pollIngestStatus().catch((err) => console.error(err));
}

async function syncModelCatalog({ afterIngest = false } = {}) {
  if (!afterIngest) {
    setIngestUiRunning(true);
  }
  const syncBtn = qs("ingest-refresh-catalog-btn");
  const originalText = syncBtn?.textContent || "Sync Model Catalog";
  if (syncBtn) syncBtn.textContent = "Syncing catalog...";
  try {
    await fetchJson("/api/catalog/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getIngestSettingsPayload()),
    });
    await loadCatalogModels();
    await loadJobRuns().catch(() => {});
  } finally {
    if (syncBtn) syncBtn.textContent = originalText;
    if (!afterIngest) {
      setIngestUiRunning(false);
    }
  }
}

async function syncModelCatalogAfterIngest() {
  renderIngestProgress({
    status: "running",
    message: "Ingest complete — syncing model catalog...",
    percent: 99,
  });
  qs("ingest-progress-wrap")?.classList.remove("hidden");
  try {
    await syncModelCatalog({ afterIngest: true });
    await loadFilters();
  } catch (err) {
    console.error("[ingest] Post-ingest catalog sync failed:", err);
    await loadCatalogModels();
  } finally {
    qs("ingest-progress-wrap")?.classList.add("hidden");
  }
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

  setIngestUiRunning(true);
  ingestUiState.watchedIngestSession = true;
  renderAnalyticsPaused();
  qs("ingest-progress-wrap")?.classList.remove("hidden");
  renderIngestProgress({
    status: "running",
    message: "Starting ingest...",
    percent: 0,
  });

  await fetchJson("/api/ingest/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  startIngestPolling();
}

function setupIngestHandlers() {
  qs("ingest-refresh-catalog-btn")?.addEventListener("click", () => {
    syncModelCatalog().catch((err) => window.alert(err.message));
  });
  qs("catalog-select-all-btn")?.addEventListener("click", selectAllCatalogModels);
  qs("catalog-select-missing-btn")?.addEventListener("click", selectMissingDataCatalogModels);
  qs("catalog-select-none-btn")?.addEventListener("click", selectNoneCatalogModels);
  qs("ingest-selected-btn")?.addEventListener("click", () => {
    if (ingestUiState.selectedModelCodes.size === 0) return;
    startIngest({ allModels: false }).catch((err) => window.alert(err.message));
  });
  qs("ingest-all-btn")?.addEventListener("click", () => {
    startIngest({ allModels: true }).catch((err) => window.alert(err.message));
  });
}

async function refreshAll({ includeAnalytics = null, showTableLoading = null } = {}) {
  paginationState.page = 1;
  histogramState.min = null;
  histogramState.max = null;
  const shouldLoadAnalytics = includeAnalytics ?? !isIngestRunning();
  const useTableLoading = showTableLoading ?? !isIngestRunning();
  await loadSummary();
  await loadInventory({ showLoading: useTableLoading });
  await loadFilters({ silent: useTableLoading });
  if (shouldLoadAnalytics) {
    scheduleAnalyticsRefresh({ delayMs: 2000 });
  } else {
    renderAnalyticsPaused();
  }
}

function clearFilters() {
  const vinQuery = qs("vin-query");
  const stockQuery = qs("stock-query");
  const dealerSearch = qs("dealer-search");
  const seriesSearch = qs("series-search");
  if (vinQuery) vinQuery.value = "";
  if (stockQuery) stockQuery.value = "";
  if (dealerSearch) dealerSearch.value = "";
  if (seriesSearch) seriesSearch.value = "";
  clearZipRadiusFilters();
  clearMultiSelect("series-values");
  for (const id of FILTER_MULTI_SELECT_IDS) {
    clearMultiSelect(id);
  }
}

function bindRowClicks() {
  const rows = document.querySelectorAll(".clickable-row");
  rows.forEach((row) => {
    row.addEventListener("click", async (event) => {
      if (event.target.closest(".select-cell, .inventory-row-select")) {
        return;
      }
      const vin = row.getAttribute("data-vin");
      if (!vin) return;
      await openVehicleDetail(vin);
    });
  });
}

let currentDetailData = null;
const inventorySelectedVins = new Set();

function renderDetail(data) {
  currentDetailData = data;
  const vehicle = data.vehicle || {};
  const latest = data.latest || {};
  const latestPricing = {
    advertized_price: latest.advertized_price,
    non_sp_advertized_price: latest.non_sp_advertized_price,
    total_msrp: latest.total_msrp,
    base_msrp: latest.base_msrp,
  };
  const salePrice = effectiveSalePrice(latestPricing);
  const msrp = effectiveMsrp(latestPricing);
  const msrpDelta = msrpDeltaValue(latestPricing);

  qs("detail-title").textContent = vehicleDisplayLabel(vehicle);

  qs("detail-meta").innerHTML = `
    <div><strong>VIN:</strong> <span class="mono">${escapeHtml(vehicle.vin || "-")}</span></div>
    <div><strong>Series:</strong> ${escapeHtml(vehicle.marketing_series || vehicle.series_code || "-")}</div>
    <div><strong>Grade:</strong> ${escapeHtml(vehicle.grade || "-")}</div>
    <div><strong>Drivetrain:</strong> ${escapeHtml(vehicle.drivetrain_title || vehicle.drivetrain_code || "-")}</div>
    <div><strong>Engine:</strong> ${escapeHtml(vehicle.engine_name || "-")}</div>
    <div><strong>Exterior:</strong> <span class="color-cell">${colorPreview(vehicle.exterior_color_hex, vehicle.exterior_color_swatch)}<span>${escapeHtml(vehicle.exterior_color_name || "-")}</span></span></div>
    <div><strong>Interior:</strong> <span class="color-cell">${colorPreview(null, vehicle.interior_color_swatch)}<span>${escapeHtml(vehicle.interior_color_name || "-")}</span></span></div>
    <div><strong>First Seen:</strong> ${escapeHtml(formatDate(vehicle.first_seen_at))}</div>
    <div><strong>Last Seen:</strong> ${escapeHtml(formatDate(vehicle.last_seen_at))}</div>
  `;

  const latestListing = latest.vdp_url
    ? `<a href="${escapeHtml(latest.vdp_url)}" target="_blank" rel="noreferrer">${escapeHtml(latest.vdp_url)}</a>`
    : "-";
  const latestDealer = latest.dealer_website
    ? `<a href="${escapeHtml(latest.dealer_website)}" target="_blank" rel="noreferrer">${escapeHtml(latest.dealer_marketing_name || latest.dealer_cd || "Dealer")}</a>`
    : escapeHtml(latest.dealer_marketing_name || latest.dealer_cd || "-");

  qs("detail-latest").innerHTML = `
    <div><strong>Run:</strong> ${escapeHtml(latest.run_id ?? "-")} (${escapeHtml(formatDate(latest.queried_at))})</div>
    <div><strong>Stock #:</strong> ${escapeHtml(latest.stock_num || "-")}</div>
    <div><strong>Status:</strong> ${escapeHtml(latest.inventory_status || "-")}</div>
    <div><strong>Stage:</strong> ${escapeHtml(latest.allocation_stage_label || latest.allocation_stage_code || "-")}</div>
    <div><strong>Distance:</strong> ${escapeHtml(latest.distance ?? "-")} mi</div>
    <div><strong>Advertised:</strong> ${escapeHtml(formatMoney(latest.advertized_price))}</div>
    <div><strong>Effective Price:</strong> ${escapeHtml(formatMoney(salePrice))}</div>
    <div><strong>Total MSRP:</strong> ${escapeHtml(formatMoney(latest.total_msrp))}</div>
    <div><strong>Effective MSRP:</strong> ${escapeHtml(formatMoney(msrp))}</div>
    <div><strong>vs MSRP:</strong> ${formatMsrpDelta(msrpDelta)}</div>
    <div><strong>Dealer:</strong> ${latestDealer}</div>
    <div><strong>Listing:</strong> ${latestListing}</div>
  `;

  const optionItems = (data.options || []).map((opt) => {
    const shortName = plainTextFromHtml(opt.marketing_name || "");
    const longName = plainTextFromHtml(opt.marketing_long_name || "");
    const label = shortName ? `${opt.option_cd} — ${shortName}` : opt.option_cd;
    const showBody = opt.marketing_long_name && longName && longName !== shortName;
    const body = showBody ? formatOptionDetailBody(opt.marketing_long_name) : "";
    return `<li><strong>${escapeHtml(label)}</strong>${body ? `<div class="muted">${body}</div>` : ""}</li>`;
  });
  qs("detail-options").innerHTML = optionItems.length ? optionItems.join("") : "<li>No options found.</li>";
  const wheelOptions = (data.wheel_options || [])
    .map((opt) => escapeHtml(plainTextFromHtml(opt.marketing_name) || opt.option_cd))
    .join(" | ");
  if (wheelOptions) {
    qs("detail-options").innerHTML =
      `<li><strong>Wheel Options:</strong><div class="muted">${wheelOptions}</div></li>` + qs("detail-options").innerHTML;
  }

  const staticMedia = (data.media || []).filter((m) => !is360MediaItem(m));
  const panoMedia = (data.media || []).filter((m) => is360MediaItem(m));

  function renderMediaCard(m) {
    const title = formatMediaTitle(m);
    const panoClass = is360MediaItem(m) ? " media-card-360" : "";
    return `
      <div
        class="media-card${panoClass}"
        role="button"
        tabindex="0"
        data-image-href="${escapeHtml(m.href)}"
        data-image-title="${escapeHtml(title)}"
      >
        ${cachedImgTag(m.href, title)}
        <span>${escapeHtml(title)}</span>
      </div>
    `;
  }

  const mediaSections = [];
  if (staticMedia.length) {
    mediaSections.push(staticMedia.map(renderMediaCard).join(""));
  }
  if (panoMedia.length) {
    const picker =
      panoMedia.length > 1
        ? `<div class="pano-picker">${panoMedia
            .map(
              (m, index) => `
                <button
                  type="button"
                  class="pano-picker-btn${index === 0 ? " is-active" : ""}"
                  data-pano-href="${escapeHtml(m.href)}"
                  data-pano-title="${escapeHtml(formatMediaTitle(m))}"
                >
                  ${escapeHtml(formatMediaTitle(m))}
                </button>
              `
            )
            .join("")}</div>`
        : "";
    mediaSections.push(`
      <div class="media-section-360">
        <div class="media-section-360-header">
          <h4>360° Interior</h4>
          <button type="button" class="pano-fullscreen-btn" data-pano-fullscreen="1">Fullscreen</button>
        </div>
        <p class="muted">Drag to look around · Scroll or pinch to zoom</p>
        <div
          id="detail-pano-viewer"
          class="pano-viewer-root pano-viewer-root-inline"
          data-pano-href="${escapeHtml(panoMedia[0].href)}"
          data-pano-title="${escapeHtml(formatMediaTitle(panoMedia[0]))}"
        ></div>
        ${picker}
      </div>
    `);
  }
  qs("detail-media").innerHTML = mediaSections.length
    ? mediaSections.join("")
    : "<div class='muted'>No media found.</div>";
  bindMediaCards();
  bindPanoViewerControls();
  scheduleDetailPanoViewer();
  hydrateImages(qs("detail-media"));

  const historyRows = (data.price_history || []).map((row) => {
    const rowPricing = {
      advertized_price: row.advertized_price,
      non_sp_advertized_price: row.non_sp_advertized_price,
      total_msrp: row.total_msrp,
      base_msrp: row.base_msrp,
    };
    return `
      <tr>
        <td>${escapeHtml(row.run_id)}</td>
        <td>${escapeHtml(formatDate(row.queried_at))}</td>
        <td>${escapeHtml(formatMoney(row.advertized_price))}</td>
        <td>${escapeHtml(formatMoney(row.total_msrp))}</td>
        <td>${formatMsrpDelta(msrpDeltaValue(rowPricing))}</td>
        <td>${escapeHtml(formatMoney(row.base_msrp))}</td>
        <td>${escapeHtml(formatMoney(row.selling_price))}</td>
      </tr>
    `;
  });
  qs("detail-price-history").innerHTML = historyRows.length
    ? historyRows.join("")
    : "<tr><td colspan='7'>No price history found.</td></tr>";
}

function pdfNormalizeMediaUrl(url) {
  return String(url || "")
    .trim()
    .replace(/^https:\/\/www\.mazdausa\.com:443/i, "https://www.mazdausa.com");
}

function is360MediaItem(item) {
  const type = String(item?.media_type || "").toLowerCase();
  if (type === "interior360" || type === "360") return true;
  const href = pdfNormalizeMediaUrl(item?.href).toLowerCase();
  if (!href) return false;
  if (/\/i360-|\/e360-|\/360\/|360-interior|360-exterior/.test(href)) return true;
  const filename = href.split("/").pop() || "";
  return filename.startsWith("i360-") || filename.startsWith("e360-");
}

function formatMediaTitle(item) {
  if (is360MediaItem(item)) {
    return "360° Interior panorama";
  }
  const tag = String(item?.image_tag || "").trim();
  if (tag && tag.toLowerCase() !== "vehicle") {
    return `${item.media_type || "media"} / ${tag}`;
  }
  const parts = [item?.media_type, item?.media_size, item?.image_tag].filter(Boolean);
  return parts.length ? parts.join(" / ") : "Photo";
}

function pdfNormalizedMediaType(item) {
  if (is360MediaItem(item)) return null;
  const type = String(item?.media_type || "").toLowerCase();
  const href = pdfNormalizeMediaUrl(item?.href).toLowerCase();
  if (type === "carjellyimage") return "exterior";
  if (type === "exterior" || type === "interior") return type;
  if (href.includes("interior")) return "interior";
  if (
    href.includes("jellies") ||
    href.includes("jelly") ||
    href.includes("profile-jellies") ||
    href.includes("exterior")
  ) {
    return "exterior";
  }
  return "exterior";
}

function pdfHeroImageScore(item) {
  if (is360MediaItem(item)) return -1000;
  const type = String(item?.media_type || "").toLowerCase();
  const href = pdfNormalizeMediaUrl(item?.href).toLowerCase();
  if (type === "carjellyimage") return 100;
  if (href.includes("interior")) return -100;
  if (href.includes("jellies") || href.includes("jelly") || href.includes("profile-jellies")) return 85;
  if (type === "exterior" || href.includes("exterior")) return 70;
  if (type === "image") return 20;
  return 10;
}

function pickCarJellyImageUrl(data) {
  const media = (data?.media || []).filter((item) => item?.href && !is360MediaItem(item));
  if (!media.length) return null;
  const ranked = [...media].sort(
    (a, b) => pdfHeroImageScore(b) - pdfHeroImageScore(a) || pdfMediaSizeScore(b.media_size) - pdfMediaSizeScore(a.media_size)
  );
  return pdfNormalizeMediaUrl(ranked[0]?.href || null);
}

const PDF_EXTERIOR_TAG_ORDER = [
  "DS front 7/8",
  "DS front 3/4",
  "DS profile",
  "DS rear 7/8",
  "DS rear 3/4",
];

const PDF_INTERIOR_TAG_ORDER = ["IP/dash", "Buck", "Rear seat profile"];

function pdfMediaSizeScore(size) {
  const value = String(size || "").toLowerCase();
  if (value.includes("1200")) return 4;
  if (value.includes("864")) return 3;
  if (value.includes("680")) return 2;
  if (value.includes("380")) return 1;
  if (value.includes("1024")) return 3;
  if (value.includes("640")) return 2;
  return 0;
}

function pickPdfMediaViews(data, mediaType, maxCount) {
  const normalizedType = String(mediaType || "").toLowerCase();
  const media = (data?.media || []).filter((item) => {
    if (!item?.href || is360MediaItem(item)) return false;
    return pdfNormalizedMediaType(item) === normalizedType;
  });
  const byTag = new Map();
  for (const item of media) {
    const tag = String(item.image_tag || item.media_size || "View").trim() || "View";
    const existing = byTag.get(tag);
    if (!existing || pdfMediaSizeScore(item.media_size) > pdfMediaSizeScore(existing.media_size)) {
      byTag.set(tag, item);
    }
  }

  const tagOrder =
    normalizedType === "exterior"
      ? PDF_EXTERIOR_TAG_ORDER
      : normalizedType === "interior"
        ? PDF_INTERIOR_TAG_ORDER
        : [];
  const picked = [];
  for (const tag of tagOrder) {
    if (byTag.has(tag)) {
      picked.push(byTag.get(tag));
      byTag.delete(tag);
    }
    if (picked.length >= maxCount) {
      return picked;
    }
  }
  const remaining = [...byTag.values()].sort(
    (a, b) => pdfMediaSizeScore(b.media_size) - pdfMediaSizeScore(a.media_size)
  );
  for (const item of remaining) {
    picked.push(item);
    if (picked.length >= maxCount) break;
  }
  return picked;
}

function pdfMediaCaption(item) {
  const href = pdfNormalizeMediaUrl(item?.href).toLowerCase();
  const tag = String(item?.image_tag || "").trim();
  if (tag && tag.toLowerCase() !== "vehicle") {
    return tag.replace(/_/g, " ");
  }
  if (href.includes("interior")) return "Interior";
  if (href.includes("profile-jellies") || href.includes("34-jellies") || href.includes("jellies")) {
    return "Exterior";
  }
  const mediaType = pdfNormalizedMediaType(item);
  if (mediaType === "interior") return "Interior";
  if (mediaType === "exterior") return "Exterior";
  return "View";
}

async function pdfEnsureDataUrl(url) {
  const href = pdfNormalizeMediaUrl(url);
  if (!href) return "";
  const cache = window.VitImageCache;
  if (!cache?.getDataUrl) return "";
  let resolved = "";
  try {
    resolved = await cache.getDataUrl(href);
  } catch {
    resolved = "";
  }
  if (resolved?.startsWith("data:")) {
    return resolved;
  }
  const fetchUrl = resolved || cache.toProxiedUrl?.(href) || href;
  try {
    const response = await fetch(fetchUrl, { credentials: "omit", cache: "force-cache" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    return await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  } catch {
    return "";
  }
}

async function pdfLoadMediaDataUrls(items) {
  const loaded = [];
  for (const item of items) {
    let dataUrl = "";
    const href = pdfNormalizeMediaUrl(item.href);
    if (href) {
      try {
        dataUrl = await pdfEnsureDataUrl(href);
      } catch (_err) {
        dataUrl = "";
      }
    }
    loaded.push({ item, dataUrl });
  }
  return loaded;
}

async function pdfDrawImageInBox(pdf, dataUrl, x, y, boxW, boxH, pad = 8) {
  if (!dataUrl?.startsWith("data:")) return false;
  try {
    const dims = await measureDataUrlImage(dataUrl);
    const maxW = boxW - pad * 2;
    const maxH = boxH - pad * 2;
    const scale = Math.min(maxW / dims.width, maxH / dims.height);
    const drawW = dims.width * scale;
    const drawH = dims.height * scale;
    const drawX = x + (boxW - drawW) / 2;
    const drawY = y + (boxH - drawH) / 2;
    pdf.addImage(
      dataUrl,
      pdfDetectImageFormat(dataUrl),
      drawX,
      drawY,
      drawW,
      drawH,
      undefined,
      "MEDIUM"
    );
    return true;
  } catch {
    return false;
  }
}

async function pdfDrawMediaGallery(pdf, data, margin, contentW, startY, endY) {
  const exteriorItems = await pdfLoadMediaDataUrls(pickPdfMediaViews(data, "exterior", 4));
  const interiorItems = await pdfLoadMediaDataUrls(pickPdfMediaViews(data, "interior", 3));
  const sections = [];
  if (exteriorItems.length) {
    sections.push({
      title: "Exterior Views",
      items: exteriorItems,
      cols: Math.min(4, exteriorItems.length),
    });
  }
  if (interiorItems.length) {
    sections.push({
      title: "Interior Views",
      items: interiorItems,
      cols: Math.min(3, interiorItems.length),
    });
  }
  if (!sections.length) return startY;

  const gap = 6;
  const titleH = 9;
  const captionH = 9;
  const sectionPad = 6;
  const overhead = sections.length * (titleH + captionH + sectionPad + gap) + gap;
  const availableH = Math.max(52, endY - startY - overhead);
  let imgH = Math.max(52, Math.floor(availableH / sections.length));
  let y = startY;

  for (const section of sections) {
    const { title, items, cols } = section;
    const usableW = contentW - 16;
    const cellW = (usableW - gap * (cols - 1)) / cols;
    let rowH = titleH + imgH + captionH + sectionPad;

    while (y + rowH > endY && imgH > 44) {
      imgH -= 4;
      rowH = titleH + imgH + captionH + sectionPad;
    }
    if (y + rowH > endY) {
      break;
    }

    pdfDrawPanel(pdf, margin, y, contentW, rowH);
    pdf.setFont(undefined, "bold");
    pdf.setFontSize(8);
    pdfTextColor(pdf, PDF_COLORS.label);
    pdf.text(title, margin + 8, y + 10);
    pdf.setFont(undefined, "normal");

    const imgY = y + titleH + 2;
    const rowItemCount = items.length;
    const rowWidth = rowItemCount * cellW + Math.max(0, rowItemCount - 1) * gap;
    const rowStartX = margin + 8 + (usableW - rowWidth) / 2;

    for (let index = 0; index < items.length; index += 1) {
      const cellX = rowStartX + index * (cellW + gap);
      const { item, dataUrl } = items[index];

      pdfFill(pdf, PDF_COLORS.statBg);
      pdfStroke(pdf, PDF_COLORS.border);
      pdf.roundedRect(cellX, imgY, cellW, imgH, 2, 2, "FD");
      const drew = await pdfDrawImageInBox(pdf, dataUrl, cellX, imgY, cellW, imgH, 3);
      if (!drew) {
        pdf.setFontSize(7);
        pdfTextColor(pdf, PDF_COLORS.muted);
        pdf.text("N/A", cellX + cellW / 2, imgY + imgH / 2, { align: "center" });
      }
      pdf.setFontSize(6);
      pdfTextColor(pdf, PDF_COLORS.muted);
      const caption = pdf.splitTextToSize(pdfMediaCaption(item), cellW - 4);
      pdf.text(caption.slice(0, 2), cellX + cellW / 2, imgY + imgH + 7, { align: "center" });
    }

    y += rowH + gap;
  }

  return y;
}

function vehicleDisplayLabel(vehicle) {
  const model = (vehicle?.model_marketing_name || "").trim();
  const grade = (vehicle?.grade || "").trim();
  let name = model;
  if (grade && model && !model.toLowerCase().includes(grade.toLowerCase())) {
    name = `${model} ${grade}`;
  }
  return [vehicle?.year, name].filter(Boolean).join(" ") || vehicle?.vin || "Vehicle";
}

function pdfReportTitle(data) {
  return vehicleDisplayLabel(data?.vehicle || {});
}

function pdfFilename(data) {
  const vehicle = data?.vehicle || {};
  const date = new Date().toISOString().slice(0, 10);
  const model = (vehicle.model_marketing_name || "").trim();
  const grade = (vehicle.grade || "").trim();
  let modelLabel = model || "Vehicle";
  if (grade && model && !model.toLowerCase().includes(grade.toLowerCase())) {
    modelLabel = `${model}_${grade}`;
  }
  const parts = [vehicle.year, modelLabel, vehicle.vin, date]
    .filter(Boolean)
    .join("_")
    .replace(/[^\w.-]+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "");
  return `${parts || "vehicle_report"}.pdf`;
}

const PDF_COLORS = {
  bg: [47, 49, 51],
  panel: [51, 53, 56],
  border: [61, 65, 69],
  accent: [255, 198, 109],
  label: [226, 192, 141],
  text: [212, 212, 212],
  muted: [154, 163, 173],
  statBg: [58, 61, 64],
  green: [127, 214, 127],
  red: [255, 138, 138],
};

function formatMsrpDeltaPlain(value) {
  if (value == null || Number.isNaN(Number(value))) return "-";
  const num = Number(value);
  const abs = Math.abs(Math.round(num)).toLocaleString("en-US");
  if (num > 0) return `+$${abs}`;
  if (num < 0) return `-$${abs}`;
  return "$0";
}

function msrpDeltaRgb(value) {
  if (value == null || Number.isNaN(Number(value))) return PDF_COLORS.text;
  const num = Number(value);
  if (num < 0) return PDF_COLORS.green;
  if (num > 0) return PDF_COLORS.red;
  return PDF_COLORS.text;
}

function pdfFill(pdf, rgb) {
  pdf.setFillColor(rgb[0], rgb[1], rgb[2]);
}

function pdfStroke(pdf, rgb) {
  pdf.setDrawColor(rgb[0], rgb[1], rgb[2]);
}

function pdfTextColor(pdf, rgb) {
  pdf.setTextColor(rgb[0], rgb[1], rgb[2]);
}

function pdfFillPage(pdf) {
  const w = pdf.internal.pageSize.getWidth();
  const h = pdf.internal.pageSize.getHeight();
  pdfFill(pdf, PDF_COLORS.bg);
  pdf.rect(0, 0, w, h, "F");
}

function pdfDetectImageFormat(dataUrl) {
  if (dataUrl.startsWith("data:image/jpeg") || dataUrl.startsWith("data:image/jpg")) return "JPEG";
  if (dataUrl.startsWith("data:image/webp")) return "WEBP";
  return "PNG";
}

function measureDataUrlImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve({ width: img.naturalWidth || 1, height: img.naturalHeight || 1 });
    img.onerror = () => reject(new Error("Could not measure image."));
    img.src = dataUrl;
  });
}

function pdfDrawPanel(pdf, x, y, w, h) {
  pdfFill(pdf, PDF_COLORS.panel);
  pdfStroke(pdf, PDF_COLORS.border);
  pdf.roundedRect(x, y, w, h, 4, 4, "FD");
}

function pdfSectionTitle(pdf, title, x, y) {
  pdf.setFont(undefined, "bold");
  pdf.setFontSize(10);
  pdfTextColor(pdf, PDF_COLORS.label);
  pdf.text(title, x, y);
  pdfStroke(pdf, PDF_COLORS.border);
  const w = pdf.getTextWidth(title);
  pdf.line(x, y + 3, x + Math.max(w, 48), y + 3);
  pdf.setFont(undefined, "normal");
}

function pdfSpecMaxLines(label) {
  if (label === "Status") return 4;
  if (label === "Stage" || label === "Exterior" || label === "Interior" || label === "Engine" || label === "Drivetrain") {
    return 2;
  }
  return 1;
}

function pdfMeasureSpecCellHeight(pdf, label, value, w) {
  const maxLines = pdfSpecMaxLines(label);
  const lines = pdf.splitTextToSize(String(value ?? "-"), Math.max(20, w - 2)).slice(0, maxLines);
  const lineCount = Array.isArray(lines) ? lines.length : 1;
  return lineCount > 1 ? 8 + lineCount * 9 : 22;
}

function pdfSpecCell(pdf, label, value, x, y, w, maxLines = 2) {
  pdf.setFontSize(6);
  pdf.setFont(undefined, "bold");
  pdfTextColor(pdf, PDF_COLORS.muted);
  pdf.text(String(label).toUpperCase(), x, y + 7);
  pdf.setFont(undefined, "normal");
  pdf.setFontSize(8);
  pdfTextColor(pdf, PDF_COLORS.text);
  const lines = pdf.splitTextToSize(String(value ?? "-"), Math.max(20, w - 2)).slice(0, maxLines);
  pdf.text(lines, x, y + 16);
  const lineCount = Array.isArray(lines) ? lines.length : 1;
  return lineCount > 1 ? 8 + lineCount * 9 : 22;
}

function pdfLabelValue(pdf, label, value, x, y, maxWidth) {
  pdf.setFontSize(8.5);
  pdfTextColor(pdf, PDF_COLORS.label);
  pdf.text(`${label}:`, x, y);
  const labelWidth = pdf.getTextWidth(`${label}: `);
  pdfTextColor(pdf, PDF_COLORS.text);
  const lines = pdf.splitTextToSize(String(value ?? "-"), Math.max(40, maxWidth - labelWidth - 2));
  pdf.text(lines, x + labelWidth, y);
  return Array.isArray(lines) ? lines.length : 1;
}

function pdfTruncateUrl(url, maxLen = 58) {
  const value = String(url || "").trim();
  if (!value || value === "-") return "-";
  if (value.length <= maxLen) return value;
  return `${value.slice(0, maxLen - 1)}…`;
}

function pdfCompactListingUrl(url) {
  const value = String(url || "").trim();
  if (!value) return "-";
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.replace(/^www\./i, "");
    const vin =
      parsed.searchParams.get("vin") ||
      (parsed.pathname.match(/[A-HJ-NPR-Z0-9]{17}/i) || [])[0] ||
      "";
    if (vin) {
      return `${host}/${vin.toUpperCase()}`;
    }
    const parts = parsed.pathname.split("/").filter(Boolean);
    const tail = parts.slice(-2).join("/") || parsed.pathname.replace(/^\//, "");
    return tail ? `${host}/${tail}` : host;
  } catch {
    return pdfTruncateUrl(value, 58);
  }
}

function pdfSplitUrlToLines(pdf, url, maxWidth, maxLines = 3) {
  const value = String(url || "").trim();
  if (!value || value === "-") return ["-"];
  if (pdf.getTextWidth(value) <= maxWidth) return [value];

  const breakAfter = new Set(["/", "?", "&", "-", "_", "="]);
  const lines = [];
  let start = 0;

  while (start < value.length && lines.length < maxLines) {
    if (lines.length === maxLines - 1) {
      let chunk = value.slice(start);
      if (pdf.getTextWidth(chunk) <= maxWidth) {
        lines.push(chunk);
      } else {
        let end = start + 1;
        while (end <= value.length && pdf.getTextWidth(`${value.slice(start, end)}…`) <= maxWidth) {
          end += 1;
        }
        const trimmedEnd = Math.max(start + 1, end - 1);
        lines.push(`${value.slice(start, trimmedEnd)}…`);
      }
      break;
    }

    let end = start + 1;
    let lastBreak = -1;
    while (end <= value.length) {
      const chunk = value.slice(start, end);
      if (breakAfter.has(value[end - 1])) {
        lastBreak = end;
      }
      if (pdf.getTextWidth(chunk) > maxWidth) {
        if (lastBreak > start) {
          lines.push(value.slice(start, lastBreak));
          start = lastBreak;
        } else if (end > start + 1) {
          lines.push(value.slice(start, end - 1));
          start = end - 1;
        } else {
          lines.push(value.slice(start, end));
          start = end;
        }
        break;
      }
      if (end === value.length) {
        lines.push(chunk);
        start = value.length;
        break;
      }
      end += 1;
    }
  }

  return lines.length ? lines : [value];
}

function pdfLinkLineCount(pdf, label, url, maxWidth, maxLines = 3, { displayUrl } = {}) {
  pdf.setFontSize(8.5);
  const labelWidth = pdf.getTextWidth(`${label}: `);
  const maxLinkWidth = Math.max(40, maxWidth - labelWidth - 2);
  const linkText = displayUrl ?? url;
  return displayUrl ? 1 : pdfSplitUrlToLines(pdf, linkText, maxLinkWidth, maxLines).length;
}

function pdfIsHttpUrl(value) {
  const url = String(value || "").trim();
  return url.startsWith("http://") || url.startsWith("https://");
}

function pdfLabelLink(pdf, label, url, x, y, maxWidth, { displayUrl } = {}) {
  pdf.setFontSize(8.5);
  pdfTextColor(pdf, PDF_COLORS.label);
  pdf.text(`${label}:`, x, y);
  const labelWidth = pdf.getTextWidth(`${label}: `);
  const linkX = x + labelWidth;
  const maxLinkWidth = Math.max(40, maxWidth - labelWidth - 2);
  const linkText = displayUrl ?? url;
  const lines = displayUrl
    ? [String(linkText)]
    : pdfSplitUrlToLines(pdf, linkText, maxLinkWidth, 3);
  const lineHeight = 11;
  const urlText = String(url || "").trim();

  if (pdfIsHttpUrl(url) && typeof pdf.textWithLink === "function") {
    pdf.setTextColor(PDF_COLORS.accent[0], PDF_COLORS.accent[1], PDF_COLORS.accent[2]);
    lines.forEach((line, index) => {
      pdf.textWithLink(line, linkX, y + index * lineHeight, { url: urlText });
    });
    pdfTextColor(pdf, PDF_COLORS.text);
  } else {
    pdfTextColor(pdf, PDF_COLORS.text);
    pdf.text(lines, linkX, y);
  }
  return lines.length;
}

function multiPdfFilename(count) {
  const date = new Date().toISOString().slice(0, 10);
  return `vehicle_inventory_${count}_vehicles_${date}.pdf`;
}

function pdfSummaryRowFromEntry(entry, index) {
  const vehicle = entry.data?.vehicle || {};
  const latest = entry.data?.latest || {};
  const latestPricing = {
    advertized_price: latest.advertized_price,
    non_sp_advertized_price: latest.non_sp_advertized_price,
    total_msrp: latest.total_msrp,
    base_msrp: latest.base_msrp,
  };
  return {
    num: String(index + 1),
    title: pdfReportTitle(entry.data),
    vin: vehicle.vin || "-",
    stock: latest.stock_num || "-",
    dealer: latest.dealer_marketing_name || latest.dealer_cd || "-",
    exterior: vehicle.exterior_color_name || "-",
    interior: vehicle.interior_color_name || "-",
    price: formatMoney(effectiveSalePrice(latestPricing)),
    msrp: formatMoney(effectiveMsrp(latestPricing)),
    delta: formatMsrpDeltaPlain(msrpDeltaValue(latestPricing)),
    status: latest.inventory_status || "-",
    stage: latest.allocation_stage_label || latest.allocation_stage_code || "-",
  };
}

function pdfSummaryColumns(contentW) {
  const fixed = [
    { key: "num", label: "#", w: 14, align: "center" },
    { key: "title", label: "Vehicle", w: 56 },
    { key: "vin", label: "VIN", w: 52 },
    { key: "stock", label: "Stock", w: 26 },
    { key: "dealer", label: "Dealer", w: 60 },
    { key: "exterior", label: "Exterior", w: 52 },
    { key: "interior", label: "Interior", w: 52 },
    { key: "price", label: "Price", w: 36, align: "right" },
    { key: "msrp", label: "MSRP", w: 36, align: "right" },
    { key: "delta", label: "Diff", w: 34, align: "right" },
  ];
  const used = fixed.reduce((sum, col) => sum + col.w, 0);
  return [...fixed, { key: "status", label: "Status", w: Math.max(60, contentW - used) }];
}

function pdfSummaryCellMaxLines(key) {
  if (key === "status") return 3;
  if (key === "dealer" || key === "title" || key === "exterior" || key === "interior") return 2;
  return 1;
}

function pdfSummaryColorSwatchKey(key) {
  if (key === "exterior") return "exteriorSwatch";
  if (key === "interior") return "interiorSwatch";
  return null;
}

function pdfDrawSummaryTableHeader(pdf, cols, x, y) {
  pdf.setFont(undefined, "bold");
  pdf.setFontSize(7);
  pdfTextColor(pdf, PDF_COLORS.label);
  let colX = x;
  for (const col of cols) {
    const textX = col.align === "right" ? colX + col.w - 2 : colX + 2;
    pdf.text(col.label, textX, y, { align: col.align === "right" ? "right" : "left" });
    colX += col.w;
  }
  pdfStroke(pdf, PDF_COLORS.border);
  pdf.line(x, y + 4, x + cols.reduce((sum, col) => sum + col.w, 0), y + 4);
  pdf.setFont(undefined, "normal");
}

function pdfDrawSummaryTableRow(pdf, cols, row, x, y, rowH) {
  pdf.setFontSize(6.5);
  pdfTextColor(pdf, PDF_COLORS.text);
  let colX = x;
  for (const col of cols) {
    const raw = String(row[col.key] ?? "-");
    const maxLines = pdfSummaryCellMaxLines(col.key);
    const swatchKey = pdfSummaryColorSwatchKey(col.key);
    const swatch = swatchKey ? row[swatchKey] : null;
    const hasSwatch = Boolean(swatch && raw !== "-");
    const textInset = hasSwatch ? PDF_SWATCH_SIZE + PDF_SWATCH_GAP : 2;
    const textWidth = Math.max(12, col.w - textInset - 2);
    const lines = pdf.splitTextToSize(raw, textWidth).slice(0, maxLines);
    if (hasSwatch) {
      pdfDrawSwatch(pdf, colX + 2, y + 10, PDF_SWATCH_SIZE, swatch);
    }
    const textX = col.align === "right" ? colX + col.w - 2 : colX + textInset;
    pdf.text(lines, textX, y + 10, { align: col.align === "right" ? "right" : "left" });
    colX += col.w;
  }
  pdfStroke(pdf, PDF_COLORS.border);
  pdf.line(x, y + rowH - 2, x + cols.reduce((sum, col) => sum + col.w, 0), y + rowH - 2);
}

function pdfMeasureSummaryRowHeight(pdf, cols, row) {
  let rowH = 18;
  for (const col of cols) {
    const raw = String(row[col.key] ?? "-");
    const maxLines = pdfSummaryCellMaxLines(col.key);
    const swatchKey = pdfSummaryColorSwatchKey(col.key);
    const hasSwatch = Boolean(swatchKey && row[swatchKey] && raw !== "-");
    const textInset = hasSwatch ? PDF_SWATCH_SIZE + PDF_SWATCH_GAP : 2;
    const lines = pdf.splitTextToSize(raw, Math.max(12, col.w - textInset - 2)).slice(0, maxLines);
    const lineCount = Array.isArray(lines) ? lines.length : 1;
    rowH = Math.max(rowH, 8 + lineCount * 8);
  }
  return rowH;
}

function pdfFilterLabels(filterId, maxItems = 5) {
  const values = selectedMultiValues(qs(filterId)).map((value) => resolveFilterLabel(filterId, value));
  if (values.length <= maxItems) {
    return values;
  }
  return [...values.slice(0, maxItems), `${values.length - maxItems} more`];
}

function pdfFilterListTokens(labels) {
  const tokens = [];
  labels.forEach((label, index) => {
    if (index > 0) {
      tokens.push({ text: index === labels.length - 1 ? " and " : ", ", bold: false });
    }
    tokens.push({ text: label, bold: true });
  });
  return tokens;
}

function facetColorSwatchInfo(filterId, value) {
  if (filterId === "exterior-color-values") {
    const item = (facetItemCache[filterId] || []).find((entry) => getFacetItemValue(entry) === value);
    return {
      label: resolveFilterLabel(filterId, value),
      hex: item?.exterior_color_hex || null,
      swatchUrl: item?.exterior_color_swatch || null,
    };
  }
  if (filterId === "interior-color-values") {
    const item = (facetItemCache[filterId] || []).find((entry) => getFacetItemValue(entry) === value);
    return {
      label: resolveFilterLabel(filterId, value),
      hex: null,
      swatchUrl: item?.interior_color_swatch || null,
    };
  }
  return null;
}

function pdfFilterColorEntries(filterId, maxItems = 5) {
  const values = selectedMultiValues(qs(filterId));
  const entries = values.map((value) => facetColorSwatchInfo(filterId, value)).filter(Boolean);
  if (entries.length <= maxItems) {
    return entries;
  }
  return [...entries.slice(0, maxItems), { label: `${entries.length - maxItems} more`, isOverflow: true }];
}

function pdfFilterColorListTokens(entries) {
  const tokens = [];
  entries.forEach((entry, index) => {
    if (index > 0) {
      tokens.push({ text: index === entries.length - 1 ? " and " : ", ", bold: false });
    }
    if (entry.isOverflow) {
      tokens.push({ text: entry.label, bold: true });
    } else {
      tokens.push({ color: entry, bold: true });
    }
  });
  return tokens;
}

const PDF_SWATCH_SIZE = 7;
const PDF_SWATCH_GAP = 3;

function pdfParseHexColor(hex) {
  if (!hex) return null;
  const clean = String(hex).replace("#", "").trim();
  if (!/^[0-9a-fA-F]{6}$/.test(clean)) return null;
  return [parseInt(clean.slice(0, 2), 16), parseInt(clean.slice(2, 4), 16), parseInt(clean.slice(4, 6), 16)];
}

function pdfDrawSwatch(pdf, x, baselineY, size, { hex, dataUrl }) {
  const top = baselineY - size + 2;
  if (dataUrl && String(dataUrl).startsWith("data:")) {
    try {
      pdf.addImage(dataUrl, pdfDetectImageFormat(dataUrl), x, top, size, size);
      pdfStroke(pdf, PDF_COLORS.border);
      pdf.rect(x, top, size, size, "S");
      return;
    } catch {
      // fall through to hex or placeholder
    }
  }
  const rgb = pdfParseHexColor(hex);
  pdfStroke(pdf, PDF_COLORS.border);
  if (rgb) {
    pdf.setFillColor(rgb[0], rgb[1], rgb[2]);
    pdf.rect(x, top, size, size, "FD");
    return;
  }
  pdfFill(pdf, PDF_COLORS.statBg);
  pdf.rect(x, top, size, size, "FD");
}

function pdfRichTextTokenWidth(pdf, segment, fontSize) {
  if (segment.color) {
    pdf.setFont(undefined, segment.bold ? "bold" : "normal");
    pdf.setFontSize(fontSize);
    return PDF_SWATCH_SIZE + PDF_SWATCH_GAP + pdf.getTextWidth(segment.color.label);
  }
  pdf.setFont(undefined, segment.bold ? "bold" : "normal");
  pdf.setFontSize(fontSize);
  return pdf.getTextWidth(segment.text);
}

async function pdfPrepareColorTokens(tokens) {
  const prepared = [];
  for (const token of tokens) {
    if (!token.color) {
      prepared.push(token);
      continue;
    }
    let dataUrl = "";
    if (token.color.swatchUrl && window.VitImageCache?.getDataUrl) {
      try {
        dataUrl = await VitImageCache.getDataUrl(token.color.swatchUrl);
      } catch {
        dataUrl = "";
      }
    }
    prepared.push({
      ...token,
      color: {
        ...token.color,
        dataUrl,
      },
    });
  }
  return prepared;
}

async function pdfPrepareSwatchInfo(info) {
  if (!info) return null;
  let dataUrl = "";
  if (info.swatchUrl && window.VitImageCache?.getDataUrl) {
    try {
      dataUrl = await VitImageCache.getDataUrl(info.swatchUrl);
    } catch {
      dataUrl = "";
    }
  }
  return { ...info, dataUrl };
}

function pdfHasAnyInventoryFilters() {
  const { stateCodes, searchZip, distanceMax } = getLocationFilterParams();
  const vinQuery = qs("vin-query")?.value.trim() || "";
  const stockQuery = qs("stock-query")?.value.trim() || "";
  const hasPriceFilter =
    histogramState.min != null && histogramState.max != null && histogramState.metric;
  return Boolean(
    selectedMultiValues(qs("series-values")).length ||
      selectedMultiValues(qs("model-values")).length ||
      selectedMultiValues(qs("dealer-values")).length ||
      selectedMultiValues(qs("state-codes")).length ||
      selectedMultiValues(qs("exterior-color-values")).length ||
      selectedMultiValues(qs("interior-color-values")).length ||
      selectedMultiValues(qs("drivetrain-codes")).length ||
      selectedMultiValues(qs("stage-codes")).length ||
      selectedMultiValues(qs("option-codes")).length ||
      (searchZip && distanceMax) ||
      stateCodes.length ||
      vinQuery ||
      stockQuery ||
      hasPriceFilter ||
      !qs("active-only")?.checked
  );
}

function buildPdfFilterSummaryBullets() {
  if (!pdfHasAnyInventoryFilters()) {
    return [{ tokens: [{ text: "All active inventory with no additional filters applied.", bold: false }] }];
  }

  const bullets = [];
  const pushBullet = (label, valueTokens) => {
    if (!valueTokens.length) return;
    bullets.push({
      tokens: [{ text: `${label}: `, bold: false }, ...valueTokens],
    });
  };

  const series = pdfFilterLabels("series-values");
  const models = pdfFilterLabels("model-values");
  const dealers = pdfFilterLabels("dealer-values");
  const states = pdfFilterLabels("state-codes");
  const exterior = pdfFilterColorEntries("exterior-color-values");
  const interior = pdfFilterColorEntries("interior-color-values");
  const drivetrains = pdfFilterLabels("drivetrain-codes");
  const stages = pdfFilterLabels("stage-codes");
  const options = pdfFilterLabels("option-codes");
  const { searchZip, distanceMax } = getLocationFilterParams();
  const vinQuery = qs("vin-query")?.value.trim() || "";
  const stockQuery = qs("stock-query")?.value.trim() || "";

  if (series.length) pushBullet("Series", pdfFilterListTokens(series));
  if (models.length) pushBullet(series.length ? "Trims" : "Models", pdfFilterListTokens(models));
  if (dealers.length) pushBullet("Dealers", pdfFilterListTokens(dealers));
  if (states.length) {
    pushBullet("States", pdfFilterListTokens(states));
  } else if (searchZip && distanceMax) {
    pushBullet("Location", [
      { text: `${distanceMax} miles of ZIP `, bold: false },
      { text: searchZip, bold: true },
    ]);
  }
  if (exterior.length) pushBullet("Exterior", pdfFilterColorListTokens(exterior));
  if (interior.length) pushBullet("Interior", pdfFilterColorListTokens(interior));
  if (drivetrains.length) pushBullet("Drivetrain", pdfFilterListTokens(drivetrains));
  if (stages.length) pushBullet("Stage", pdfFilterListTokens(stages));
  if (options.length) pushBullet("Options", pdfFilterListTokens(options));
  if (vinQuery) pushBullet("VIN", [{ text: vinQuery, bold: true }]);
  if (stockQuery) pushBullet("Stock", [{ text: stockQuery, bold: true }]);

  if (histogramState.min != null && histogramState.max != null && histogramState.metric) {
    const metricLabel = histogramState.metric === "total_msrp" ? "MSRP" : "Advertised price";
    pushBullet("Price", [
      { text: metricLabel, bold: true },
      { text: " from ", bold: false },
      { text: formatMoney(histogramState.min), bold: true },
      { text: " to ", bold: false },
      { text: formatMoney(histogramState.max), bold: true },
    ]);
  }

  if (!qs("active-only")?.checked) {
    pushBullet("Inventory", [{ text: "Including inactive vehicles", bold: true }]);
  }

  return bullets;
}

async function pdfPrepareFilterBullets(bullets) {
  const prepared = [];
  for (const bullet of bullets) {
    prepared.push({
      tokens: await pdfPrepareColorTokens(bullet.tokens),
    });
  }
  return prepared;
}

async function pdfPrepareSummaryRows(entries) {
  const rows = [];
  for (let i = 0; i < entries.length; i += 1) {
    const entry = entries[i];
    const vehicle = entry.data?.vehicle || {};
    const row = pdfSummaryRowFromEntry(entry, i);
    row.exteriorSwatch = await pdfPrepareSwatchInfo({
      hex: vehicle.exterior_color_hex || null,
      swatchUrl: vehicle.exterior_color_swatch || null,
    });
    row.interiorSwatch = await pdfPrepareSwatchInfo({
      hex: null,
      swatchUrl: vehicle.interior_color_swatch || null,
    });
    rows.push(row);
  }
  return rows;
}

function pdfMeasureRichTextBlockHeight(pdf, tokens, maxWidth, fontSize = 8.5) {
  const lineHeight = fontSize + 3;
  const lines = pdfLayoutRichTextLines(pdf, tokens, maxWidth, fontSize);
  return Math.max(lineHeight, lines.length * lineHeight);
}

function pdfDrawBulletList(pdf, bullets, x, y, maxWidth, fontSize = 8) {
  const bulletIndent = 10;
  const bulletGap = 3;
  let cursorY = y;
  for (const bullet of bullets) {
    pdf.setFont(undefined, "normal");
    pdf.setFontSize(fontSize);
    pdfTextColor(pdf, PDF_COLORS.label);
    pdf.text("•", x, cursorY);
    const blockHeight = pdfDrawRichTextBlock(
      pdf,
      bullet.tokens,
      x + bulletIndent,
      cursorY,
      maxWidth - bulletIndent,
      fontSize
    );
    cursorY += blockHeight + bulletGap;
  }
  return Math.max(fontSize + 3, cursorY - y - bulletGap);
}

function pdfLayoutRichTextLines(pdf, tokens, maxWidth, fontSize = 8.5) {
  pdf.setFontSize(fontSize);
  const lines = [];
  let currentLine = [];
  let currentWidth = 0;

  for (const token of tokens) {
    if (token.color) {
      const segment = { color: token.color, bold: token.bold };
      const segmentWidth = pdfRichTextTokenWidth(pdf, segment, fontSize);
      if (currentWidth + segmentWidth > maxWidth && currentLine.length) {
        lines.push(currentLine);
        currentLine = [];
        currentWidth = 0;
      }
      currentLine.push(segment);
      currentWidth += segmentWidth;
      continue;
    }

    pdf.setFont(undefined, token.bold ? "bold" : "normal");
    const parts = String(token.text).match(/\S+\s*/g) || [token.text];
    for (const part of parts) {
      const partWidth = pdf.getTextWidth(part);
      if (currentWidth + partWidth > maxWidth && currentLine.length) {
        lines.push(currentLine);
        currentLine = [];
        currentWidth = 0;
      }
      currentLine.push({ text: part, bold: token.bold });
      currentWidth += partWidth;
    }
  }
  if (currentLine.length) {
    lines.push(currentLine);
  }
  return lines;
}

function pdfDrawRichTextBlock(pdf, tokens, x, y, maxWidth, fontSize = 8.5) {
  const lineHeight = fontSize + 3;
  const lines = pdfLayoutRichTextLines(pdf, tokens, maxWidth, fontSize);
  lines.forEach((line, index) => {
    let cursorX = x;
    const lineY = y + index * lineHeight;
    for (const segment of line) {
      if (segment.color) {
        pdfDrawSwatch(pdf, cursorX, lineY, PDF_SWATCH_SIZE, segment.color);
        cursorX += PDF_SWATCH_SIZE + PDF_SWATCH_GAP;
        pdf.setFont(undefined, segment.bold ? "bold" : "normal");
        pdf.setFontSize(fontSize);
        pdfTextColor(pdf, segment.bold ? PDF_COLORS.label : PDF_COLORS.text);
        pdf.text(segment.color.label, cursorX, lineY);
        cursorX += pdf.getTextWidth(segment.color.label);
        continue;
      }
      pdf.setFont(undefined, segment.bold ? "bold" : "normal");
      pdf.setFontSize(fontSize);
      pdfTextColor(pdf, segment.bold ? PDF_COLORS.label : PDF_COLORS.text);
      pdf.text(segment.text, cursorX, lineY);
      cursorX += pdf.getTextWidth(segment.text);
    }
  });
  return Math.max(lineHeight, lines.length * lineHeight);
}

function pdfMeasureSpecColorCellHeight(pdf, label, value, w) {
  const maxLines = pdfSpecMaxLines(label);
  const swatchOffset = PDF_SWATCH_SIZE + PDF_SWATCH_GAP;
  const lines = pdf.splitTextToSize(String(value ?? "-"), Math.max(20, w - swatchOffset - 2)).slice(0, maxLines);
  const lineCount = Array.isArray(lines) ? lines.length : 1;
  return lineCount > 1 ? 8 + lineCount * 9 : 22;
}

function pdfSpecColorCell(pdf, label, value, swatch, x, y, w, maxLines = 2) {
  const swatchOffset = PDF_SWATCH_SIZE + PDF_SWATCH_GAP;
  pdf.setFontSize(6);
  pdf.setFont(undefined, "bold");
  pdfTextColor(pdf, PDF_COLORS.muted);
  pdf.text(String(label).toUpperCase(), x, y + 7);
  pdf.setFont(undefined, "normal");
  pdf.setFontSize(8);
  pdfTextColor(pdf, PDF_COLORS.text);
  pdfDrawSwatch(pdf, x, y + 16, PDF_SWATCH_SIZE, swatch);
  const lines = pdf.splitTextToSize(String(value ?? "-"), Math.max(20, w - swatchOffset - 2)).slice(0, maxLines);
  pdf.text(lines, x + swatchOffset, y + 16);
  const lineCount = Array.isArray(lines) ? lines.length : 1;
  return lineCount > 1 ? 8 + lineCount * 9 : 22;
}

async function renderPdfPacketSummaryPages(pdf, entries) {
  const margin = 28;
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const contentW = pageW - margin * 2;
  const footerY = pageH - 14;
  const cols = pdfSummaryColumns(contentW);
  const tableW = cols.reduce((sum, col) => sum + col.w, 0);
  const [preparedFilterBullets, rows] = await Promise.all([
    pdfPrepareFilterBullets(buildPdfFilterSummaryBullets()),
    pdfPrepareSummaryRows(entries),
  ]);
  let pageCount = 0;
  let rowIndex = 0;

  while (rowIndex < rows.length) {
    if (pageCount > 0) {
      pdf.addPage();
      pdfFillPage(pdf);
    }
    pageCount += 1;

    pdfFill(pdf, PDF_COLORS.accent);
    pdf.rect(0, 0, pageW, 3, "F");

    let y = margin;
    pdf.setFont(undefined, "bold");
    pdf.setFontSize(18);
    pdfTextColor(pdf, PDF_COLORS.accent);
    pdf.text("Inventory Packet Summary", margin, y + 14);
    y += 24;

    pdf.setFont(undefined, "normal");
    pdf.setFontSize(9);
    pdfTextColor(pdf, PDF_COLORS.muted);
    const sortCol = INVENTORY_TABLE_COLUMNS.find((col) => col.key === sortState.key);
    const sortLabel = sortCol?.label || sortState.key.replaceAll("_", " ");
    const subtitle =
      pageCount === 1
        ? `${entries.length} vehicles · Sorted by ${sortLabel} (${sortState.dir}) · ${new Date().toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
        : `Summary continued (${rowIndex + 1}-${entries.length})`;
    pdf.text(subtitle, margin, y);
    y += 14;

    if (pageCount === 1 && preparedFilterBullets.length) {
      pdf.setFont(undefined, "bold");
      pdf.setFontSize(8.5);
      pdfTextColor(pdf, PDF_COLORS.label);
      pdf.text("Active filters", margin, y);
      y += 12;
      pdf.setFont(undefined, "normal");
      pdfTextColor(pdf, PDF_COLORS.text);
      const filterBlockHeight = pdfDrawBulletList(pdf, preparedFilterBullets, margin, y, contentW, 8);
      y += filterBlockHeight + 10;
    }

    pdfDrawPanel(pdf, margin, y, tableW + 8, Math.min(footerY - y - 8, pageH - y - 40));
    const tableX = margin + 4;
    y += 10;
    pdfDrawSummaryTableHeader(pdf, cols, tableX, y);
    y += 12;

    while (rowIndex < rows.length) {
      const row = rows[rowIndex];
      const rowH = pdfMeasureSummaryRowHeight(pdf, cols, row);
      if (y + rowH > footerY - 6) {
        break;
      }
      pdfDrawSummaryTableRow(pdf, cols, row, tableX, y, rowH);
      y += rowH;
      rowIndex += 1;
    }

    pdf.setFontSize(7);
    pdfTextColor(pdf, PDF_COLORS.muted);
    pdf.text(`Vehicle Inventory Packet · Summary page ${pageCount}`, margin, footerY);
    pdf.text(`${entries.length} vehicles`, pageW - margin, footerY, { align: "right" });
  }

  return pageCount;
}

async function renderVehiclePdfPage(pdf, data, imageDataUrl, { pageNumber = 1, pageCount = 1 } = {}) {
  const vehicle = data?.vehicle || {};
  const latest = data?.latest || {};
  const latestPricing = {
    advertized_price: latest.advertized_price,
    non_sp_advertized_price: latest.non_sp_advertized_price,
    total_msrp: latest.total_msrp,
    base_msrp: latest.base_msrp,
  };
  const salePrice = effectiveSalePrice(latestPricing);
  const msrp = effectiveMsrp(latestPricing);
  const msrpDelta = msrpDeltaValue(latestPricing);

  const margin = 28;
  const pageW = pdf.internal.pageSize.getWidth();
  const pageH = pdf.internal.pageSize.getHeight();
  const contentW = pageW - margin * 2;
  const footerY = pageH - 14;
  let y = margin;

  pdfFill(pdf, PDF_COLORS.accent);
  pdf.rect(0, 0, pageW, 3, "F");

  pdf.setFont(undefined, "bold");
  pdf.setFontSize(17);
  pdfTextColor(pdf, PDF_COLORS.accent);
  pdf.text(pdfReportTitle(data), margin, y + 13);
  pdf.setFont(undefined, "normal");
  pdf.setFontSize(8.5);
  pdfTextColor(pdf, PDF_COLORS.muted);
  const vinLine = [`VIN ${vehicle.vin || "-"}`, latest.stock_num ? `Stock # ${latest.stock_num}` : ""]
    .filter(Boolean)
    .join("  ·  ");
  pdf.text(vinLine, margin, y + 26);
  pdf.text(
    new Date().toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
    pageW - margin,
    y + 13,
    { align: "right" }
  );
  y += 34;

  const heroH = 118;
  pdfDrawPanel(pdf, margin, y, contentW, heroH);
  if (imageDataUrl && imageDataUrl.startsWith("data:")) {
    try {
      const dims = await measureDataUrlImage(imageDataUrl);
      const pad = 6;
      const maxW = contentW - pad * 2;
      const maxH = heroH - pad * 2;
      const scale = Math.min(maxW / dims.width, maxH / dims.height);
      const drawW = dims.width * scale;
      const drawH = dims.height * scale;
      const drawX = margin + (contentW - drawW) / 2;
      const drawY = y + (heroH - drawH) / 2;
      pdf.addImage(
        imageDataUrl,
        pdfDetectImageFormat(imageDataUrl),
        drawX,
        drawY,
        drawW,
        drawH,
        undefined,
        "MEDIUM"
      );
    } catch {
      pdf.setFontSize(8);
      pdfTextColor(pdf, PDF_COLORS.muted);
      pdf.text("Image unavailable", margin + contentW / 2, y + heroH / 2, { align: "center" });
    }
  } else {
    pdf.setFontSize(8);
    pdfTextColor(pdf, PDF_COLORS.muted);
    pdf.text("No image available", margin + contentW / 2, y + heroH / 2, { align: "center" });
  }
  y += heroH + 6;

  const exteriorSwatch = await pdfPrepareSwatchInfo({
    hex: vehicle.exterior_color_hex || null,
    swatchUrl: vehicle.exterior_color_swatch || null,
  });
  const interiorSwatch = await pdfPrepareSwatchInfo({
    hex: null,
    swatchUrl: vehicle.interior_color_swatch || null,
  });

  const specs = [
    { label: "Series", value: vehicle.marketing_series || vehicle.series_code || "-" },
    { label: "Drivetrain", value: vehicle.drivetrain_title || vehicle.drivetrain_code || "-" },
    { label: "Engine", value: vehicle.engine_name || "-" },
    { label: "Exterior", value: vehicle.exterior_color_name || "-", swatch: exteriorSwatch },
    { label: "Interior", value: vehicle.interior_color_name || "-", swatch: interiorSwatch },
  ];
  const status = latest.inventory_status;
  const stage = latest.allocation_stage_label || latest.allocation_stage_code;
  if (status && status !== "-") specs.push({ label: "Status", value: status });
  if (stage && stage !== "-") specs.push({ label: "Stage", value: stage });

  const specCols = 3;
  const specColW = contentW / specCols;
  const specRows = [];
  for (let i = 0; i < specs.length; i += specCols) {
    let rowH = 22;
    for (let c = 0; c < specCols; c += 1) {
      const spec = specs[i + c];
      if (!spec) continue;
      rowH = Math.max(
        rowH,
        spec.swatch
          ? pdfMeasureSpecColorCellHeight(pdf, spec.label, spec.value, specColW - 10)
          : pdfMeasureSpecCellHeight(pdf, spec.label, spec.value, specColW - 10)
      );
    }
    specRows.push(rowH);
  }
  const specPanelH = specRows.reduce((sum, h) => sum + h, 0) + 8;
  pdfDrawPanel(pdf, margin, y, contentW, specPanelH);
  let specRowY = y + 6;
  let specIndex = 0;
  for (const rowH of specRows) {
    for (let c = 0; c < specCols && specs[specIndex]; c += 1) {
      const spec = specs[specIndex];
      const cellX = margin + 8 + c * specColW;
      const cellW = specColW - 10;
      const maxLines = pdfSpecMaxLines(spec.label);
      if (spec.swatch) {
        pdfSpecColorCell(pdf, spec.label, spec.value, spec.swatch, cellX, specRowY, cellW, maxLines);
      } else {
        pdfSpecCell(pdf, spec.label, spec.value, cellX, specRowY, cellW, maxLines);
      }
      specIndex += 1;
    }
    specRowY += rowH;
  }
  y += specPanelH + 6;

  const listingUrl = String(latest.vdp_url || "").trim();
  const dealerWebsite = String(latest.dealer_website || "").trim();
  const topOptions = (data.options || [])
    .slice(0, 8)
    .map((opt) => plainTextFromHtml(opt.marketing_name || opt.option_cd))
    .filter(Boolean);

  const dealerColW = contentW * 0.33 - 16;
  pdf.setFontSize(8.5);
  const websiteLineCount = dealerWebsite ? pdfLinkLineCount(pdf, "Website", dealerWebsite, dealerColW) : 0;
  const listingLineCount = listingUrl
    ? pdfLinkLineCount(pdf, "Listing", listingUrl, dealerColW, 3, {
        displayUrl: pdfCompactListingUrl(listingUrl),
      })
    : 0;

  let infoH = 50;
  if (dealerWebsite) infoH += websiteLineCount * 11;
  if (listingUrl) infoH += listingLineCount * 11;
  infoH = Math.max(62, infoH);

  pdfDrawPanel(pdf, margin, y, contentW, infoH);
  const col1W = contentW * 0.34;
  const col2W = contentW * 0.33;
  const col3W = contentW - col1W - col2W;
  const col1X = margin + 8;
  const col2X = margin + col1W;
  const col3X = margin + col1W + col2W;

  pdfSectionTitle(pdf, "Pricing", col1X, y + 12);
  const stats = [
    ["Price", formatMoney(salePrice), PDF_COLORS.text],
    ["MSRP", formatMoney(msrp), PDF_COLORS.text],
    ["Diff", formatMsrpDeltaPlain(msrpDelta), msrpDeltaRgb(msrpDelta)],
  ];
  stats.forEach((stat, index) => {
    const sy = y + 20 + index * 14;
    pdf.setFontSize(7);
    pdfTextColor(pdf, PDF_COLORS.muted);
    pdf.text(stat[0].toUpperCase(), col1X, sy);
    pdf.setFontSize(10);
    pdf.setFont(undefined, "bold");
    pdfTextColor(pdf, stat[2]);
    pdf.text(String(stat[1]), col1X + 42, sy);
    pdf.setFont(undefined, "normal");
  });

  pdfSectionTitle(pdf, "Dealer", col2X + 8, y + 12);
  let dy = y + 22;
  pdfLabelValue(pdf, "Name", latest.dealer_marketing_name || latest.dealer_cd || "-", col2X + 8, dy, col2W - 16);
  dy += 12;
  pdfLabelValue(pdf, "Distance", `${latest.distance ?? "-"} mi`, col2X + 8, dy, col2W - 16);
  dy += 12;
  if (dealerWebsite) {
    dy += pdfLabelLink(pdf, "Website", dealerWebsite, col2X + 8, dy, col2W - 16) * 11;
  }
  if (listingUrl) {
    dy +=
      pdfLabelLink(pdf, "Listing", listingUrl, col2X + 8, dy, col2W - 16, {
        displayUrl: pdfCompactListingUrl(listingUrl),
      }) * 11;
  }

  if (topOptions.length) {
    pdfSectionTitle(pdf, "Options", col3X + 8, y + 12);
    pdf.setFontSize(7);
    pdfTextColor(pdf, PDF_COLORS.text);
    const optColW = (col3W - 20) / 2;
    topOptions.slice(0, 6).forEach((opt, index) => {
      const col = index % 2;
      const row = Math.floor(index / 2);
      const ox = col3X + 8 + col * optColW;
      const oy = y + 22 + row * 10;
      const line = pdf.splitTextToSize(opt, optColW - 8).slice(0, 1)[0] || opt;
      pdf.text(`• ${line}`, ox, oy);
    });
  }

  y += infoH + 6;

  const hasGalleryMedia = (data?.media || []).some((item) => {
    const type = pdfNormalizedMediaType(item);
    return type === "exterior" || type === "interior";
  });
  const has360Media = (data?.media || []).some((item) => is360MediaItem(item));
  const footerReserve = has360Media ? 30 : 20;
  const galleryEndY = footerY - footerReserve;
  if (hasGalleryMedia && y + 80 < galleryEndY) {
    y = await pdfDrawMediaGallery(pdf, data, margin, contentW, y, galleryEndY);
  }
  if (has360Media) {
    pdf.setFontSize(7);
    pdfTextColor(pdf, PDF_COLORS.muted);
    const noteY = Math.min(y + 8, footerY - 18);
    const noteLines = pdf.splitTextToSize(
      "360° interior panorama available in the online listing (omitted from PDF).",
      contentW
    );
    pdf.text(noteLines.slice(0, 2), margin, noteY);
  }

  pdf.setFontSize(7);
  pdfTextColor(pdf, PDF_COLORS.muted);
  const footerLeft =
    pageCount > 1
      ? `Vehicle Inventory Report · Run ${latest.run_id ?? "-"} · Page ${pageNumber} of ${pageCount}`
      : `Vehicle Inventory Report · Run ${latest.run_id ?? "-"}`;
  pdf.text(footerLeft, margin, footerY);
  pdf.text(vehicle.vin || "", pageW - margin, footerY, { align: "right" });
}

async function renderVehiclePdfDocument(data, imageDataUrl) {
  const JsPDF = getJsPDFConstructor();
  const pdf = new JsPDF({ orientation: "portrait", unit: "pt", format: "letter", compress: true });
  pdfFillPage(pdf);
  await renderVehiclePdfPage(pdf, data, imageDataUrl);
  pdf.save(pdfFilename(data));
}

async function renderMultiVehiclePdfDocument(entries) {
  if (!entries.length) return;
  const JsPDF = getJsPDFConstructor();
  const pdf = new JsPDF({ orientation: "portrait", unit: "pt", format: "letter", compress: true });
  pdfFillPage(pdf);
  const summaryPages = await renderPdfPacketSummaryPages(pdf, entries);
  const totalPages = summaryPages + entries.length;
  for (let i = 0; i < entries.length; i += 1) {
    pdf.addPage();
    pdfFillPage(pdf);
    await renderVehiclePdfPage(pdf, entries[i].data, entries[i].imageDataUrl, {
      pageNumber: summaryPages + i + 1,
      pageCount: totalPages,
    });
  }
  pdf.save(entries.length === 1 ? pdfFilename(entries[0].data) : multiPdfFilename(entries.length));
}

async function fetchOrderedSelectedVins(vins) {
  if (!vins.length) return [];
  const query =
    `${buildInventoryQueryParams(false)}` +
    `&vins=${encodeURIComponent(vins.join(","))}` +
    `&page=1&page_size=${Math.min(vins.length, 200)}`;
  const data = await fetchJson(`/api/inventory?${query}`);
  const ordered = (data.items || []).map((item) => item.vin).filter(Boolean);
  for (const vin of vins) {
    if (!ordered.includes(vin)) {
      ordered.push(vin);
    }
  }
  return ordered;
}

async function exportSelectedVehiclesPdf() {
  const vins = [...inventorySelectedVins];
  if (!vins.length) {
    alert("Select at least one vehicle to export.");
    return;
  }
  if (vins.length > 200) {
    alert("Select up to 200 vehicles for PDF export.");
    return;
  }

  const btn = qs("export-pdf-btn");
  const originalText = btn?.textContent || "Export PDF";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Preparing…";
  }

  try {
    await loadPdfLibraries();
    if (!getJsPDFConstructor()) {
      throw new Error("PDF library is unavailable.");
    }

    const orderedVins = await fetchOrderedSelectedVins(vins);
    const entries = [];
    for (let i = 0; i < orderedVins.length; i += 1) {
      const vin = orderedVins[i];
      if (btn) {
        btn.textContent = `Loading ${i + 1}/${orderedVins.length}…`;
      }
      const data = await fetchJson(`/api/vehicle/${encodeURIComponent(vin)}`);
      let imageDataUrl = "";
      const imageUrl = pickCarJellyImageUrl(data);
      if (imageUrl) {
        imageDataUrl = await pdfEnsureDataUrl(imageUrl);
      }
      entries.push({ data, imageDataUrl });
    }

    if (btn) btn.textContent = "Generating PDF…";
    await renderMultiVehiclePdfDocument(entries);
  } catch (err) {
    console.error("[pdf]", err);
    alert(err.message || "Failed to generate PDF.");
  } finally {
    if (btn) {
      btn.disabled = inventorySelectedVins.size === 0;
      btn.textContent = originalText;
    }
    renderPaginationControls();
  }
}

function getJsPDFConstructor() {
  if (window.jspdf?.jsPDF) return window.jspdf.jsPDF;
  if (typeof window.jsPDF === "function") return window.jsPDF;
  return null;
}

let pdfLibsPromise = null;

function loadScriptOnce(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[data-pdf-lib="${src}"]`)) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.dataset.pdfLib = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

async function loadPdfLibraries() {
  if (getJsPDFConstructor()) {
    return;
  }
  if (!pdfLibsPromise) {
    pdfLibsPromise = (async () => {
      await loadScriptOnce("/static/vendor/jspdf.umd.min.js?v=2.5.2");
      if (!getJsPDFConstructor()) {
        throw new Error("PDF library loaded but jsPDF is unavailable.");
      }
    })();
  }
  await pdfLibsPromise;
}

async function exportDetailPdf() {
  if (!currentDetailData) return;

  const btn = qs("detail-export-pdf");
  const originalText = btn?.textContent || "Download PDF";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Generating…";
  }

  try {
    await loadPdfLibraries();
    if (!getJsPDFConstructor()) {
      throw new Error("PDF library is unavailable.");
    }

    const imageUrl = pickCarJellyImageUrl(currentDetailData);
    let imageDataUrl = "";
    if (imageUrl) {
      if (btn) btn.textContent = "Loading images…";
      imageDataUrl = await pdfEnsureDataUrl(imageUrl);
    }

    await renderVehiclePdfDocument(currentDetailData, imageDataUrl);
  } catch (err) {
    console.error("[pdf]", err);
    alert(err.message || "Failed to generate PDF.");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

function formatJobDurationSec(sec) {
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

function formatJobStartedAt(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatJobTypeLabel(jobType) {
  const labels = {
    ingest: "Ingest",
    geocode: "Geocode",
    catalog_sync: "Catalog sync",
    dealer_sync: "Dealer sync",
    dealer_vehicle_refresh: "Dealer ZIP refresh",
  };
  return labels[jobType] || jobType;
}

function summarizeJobParams(run) {
  const params = run.params || {};
  if (run.job_type === "ingest") {
    const models = params.all_models
      ? "all models"
      : `${(params.model_codes || []).length} model(s)`;
    return `ZIP ${params.zip_code ?? "—"}, ${params.distance ?? "—"} mi, ${models}`;
  }
  if (run.job_type === "geocode") {
    const limit = params.limit == null ? "all remaining" : `${params.limit} max`;
    return `${limit}, ${params.workers || 1} worker(s)${params.force ? ", force" : ""}`;
  }
  if (run.job_type === "catalog_sync") {
    return `ZIP ${params.zip_code ?? "—"}`;
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

function summarizeJobResult(run) {
  const result = run.result || {};
  if (run.job_type === "ingest") {
    const parts = [];
    if (result.vehicles_persisted != null) {
      parts.push(`${Number(result.vehicles_persisted).toLocaleString()} saved`);
    }
    if (result.completed_models?.length != null) {
      parts.push(`${result.completed_models.length} model(s)`);
    }
    return parts.join(", ") || run.message || "—";
  }
  if (run.job_type === "geocode") {
    const parts = [];
    if (result.geocoded != null) parts.push(`${Number(result.geocoded).toLocaleString()} geocoded`);
    if (result.failed != null && Number(result.failed) > 0) {
      parts.push(`${Number(result.failed).toLocaleString()} failed`);
    }
    if (result.remaining != null) parts.push(`${Number(result.remaining).toLocaleString()} left`);
    return parts.join(", ") || run.message || "—";
  }
  if (run.job_type === "catalog_sync") {
    if (result.count != null) return `${Number(result.count).toLocaleString()} model(s)`;
  }
  if (run.job_type === "dealer_sync") {
    const parts = [];
    if (result.count != null) parts.push(`${Number(result.count).toLocaleString()} dealer(s)`);
    if (result.seed_zips != null) parts.push(`${Number(result.seed_zips).toLocaleString()} seed ZIPs`);
    if (parts.length) return parts.join(", ");
  }
  if (run.job_type === "dealer_vehicle_refresh") {
    const parts = [];
    if (result.vehicles_persisted != null) parts.push(`${Number(result.vehicles_persisted).toLocaleString()} saved`);
    if (result.completed_models?.length != null) {
      parts.push(`${result.completed_models.length} model(s)`);
    }
    if (parts.length) return parts.join(", ");
  }
  return run.message || run.error || "—";
}

function renderJobRunsSummary(summary) {
  const container = qs("job-runs-summary");
  if (!container) return;
  const entries = Object.entries(summary || {});
  if (!entries.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = entries
    .map(([jobType, stats]) => {
      const avg = stats.avg_duration_sec != null ? formatJobDurationSec(stats.avg_duration_sec) : "—";
      return `<span class="job-runs-summary-chip"><strong>${formatJobTypeLabel(jobType)}</strong>: ${stats.count} run(s), avg ${avg}</span>`;
    })
    .join("");
}

function renderJobRuns(payload) {
  const tbody = qs("job-runs-tbody");
  if (!tbody) return;
  renderJobRunsSummary(payload?.summary);
  const runs = payload?.runs || [];
  if (!runs.length) {
    tbody.innerHTML = '<tr><td colspan="6" class="job-runs-empty">No job runs yet.</td></tr>';
    return;
  }
  tbody.innerHTML = runs
    .map((run) => {
      const statusClass = String(run.status || "unknown").toLowerCase();
      const trigger = run.trigger_source ? `<div class="job-runs-meta">${run.trigger_source}</div>` : "";
      return `
        <tr>
          <td>${formatJobTypeLabel(run.job_type)}${trigger}</td>
          <td><span class="job-run-status ${statusClass}">${run.status || "unknown"}</span></td>
          <td>${formatJobStartedAt(run.started_at)}</td>
          <td>${formatJobDurationSec(run.duration_sec)}</td>
          <td>${summarizeJobParams(run)}</td>
          <td>${summarizeJobResult(run)}</td>
        </tr>
      `;
    })
    .join("");
}

async function loadJobRuns() {
  const payload = await fetchJson("/api/jobs/runs?limit=25&since_days=30", { optional: true });
  if (!payload) return;
  renderJobRuns(payload);
}

async function ensureDealerGeocodeJob() {
  try {
    const status = await fetchJson("/api/dealers/geocode-status", { optional: true });
    if (!status) return;

    renderGeocodeProgress(status);

    if (status.job?.status === "running") {
      startGeocodePolling();
      return;
    }

    if (Number(status.remaining || 0) <= 0) {
      return;
    }

    const res = await fetch(
      "/api/dealers/geocode-batch?all=1&background=1&workers=8",
      { method: "POST" }
    );
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      console.warn("[geocode] Could not start job:", body.error || res.status);
      return;
    }
    const body = await res.json().catch(() => ({}));
    renderGeocodeProgress(body);
    startGeocodePolling();
  } catch (err) {
    console.warn("[geocode] Background job start skipped:", err.message);
  }
}

function renderGeocodeProgress(status) {
  const panel = qs("geocode-progress-panel");
  const label = qs("geocode-progress-label");
  const percent = qs("geocode-progress-percent");
  const bar = qs("geocode-progress-bar");
  const detail = qs("geocode-progress-detail");
  if (!panel || !label || !percent || !bar || !detail) return;

  const job = status.job || {};
  const isRunning = job.status === "running";
  const dealersTotal = Number(status.dealers_in_inventory || job.total || 0);
  const processed = Number(job.processed || 0);
  const geocoded = Number(status.geocoded || job.geocoded || 0);
  const remaining = Number(status.remaining ?? job.remaining ?? 0);
  const pct =
    dealersTotal > 0
      ? Math.max(0, Math.min(100, (geocoded / dealersTotal) * 100))
      : job.total > 0
        ? Math.max(0, Math.min(100, (processed / job.total) * 100))
        : 0;

  panel.classList.remove("hidden");
  panel.classList.toggle("is-complete", !isRunning && remaining <= 0 && job.status !== "failed");

  label.textContent =
    job.message ||
    (isRunning
      ? "Geocoding dealer locations…"
      : remaining > 0
        ? `${remaining.toLocaleString()} dealer(s) still need geocoding`
        : "Dealer geocoding complete");
  percent.textContent = `${pct.toFixed(0)}%`;
  bar.value = pct;

  const parts = [];
  if (dealersTotal > 0) {
    parts.push(`${geocoded.toLocaleString()}/${dealersTotal.toLocaleString()} geocoded`);
  }
  if (processed > 0 && job.total > 0) {
    parts.push(`${processed.toLocaleString()}/${Number(job.total).toLocaleString()} processed this run`);
  }
  if (job.current_dealer_cd) {
    parts.push(`Current: ${job.current_dealer_cd}`);
  }
  if (remaining > 0) {
    parts.push(`${remaining.toLocaleString()} remaining`);
  }
  if (job.error) {
    parts.push(`Error: ${job.error}`);
  }
  detail.textContent = parts.join(" · ");
}

async function pollGeocodeStatus() {
  const status = await fetchJson("/api/dealers/geocode-status", { optional: true });
  if (!status) return;

  renderGeocodeProgress(status);
  const job = status.job || {};

  if (job.status === "running") {
    const geocoded = Number(status.geocoded || 0);
    if (geocoded - geocodeUiState.lastGeocodedRefresh >= 50) {
      geocodeUiState.lastGeocodedRefresh = geocoded;
      if (!isFilterBackgroundReloadBusy()) {
        await loadFilters({ silent: true }).catch(() => {});
      }
      if (window.VitGeoMap?.renderGeoMapSectionAsync) {
        window.VitGeoMap.renderGeoMapSectionAsync().catch(() => {});
      }
    }
    return;
  }

  clearInterval(geocodePollTimer);
  geocodePollTimer = null;
  geocodeUiState.lastGeocodedRefresh = 0;

  if (job.status === "completed" || Number(status.remaining || 0) === 0) {
    await loadJobRuns().catch(() => {});
    if (!isFilterBackgroundReloadBusy()) {
      await loadFilters({ silent: true }).catch(() => {});
    }
    if (window.VitGeoMap?.renderGeoMapSectionAsync) {
      await window.VitGeoMap.renderGeoMapSectionAsync().catch(() => {});
    }
  }
}

function startGeocodePolling() {
  if (geocodePollTimer) return;
  geocodePollTimer = setInterval(() => {
    pollGeocodeStatus().catch((err) => console.warn("[geocode]", err.message));
  }, 2500);
  pollGeocodeStatus().catch((err) => console.warn("[geocode]", err.message));
}

async function openVehicleDetail(vin) {
  const data = await fetchJson(`/api/vehicle/${encodeURIComponent(vin)}`);
  qs("vehicle-detail").classList.remove("hidden");
  qs("detail-backdrop").classList.remove("hidden");
  qs("vehicle-detail").setAttribute("aria-hidden", "false");
  renderDetail(data);
  requestAnimationFrame(() => {
    hydrateImages(qs("detail-media"));
    scheduleDetailPanoViewer();
    window.VIT?.primeImageUrls?.((data.media || []).map((item) => item.href).filter(Boolean));
  });
}

function closeVehicleDetail() {
  closeImageLightbox();
  window.VitPanoViewer?.closeModal();
  window.VitPanoViewer?.destroyAllInline();
  qs("vehicle-detail").classList.add("hidden");
  qs("detail-backdrop").classList.add("hidden");
  qs("vehicle-detail").setAttribute("aria-hidden", "true");
}

function setupEventHandlers() {
  const refreshBtn = qs("refresh-btn");
  const exportCsvBtn = qs("export-csv-btn");
  const clearBtn = qs("clear-btn");
  const seriesContainer = qs("series-values");
  const activeOnly = qs("active-only");
  const vinQuery = qs("vin-query");
  const stockQuery = qs("stock-query");
  const searchZipCode = qs("search-zip-code");
  const distanceMaxMiles = qs("distance-max-miles");
  const detailClose = qs("detail-close");
  const detailExportPdf = qs("detail-export-pdf");
  const detailBackdrop = qs("detail-backdrop");
  const imageLightboxClose = qs("image-lightbox-close");
  const imageLightboxBackdrop = qs("image-lightbox-backdrop");
  const imageLightboxOpenTab = qs("image-lightbox-open-tab");
  const imageLightboxImageWrap = qs("image-lightbox-image-wrap");
  const panoLightboxClose = qs("pano-lightbox-close");
  const panoLightboxBackdrop = qs("pano-lightbox-backdrop");
  const panoLightboxOpenTab = qs("pano-lightbox-open-tab");
  const multiSelectIds = FILTER_MULTI_SELECT_IDS;
  const inventoryTableHead = document.querySelector(".inventory-table thead");

  renderInventoryTableHeader();
  setupPaginationControls();

  for (const id of multiSelectIds) {
    const selectEl = qs(id);
    if (!selectEl) continue;
    if (isColorFilterList(selectEl)) {
      ensureColorFilterListReady(selectEl);
    } else if (selectEl.id === "state-codes") {
      ensureStateFilterListReady(selectEl);
    } else if (selectEl.classList.contains("dealer-filter-list")) {
      ensureDealerFilterListReady(selectEl);
    } else if (FACET_BUTTON_LIST_IDS.has(id)) {
      ensureFacetButtonListReady(id, selectEl);
    }
  }
  const dealerSearch = qs("dealer-search");
  if (dealerSearch && !dealerSearch.dataset.ready) {
    dealerSearch.dataset.ready = "1";
    dealerSearch.addEventListener("input", () => renderDealerFilterList());
  }
  if (inventoryTableHead && !inventoryTableHead.dataset.ready) {
    inventoryTableHead.dataset.ready = "1";
    inventoryTableHead.addEventListener("click", async (event) => {
      const header = event.target.closest("th.sortable");
      if (!header) return;
      const key = header.getAttribute("data-sort-key");
      if (!key) return;
      if (sortState.key === key) {
        sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
      } else {
        sortState.key = key;
        sortState.dir = "asc";
      }
      paginationState.page = 1;
      await loadInventory({ showLoading: true });
      scheduleFilterStateSave();
    });
  }

  if (refreshBtn) {
    refreshBtn.addEventListener("click", async () => {
      paginationState.page = 1;
      if (filterReloadTimer) {
        clearTimeout(filterReloadTimer);
        filterReloadTimer = null;
      }
      await refreshFiltersAndInventory({ showTableLoading: true, silentFilters: false });
    });
  }
  if (exportCsvBtn) {
    exportCsvBtn.addEventListener("click", exportSelectionCsv);
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      clearFilters();
      paginationState.page = 1;
      histogramState.min = null;
      histogramState.max = null;
      await refreshFiltersAndInventory({
        showTableLoading: true,
        silentFilters: false,
        clearDependents: true,
      });
      scheduleFilterStateSave();
    });
  }
  if (seriesContainer) {
    ensureSeriesFilterListReady(seriesContainer);
    seriesContainer.addEventListener("change", onFacetFilterChange);
  }
  const stateContainer = qs("state-codes");
  if (stateContainer) {
    ensureStateFilterListReady(stateContainer);
    stateContainer.addEventListener("change", onFacetFilterChange);
  }
  const seriesSearch = qs("series-search");
  if (seriesSearch && !seriesSearch.dataset.ready) {
    seriesSearch.dataset.ready = "1";
    seriesSearch.addEventListener("input", () => renderSeriesFilterList());
  }
  if (activeOnly) {
    activeOnly.addEventListener("change", async () => {
      paginationState.page = 1;
      await refreshFiltersAndInventory({
        showTableLoading: true,
        silentFilters: false,
        clearDependents: true,
      });
      scheduleFilterStateSave();
    });
  }
  for (const id of multiSelectIds) {
    const selectEl = qs(id);
    if (!selectEl) continue;
    selectEl.addEventListener("change", onFacetFilterChange);
  }
  if (vinQuery) {
    vinQuery.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        paginationState.page = 1;
        await refreshInventoryData();
        scheduleFilterStateSave();
      }
    });
  }
  if (stockQuery) {
    stockQuery.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        paginationState.page = 1;
        await refreshInventoryData();
        scheduleFilterStateSave();
      }
    });
  }
  const applyLocationFilters = async () => {
    clearMultiSelect("state-codes");
    paginationState.page = 1;
    await refreshFiltersAndInventory({ showTableLoading: false, silentFilters: true });
    scheduleFilterStateSave();
  };
  if (searchZipCode) {
    searchZipCode.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        await applyLocationFilters();
      }
    });
    searchZipCode.addEventListener("change", () => {
      clearMultiSelect("state-codes");
      applySearchLocation(
        searchZipCode.value,
        qs("distance-max-miles")?.value || DEFAULT_SEARCH_RADIUS_MILES
      );
      scheduleFilterStateSave();
    });
  }
  if (distanceMaxMiles) {
    distanceMaxMiles.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        await applyLocationFilters();
      }
    });
    distanceMaxMiles.addEventListener("change", applyLocationFilters);
  }
  if (detailClose) {
    detailClose.addEventListener("click", closeVehicleDetail);
  }
  if (detailExportPdf) {
    detailExportPdf.addEventListener("click", exportDetailPdf);
  }
  if (detailBackdrop) {
    detailBackdrop.addEventListener("click", closeVehicleDetail);
  }
  if (imageLightboxClose) {
    imageLightboxClose.addEventListener("click", closeImageLightbox);
  }
  if (imageLightboxBackdrop) {
    imageLightboxBackdrop.addEventListener("click", closeImageLightbox);
  }
  if (imageLightboxOpenTab) {
    imageLightboxOpenTab.addEventListener("click", openImageInNewTab);
  }
  if (imageLightboxImageWrap) {
    imageLightboxImageWrap.addEventListener("click", openImageInNewTab);
  }
  if (panoLightboxClose) {
    panoLightboxClose.addEventListener("click", () => window.VitPanoViewer?.closeModal());
  }
  if (panoLightboxBackdrop) {
    panoLightboxBackdrop.addEventListener("click", () => window.VitPanoViewer?.closeModal());
  }
  if (panoLightboxOpenTab) {
    panoLightboxOpenTab.addEventListener("click", () => window.VitPanoViewer?.openModalHrefInNewTab());
  }
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      const panoLightbox = qs("pano-lightbox");
      if (panoLightbox && !panoLightbox.classList.contains("hidden")) {
        window.VitPanoViewer?.closeModal();
        return;
      }
      const lightbox = qs("image-lightbox");
      if (lightbox && !lightbox.classList.contains("hidden")) {
        closeImageLightbox();
        return;
      }
      closeVehicleDetail();
    }
  });
}

window.addEventListener("load", async () => {
  try {
    if (window.VIT?.initMakeSwitcher) {
      await window.VIT.initMakeSwitcher("make-select");
    }
    setupEventHandlers();
    startUserLocationWatch();
    await initializeSearchLocation();
    const ingestStatus = await fetchJson("/api/ingest/status").catch(() => ({ status: "idle" }));
    const ingestActive = ingestStatus.status === "running";
    if (ingestActive) {
      setIngestUiRunning(true);
    }
    await refreshAll({ includeAnalytics: !ingestActive, showTableLoading: !ingestActive });
    if (ingestActive) {
      startIngestPolling();
    }
  } catch (err) {
    const title = qs("result-title");
    if (title) {
      title.textContent = `Error loading data: ${err.message}`;
    }
  }
});
