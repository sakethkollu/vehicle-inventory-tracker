/** Shared make context for Vehicle Inventory Tracker frontends. */
window.VIT = window.VIT || {};

VIT.MAKE_STORAGE_KEY = "vit-selected-make";
VIT.currentMake = document.body?.dataset?.make || "toyota";
VIT.currentMakeInfo = null;

VIT.MAKE_DEFAULTS = {
  toyota: { zip: "95132", distance: 500, pageSize: 250 },
  mazda: { zip: "95101", distance: 50, pageSize: 100, nationwide: true },
};

VIT.getIngestDefaults = function getIngestDefaults(slug) {
  return VIT.MAKE_DEFAULTS[slug] || VIT.MAKE_DEFAULTS.toyota;
};

VIT.searchZipStorageKey = function searchZipStorageKey(make) {
  const slug = make || VIT.currentMake || "toyota";
  return `vit-search-zip:${slug}`;
};

VIT.searchRadiusStorageKey = function searchRadiusStorageKey(make) {
  const slug = make || VIT.currentMake || "toyota";
  return `vit-search-radius:${slug}`;
};

VIT.readStoredSearchZip = function readStoredSearchZip(make) {
  try {
    const slug = make || VIT.currentMake || "toyota";
    const key = VIT.searchZipStorageKey(slug);
    let value = localStorage.getItem(key);
    if (!value && slug === "toyota") {
      value = localStorage.getItem("toyota-search-zip");
    }
    return value;
  } catch (_err) {
    return null;
  }
};

VIT.readStoredSearchRadius = function readStoredSearchRadius(make) {
  try {
    return localStorage.getItem(VIT.searchRadiusStorageKey(make));
  } catch (_err) {
    return null;
  }
};

VIT.persistSearchLocation = function persistSearchLocation(zip, radiusMiles, make) {
  try {
    const normalizedZip = String(zip || "").trim();
    const radius = Number(radiusMiles);
    if (normalizedZip) {
      localStorage.setItem(VIT.searchZipStorageKey(make), normalizedZip);
    }
    if (Number.isFinite(radius) && radius > 0) {
      localStorage.setItem(VIT.searchRadiusStorageKey(make), String(radius));
    }
  } catch (_err) {
    // Ignore storage failures (private mode, quota, etc.).
  }
};

VIT.hydrateIngestLocationFields = function hydrateIngestLocationFields() {
  const defaults = VIT.getIngestDefaults(VIT.currentMake);
  const storedZip = VIT.readStoredSearchZip();
  const storedRadius = VIT.readStoredSearchRadius();
  const zipEl = document.getElementById("ingest-zip-code");
  const distEl = document.getElementById("ingest-distance");
  if (zipEl && !zipEl.value.trim()) {
    zipEl.value = storedZip || defaults.zip;
  }
  if (distEl && !distEl.value.trim()) {
    distEl.value = storedRadius || String(defaults.distance);
  }
};

VIT.getIngestSettingsPayload = function getIngestSettingsPayload(options = {}) {
  const defaults = VIT.getIngestDefaults(VIT.currentMake);
  const zipRaw =
    document.getElementById("ingest-zip-code")?.value?.trim() ||
    document.getElementById("search-zip-code")?.value?.trim() ||
    VIT.readStoredSearchZip() ||
    defaults.zip;
  const distanceRaw =
    document.getElementById("ingest-distance")?.value?.trim() ||
    document.getElementById("distance-max-miles")?.value?.trim() ||
    VIT.readStoredSearchRadius() ||
    String(defaults.distance);
  const distance = Number(distanceRaw);
  let nationwide;
  if (options.nationwide != null) {
    nationwide = Boolean(options.nationwide);
  } else if (options.forCatalogSync) {
    nationwide = defaults.nationwide !== false;
  } else {
    nationwide = false;
  }
  return {
    zip_code: zipRaw,
    distance: Number.isFinite(distance) && distance > 0 ? distance : defaults.distance,
    page_size: defaults.pageSize,
    nationwide,
  };
};

