const tagInput = document.querySelector("#tagInput");
const tagChips = document.querySelector("#tagChips");
const gallery = document.querySelector("#gallery");
const viewer = document.querySelector("#viewer");
const resultCount = document.querySelector("#resultCount");
const resultTitle = document.querySelector("#resultTitle");
const loadMoreImages = document.querySelector("#loadMoreImages");
const dateFrom = document.querySelector("#dateFrom");
const dateTo = document.querySelector("#dateTo");
const ratingFilter = document.querySelector("#ratingFilter");
const sortOrder = document.querySelector("#sortOrder");
const tokenInput = document.querySelector("#tokenInput");
const toggleTokenVisibility = document.querySelector("#toggleTokenVisibility");
const getToken = document.querySelector("#getToken");
const tokenStatus = document.querySelector("#tokenStatus");
const tokenLog = document.querySelector("#tokenLog");
const stopAtExisting = document.querySelector("#stopAtExisting");
const includeRestricted = document.querySelector("#includeRestricted");
const startDownload = document.querySelector("#startDownload");
const refreshLibrary = document.querySelector("#refreshLibrary");
const downloadStatus = document.querySelector("#downloadStatus");
const downloadLog = document.querySelector("#downloadLog");
const lightbox = document.querySelector("#lightbox");
const lightboxImage = document.querySelector("#lightboxImage");
const lightboxClose = document.querySelector("#lightboxClose");
const mobileTabs = document.querySelectorAll(".mobile-tab");
const mobilePanes = {
  "viewer-pane": document.querySelector(".viewer-pane"),
  "results-pane": document.querySelector(".results-pane"),
  sidebar: document.querySelector(".sidebar"),
};

let currentImages = [];
let selectedId = null;
let selectedPageIndex = 0;
let searchTimer = null;
let statusTimer = null;
let tokenTimer = null;
let swipeStartX = 0;
let swipeStartY = 0;
const pageLimit = 100;
let loadedCount = 0;
let totalImages = 0;
let hasMoreImages = false;
let isLoadingImages = false;
let activeImageLoads = 0;
let imageRequestSeq = 0;

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    const detail = String(data.error || "").replace(/\s+/g, " ").trim();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  if (!contentType.includes("application/json")) {
    throw new Error("サーバーからJSONではない応答が返りました。サーバーを再起動してください。");
  }
  return data;
}

function escapeText(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[char]));
}

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value));
    if (!["http:", "https:"].includes(url.protocol)) return "";
    return url.href;
  } catch {
    return "";
  }
}

function activateMobilePane(target) {
  Object.entries(mobilePanes).forEach(([name, element]) => {
    element.classList.toggle("mobile-active", name === target);
  });
  mobileTabs.forEach((button) => {
    button.classList.toggle("active", button.dataset.target === target);
  });
}

function selectedIndex() {
  return currentImages.findIndex((image) => image.id === selectedId);
}

function selectedImage() {
  return currentImages.find((image) => image.id === selectedId) || null;
}

function clearSelection() {
  selectedId = null;
  selectedPageIndex = 0;
}

function imagePages(image) {
  if (Array.isArray(image.pages) && image.pages.length) return image.pages;
  return [{
    id: image.id,
    page_index: image.page_index,
    image_url: image.image_url,
    thumb_url: image.thumb_url || image.image_url,
  }];
}

function selectedPage(image) {
  const pages = imagePages(image);
  selectedPageIndex = Math.min(Math.max(selectedPageIndex, 0), pages.length - 1);
  return pages[selectedPageIndex];
}

function updateLightboxImage(image) {
  const page = selectedPage(image);
  lightboxImage.src = page.image_url;
  lightboxImage.alt = imagePages(image).length > 1
    ? `${image.title} ${selectedPageIndex + 1}/${imagePages(image).length}`
    : image.title;
}

function selectImageByIndex(index, showViewer = true, pageIndex = 0) {
  if (!currentImages.length) return;
  const wrappedIndex = (index + currentImages.length) % currentImages.length;
  const image = currentImages[wrappedIndex];
  const pages = imagePages(image);
  selectedPageIndex = Math.min(Math.max(pageIndex, 0), pages.length - 1);
  selectedId = image.id;
  renderGallery(currentImages);
  renderViewer(image);
  if (lightbox.classList.contains("open")) {
    updateLightboxImage(image);
  }
  if (showViewer && window.matchMedia("(max-width: 980px)").matches) {
    activateMobilePane("viewer-pane");
  }
}

