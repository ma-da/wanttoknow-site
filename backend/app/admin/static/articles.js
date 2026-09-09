(() => {
  "use strict";

  const PAGE_SIZE = 100;
  const SEARCH_DELAY_MS = 180;

  const list = document.getElementById("article-list");
  const count = document.getElementById("result-count");
  const search = document.getElementById("article-search");
  const browser = document.getElementById("article-browser");
  const previewToggle = document.getElementById("preview-toggle");
  const sortHeaders = Array.from(document.querySelectorAll(".article-sort-head"));
  const loadState = document.getElementById("load-state");
  const sentinel = document.getElementById("load-sentinel");
  const addArticleButton = document.getElementById("add-article");
  const draftFilterButton = document.getElementById("draft-filter");
  const publishBatchButton = document.getElementById("publish-batch");
  const batchSummary = document.getElementById("batch-summary");
  const batchSummaryText = document.getElementById("batch-summary-text");
		const batchPublishStatus =
  document.getElementById("batch-publish-status");
  const createDialog = document.getElementById("create-article-dialog");
  const createForm = document.getElementById("create-article-form");
  const createTitle = document.getElementById("create-title");
  const createSourceUrl = document.getElementById("create-source-url");
  const createStatus = document.getElementById("create-article-status");
  const createCancel = document.getElementById("create-article-cancel");
  const createSubmitButtons = Array.from(document.querySelectorAll(".admin-create-submit"));

  const previewEmpty = document.getElementById("preview-empty");
  const previewContent = document.getElementById("preview-content");
  const previewTitle = document.getElementById("preview-title");
  const previewMeta = document.getElementById("preview-meta");
  const previewTags = document.getElementById("preview-tags");
  const previewSummary = document.getElementById("preview-summary");

  const state = {
    q: "",
    workflowState: "",
    sort: "posted_desc",
    previewVisible: true,
    cursor: null,
    loading: false,
    done: false,
    requestVersion: 0,
    activeRow: null,
  };

  let searchTimer = null;
  let csrfToken = "";

  const SORT_KEYS = {
    posted: { asc: "posted_asc", desc: "posted_desc" },
    priority: { asc: "priority_asc", desc: "priority_desc" },
    publication: { asc: "publisher_asc", desc: "publisher_desc" },
    title: { asc: "title_asc", desc: "title_desc" },
    id: { asc: "id_asc", desc: "id_desc" },
  };

  function sortStateFromKey(key) {
    for (const [field, directions] of Object.entries(SORT_KEYS)) {
      for (const [direction, value] of Object.entries(directions)) {
        if (value === key) return { field, direction };
      }
    }
    return { field: "posted", direction: "desc" };
  }

  function updateSortHeaders() {
    const active = sortStateFromKey(state.sort);
    for (const button of sortHeaders) {
      const isActive = button.dataset.sortField === active.field;
      if (isActive) {
        button.dataset.active = "true";
        button.dataset.direction = active.direction;
        button.setAttribute(
          "aria-label",
          `Sort ${button.textContent.trim()} ${active.direction === "asc" ? "descending" : "ascending"}`,
        );
      } else {
        delete button.dataset.active;
        delete button.dataset.direction;
        button.setAttribute("aria-label", `Sort by ${button.textContent.trim()}`);
      }
    }
  }

  function setPreviewVisible(visible) {
    state.previewVisible = visible;
    if (visible) {
      browser.removeAttribute("data-preview-hidden");
      previewToggle.textContent = "Hide preview";
      previewToggle.setAttribute("aria-expanded", "true");
    } else {
      browser.dataset.previewHidden = "true";
      previewToggle.textContent = "Show preview";
      previewToggle.setAttribute("aria-expanded", "false");
      setActiveRow(null);
    }
  }

  function readableDate(value) {
    if (!value) return "—";
    const parts = value.split("-");
    if (parts.length !== 3) return value;
    return `${parts[1]}/${parts[2]}/${parts[0].slice(2)}`;
  }

  function safeHttpUrl(value) {
    try {
      const parsed = new URL(value);
      return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
    } catch {
      return null;
    }
  }

  function markdownLinkAt(source, index) {
    if (source[index] !== "[") return null;
    const labelEnd = source.indexOf("](", index + 1);
    if (labelEnd < 0) return null;

    const urlStart = labelEnd + 2;
    let depth = 0;
    for (let i = urlStart; i < source.length; i += 1) {
      const char = source[i];
      if (char === "(" ) {
        depth += 1;
      } else if (char === ")") {
        if (depth === 0) {
          return {
            label: source.slice(index + 1, labelEnd),
            url: source.slice(urlStart, i),
            end: i + 1,
          };
        }
        depth -= 1;
      }
    }
    return null;
  }

  function bareUrlAt(source, index) {
    if (!source.startsWith("http://", index) && !source.startsWith("https://", index)) return null;
    let end = index;
    while (end < source.length && !/[\s<>]/.test(source[end])) end += 1;

    let urlEnd = end;
    while (urlEnd > index && /[.,;:!?]/.test(source[urlEnd - 1])) urlEnd -= 1;
    if (urlEnd <= index) return null;
    return { url: source.slice(index, urlEnd), end: urlEnd };
  }

  function appendInlineMarkdown(parent, source) {
    let index = 0;

    while (index < source.length) {
      const link = markdownLinkAt(source, index);
      if (link) {
        const href = safeHttpUrl(link.url.trim());
        if (href) {
          const anchor = document.createElement("a");
          anchor.href = href;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          appendInlineMarkdown(anchor, link.label);
          parent.append(anchor);
        } else {
          parent.append(document.createTextNode(source.slice(index, link.end)));
        }
        index = link.end;
        continue;
      }

      if (source.startsWith("**", index) || source.startsWith("__", index)) {
        const marker = source.slice(index, index + 2);
        const close = source.indexOf(marker, index + 2);
        if (close > index + 2) {
          const strong = document.createElement("strong");
          appendInlineMarkdown(strong, source.slice(index + 2, close));
          parent.append(strong);
          index = close + 2;
          continue;
        }
      }

      if (source[index] === "*" || source[index] === "_") {
        const marker = source[index];
        const close = source.indexOf(marker, index + 1);
        if (close > index + 1) {
          const em = document.createElement("em");
          appendInlineMarkdown(em, source.slice(index + 1, close));
          parent.append(em);
          index = close + 1;
          continue;
        }
      }

      if (source[index] === "`") {
        const close = source.indexOf("`", index + 1);
        if (close > index + 1) {
          const code = document.createElement("code");
          code.textContent = source.slice(index + 1, close);
          parent.append(code);
          index = close + 1;
          continue;
        }
      }

      const bare = bareUrlAt(source, index);
      if (bare) {
        const href = safeHttpUrl(bare.url);
        if (href) {
          const anchor = document.createElement("a");
          anchor.href = href;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          anchor.textContent = bare.url;
          parent.append(anchor);
          index = bare.end;
          continue;
        }
      }

      if (source[index] === "\n") {
        parent.append(document.createElement("br"));
        index += 1;
        continue;
      }

      let next = index + 1;
      while (next < source.length) {
        if (
          source[next] === "[" ||
          source[next] === "*" ||
          source[next] === "_" ||
          source[next] === "`" ||
          source[next] === "\n" ||
          source.startsWith("http://", next) ||
          source.startsWith("https://", next)
        ) break;
        next += 1;
      }
      parent.append(document.createTextNode(source.slice(index, next)));
      index = next;
    }
  }

  function renderSummaryMarkdown(value) {
    previewSummary.replaceChildren();
    const source = String(value || "").replace(/\r\n?/g, "\n");
    if (!source.trim()) {
      previewSummary.textContent = "No summary.";
      return;
    }

    const blocks = source.split(/\n{2,}/);
    for (const rawBlock of blocks) {
      const block = rawBlock.trim();
      if (!block) continue;

      const element = block.split("\n").every((line) => /^\s{0,3}>/.test(line))
        ? document.createElement("blockquote")
        : document.createElement("p");
      const content = element.tagName === "BLOCKQUOTE"
        ? block.split("\n").map((line) => line.replace(/^\s{0,3}>\s?/, "")).join("\n")
        : block;
      appendInlineMarkdown(element, content);
      previewSummary.append(element);
    }
  }

		function setBatchPublishStatus(text = "", type = "") {
				batchPublishStatus.textContent = text;

				if (type) {
						batchPublishStatus.dataset.type = type;
				} else {
						delete batchPublishStatus.dataset.type;
				}
		}

  function setActiveRow(row) {
    if (state.activeRow && state.activeRow !== row) {
      state.activeRow.removeAttribute("data-preview-active");
    }
    state.activeRow = row;
    if (row) row.setAttribute("data-preview-active", "true");
  }

  function showPreview(article, row) {
    if (!state.previewVisible) return;
    setActiveRow(row);
    previewEmpty.hidden = true;
    previewContent.hidden = false;

    previewTitle.textContent = article.title || "Untitled article";
    previewMeta.replaceChildren();

    const meta = [
      article.publication_name || article.publication_group || "Unknown publisher",
      `Published ${article.publication_date || "—"}`,
      `WTK ${article.posted_date || "—"}`,
      `Priority ${article.priority ?? "—"}`,
      `ID ${article.article_id}`,
    ];

    for (const value of meta) {
      const span = document.createElement("span");
      span.textContent = value;
      previewMeta.append(span);
    }

    previewTags.replaceChildren();
    for (const tag of article.tags || []) {
      const span = document.createElement("span");
      span.className = "article-preview__tag";
      span.textContent = tag;
      previewTags.append(span);
    }

    renderSummaryMarkdown(article.summary_markdown);
  }

  function makeRow(article) {
    const row = document.createElement("div");
    row.className = "article-row";
    row.setAttribute("role", "listitem");
    row.setAttribute("tabindex", "0");
    row.setAttribute("aria-label", `${article.title}, article ${article.article_id}`);

    const date = document.createElement("span");
    date.className = "article-row__date";
    date.textContent = readableDate(article.posted_date);

    const live = document.createElement("a");
    live.className = "article-row__live";
    live.href = article.path || `/news/${article.slug}`;
    live.target = "_blank";
    live.rel = "noopener noreferrer";
    live.title = "Open live article";
    live.setAttribute("aria-label", `Open live article: ${article.title || "Untitled article"}`);
    live.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Zm9.5 3.2a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z"/></svg>';
    live.addEventListener("click", (event) => event.stopPropagation());
    if (article.edit_state === "new") {
      live.hidden = true;
      live.removeAttribute("href");
    }

    const priority = document.createElement("span");
    priority.className = "article-row__priority";
    priority.textContent = article.priority ?? "—";

    const publication = document.createElement("span");
    publication.className = "article-row__publication";
    publication.textContent = article.publication_name || article.publication_group || "—";
    publication.title = publication.textContent;

    const title = document.createElement("a");
    title.className = "article-row__title article-row__title-link";
    title.textContent = article.title || "Untitled article";
    title.title = `Edit ${title.textContent}`;
    title.href = `/admin/articles/${article.article_id}/edit`;

    const stateBadge = document.createElement("span");
    const displayState = article.withdrawal_pending ? "withdrawn" : (article.workflow_state || "published");
    stateBadge.className = `article-row__state article-row__state--${displayState}`;
    stateBadge.textContent = displayState === "withdrawn" ? "WITHDRAW" : displayState.toUpperCase();
    title.append(stateBadge);

    const id = document.createElement("span");
    id.className = "article-row__id";
    if ((article.workflow_state || "published") === "draft") {
      id.classList.add("article-row__id--draft");
    }
    id.textContent = article.article_id;

    row.append(date, live, priority, publication, title, id);

    row.addEventListener("pointerenter", () => showPreview(article, row));
    row.addEventListener("focus", () => showPreview(article, row));
    row.addEventListener("click", () => showPreview(article, row));

    return row;
  }

  function queryUrl() {
    const params = new URLSearchParams();
    params.set("limit", String(PAGE_SIZE));
    params.set("sort", state.sort);
    if (state.q) params.set("q", state.q);
    if (state.workflowState) params.set("workflow_state", state.workflowState);
    if (state.cursor) params.set("cursor", state.cursor);
    return `/api/admin/articles?${params.toString()}`;
  }

  function setLoadMessage(message, isError = false) {
    loadState.textContent = message;
    if (isError) {
      loadState.dataset.error = "true";
    } else {
      delete loadState.dataset.error;
    }
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
      headers: {
        Accept: "application/json",
        ...(options.headers || {}),
      },
    });
    if (response.status === 401) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/admin/login?next=${next}`);
      throw new Error("Authentication required");
    }
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
    return body;
  }

  async function loadSession() {
    const session = await apiJson("/api/admin/session");
    csrfToken = session.csrf_token || "";
  }

  async function loadBatchSummary() {
    try {
      const payload = await apiJson("/api/admin/articles/batch/current");
      const batch = payload.batch;
      if (!batch || !batch.total) {
        batchSummary.hidden = true;
        draftFilterButton.textContent = "Drafts";
        publishBatchButton.disabled = true;
        return;
      }
      batchSummary.hidden = false;
      const parts = [
        `${batch.name}`,
        `${batch.total} draft${batch.total === 1 ? "" : "s"}`,
        `${batch.new} new`,
        `${batch.modified} modified`,
      ];
      if (batch.image_only) parts.push(`${batch.image_only} image-only`);
      if (batch.withdrawals) parts.push(`${batch.withdrawals} withdrawal${batch.withdrawals === 1 ? "" : "s"}`);
      batchSummaryText.textContent = parts.join(" · ");
      draftFilterButton.textContent = state.workflowState === "draft" ? `Show all (${batch.total} drafts)` : `View drafts (${batch.total})`;
      publishBatchButton.disabled = !payload.publishing_enabled;
      publishBatchButton.title = payload.publishing_enabled ? "Publish current draft batch" : (payload.publishing_message || "Publishing is not enabled yet");
    } catch (error) {
      batchSummary.hidden = false;
      batchSummaryText.textContent = error instanceof Error ? error.message : "Unable to load batch status";
      publishBatchButton.disabled = true;
    }
  }

  function openCreateDialog() {
    createForm.reset();
    createStatus.textContent = "";
    for (const button of createSubmitButtons) button.disabled = false;
    createDialog.showModal();
    window.setTimeout(() => createTitle.focus(), 0);
  }

  async function createDraft(event) {
    event.preventDefault();
    const action = event.submitter?.dataset.afterCreate || "editor";
    const title = createTitle.value.trim();
    const sourceUrl = createSourceUrl.value.trim();
    if (!title || !sourceUrl) {
      createStatus.textContent = "Title and Source URL are required.";
      return;
    }
    for (const button of createSubmitButtons) button.disabled = true;
    createStatus.textContent = "Creating draft…";
    try {
      const payload = await apiJson("/api/admin/articles/drafts", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({ title, source_url: sourceUrl }),
      });

      const createdId = payload.article?.article_id || "";
      if (action === "another") {
        createForm.reset();
        createStatus.textContent = `Draft ${createdId} created. Add the next article.`;
        for (const button of createSubmitButtons) button.disabled = false;
        resetAndLoad();
        await loadBatchSummary();
        createTitle.focus();
        return;
      }

      if (action === "archive") {
        createDialog.close();
        resetAndLoad();
        await loadBatchSummary();
        return;
      }

      window.location.assign(payload.editor_url);
    } catch (error) {
      createStatus.textContent = error instanceof Error ? error.message : "Unable to create draft";
      for (const button of createSubmitButtons) button.disabled = false;
    }
  }

  async function loadMore() {
    if (state.loading || state.done) return;

    state.loading = true;
    const version = state.requestVersion;
    setLoadMessage(state.cursor ? "Loading more…" : "Loading articles…");

    try {
      const response = await fetch(queryUrl(), {
        headers: { Accept: "application/json" },
        cache: "no-store",
      });

      if (response.status === 401) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign(`/admin/login?next=${next}`);
        return;
      }

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || `Request failed (${response.status})`);
      }

      const payload = await response.json();
      if (version !== state.requestVersion) return;

      count.textContent = Number(payload.total || 0).toLocaleString();

      const fragment = document.createDocumentFragment();
      for (const article of payload.items || []) {
        fragment.append(makeRow(article));
      }
      list.append(fragment);

      state.cursor = payload.next_cursor || null;
      state.done = !state.cursor;
      setLoadMessage(state.done ? "End of results" : "");

      if (!state.activeRow) {
        const first = list.querySelector(".article-row");
        if (first) first.dispatchEvent(new Event("focus"));
      }
    } catch (error) {
      if (version === state.requestVersion) {
        setLoadMessage(error instanceof Error ? error.message : "Unable to load articles", true);
      }
    } finally {
      if (version === state.requestVersion) {
        state.loading = false;
      }
    }
  }

  function resetAndLoad() {
    state.requestVersion += 1;
    state.cursor = null;
    state.done = false;
    state.loading = false;
    state.activeRow = null;
    list.replaceChildren();
    previewContent.hidden = true;
    previewEmpty.hidden = false;
    count.textContent = "…";
    loadMore();
  }

  search.addEventListener("input", () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      state.q = search.value.trim();
      resetAndLoad();
    }, SEARCH_DELAY_MS);
  });

  for (const button of sortHeaders) {
    button.addEventListener("click", () => {
      const field = button.dataset.sortField;
      const options = SORT_KEYS[field];
      if (!options) return;

      const active = sortStateFromKey(state.sort);
      const direction = active.field === field
        ? (active.direction === "asc" ? "desc" : "asc")
        : (button.dataset.defaultDirection || "asc");

      state.sort = options[direction];
      updateSortHeaders();
      resetAndLoad();
    });
  }

  previewToggle.addEventListener("click", () => {
    setPreviewVisible(!state.previewVisible);
  });

  addArticleButton.addEventListener("click", openCreateDialog);
  createCancel.addEventListener("click", () => createDialog.close());
  createForm.addEventListener("submit", createDraft);
  draftFilterButton.addEventListener("click", () => {
    state.workflowState = state.workflowState === "draft" ? "" : "draft";
    draftFilterButton.dataset.active = state.workflowState === "draft" ? "true" : "false";
    resetAndLoad();
    loadBatchSummary();
  });
		publishBatchButton.addEventListener("click", async () => {
				if (publishBatchButton.disabled) return;

				const confirmed = window.confirm(
						"Publish the complete current draft batch now?\n\n" +
						"All drafts in the current batch must pass validation. " +
						"The canonical article data, related-news data and static " +
						"news pages will be rebuilt as one publication run.",
				);

				if (!confirmed) return;

				const originalText = publishBatchButton.textContent;

				publishBatchButton.disabled = true;
				publishBatchButton.textContent = "Publishing…";

				setBatchPublishStatus(
						"Publishing current batch and rebuilding site data…"
				);

				try {
						const result = await apiJson(
								"/api/admin/articles/batch/current/publish",
								{
										method: "POST",
										headers: {
												"X-CSRF-Token": csrfToken,
										},
								},
						);

						const published = Number(result.published_count || 0);
						const removed = Number(result.withdrawal_count || 0);

						let summary = `✓ Published ${published} article${
								published === 1 ? "" : "s"
						}`;

						if (removed) {
								summary += ` · removed ${removed} article${
										removed === 1 ? "" : "s"
								}`;
						}

						setBatchPublishStatus(summary, "ok");

						state.workflowState = "";
						draftFilterButton.dataset.active = "false";

						resetAndLoad();
						await loadBatchSummary();

				} catch (error) {
						const detail = error instanceof Error
								? error.message
								: "Batch publication failed";

						setBatchPublishStatus(
								`Publication failed: ${detail}`,
								"error",
						);

						await loadBatchSummary();

				} finally {
						publishBatchButton.textContent = originalText;
				}
		});

  const observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadMore();
    },
    { rootMargin: "700px 0px" },
  );

  observer.observe(sentinel);
  updateSortHeaders();
  setPreviewVisible(true);

  (async () => {
    try {
      await loadSession();
      await Promise.all([loadMore(), loadBatchSummary()]);
    } catch (error) {
      setLoadMessage(error instanceof Error ? error.message : "Unable to initialize article admin", true);
    }
  })();
})();
