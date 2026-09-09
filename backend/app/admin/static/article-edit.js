(() => {
  "use strict";

  const match = window.location.pathname.match(/^\/admin\/articles\/(\d+)\/edit\/?$/);
  if (!match) return;
  const articleId = match[1];

  const form = document.getElementById("article-edit-form");
  const message = document.getElementById("editor-message");
  const heading = document.getElementById("editor-heading");
  const stateBox = document.getElementById("editor-state");
  const categoryList = document.getElementById("category-list");
  const categoryFilter = document.getElementById("category-filter");
  const publicationOptions = document.getElementById("publication-options");
  const publicationInput = document.getElementById("field-publication");
  const slugInput = document.getElementById("field-slug");
  const saveButton = document.getElementById("save-article");
  const previewButton = document.getElementById("preview-newsletter");
  const publishButton = document.getElementById("publish-article");
  const deleteArticleButton = document.getElementById("delete-article");
  const removeArticleButton = document.getElementById("remove-article");
  const cancelRemovalButton = document.getElementById("cancel-removal");
  const withdrawDialog = document.getElementById("withdraw-article-dialog");
  const withdrawForm = document.getElementById("withdraw-article-form");
  const withdrawClose = document.getElementById("withdraw-article-close");
  const withdrawCancelDialog = document.getElementById("withdraw-article-cancel-dialog");
  const withdrawReason = document.getElementById("withdraw-reason");
  const withdrawReasonText = document.getElementById("withdraw-reason-text");
  const withdrawRedirectPath = document.getElementById("withdraw-redirect-path");
  const withdrawStatus = document.getElementById("withdraw-article-status");
  const withdrawSubmit = document.getElementById("withdraw-article-submit");
  const previewDialog = document.getElementById("newsletter-preview-dialog");
  const previewClose = document.getElementById("close-newsletter-preview");
  const previewTitle = document.getElementById("newsletter-preview-title");
  const previewMeta = document.getElementById("newsletter-preview-meta");
  const previewSource = document.getElementById("newsletter-preview-source");
  const previewSummary = document.getElementById("newsletter-preview-summary");
  const previewNote = document.getElementById("newsletter-preview-note");
  const imageInput = document.getElementById("field-image-upload");
  const imageUploadLabel = document.getElementById("image-upload-label");
  const imageDiscardButton = document.getElementById("discard-staged-image");
  const imageStageBadge = document.getElementById("image-stage-badge");
  const imageFullFigure = document.getElementById("image-full-figure");
  const imageThumbFigure = document.getElementById("image-thumb-figure");
  const imageFullPreview = document.getElementById("image-full-preview");
  const imageThumbPreview = document.getElementById("image-thumb-preview");
  const imageEmptyState = document.getElementById("image-empty-state");
  const imageFilename = document.getElementById("image-filename");
  const imagePath = document.getElementById("image-path");
  const imageProcessingMeta = document.getElementById("image-processing-meta");

  const fields = {
    articleId: document.getElementById("field-article-id"),
    title: document.getElementById("field-title"),
    slug: slugInput,
    path: document.getElementById("field-path"),
    url: document.getElementById("field-url"),
    legacyUrl: document.getElementById("field-legacy-url"),
    publicationDate: document.getElementById("field-publication-date"),
    postedDate: document.getElementById("field-posted-date"),
    publicationDetail: document.getElementById("field-publication-detail"),
    publicationRaw: document.getElementById("field-publication-raw"),
    sourceUrl: document.getElementById("field-source-url"),
    summary: document.getElementById("field-summary"),
    note: document.getElementById("field-note"),
    priority: document.getElementById("field-priority"),
    imageCaptionMarkdown: document.getElementById("field-image-caption-markdown"),
  };

  let csrfToken = "";
  let referenceData = null;
  let publicationByName = new Map();
  let dirty = false;
  let loading = true;
  let currentAdminState = null;

  function setMessage(text, type = "") {
    message.textContent = text;
    message.dataset.type = type;
  }



  function safePreviewUrl(value) {
    const raw = String(value || "").trim();
    if (!raw) return null;
    if (raw.startsWith("/")) return `https://www.wanttoknow.info${raw}`;
    try {
      const parsed = new URL(raw);
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
      if (char === "(") {
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
        const href = safePreviewUrl(link.url);
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
        const href = safePreviewUrl(bare.url);
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

  function renderMarkdownInto(target, value, emptyText = "") {
    target.replaceChildren();
    const source = String(value || "").replace(/\r\n?/g, "\n");
    if (!source.trim()) {
      if (emptyText) target.textContent = emptyText;
      return;
    }

    const blocks = source.split(/\n{2,}/);
    for (const rawBlock of blocks) {
      const block = rawBlock.trim();
      if (!block) continue;
      const isQuote = block.split("\n").every((line) => /^\s{0,3}>/.test(line));
      const element = document.createElement(isQuote ? "blockquote" : "p");
      const content = isQuote
        ? block.split("\n").map((line) => line.replace(/^\s{0,3}>\s?/, "")).join("\n")
        : block;
      appendInlineMarkdown(element, content);
      target.append(element);
    }
  }

  function formatNewsletterDate(value) {
    const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!match) return value || "Date not set";
    const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
    return new Intl.DateTimeFormat("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    }).format(date);
  }

  function displayUrl(value, max = 92) {
    const text = String(value || "").trim();
    return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
  }

  function openNewsletterPreview() {
    const publicationName = publicationInput.value.trim() || "Publication not set";
    const strongTitle = document.createElement("strong");
    strongTitle.textContent = fields.title.value.trim() || "Untitled article";
    previewTitle.replaceChildren(strongTitle);

    const metaStrong = document.createElement("strong");
    metaStrong.append(document.createTextNode(`${formatNewsletterDate(fields.publicationDate.value)}, `));
    const publicationEm = document.createElement("em");
    publicationEm.textContent = publicationName;
    metaStrong.append(publicationEm);
    previewMeta.replaceChildren(metaStrong);

    const sourceHref = safePreviewUrl(fields.sourceUrl.value);
    if (sourceHref) {
      previewSource.hidden = false;
      previewSource.href = sourceHref;
      previewSource.textContent = displayUrl(fields.sourceUrl.value);
    } else {
      previewSource.hidden = true;
      previewSource.removeAttribute("href");
      previewSource.textContent = "";
    }

    renderMarkdownInto(previewSummary, fields.summary.value, "No summary entered.");
    renderMarkdownInto(previewNote, fields.note.value);
    if (previewNote.childNodes.length) {
      const first = previewNote.firstElementChild || previewNote;
      const label = document.createElement("strong");
      label.textContent = "Note: ";
      first.insertBefore(label, first.firstChild);
      previewNote.hidden = false;
    } else {
      previewNote.hidden = true;
    }

    previewDialog.showModal();
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }

  function thumbnailPathFor(articleIdValue) {
    return `/assets/images/article-thumbs/${articleIdValue}-thumb.jpg`;
  }

  function setImagePreview(img, figure, url) {
    if (!url) {
      img.removeAttribute("src");
      figure.hidden = true;
      return;
    }
    img.src = url;
    figure.hidden = false;
  }

  function renderImageStatus(status) {
    const staged = status?.staged || null;
    const published = status?.published || null;
    const working = status?.working || null;

    imageStageBadge.hidden = !staged;
    imageDiscardButton.hidden = !staged;
    imageUploadLabel.textContent = staged || working ? "Replace image" : "Choose image";

    if (staged) {
      const cacheKey = staged.full?.sha256 ? staged.full.sha256.slice(0, 12) : Date.now();
      setImagePreview(
        imageFullPreview,
        imageFullFigure,
        `${staged.full.preview_url}?v=${encodeURIComponent(cacheKey)}`,
      );
      setImagePreview(
        imageThumbPreview,
        imageThumbFigure,
        `${staged.thumbnail.preview_url}?v=${encodeURIComponent(cacheKey)}`,
      );
      imageEmptyState.hidden = true;
      imageFilename.textContent = working?.filename || `${articleId}i.jpg`;
      imagePath.textContent = working?.path || `/assets/images/article-images/${articleId}i.jpg`;
      imageProcessingMeta.textContent = [
        `${staged.full.width}×${staged.full.height}`,
        formatBytes(staged.full.bytes),
        `thumbnail ${staged.thumbnail.width}×${staged.thumbnail.height}`,
        `staged by ${staged.staged_by}`,
      ].filter(Boolean).join(" · ");
      return;
    }

    if (published) {
      setImagePreview(imageFullPreview, imageFullFigure, published.path);
      setImagePreview(imageThumbPreview, imageThumbFigure, thumbnailPathFor(articleId));
      imageEmptyState.hidden = true;
      imageFilename.textContent = published.filename;
      imagePath.textContent = published.path;
      imageProcessingMeta.textContent = "Published image; replacement will be staged privately.";
      return;
    }

    setImagePreview(imageFullPreview, imageFullFigure, null);
    setImagePreview(imageThumbPreview, imageThumbFigure, null);
    imageEmptyState.hidden = false;
    imageFilename.textContent = "No article image";
    imagePath.textContent = "";
    imageProcessingMeta.textContent = "";
  }

  async function uploadImage(file) {
    if (!file) return;
    const maxBytes = 5 * 1024 * 1024;
    const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);

    if (file.size > maxBytes) {
      setMessage("Image exceeds the 5 MB upload limit.", "error");
      imageInput.value = "";
      return;
    }
    if (file.type && !allowedTypes.has(file.type)) {
      setMessage("Choose a JPEG, PNG or WebP image.", "error");
      imageInput.value = "";
      return;
    }

    imageInput.disabled = true;
    imageDiscardButton.disabled = true;
    imageUploadLabel.textContent = "Processing…";
    setMessage("Uploading and processing image in memory…");

    try {
      const response = await fetch(`/api/admin/articles/${articleId}/image`, {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": file.type || "application/octet-stream",
          "X-CSRF-Token": csrfToken,
        },
        body: file,
      });
      if (response.status === 401) {
        const next = encodeURIComponent(window.location.pathname + window.location.search);
        window.location.assign(`/admin/login?next=${next}`);
        return;
      }
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || `Image upload failed (${response.status})`);

      renderState({
        edit_state: body.edit_state,
        workflow_state: body.workflow_state,
        admin_updated_by: body.staged?.staged_by,
      });
      const status = await apiJson(`/api/admin/articles/${articleId}/image`);
      renderImageStatus(status);
      setMessage("Processed image staged in SQLite/admin storage. Public image remains unchanged.", "ok");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to stage image", "error");
    } finally {
      imageInput.disabled = false;
      imageDiscardButton.disabled = false;
      imageInput.value = "";
      if (imageUploadLabel.textContent === "Processing…") imageUploadLabel.textContent = "Choose image";
    }
  }

  async function discardStagedImage() {
    imageDiscardButton.disabled = true;
    imageInput.disabled = true;
    setMessage("Discarding staged image…");
    try {
      const result = await apiJson(`/api/admin/articles/${articleId}/image`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrfToken },
      });
      renderState({
        edit_state: result.edit_state,
        workflow_state: result.workflow_state,
      });
      const status = await apiJson(`/api/admin/articles/${articleId}/image`);
      renderImageStatus(status);
      setMessage("Staged image discarded. Previous published image restored in the working copy.", "ok");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to discard staged image", "error");
    } finally {
      imageDiscardButton.disabled = false;
      imageInput.disabled = false;
    }
  }

  function openWithdrawalDialog() {
    if (dirty) {
      setMessage("Save the current draft before scheduling removal so the audit record matches the SQLite working copy.", "warning");
      return;
    }
    withdrawForm.reset();
    withdrawStatus.textContent = "";
    withdrawSubmit.disabled = false;
    withdrawDialog.showModal();
    window.setTimeout(() => withdrawReason.focus(), 0);
  }

  async function scheduleWithdrawal(event) {
    event.preventDefault();
    const reasonCode = withdrawReason.value;
    const reasonText = withdrawReasonText.value.trim();
    const redirectPath = withdrawRedirectPath.value.trim();
    if (!reasonCode) {
      withdrawStatus.textContent = "Choose a removal reason.";
      withdrawReason.focus();
      return;
    }
    if (reasonCode === "other" && !reasonText) {
      withdrawStatus.textContent = "Describe the removal reason when choosing Other.";
      withdrawReasonText.focus();
      return;
    }

    withdrawSubmit.disabled = true;
    withdrawStatus.textContent = "Scheduling removal…";
    try {
      const result = await apiJson(`/api/admin/articles/${articleId}/withdrawal`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify({
          reason_code: reasonCode,
          reason_text: reasonText,
          redirect_path: redirectPath,
        }),
      });
      renderState({ ...(result.admin || {}), withdrawal: result.withdrawal || null });
      withdrawDialog.close();
      const disposition = result.withdrawal?.redirect_path
        ? `301 redirect to ${result.withdrawal.redirect_path}`
        : "410 Gone";
      setMessage(`Removal scheduled in the current batch (${disposition}). Master JSONL and live site are unchanged.`, "warning");
    } catch (error) {
      withdrawStatus.textContent = error instanceof Error ? error.message : "Unable to schedule removal";
      withdrawSubmit.disabled = false;
    }
  }

  async function cancelWithdrawal() {
    const withdrawal = currentAdminState?.withdrawal;
    if (!withdrawal) return;
    const confirmed = window.confirm(
      `Cancel scheduled removal for article ${articleId}?\n\nThe article will remain live. Any other saved draft edits or staged image will remain as drafts.`
    );
    if (!confirmed) return;

    cancelRemovalButton.disabled = true;
    setMessage("Cancelling scheduled removal…");
    try {
      const result = await apiJson(`/api/admin/articles/${articleId}/withdrawal`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrfToken },
      });
      renderState({ ...(result.admin || {}), withdrawal: null });
      setMessage("Scheduled removal cancelled. The live site and master JSONL were never changed.", "ok");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to cancel removal", "error");
    } finally {
      cancelRemovalButton.disabled = false;
    }
  }

  async function deleteArticleEntry() {
    if (currentAdminState?.edit_state !== "new") return;
    const title = fields.title.value.trim() || `article ${articleId}`;
    const confirmed = window.confirm(
      `Delete draft ${articleId}: ${title}?\n\nThis removes the never-published SQLite entry and any staged image. The public site and master JSONL are unchanged.`
    );
    if (!confirmed) return;

    deleteArticleButton.disabled = true;
    saveButton.disabled = true;
    setMessage("Deleting draft entry…");
    try {
      await apiJson(`/api/admin/articles/${articleId}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": csrfToken },
      });
      dirty = false;
      window.location.assign("/admin/articles");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to delete draft", "error");
      deleteArticleButton.disabled = false;
      saveButton.disabled = false;
    }
  }

  function updateGeneratedUrl() {
    const slug = fields.slug.value.trim();
    fields.path.value = slug ? `/news/${slug}` : "";
    fields.url.value = slug ? `https://www.wanttoknow.info/news/${slug}` : "";
  }

  function renderState(admin) {
    currentAdminState = { ...(currentAdminState || {}), ...(admin || {}) };
    const state = currentAdminState;
    const withdrawal = state.withdrawal || null;
    const isNew = state.edit_state === "new";

    deleteArticleButton.hidden = !isNew;
    removeArticleButton.hidden = isNew || Boolean(withdrawal);
    cancelRemovalButton.hidden = !withdrawal;

				const publishable =
						Boolean(withdrawal) ||
						["draft", "ready"].includes(state.workflow_state);

				if (publishable) {
						publishButton.disabled = false;
						publishButton.textContent = withdrawal
								? "Publish Removal"
								: "Publish to Site";

						publishButton.title = withdrawal
								? "Publish this removal to the site"
								: "Publish this article to the site";
				} else {
						publishButton.disabled = true;
						publishButton.textContent = "✓ Published";
						publishButton.title = "This article has no unpublished changes";
				}

    stateBox.replaceChildren();
    const edit = document.createElement("span");
    edit.className = "article-edit-state__badge";
    edit.textContent = state.edit_state || "clean";

    const workflow = document.createElement("span");
    workflow.className = withdrawal
      ? "article-edit-state__badge article-edit-state__badge--withdrawn"
      : "article-edit-state__badge";
    workflow.textContent = withdrawal ? "withdrawn" : (state.workflow_state || "published");
    stateBox.append(edit, workflow);

    if (withdrawal) {
      const detail = document.createElement("small");
      const disposition = withdrawal.redirect_path ? `301 → ${withdrawal.redirect_path}` : "410 Gone";
      detail.className = "article-edit-state__withdrawal";
      detail.textContent = `${withdrawal.reason_label || withdrawal.reason_code} · ${disposition}`;
      stateBox.append(detail);
    } else if (state.admin_updated_by) {
      const by = document.createElement("small");
      by.textContent = `Last saved by ${state.admin_updated_by}`;
      stateBox.append(by);
    }
  }
		
		function markEditorDirty() {
				if (loading) return;

				dirty = true;

				publishButton.disabled = false;
				publishButton.textContent = currentAdminState?.withdrawal
						? "Publish Removal"
						: "Publish to Site";

				publishButton.title = currentAdminState?.withdrawal
						? "Save these edits and publish the scheduled removal"
						: "Save these edits and publish this article to the site";
		}		

  function renderReferences(data) {
    referenceData = data;
    publicationByName = new Map();
    publicationOptions.replaceChildren();
    for (const pub of data.publications || []) {
      publicationByName.set(pub.display_name, pub.slug);
      const option = document.createElement("option");
      option.value = pub.display_name;
      publicationOptions.append(option);
    }
  }

  function renderCategories(selected) {
    const selectedSet = new Set(selected || []);
    categoryList.replaceChildren();

    for (const category of referenceData.categories || []) {
      const label = document.createElement("label");
      label.className = "article-category-option";
      label.dataset.categorySearch = `${category.label} ${category.slug} ${category.topic || ""} ${(category.secondary_topics || []).join(" ")}`.toLowerCase();
      label.title = `${category.label} · used by ${Number(category.usage_count || 0).toLocaleString()} articles`;

      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = category.slug;
      input.checked = selectedSet.has(category.slug);
      input.dataset.articleCategory = "true";

      const text = document.createElement("span");
      text.textContent = category.label;
      label.append(input, text);
      categoryList.append(label);
    }
  }

  function populateArticle(article) {
    heading.textContent = `Edit article ${article.article_id}`;
    fields.articleId.value = article.article_id;
    fields.title.value = article.title || "";
    fields.slug.value = article.slug || "";
    fields.path.value = article.path || "";
    fields.url.value = article.url || "";
    fields.legacyUrl.value = article.legacy_url || "";
    fields.publicationDate.value = article.publication_date || "";
    fields.postedDate.value = article.posted_date || "";
    publicationInput.value = article.publication_name || "";
    publicationInput.dataset.slug = article.publication_group || "";
    fields.publicationDetail.value = article.publication_detail || "";
    fields.publicationRaw.value = article.publication_raw || "";
    fields.sourceUrl.value = article.source_url || "";
    fields.summary.value = article.summary_markdown || "";
    fields.note.value = article.note_markdown || "";
    fields.priority.value = String(article.priority ?? "");
    fields.imageCaptionMarkdown.value = article.image_caption_markdown || "";
    document.getElementById("related-count").textContent = String((article.related_articles || []).length);
    document.getElementById("qc-count").textContent = String((article.qc_flags || []).length);
    renderCategories(article.tags || []);
    renderState(article.admin || {});
    form.hidden = false;
    dirty = false;
  }

  async function apiJson(url, options = {}) {
    const response = await fetch(url, { cache: "no-store", ...options });
    if (response.status === 401) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/admin/login?next=${next}`);
      throw new Error("Authentication required");
    }
    const body = await response.json().catch(() => null);
    if (!response.ok) throw new Error(body?.detail || `Request failed (${response.status})`);
    return body;
  }

  async function initialize() {
    try {
      setMessage("Loading article…");
      const [session, refs, article, imageStatus] = await Promise.all([
        apiJson("/api/admin/session"),
        apiJson("/api/admin/articles/reference-data"),
        apiJson(`/api/admin/articles/${articleId}`),
        apiJson(`/api/admin/articles/${articleId}/image`),
      ]);
      csrfToken = session.csrf_token;
      renderReferences(refs);
      populateArticle(article);
      renderImageStatus(imageStatus);
      setMessage("SQLite working copy loaded.", "ok");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to load article", "error");
    } finally {
      loading = false;
    }
  }



  function collectArticlePayload() {
    const publicationText = publicationInput.value.trim();
    const publicationGroup = publicationText ? publicationByName.get(publicationText) : "";
    if (publicationText && !publicationGroup) {
      setMessage("Choose a publication from the canonical publication list, or leave it blank while drafting.", "error");
      publicationInput.focus();
      return null;
    }

    const tags = Array.from(
      document.querySelectorAll("[data-article-category]:checked"),
      (input) => input.value,
    );
    const priority = Number.parseInt(fields.priority.value || "0", 10);
    return {
      title: fields.title.value,
      slug: fields.slug.value,
      legacy_url: fields.legacyUrl.value,
      publication_date: fields.publicationDate.value,
      posted_date: fields.postedDate.value,
      publication_group: publicationGroup,
      publication_detail: fields.publicationDetail.value,
      publication_raw: fields.publicationRaw.value,
      source_url: fields.sourceUrl.value,
      summary_markdown: fields.summary.value,
      note_markdown: fields.note.value,
      tags,
      priority,
      image_caption_markdown: fields.imageCaptionMarkdown.value,
    };
  }

  async function saveDraft({ quiet = false } = {}) {
    const payload = collectArticlePayload();
    if (!payload) return false;

    saveButton.disabled = true;
    if (!quiet) setMessage("Saving draft to SQLite…");
    try {
      const result = await apiJson(`/api/admin/articles/${articleId}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
      });
      renderState(result.admin || {});
      updateGeneratedUrl();
      dirty = false;
      if (!quiet) {
        const warning = (result.warnings || []).join(" ");
        setMessage(
          warning ? `Saved to SQLite. Master JSONL unchanged. ${warning}` : "Saved to SQLite. Master JSONL and public site are unchanged.",
          warning ? "warning" : "ok",
        );
      }
      return true;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save article", "error");
      return false;
    } finally {
      saveButton.disabled = false;
    }
  }

  async function publishCurrentArticle() {
    if (publishButton.disabled) return;

    if (dirty) {
      setMessage("Saving current edits before publication…");
      const saved = await saveDraft({ quiet: true });
      if (!saved) return;
    }

    const withdrawal = currentAdminState?.withdrawal || null;
    const confirmed = window.confirm(
      withdrawal
        ? `Publish removal of article ${articleId} now?\n\nThis will remove it from the canonical JSONL and regenerated site output.`
        : `Publish article ${articleId} to the site now?\n\nThis will rebuild the canonical article data, related-news data and static news pages.`,
    );
    if (!confirmed) return;

    publishButton.disabled = true;
    saveButton.disabled = true;
    setMessage(withdrawal ? "Publishing article removal…" : "Publishing article and rebuilding site data…");
    try {
      const result = await apiJson(`/api/admin/articles/${articleId}/publish`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      });
      dirty = false;
      if (Number(result.withdrawal_count || 0) > 0) {
        window.location.assign("/admin/articles");
        return;
      }
      const warnings = (result.warnings || []).join(" ");
      await initialize();
      setMessage(
        warnings ? `Published successfully. ${warnings}` : "Published successfully. Canonical data and generated news pages are current.",
        warnings ? "warning" : "ok",
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Publication failed", "error");
      renderState(currentAdminState || {});
    } finally {
      saveButton.disabled = false;
      if (currentAdminState) renderState(currentAdminState);
    }
  }

  previewButton.addEventListener("click", openNewsletterPreview);
  publishButton.addEventListener("click", publishCurrentArticle);
  previewClose.addEventListener("click", () => previewDialog.close());
  previewDialog.addEventListener("click", (event) => {
    if (event.target === previewDialog) previewDialog.close();
  });

  imageInput.addEventListener("change", () => {
    uploadImage(imageInput.files?.[0] || null);
  });
  imageDiscardButton.addEventListener("click", discardStagedImage);
  deleteArticleButton.addEventListener("click", deleteArticleEntry);
  removeArticleButton.addEventListener("click", openWithdrawalDialog);
  cancelRemovalButton.addEventListener("click", cancelWithdrawal);
  withdrawForm.addEventListener("submit", scheduleWithdrawal);
  withdrawClose.addEventListener("click", () => withdrawDialog.close());
  withdrawCancelDialog.addEventListener("click", () => withdrawDialog.close());
  withdrawDialog.addEventListener("click", (event) => {
    if (event.target === withdrawDialog) withdrawDialog.close();
  });

  publicationInput.addEventListener("input", () => {
    publicationInput.dataset.slug = publicationByName.get(publicationInput.value.trim()) || "";
  });

  slugInput.addEventListener("input", updateGeneratedUrl);

  categoryFilter.addEventListener("input", () => {
    const query = categoryFilter.value.trim().toLowerCase();
    for (const option of categoryList.querySelectorAll(".article-category-option")) {
      option.hidden = Boolean(query) && !option.dataset.categorySearch.includes(query);
    }
  });

		form.addEventListener("input", markEditorDirty);
		form.addEventListener("change", markEditorDirty);

				form.addEventListener("submit", async (event) => {
						event.preventDefault();
						await saveDraft();
				});

  window.addEventListener("beforeunload", (event) => {
    if (!dirty) return;
    event.preventDefault();
    event.returnValue = "";
  });

  initialize();
})();
