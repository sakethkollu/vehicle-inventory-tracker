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