function moveSelection(direction) {
  const index = selectedIndex();
  if (index < 0) return;
  const targetIndex = (index + direction + currentImages.length) % currentImages.length;
  const targetImage = currentImages[targetIndex];
  const targetPages = imagePages(targetImage);
  const targetPageIndex = direction < 0 ? targetPages.length - 1 : 0;
  selectImageByIndex(targetIndex, true, targetPageIndex);
}

function moveWorkPage(direction) {
  const image = selectedImage();
  if (!image) return false;
  const pages = imagePages(image);
  if (pages.length <= 1) return false;
  const nextPageIndex = selectedPageIndex + direction;
  if (nextPageIndex < 0 || nextPageIndex >= pages.length) return false;
  selectedPageIndex = nextPageIndex;
  renderViewer(image);
  if (lightbox.classList.contains("open")) {
    updateLightboxImage(image);
  }
  return true;
}

function moveViewer(direction) {
  if (!moveWorkPage(direction)) {
    moveSelection(direction);
  }
}

function handleSwipe(startX, startY, endX, endY) {
  const deltaX = endX - startX;
  const deltaY = endY - startY;
  if (Math.abs(deltaX) < 60 || Math.abs(deltaX) < Math.abs(deltaY) * 1.25) return;
  if (deltaX < 0) {
    moveViewer(1);
  } else {
    moveViewer(-1);
  }
}

function attachSwipe(element) {
  element.addEventListener("touchstart", (event) => {
    if (!event.changedTouches.length) return;
    swipeStartX = event.changedTouches[0].clientX;
    swipeStartY = event.changedTouches[0].clientY;
  }, { passive: true });

  element.addEventListener("touchend", (event) => {
    if (!event.changedTouches.length) return;
    handleSwipe(
      swipeStartX,
      swipeStartY,
      event.changedTouches[0].clientX,
      event.changedTouches[0].clientY,
    );
  }, { passive: true });
}

function renderPagination() {
  resultCount.textContent = totalImages
    ? `${loadedCount}/${totalImages} items`
    : `${loadedCount} items`;
  loadMoreImages.disabled = isLoadingImages;
  loadMoreImages.textContent = isLoadingImages ? "読み込み中..." : "さらに読み込む";
  loadMoreImages.parentElement.classList.toggle("is-concealed", !hasMoreImages && !isLoadingImages);
}

function renderGallery(images) {
  currentImages = images;
  loadedCount = images.length;
  renderPagination();
  const hasFilter = tagInput.value.trim() || dateFrom.value || dateTo.value || ratingFilter.value !== "all";
  resultTitle.textContent = hasFilter ? "検索結果" : "画像一覧";

  if (!images.length) {
    gallery.innerHTML = '<div class="empty-list">条件に一致する画像がありません。</div>';
    renderViewer(null);
    return;
  }

  gallery.innerHTML = images.map((image) => `
    <button class="thumb ${image.id === selectedId ? "active" : ""}" data-id="${image.id}">
      <img src="${image.thumb_url || image.image_url}" alt="${escapeText(image.title)}" loading="lazy" />
      <span class="thumb-meta">
        <span class="thumb-title">${escapeText(image.title)}</span>
        <span class="thumb-subline">
          ${image.posted_at ? escapeText(image.posted_at.slice(0, 10)) : "日付なし"}
          ${(image.page_count || 0) > 1 ? `<span class="page-badge">${image.page_count}P</span>` : ""}
          ${image.is_r18 ? '<span class="rating-badge">R-18</span>' : ""}
        </span>
        <span class="thumb-tags">${escapeText(image.tags.join(" / "))}</span>
      </span>
    </button>
  `).join("");

  gallery.querySelectorAll(".thumb").forEach((button) => {
    button.addEventListener("click", () => {
      const image = currentImages.find((item) => item.id === Number(button.dataset.id));
      selectImageByIndex(currentImages.indexOf(image));
    });
  });

  if (!selectedId || !images.some((image) => image.id === selectedId)) {
    selectedId = images[0].id;
    selectedPageIndex = 0;
    renderViewer(images[0]);
  }
}

