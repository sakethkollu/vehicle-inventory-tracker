(() => {
  const CACHE_NAME = "vehicle-inventory-images-v2";
  const LS_LEGACY_KEY = "toyota-image-cache-v1";
  const LS_LEGACY_ENTRY_PREFIX = "toyota-img-v2:";
  const LS_LEGACY_INDEX_KEY = "toyota-img-index-v2";
  const LS_ENTRY_PREFIX = "vit-img-v3:";
  const LS_INDEX_KEY = "vit-img-index-v3";
  const LS_MAX_ENTRIES = 200;
  const LS_MAX_BYTES = 480_000;
  const MAX_CONCURRENT = 4;
  const FETCH_TIMEOUT_MS = 25000;
  const PLACEHOLDER =
    "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==";

  const memory = new Map();
  let indexCache = null;
  let indexCacheMake = null;
  let activeFetches = 0;
  const pendingQueue = [];
  let observer = null;

  function normalizeImageUrl(url) {
    let value = String(url || "").trim();
    if (!value) {
      return "";
    }
    if (value.startsWith("/") && !value.startsWith("//")) {
      if (currentMakeSlug() === "mazda") {
        value = `https://www.mazdausa.com${value}`;
      }
    }
    return value.replace(/^https:\/\/www\.mazdausa\.com:443/i, "https://www.mazdausa.com");
  }

  function canUseCacheApi() {
    return typeof caches !== "undefined";
  }

  function isSameOrigin(url) {
    try {
      return new URL(url, window.location.origin).origin === window.location.origin;
    } catch {
      return false;
    }
  }

  function isProxiedUrl(url) {
    return String(url || "").startsWith("/api/image-proxy?");
  }

  function shouldProxy(url) {
    if (!url || url.startsWith("data:") || url.startsWith("blob:") || isProxiedUrl(url)) {
      return false;
    }
    return !isSameOrigin(url);
  }

  function toProxiedUrl(url) {
    if (!url || url.startsWith("data:") || url.startsWith("blob:")) {
      return url;
    }
    if (isProxiedUrl(url) || isSameOrigin(url)) {
      return url;
    }
    const proxied = `/api/image-proxy?url=${encodeURIComponent(url)}`;
    return window.VIT?.withMakeQuery ? window.VIT.withMakeQuery(proxied) : proxied;
  }

  function hashUrl(url) {
    let hash = 2166136261;
    for (let i = 0; i < url.length; i += 1) {
      hash ^= url.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return (hash >>> 0).toString(36);
  }

  function currentMakeSlug() {
    return document.body?.dataset?.make || window.VIT?.currentMake || "shared";
  }

  function indexStorageKey() {
    return `${LS_INDEX_KEY}:${currentMakeSlug()}`;
  }

  function entryStorageKey(url) {
    return `${LS_ENTRY_PREFIX}${currentMakeSlug()}:${hashUrl(url)}`;
  }

  function loadIndex() {
    const make = currentMakeSlug();
    if (indexCache && indexCacheMake === make) {
      return indexCache;
    }
    indexCacheMake = make;
    try {
      const raw = localStorage.getItem(indexStorageKey());
      indexCache = raw ? JSON.parse(raw) : { entries: [] };
      if (!Array.isArray(indexCache.entries)) {
        indexCache = { entries: [] };
      }
    } catch {
      indexCache = { entries: [] };
    }
    return indexCache;
  }

  function saveIndex(index) {
    indexCache = index;
    indexCacheMake = currentMakeSlug();
    try {
      localStorage.setItem(indexStorageKey(), JSON.stringify(index));
    } catch {
      trimIndexEntries(Math.max(1, Math.floor(index.entries.length / 2)));
      try {
        localStorage.setItem(indexStorageKey(), JSON.stringify(indexCache));
      } catch {
        /* ignore quota errors */
      }
    }
  }

  function trimIndexEntries(removeCount) {
    const index = loadIndex();
    if (!removeCount || !index.entries.length) {
      return;
    }
    const sorted = [...index.entries].sort((a, b) => (a.t || 0) - (b.t || 0));
    const removed = sorted.splice(0, removeCount);
    index.entries = sorted;
    for (const entry of removed) {
      try {
        localStorage.removeItem(entryStorageKey(entry.u));
      } catch {
        /* ignore */
      }
      if (entry.u) {
        memory.delete(entry.u);
      }
    }
    saveIndex(index);
  }

  function touchIndexEntry(url, hash, timestamp) {
    const index = loadIndex();
    index.entries = index.entries.filter((entry) => entry.u !== url);
    index.entries.push({ h: hash, u: url, t: timestamp });
    if (index.entries.length > LS_MAX_ENTRIES) {
      trimIndexEntries(index.entries.length - LS_MAX_ENTRIES);
      return loadIndex();
    }
    saveIndex(index);
    return index;
  }

  function readLocalStorage(url) {
    try {
      const hash = hashUrl(url);
      const raw =
        localStorage.getItem(entryStorageKey(url)) ||
        localStorage.getItem(`${LS_LEGACY_ENTRY_PREFIX}${hash}`);
      if (!raw) {
        return null;
      }
      const entry = JSON.parse(raw);
      if (!entry?.d) {
        return null;
      }
      touchIndexEntry(url, hashUrl(url), entry.t || Date.now());
      return entry.d;
    } catch {
      return null;
    }
  }

  function writeLocalStorage(url, dataUrl, size) {
    if (!dataUrl || size > LS_MAX_BYTES) {
      return;
    }
    const timestamp = Date.now();
    const hash = hashUrl(url);
    const payload = JSON.stringify({ d: dataUrl, s: size, t: timestamp });
    try {
      localStorage.setItem(entryStorageKey(url), payload);
      touchIndexEntry(url, hash, timestamp);
    } catch {
      trimIndexEntries(Math.max(1, Math.floor(loadIndex().entries.length / 2)));
      try {
        localStorage.setItem(entryStorageKey(url), payload);
        touchIndexEntry(url, hash, timestamp);
      } catch {
        /* ignore quota errors */
      }
    }
  }

  function migrateLegacyStore() {
    try {
      const raw = localStorage.getItem(LS_LEGACY_KEY);
      if (!raw) {
        return;
      }
      const legacy = JSON.parse(raw);
      if (!legacy || typeof legacy !== "object") {
        localStorage.removeItem(LS_LEGACY_KEY);
        return;
      }
      for (const [url, entry] of Object.entries(legacy)) {
        if (entry?.d) {
          writeLocalStorage(url, entry.d, entry.s || entry.d.length);
        }
      }
      localStorage.removeItem(LS_LEGACY_KEY);
    } catch {
      try {
        localStorage.removeItem(LS_LEGACY_KEY);
      } catch {
        /* ignore */
      }
    }
  }

  migrateLegacyStore();

  function rememberResolved(url, resolved) {
    if (!url || !resolved) return resolved;
    memory.set(url, resolved);
    return resolved;
  }

  function runQueue() {
    while (activeFetches < MAX_CONCURRENT && pendingQueue.length) {
      const job = pendingQueue.shift();
      activeFetches += 1;
      job()
        .catch(() => {})
        .finally(() => {
          activeFetches -= 1;
          runQueue();
        });
    }
  }

  function enqueueTask(task) {
    return new Promise((resolve, reject) => {
      pendingQueue.push(() => task().then(resolve, reject));
      runQueue();
    });
  }

  async function cacheMatch(fetchUrl) {
    if (!canUseCacheApi()) return null;
    try {
      const cache = await caches.open(CACHE_NAME);
      const response = await cache.match(fetchUrl);
      if (!response) return null;
      return response.blob();
    } catch {
      return null;
    }
  }

  async function cachePut(fetchUrl, response) {
    if (!canUseCacheApi()) return;
    try {
      const cache = await caches.open(CACHE_NAME);
      await cache.put(fetchUrl, response.clone());
    } catch {
      /* ignore cache write failures */
    }
  }

  function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
  }

  async function fetchWithTimeout(url, options = {}, timeoutMs = FETCH_TIMEOUT_MS) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchImageBlob(url) {
    const fetchUrl = toProxiedUrl(url);
    const response = await fetchWithTimeout(fetchUrl, { credentials: "omit", cache: "force-cache" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    await cachePut(fetchUrl, response);
    return blob;
  }

  async function resolveFromNetwork(url) {
    const fetchUrl = toProxiedUrl(url);
    const cachedBlob = await cacheMatch(fetchUrl);
    if (cachedBlob) {
      if (cachedBlob.size <= LS_MAX_BYTES) {
        try {
          const dataUrl = await blobToDataUrl(cachedBlob);
          writeLocalStorage(url, dataUrl, cachedBlob.size);
          return rememberResolved(url, dataUrl);
        } catch {
          /* fall through to blob URL */
        }
      }
      return rememberResolved(url, URL.createObjectURL(cachedBlob));
    }

    const blob = await fetchImageBlob(url);
    if (blob.size <= LS_MAX_BYTES) {
      try {
        const dataUrl = await blobToDataUrl(blob);
        writeLocalStorage(url, dataUrl, blob.size);
        return rememberResolved(url, dataUrl);
      } catch {
        /* fall through */
      }
    }
    return rememberResolved(url, URL.createObjectURL(blob));
  }

  async function get(url) {
    url = normalizeImageUrl(url);
    if (!url || url.startsWith("data:") || url.startsWith("blob:")) {
      return url;
    }
    if (memory.has(url)) {
      return memory.get(url);
    }

    const fromLocal = readLocalStorage(url);
    if (fromLocal) {
      return rememberResolved(url, fromLocal);
    }

    return enqueueTask(() => resolveFromNetwork(url)).catch(() => {
      if (shouldProxy(url)) {
        return rememberResolved(url, toProxiedUrl(url));
      }
      return rememberResolved(url, url);
    });
  }

  async function getDataUrl(url) {
    const resolved = await get(url);
    if (!resolved || resolved.startsWith("data:")) {
      return resolved;
    }
    try {
      const response = await fetchWithTimeout(resolved, { credentials: "omit", cache: "force-cache" });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const dataUrl = await blobToDataUrl(blob);
      writeLocalStorage(url, dataUrl, blob.size);
      return rememberResolved(url, dataUrl);
    } catch {
      return resolved.startsWith("data:") ? resolved : "";
    }
  }

  function applyResolvedImage(img, url, resolved) {
    if (!img.isConnected || img.getAttribute("data-cache-src") !== url) {
      return;
    }
    img.src = resolved;
    img.dataset.cacheReady = "1";
    img.classList.remove("img-cache-pending", "img-cache-loading");
    img.classList.add("img-cache-ready");
  }

  async function resolveImageElement(img) {
    const url = img.getAttribute("data-cache-src");
    if (!url || img.dataset.cacheReady === "1") {
      return;
    }

    if (memory.has(url)) {
      applyResolvedImage(img, url, memory.get(url));
      return;
    }

    const fromLocal = readLocalStorage(url);
    if (fromLocal) {
      applyResolvedImage(img, url, rememberResolved(url, fromLocal));
      return;
    }

    img.classList.add("img-cache-loading");
    try {
      const resolved = await get(url);
      applyResolvedImage(img, url, resolved);
    } catch {
      if (img.isConnected && img.getAttribute("data-cache-src") === url) {
        img.src = toProxiedUrl(url);
        img.dataset.cacheReady = "1";
        img.classList.remove("img-cache-pending", "img-cache-loading");
      }
    }
  }

  function ensureObserver() {
    if (observer) {
      return observer;
    }
    observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          const img = entry.target;
          observer.unobserve(img);
          resolveImageElement(img);
        });
      },
      { rootMargin: "160px", threshold: 0.01 }
    );
    return observer;
  }

  function observeImages(root = document) {
    const scope = root instanceof Element ? root : document;
    const images = scope.querySelectorAll("img[data-cache-src]:not([data-cache-ready])");
    if (!images.length) {
      return;
    }

    const obs = ensureObserver();
    images.forEach((img) => {
      const url = img.getAttribute("data-cache-src");
      if (!url) {
        return;
      }
      if (memory.has(url)) {
        applyResolvedImage(img, url, memory.get(url));
        return;
      }
      const fromLocal = readLocalStorage(url);
      if (fromLocal) {
        applyResolvedImage(img, url, rememberResolved(url, fromLocal));
        return;
      }
      if (img.offsetParent !== null) {
        resolveImageElement(img);
        return;
      }
      obs.observe(img);
    });
  }

  function imgTag(url, alt = "", className = "") {
    if (!url) return "";
    url = normalizeImageUrl(url);
    const displaySrc = toProxiedUrl(url);
    const classes = [className].filter(Boolean).join(" ");
    const cls = classes ? ` class="${classes.replace(/"/g, "&quot;")}"` : "";
    const safeUrl = String(url).replace(/"/g, "&quot;");
    const safeDisplaySrc = String(displaySrc).replace(/"/g, "&quot;");
    const safeAlt = String(alt).replace(/"/g, "&quot;");
    return `<img src="${safeDisplaySrc}" data-cache-src="${safeUrl}" alt="${safeAlt}" loading="lazy" decoding="async"${cls} />`;
  }

  function hydrate(root = document) {
    observeImages(root);
  }

  function prime(urls) {
    const unique = [...new Set((urls || []).map((url) => normalizeImageUrl(url)).filter(Boolean))];
    unique.forEach((url) => {
      if (memory.has(url) || readLocalStorage(url)) {
        return;
      }
      enqueueTask(() => get(url)).catch(() => {});
    });
  }

  window.VitImageCache = {
    get,
    getDataUrl,
    hydrate,
    prime,
    imgTag,
    toProxiedUrl,
    normalizeImageUrl,
  };
})();
