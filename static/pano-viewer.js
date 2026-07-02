(() => {
  const inlineViewers = new Map();
  let modalViewer = null;
  let modalHref = "";

  function proxiedPanoramaUrl(href) {
    const normalized = window.VitImageCache?.normalizeImageUrl
      ? window.VitImageCache.normalizeImageUrl(href)
      : String(href || "").replace(/^https:\/\/www\.mazdausa\.com:443/i, "https://www.mazdausa.com");
    if (!normalized) return "";
    if (window.VitImageCache?.toProxiedUrl) {
      return window.VitImageCache.toProxiedUrl(normalized);
    }
    const proxied = `/api/image-proxy?url=${encodeURIComponent(normalized)}`;
    return window.VIT?.withMakeQuery ? window.VIT.withMakeQuery(proxied) : proxied;
  }

  function destroyViewer(viewer) {
    if (viewer && typeof viewer.destroy === "function") {
      try {
        viewer.destroy();
      } catch {
        /* ignore teardown errors */
      }
    }
  }

  function buildViewer(container, href, { compact = false } = {}) {
    if (!container || !href) return null;
    if (typeof pannellum === "undefined") {
      container.innerHTML = '<p class="muted pano-viewer-error">360° viewer failed to load.</p>';
      return null;
    }

    container.innerHTML = "";
    container.classList.add("pannellum-host");
    return pannellum.viewer(container, {
      type: "equirectangular",
      panorama: proxiedPanoramaUrl(href),
      autoLoad: true,
      showControls: !compact,
      compass: false,
      mouseZoom: true,
      draggable: true,
      friction: 0.15,
      hfov: compact ? 95 : 100,
      minHfov: 45,
      maxHfov: 120,
      backgroundColor: [47, 49, 51],
    });
  }

  function mountInline(container, href) {
    if (!container) return null;
    destroyInline(container);
    const viewer = buildViewer(container, href, { compact: true });
    if (viewer) {
      inlineViewers.set(container, viewer);
    }
    return viewer;
  }

  function destroyInline(container) {
    if (!container) return;
    destroyViewer(inlineViewers.get(container));
    inlineViewers.delete(container);
    container.innerHTML = "";
    container.classList.remove("pannellum-host");
  }

  function destroyAllInline() {
    for (const container of inlineViewers.keys()) {
      destroyInline(container);
    }
  }

  function openModal(href, title) {
    const modal = document.getElementById("pano-lightbox");
    const container = document.getElementById("pano-viewer-root");
    const titleEl = document.getElementById("pano-lightbox-title");
    if (!modal || !container || !href) return;

    closeModal(false);
    modalHref = href;
    if (titleEl) {
      titleEl.textContent = title || "360° View";
    }
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    modalViewer = buildViewer(container, href, { compact: false });
  }

  function closeModal(clearHref = true) {
    destroyViewer(modalViewer);
    modalViewer = null;
    const container = document.getElementById("pano-viewer-root");
    if (container) {
      container.innerHTML = "";
      container.classList.remove("pannellum-host");
    }
    const modal = document.getElementById("pano-lightbox");
    if (modal) {
      modal.classList.add("hidden");
      modal.setAttribute("aria-hidden", "true");
    }
    if (clearHref) {
      modalHref = "";
    }
  }

  function openModalHrefInNewTab() {
    if (!modalHref) return;
    window.open(modalHref, "_blank", "noopener,noreferrer");
  }

  window.VitPanoViewer = {
    proxiedPanoramaUrl,
    mountInline,
    destroyInline,
    destroyAllInline,
    openModal,
    closeModal,
    openModalHrefInNewTab,
    getModalHref: () => modalHref,
  };
})();