function renderViewer(image) {
  if (!image) {
    viewer.className = "viewer empty";
    viewer.innerHTML = `
      <div class="empty-state">
        <strong>画像を選択</strong>
        <span>一覧から選ぶとここに表示されます。</span>
      </div>
    `;
    return;
  }

  const tagHtml = image.tags.map((tag) => (
    `<button class="tag-chip" data-tag="${escapeText(tag)}">${escapeText(tag)}</button>`
  )).join("");
  const sourceUrl = safeExternalUrl(image.source_url);
  const pages = imagePages(image);
  const page = selectedPage(image);
  const pageControls = pages.length > 1 ? `
    <div class="page-controls" aria-label="作品ページ">
      <button class="page-button" type="button" data-page-move="-1" title="前のページ">‹</button>
      <span class="page-indicator">${selectedPageIndex + 1} / ${pages.length}</span>
      <button class="page-button" type="button" data-page-move="1" title="次のページ">›</button>
    </div>
  ` : "";

  viewer.className = "viewer";
  viewer.innerHTML = `
    <div class="viewer-content">
      <img class="viewer-image" src="${page.image_url}" alt="${escapeText(image.title)}" />
      <div class="viewer-info">
        <div>
          <h3>${escapeText(image.title)} ${image.is_r18 ? '<span class="rating-badge">R-18</span>' : ""}</h3>
          ${image.posted_at ? `<div class="posted-at">投稿日 ${escapeText(image.posted_at.slice(0, 10))}</div>` : ""}
          ${pageControls}
          <div class="viewer-tags">${tagHtml}</div>
        </div>
        ${sourceUrl ? `<a class="source-link" href="${escapeText(sourceUrl)}" target="_blank" rel="noreferrer noopener">Pixivで開く</a>` : ""}
      </div>
    </div>
  `;

  viewer.querySelector(".viewer-image").addEventListener("click", () => {
    openLightbox(image);
  });

  viewer.querySelectorAll("[data-page-move]").forEach((button) => {
    button.addEventListener("click", () => {
      moveViewer(Number(button.dataset.pageMove));
    });
  });

  viewer.querySelectorAll(".tag-chip").forEach((button) => {
    button.addEventListener("click", () => {
      tagInput.value = button.dataset.tag;
      clearSelection();
      loadImages();
      activateMobilePane("results-pane");
    });
  });
}

function openLightbox(image) {
  updateLightboxImage(image);
  lightbox.classList.add("open");

  document.body.classList.add("lightbox-open");
}

function closeLightbox() {
  lightbox.classList.remove("open");

  document.body.classList.remove("lightbox-open");
  lightboxImage.removeAttribute("src");
}

async function loadImages({ append = false } = {}) {
  if (append && isLoadingImages) return;
  const requestId = ++imageRequestSeq;
  activeImageLoads += 1;
  isLoadingImages = true;
  renderPagination();
  const query = tagInput.value.trim();
  const params = new URLSearchParams();
  if (query) params.set("tag", query);
  if (dateFrom.value) params.set("from", dateFrom.value);
  if (dateTo.value) params.set("to", dateTo.value);
  params.set("rating", ratingFilter.value);
  params.set("sort", sortOrder.value);
  params.set("limit", String(pageLimit));
  params.set("offset", String(append ? loadedCount : 0));
  try {
    const data = await fetchJson(`/api/images?${params.toString()}`);
    if (requestId !== imageRequestSeq) return;
    totalImages = Number(data.total || 0);
    hasMoreImages = Boolean(data.has_more);
    const images = append ? currentImages.concat(data.images || []) : (data.images || []);
    renderGallery(images);
  } finally {
    activeImageLoads = Math.max(0, activeImageLoads - 1);
    isLoadingImages = activeImageLoads > 0;
    renderPagination();
  }
}

async function loadTags() {
  const params = new URLSearchParams();
  if (dateFrom.value) params.set("from", dateFrom.value);
  if (dateTo.value) params.set("to", dateTo.value);
  params.set("rating", ratingFilter.value);
  const data = await fetchJson(`/api/tags?${params.toString()}`);
  tagChips.innerHTML = data.tags.map((tag) => (
    `<button class="tag-chip" data-tag="${escapeText(tag.name)}">${escapeText(tag.name)} ${tag.count}</button>`
  )).join("");

  tagChips.querySelectorAll(".tag-chip").forEach((button) => {
    button.addEventListener("click", () => {
      tagInput.value = button.dataset.tag;
      clearSelection();
      loadImages();
      activateMobilePane("results-pane");
    });
  });
}

function renderDownloadStatus(status) {
  startDownload.disabled = status.running;
  downloadStatus.textContent = status.running ? `実行中: ${status.message}` : status.message;
  downloadStatus.classList.toggle("running", status.running);
  downloadStatus.classList.toggle("failed", status.returncode !== null && status.returncode !== 0);
  downloadLog.textContent = (status.log || []).join("\n");
  downloadLog.scrollTop = downloadLog.scrollHeight;

  if (status.running && !statusTimer) {
    statusTimer = setInterval(loadDownloadStatus, 1500);
  }
  if (!status.running && statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
    loadTags();
    loadImages();
  }
}

