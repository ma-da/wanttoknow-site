(() => {
  "use strict";

  const CONFIG = {
    manifestUrl: "assets/data/ultra_manifest.json",
    indexUrl: "assets/data/ultra_page_index.jsonl",
    imageBase: "images/",
    thumbBase: "thumbs/",
    maxResults: 50,
    snippetLength: 340
  };

  const state = {
    records: [],
    activeRecord: null,
    activeCard: null,
    loaded: false
  };

  const $ = selector => document.querySelector(selector);

  const els = {
    form: $("#search-form"),
    input: $("#search-input"),
    status: $("#status"),

    results: $("#results"),
    title: $("#results-title"),
    count: $("#result-count"),

    panel: $("#transcription-panel"),
    transTitle: $("#transcription-title"),
    transMeta: $("#transcription-meta"),
    transText: $("#transcription-text"),
    closeTrans: $("#close-transcription"),

    modal: $("#image-modal"),
    modalImage: $("#modal-image"),
    modalTitle: $("#modal-title"),
    closeModal: $("#close-modal"),

    pageTotal: $("#page-total"),
    documentTotal: $("#document-total")
  };

  function assertRequiredElements() {
    const missing = Object.entries(els)
      .filter(([, element]) => !element)
      .map(([name]) => name);

    if (missing.length) {
      throw new Error(
        `Missing required page elements: ${missing.join(", ")}`
      );
    }
  }

  function escapeHtml(value = "") {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function normalize(value = "") {
    return String(value)
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[^a-z0-9\s'-]/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parseJsonl(text) {
    const records = [];

    for (const [index, rawLine] of String(text).split(/\r?\n/).entries()) {
      const line = rawLine.trim();

      if (!line) {
        continue;
      }

      try {
        records.push(JSON.parse(line));
      } catch (error) {
        throw new Error(
          `Invalid JSON on index line ${index + 1}: ${error.message}`
        );
      }
    }

    return records;
  }

  function arrayValues(value) {
    if (Array.isArray(value)) {
      return value.filter(Boolean);
    }

    if (value === null || value === undefined || value === "") {
      return [];
    }

    return [value];
  }

  function recordSearchText(record) {
    return normalize([
      record.text,
      record.mori_id,
      record.mori_document_id,
      record.page,
      ...arrayValues(record.dates),
      ...arrayValues(record.subprojects)
    ].join(" "));
  }

  function queryTerms(query) {
    return normalize(query)
      .split(" ")
      .map(term => term.trim())
      .filter(Boolean);
  }

  function countOccurrences(text, term) {
    if (!text || !term) {
      return 0;
    }

    let count = 0;
    let position = 0;

    while ((position = text.indexOf(term, position)) !== -1) {
      count += 1;
      position += Math.max(term.length, 1);
    }

    return count;
  }

  function scoreRecord(record, query) {
    const normalizedQuery = normalize(query);

    if (!normalizedQuery) {
      return 0;
    }

    const terms = queryTerms(query);
    const searchable = record._search || recordSearchText(record);

    let score = 0;

    /*
     * Exact MORI IDs and document IDs should rank first.
     */
    const moriId = normalize(record.mori_id);
    const documentId = normalize(record.mori_document_id);

    if (moriId === normalizedQuery) {
      score += 10000;
    } else if (moriId.includes(normalizedQuery)) {
      score += 2500;
    }

    if (documentId === normalizedQuery) {
      score += 5000;
    } else if (documentId.includes(normalizedQuery)) {
      score += 1000;
    }

    /*
     * Reward exact phrase matches heavily.
     */
    if (searchable.includes(normalizedQuery)) {
      score += 300;
      score += Math.min(
        countOccurrences(searchable, normalizedQuery) * 60,
        600
      );
    }

    /*
     * Require every meaningful query term to be present.
     * This keeps multiword results reasonably precise.
     */
    let matchedTerms = 0;

    for (const term of terms) {
      if (!searchable.includes(term)) {
        continue;
      }

      matchedTerms += 1;

      const occurrences = countOccurrences(searchable, term);
      score += 30;
      score += Math.min(occurrences * 8, 120);

      if (moriId.includes(term)) {
        score += 160;
      }

      if (documentId.includes(term)) {
        score += 100;
      }

      if (
        arrayValues(record.subprojects)
          .some(value => normalize(value).includes(term))
      ) {
        score += 90;
      }

      if (
        arrayValues(record.dates)
          .some(value => normalize(value).includes(term))
      ) {
        score += 65;
      }
    }

    if (!matchedTerms) {
      return 0;
    }

    /*
     * Give complete multi-term matches a substantial bonus.
     */
    if (matchedTerms === terms.length) {
      score += 150 + terms.length * 35;
    } else {
      score *= matchedTerms / terms.length;
    }

    return score;
  }

  function makeSnippet(text, query, length = CONFIG.snippetLength) {
    const flat = String(text || "")
      .replace(/\s+/g, " ")
      .trim();

    if (!flat) {
      return "No usable transcription is available for this page.";
    }

    const terms = queryTerms(query)
      .filter(term => term.length > 1);

    const lower = flat.toLowerCase();

    const positions = terms
      .map(term => lower.indexOf(term.toLowerCase()))
      .filter(position => position >= 0);

    const center = positions.length
      ? Math.min(...positions)
      : 0;

    let start = Math.max(
      0,
      center - Math.floor(length * 0.25)
    );

    /*
     * Avoid beginning in the middle of a word.
     */
    if (start > 0) {
      const nextSpace = flat.indexOf(" ", start);

      if (nextSpace >= 0 && nextSpace - start < 30) {
        start = nextSpace + 1;
      }
    }

    const end = Math.min(flat.length, start + length);

    return [
      start > 0 ? "…" : "",
      flat.slice(start, end),
      end < flat.length ? "…" : ""
    ].join("");
  }

  function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function highlight(text, query) {
    let safe = escapeHtml(text);

    const terms = queryTerms(query)
      .filter(term => term.length > 1)
      .sort((a, b) => b.length - a.length);

    for (const term of terms) {
      const pattern = new RegExp(
        `(${escapeRegExp(term)})`,
        "gi"
      );

      safe = safe.replace(pattern, "<mark>$1</mark>");
    }

    return safe;
  }

  function formatMeta(record) {
    return [
      Number.isFinite(Number(record.page))
        ? `Page ${Number(record.page)}`
        : "",

      ...arrayValues(record.dates).slice(0, 2),
      ...arrayValues(record.subprojects).slice(0, 2),

      record.transcription_status &&
      record.transcription_status !== "usable"
        ? "Needs review"
        : "",

      Number(record.redaction_count) > 0
        ? `${Number(record.redaction_count)} probable redaction${
            Number(record.redaction_count) === 1 ? "" : "s"
          }`
        : ""
    ].filter(Boolean);
  }

  function formatTranscriptionMeta(record) {
    return [
      record.mori_document_id
        ? `Document ${record.mori_document_id}`
        : "",

      Number.isFinite(Number(record.page))
        ? `Page ${Number(record.page)}`
        : "",

      ...arrayValues(record.dates),
      ...arrayValues(record.subprojects),

      Number(record.redaction_count) > 0
        ? `${Number(record.redaction_count)} probable redaction${
            Number(record.redaction_count) === 1 ? "" : "s"
          }`
        : "",

      record.transcription_status &&
      record.transcription_status !== "usable"
        ? "Transcription requires review"
        : ""
    ].filter(Boolean);
  }

  function closeTranscription() {
    if (state.activeCard) {
      state.activeCard.classList.remove("is-selected");
    }

    state.activeCard = null;
    state.activeRecord = null;
    els.panel.hidden = true;
  }

  function openTranscription(record, card) {
    if (!record || !card) {
      return;
    }

    if (state.activeCard && state.activeCard !== card) {
      state.activeCard.classList.remove("is-selected");
    }

    state.activeRecord = record;
    state.activeCard = card;

    card.classList.add("is-selected");

    els.transTitle.textContent =
      record.mori_id ||
      `${record.mori_document_id || "Document"} page ${record.page || ""}`;

	els.transText.textContent =
	  record.text ||
	  "No usable transcription is available for this page.";

    const meta = formatTranscriptionMeta(record);

    els.transMeta.innerHTML = meta
      .map(value => `<span>${escapeHtml(value)}</span>`)
      .join("");

    /*
     * Moving the existing element ensures there is only one open
     * transcription panel. Selecting a second result moves this same
     * panel underneath the new card.
     */
    card.insertAdjacentElement("afterend", els.panel);
    els.panel.hidden = false;

    /*
     * Re-trigger the reveal animation when moving between results.
     */
    const transcriptionCard =
      els.panel.querySelector(".transcription-card");

    if (transcriptionCard) {
      transcriptionCard.style.animation = "none";
      void transcriptionCard.offsetWidth;
      transcriptionCard.style.animation = "";
    }

    requestAnimationFrame(() => {
      els.panel.scrollIntoView({
        behavior: "smooth",
        block: "nearest"
      });
    });
  }
  
  function animateCount(element, target, options = {}) {
    const {
      duration = 900,
      start = 0
    } = options;
  
    const finalValue = Number(target);
  
    if (!element || !Number.isFinite(finalValue)) {
      return;
    }
  
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
  
    if (reduceMotion || duration <= 0) {
      element.textContent = Math.round(finalValue).toLocaleString();
      return;
    }
  
    const startTime = performance.now();
  
    element.textContent = Math.round(start).toLocaleString();
  
    function update(currentTime) {
      const elapsed = currentTime - startTime;
      const progress = Math.min(elapsed / duration, 1);
  
      /*
       * Ease-out cubic:
       * moves quickly at first, then settles smoothly.
       */
      const eased = 1 - Math.pow(1 - progress, 3);
  
      const currentValue =
        start + (finalValue - start) * eased;
  
      element.textContent =
        Math.round(currentValue).toLocaleString();
  
      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        element.textContent =
          Math.round(finalValue).toLocaleString();
      }
    }
  
    requestAnimationFrame(update);
  }  

  function openImage(record) {
    if (!record || !record.source_filename) {
      return;
    }

    els.modalTitle.textContent =
      `Original page — ${record.mori_id || record.source_filename}`;

    els.modalImage.src =
      CONFIG.imageBase +
      encodeURIComponent(record.source_filename);

    els.modalImage.alt =
      `Original scanned page ${record.mori_id || ""}`.trim();

    if (typeof els.modal.showModal === "function") {
      els.modal.showModal();
    } else {
      els.modal.setAttribute("open", "");
    }
  }

  function closeImage() {
    if (typeof els.modal.close === "function" && els.modal.open) {
      els.modal.close();
    } else {
      els.modal.removeAttribute("open");
    }

    els.modalImage.removeAttribute("src");
  }

  function createResultCard(record, relevance, query) {
    const article = document.createElement("article");

    article.className = "result-card";
    article.dataset.recordId =
      record.mori_id || "";

    const meta = formatMeta(record);

    const thumbnailUrl =
      CONFIG.thumbBase +
      encodeURIComponent(record.thumbnail_filename || "");

    const relevanceLabel = Math.max(
      1,
      Math.round(relevance)
    ).toLocaleString();

    article.innerHTML = `
      <img
        class="result-thumb"
        src="${thumbnailUrl}"
        alt="Thumbnail of ${escapeHtml(record.mori_id || "archive page")}"
        loading="lazy"
      >

      <div class="result-content">
        <div class="result-id">
          ${escapeHtml(record.mori_id || "Unknown MORI ID")}
        </div>

        <div class="result-meta">
          ${meta
            .map(value => `<span>${escapeHtml(value)}</span>`)
            .join("")}
        </div>

        <p class="result-snippet">
          ${highlight(
            makeSnippet(record.text, query),
            query
          )}
        </p>

        <div class="result-actions">
          <button
            class="small-button primary transcription-button"
            type="button"
          >
            Read transcription
          </button>

          <button
            class="small-button image-button"
            type="button"
          >
            Inspect full image
          </button>

          <span class="result-relevance">
            Relevance ${relevanceLabel}
          </span>
        </div>
      </div>
    `;

    const thumbnail =
      article.querySelector(".result-thumb");

    const imageButton =
      article.querySelector(".image-button");

    const transcriptionButton =
      article.querySelector(".transcription-button");

    thumbnail.addEventListener("click", () => {
      openImage(record);
    });

    thumbnail.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openImage(record);
      }
    });

    thumbnail.tabIndex = 0;
    thumbnail.setAttribute("role", "button");

    imageButton.addEventListener("click", () => {
      openImage(record);
    });

    transcriptionButton.addEventListener("click", () => {
      openTranscription(record, article);
    });

    return article;
  }

  function render(results, query) {
    /*
     * Hide the panel before rebuilding result nodes, because its
     * selected card may be removed by innerHTML replacement.
     */
    closeTranscription();

    els.results.replaceChildren();

    els.title.textContent = query
      ? `Results for “${query}”`
      : "Ready to search";

    els.count.textContent = query
      ? `${results.length.toLocaleString()} result${
          results.length === 1 ? "" : "s"
        }`
      : "";

    if (!query) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent =
        "Enter a keyword, phrase, MORI ID, date, or subproject.";

      els.results.appendChild(empty);
      return;
    }

    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.textContent =
        "No matching pages were found.";

      els.results.appendChild(empty);
      return;
    }

    const fragment = document.createDocumentFragment();

    for (const result of results) {
      fragment.appendChild(
        createResultCard(
          result.record,
          result.score,
          query
        )
      );
    }

    els.results.appendChild(fragment);
  }

  function runSearch() {
    if (!state.loaded) {
      els.status.textContent =
        "The archive is still loading.";
      return;
    }

    const query = els.input.value.trim();

    if (!query) {
      render([], "");
      els.status.textContent =
        `${state.records.length.toLocaleString()} pages loaded.`;
      return;
    }

    els.status.textContent =
      `Searching ${state.records.length.toLocaleString()} pages…`;

    /*
     * Let the status message paint before doing the synchronous scan.
     */
    requestAnimationFrame(() => {
      const results = state.records
        .map(record => ({
          record,
          score: scoreRecord(record, query)
        }))
        .filter(result => result.score > 0)
        .sort((a, b) => {
          if (b.score !== a.score) {
            return b.score - a.score;
          }

          return String(a.record.mori_id || "")
            .localeCompare(String(b.record.mori_id || ""));
        })
        .slice(0, CONFIG.maxResults);

      render(results, query);

      els.status.textContent = results.length
        ? `Showing the ${results.length.toLocaleString()} highest-ranking matching pages.`
        : "No matching pages were found.";
    });
  }

  async function fetchJson(url) {
    const response = await fetch(url, {
      cache: "no-cache"
    });

    if (!response.ok) {
      throw new Error(
        `${url} returned HTTP ${response.status}`
      );
    }

    return response.json();
  }

  async function fetchText(url) {
    const response = await fetch(url, {
      cache: "no-cache"
    });

    if (!response.ok) {
      throw new Error(
        `${url} returned HTTP ${response.status}`
      );
    }

    return response.text();
  }

  async function loadArchive() {
    try {
      els.status.textContent = "Loading archive…";

      const [manifest, indexText] = await Promise.all([
        fetchJson(CONFIG.manifestUrl),
        fetchText(CONFIG.indexUrl)
      ]);

      const parsedRecords = parseJsonl(indexText);

      state.records = parsedRecords.map(record => ({
        ...record,
        _search: recordSearchText(record)
      }));

      state.loaded = true;

      const manifestPages =
        Number(manifest?.counts?.pages);

      const manifestDocuments =
        Number(manifest?.counts?.documents);

      const pageCount = Number.isFinite(manifestPages)
        ? manifestPages
        : state.records.length;
      
      const documentCount = Number.isFinite(manifestDocuments)
        ? manifestDocuments
        : new Set(
            state.records
              .map(record => record.mori_document_id)
              .filter(Boolean)
          ).size;
      
      animateCount(els.pageTotal, pageCount, {
        duration: 950
      });
      
      setTimeout(() => {
        animateCount(els.documentTotal, documentCount, {
          duration: 3600
        });
      }, 90);

      els.status.textContent =
        `${state.records.length.toLocaleString()} pages loaded.`;

      render([], "");
    } catch (error) {
      console.error("ULTRA archive load failed:", error);

      state.loaded = false;

      els.status.textContent =
        "Could not load the archive index. Serve this folder over HTTP and verify the data paths.";

      els.title.textContent =
        "Archive unavailable";

      els.results.innerHTML = `
        <div class="empty-state">
          The browser could not load
          <code>${escapeHtml(CONFIG.indexUrl)}</code>
          or
          <code>${escapeHtml(CONFIG.manifestUrl)}</code>.
          Check the browser console for details.
        </div>
      `;
    }
  }

  function bindEvents() {
    els.form.addEventListener("submit", event => {
      event.preventDefault();
      runSearch();
    });

    els.closeTrans.addEventListener(
      "click",
      closeTranscription
    );

    els.closeModal.addEventListener(
      "click",
      closeImage
    );

    els.modal.addEventListener("click", event => {
      if (event.target === els.modal) {
        closeImage();
      }
    });

    els.modal.addEventListener("cancel", event => {
      event.preventDefault();
      closeImage();
    });

    document.addEventListener("keydown", event => {
      if (event.key !== "Escape") {
        return;
      }

      if (els.modal.open) {
        closeImage();
        return;
      }

      if (!els.panel.hidden) {
        closeTranscription();
      }
    });
  }

  function initialize() {
    try {
      assertRequiredElements();
      bindEvents();
      loadArchive();
    } catch (error) {
      console.error("ULTRA search initialization failed:", error);
    }
  }

  initialize();
})();