VIT.formatIngestScope = function formatIngestScope(status) {
  if (!status) return "";
  if (status.job_type === "dealer_vehicle_refresh") {
    return "1 mi radius per dealer ZIP";
  }
  if (status.nationwide) {
    return "Nationwide dealer search";
  }
  const zip = status.zip_code;
  const distance = status.distance;
  if (!zip && (distance == null || distance === "")) return "";
  if (zip && distance != null && distance !== "") {
    return `Near ZIP ${zip} · ${distance} mi radius`;
  }
  if (zip) return `Near ZIP ${zip}`;
  if (distance != null && distance !== "") return `${distance} mi radius`;
  return "";
};

VIT.isJobStatusActive = function isJobStatusActive(status) {
  return status === "running" || status === "queued";
};

VIT.withMakeQuery = function withMakeQuery(url) {
  const resolved = new URL(url, window.location.origin);
  resolved.searchParams.set("make", VIT.currentMake);
  return `${resolved.pathname}${resolved.search}`;
};

VIT.updateMakeLabels = function updateMakeLabels() {
  const name = VIT.currentMakeInfo?.display_name;
  if (!name) return;
  document.querySelectorAll("[data-make-label]").forEach((el) => {
    el.textContent = name;
  });
};

VIT.initMakeSwitcher = async function initMakeSwitcher(selectId) {
  const select = document.getElementById(selectId);
  if (!select) return null;
  try {
    const stored = localStorage.getItem(VIT.MAKE_STORAGE_KEY);
    if (stored) VIT.currentMake = stored;
  } catch (_err) {
    // Ignore storage failures.
  }
  const res = await fetch(VIT.withMakeQuery("/api/makes"));
  if (!res.ok) return null;
  const data = await res.json();
  VIT.currentMake = data.current?.slug || VIT.currentMake;
  VIT.currentMakeInfo = data.current || null;
  if (document.body) {
    document.body.dataset.make = VIT.currentMake;
  }
  select.innerHTML = "";
  for (const make of data.makes || []) {
    const option = document.createElement("option");
    option.value = make.slug;
    option.textContent = make.display_name;
    option.selected = make.slug === VIT.currentMake;
    select.appendChild(option);
  }
  VIT.updateMakeLabels();
  select.addEventListener("change", async () => {
    const slug = select.value;
    await fetch("/api/session/make", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ make: slug }),
    });
    try {
      localStorage.setItem(VIT.MAKE_STORAGE_KEY, slug);
    } catch (_err) {
      // Ignore storage failures.
    }
    if (typeof window.VIT?.saveFilterState === "function") {
      window.VIT.saveFilterState();
    }
    window.location.reload();
  });
  return data;
};

VIT.cachedImgTag = function cachedImgTag(url, alt = "", className = "") {
  if (!url) return "";
  if (window.VitImageCache?.imgTag) {
    return VitImageCache.imgTag(url, alt, className);
  }
  const safeUrl = String(url).replace(/"/g, "&quot;");
  const safeAlt = String(alt).replace(/"/g, "&quot;");
  const cls = className ? ` class="${String(className).replace(/"/g, "&quot;")}"` : "";
  return `<img src="${safeUrl}" alt="${safeAlt}" loading="lazy" decoding="async"${cls} />`;
};

VIT.hydrateImages = function hydrateImages(root) {
  window.VitImageCache?.hydrate?.(root);
};

VIT.scheduleHydrateImages = function scheduleHydrateImages(root) {
  if (!root) return;
  const run = () => VIT.hydrateImages(root);
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(run, { timeout: 2500 });
  } else {
    setTimeout(run, 16);
  }
};

VIT.primeImageUrls = function primeImageUrls(urls) {
  window.VitImageCache?.prime?.(urls);
};