function renderTokenStatus(status) {
  getToken.disabled = status.running;
  tokenStatus.textContent = status.running ? `実行中: ${status.message}` : status.message;
  tokenStatus.classList.toggle("running", status.running);
  tokenStatus.classList.toggle("failed", status.returncode !== null && status.returncode !== 0);
  tokenLog.textContent = (status.log || []).join("\n");
  tokenLog.scrollTop = tokenLog.scrollHeight;

  if (status.token) {
    tokenInput.value = status.token;
    tokenStatus.textContent = "トークンを取得して入力欄へセットしました";
  }

  if (status.running && !tokenTimer) {
    tokenTimer = setInterval(loadTokenStatus, 1500);
  }
  if (!status.running && tokenTimer) {
    clearInterval(tokenTimer);
    tokenTimer = null;
  }
}

async function loadDownloadStatus() {
  const status = await fetchJson("/api/download/status");
  renderDownloadStatus(status);
}

async function loadTokenStatus() {
  const status = await fetchJson("/api/token/status");
  renderTokenStatus(status);
}

async function startTokenCapture() {
  const data = await fetchJson("/api/token/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  renderTokenStatus(data.status);
}

async function startPixivDownload() {
  const refreshToken = tokenInput.value.trim();
  if (!refreshToken) {
    renderDownloadStatus({
      running: false,
      returncode: 1,
      message: "refresh_tokenを入力してください",
      log: [],
    });
    return;
  }

  const data = await fetchJson("/api/download/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      refresh_token: refreshToken,
      stop_at_existing: stopAtExisting.checked,
      include_restricted: includeRestricted.checked,
    }),
  });
  renderDownloadStatus(data.status);
}

function setTokenVisible(visible) {
  tokenInput.type = visible ? "text" : "password";
  toggleTokenVisibility.classList.toggle("active", visible);
  toggleTokenVisibility.setAttribute("aria-label", visible ? "トークンを非表示" : "トークンを表示");
  toggleTokenVisibility.title = visible ? "トークンを非表示" : "トークンを表示";
}

tagInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    clearSelection();
    loadImages();
  }, 180);
});

[dateFrom, dateTo, ratingFilter].forEach((input) => {
  input.addEventListener("change", () => {
    clearSelection();
    loadTags();
    loadImages();
  });
});

sortOrder.addEventListener("change", () => {
  clearSelection();
  loadImages();
});

loadMoreImages.addEventListener("click", () => {
  loadImages({ append: true }).catch((error) => {
    gallery.insertAdjacentHTML("beforeend", `<div class="empty-list">${escapeText(error.message)}</div>`);
  });
});

startDownload.addEventListener("click", () => {
  startPixivDownload().catch((error) => {
    renderDownloadStatus({
      running: false,
      returncode: 1,
      message: error.message,
      log: [],
    });
    loadDownloadStatus().catch(() => {});
  });
});

getToken.addEventListener("click", () => {
  startTokenCapture().catch((error) => {
    renderTokenStatus({
      running: false,
      returncode: 1,
      message: error.message,
      token: null,
      log: [],
    });
  });
});

toggleTokenVisibility.addEventListener("click", () => {
  setTokenVisible(tokenInput.type === "password");
});

mobileTabs.forEach((button) => {
  button.addEventListener("click", () => activateMobilePane(button.dataset.target));
});

lightboxClose.addEventListener("click", closeLightbox);
lightbox.addEventListener("click", (event) => {
  if (event.target === lightbox) closeLightbox();
});
document.addEventListener("keydown", (event) => {
  const target = event.target;
  if (target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
  if (event.key === "Escape" && lightbox.classList.contains("open")) {
    closeLightbox();
    return;
  }
  if (event.key === "ArrowRight") moveViewer(1);
  if (event.key === "ArrowLeft") moveViewer(-1);
});

attachSwipe(viewer);
attachSwipe(lightbox);

refreshLibrary.addEventListener("click", () => {
  loadTags();
  loadImages();
});

activateMobilePane("sidebar");

Promise.all([loadTags(), loadImages(), loadDownloadStatus(), loadTokenStatus()])
  .catch((error) => {
  gallery.innerHTML = `<div class="empty-list">${escapeText(error.message)}</div>`;
  });

