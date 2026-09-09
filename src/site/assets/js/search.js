(() => {
  "use strict";

  const DEFAULT_WEIGHTS = Object.freeze({
    title: 3.0,
    text: 6.0,
    publisher: 2.0,
    topics: 2.5
  });

  const PAGE_SIZE = 20;
  const ALL_RECORD_TYPES = Object.freeze([
    "news",
    "page_chunk",
    "substack_chunk",
    "youtube_chunk"
  ]);

  const TYPE_LABELS = Object.freeze({
    news: "News",
    page_chunk: "WTK Page",
    substack_chunk: "PEERS Substack",
    youtube_chunk: "Video Transcript"
  });

  const API_BASE = String(
    document.documentElement.dataset.apiBase || ""
  ).replace(/\/$/, "");

  const SEARCH_URL = `${API_BASE}/api/search`;
  const OPTIONS_URL = `${API_BASE}/api/search/options`;
  const DETAIL_URL = (refId) => `${API_BASE}/api/search/result/${encodeURIComponent(refId)}`;
  const RELATED_URL = (refId) => (
    `${API_BASE}/api/search/related/${encodeURIComponent(refId)}`
  );
  const AI_SYNTHESIS_URL = `${API_BASE}/api/search/synthesis`;
  const AI_CONFIG_URL = `${AI_SYNTHESIS_URL}/config`;

  function $(selector, root = document) {
    if (!root || typeof root.querySelector !== "function") {
      return null;
    }

    return root.querySelector(selector);
  }

  function $$(selector, root = document) {
    if (!root || typeof root.querySelectorAll !== "function") {
      return [];
    }

    return [...root.querySelectorAll(selector)];
  }

  let activeController = null;
  let currentResultCount = 0;
  let lastRequest = null;
  let modalReturnFocus = null;
  let relatedModalReturnFocus = null;
  let relatedRequestSerial = 0;

  let aiPublicConfig = null;
  let aiConfigFailed = false;
  let aiPageLoadedAt = null;
  let aiGateTimer = null;
  let aiCooldownUntil = 0;
  let aiController = null;
  let aiActive = false;
  let aiSearchSerial = 0;
  let aiRunSerial = 0;
  let completedSearchSnapshot = null;
  let aiCanonicalMarkdown = "";
  let aiStreamSources = [];
  let aiQualityRatingTouched = false;

  const detailCache = new Map();
  const relatedDataCache = new Map();

  const dom = {};

  function escapeHtml(value = "") {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeHref(value = "") {
    const href = String(value || "").trim();

    if (
      href.startsWith("/")
      || /^https?:\/\//i.test(href)
    ) {
      return href;
    }

    return "#";
  }

  function resultHref(result) {
    const href = safeHref(result?.url);

    if (result?.record_type !== "news" || href === "#") {
      return href;
    }

    try {
      const url = new URL(href, window.location.origin);

      if (url.pathname.startsWith("/news/")) {
        return `${url.pathname}${url.search}${url.hash}`;
      }
    } catch {
      // Fall back to the stored URL if it cannot be parsed.
    }

    return href;
  }

		function setAiQualityRating(rating) {
				if (!dom.aiLogToggle) return;

				const normalized = rating === "minus"
						? "minus"
						: "plus";

				const isPlus = normalized === "plus";

				dom.aiLogToggle.dataset.qualityRating = normalized;
				dom.aiLogToggle.setAttribute("aria-pressed", String(isPlus));

				if (dom.aiLogSymbol) {
						dom.aiLogSymbol.textContent = isPlus ? "+" : "−";
				}

				const label = isPlus
						? "Quality classification: plus. Click to classify as minus."
						: "Quality classification: minus. Click to classify as plus.";

				dom.aiLogToggle.setAttribute("aria-label", label);
				dom.aiLogToggle.title = label;
		}


		function aiQualityRating() {
				return dom.aiLogToggle?.dataset.qualityRating === "minus"
						? "minus"
						: "plus";
		}

  function initializeAiPageGate() {
    const markLoaded = () => {
      if (aiPageLoadedAt !== null) return;
      aiPageLoadedAt = Date.now();
      updateAiButtonState();
    };

    if (document.readyState === "complete") {
      markLoaded();
    } else {
      window.addEventListener("load", markLoaded, { once: true });
    }
  }

  async function loadAiConfig() {
    try {
      const response = await fetch(AI_CONFIG_URL, {
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
      });

      if (!response.ok) {
        throw new Error(`AI config request failed (${response.status}).`);
      }

      const payload = await response.json();
      const initialDelay = Number(payload.initial_button_delay_seconds);
      const cooldown = Number(payload.cooldown_seconds);
      const sourceCount = Number(payload.source_count);

      if (
        !Number.isFinite(initialDelay)
        || initialDelay < 0
        || !Number.isFinite(cooldown)
        || cooldown < 0
        || !Number.isInteger(sourceCount)
        || sourceCount < 1
      ) {
        throw new Error("AI configuration response was malformed.");
      }

						aiPublicConfig = {
								initialButtonDelaySeconds: initialDelay,
								cooldownSeconds: cooldown,
								sourceCount,
								qualityRatingDefault:
										payload.quality_rating_default === "minus"
												? "minus"
												: "plus",
								model:
										typeof payload.model === "string"
												? payload.model.trim()
												: ""
						};
						if (dom.aiModel) {
								dom.aiModel.textContent =
										aiPublicConfig.model || "Unavailable";

								dom.aiModel.title =
										aiPublicConfig.model || "";
						}				
      aiConfigFailed = payload.available === false;

      if (aiConfigFailed) {
        console.warn("AI synthesis backend is not ready.", {
          keyConfigured: payload.key_configured,
          promptConfigured: payload.prompt_configured
        });
      }

						if (!aiQualityRatingTouched) {
								setAiQualityRating(aiPublicConfig.qualityRatingDefault);
						}
    } catch (error) {
      aiPublicConfig = null;
      aiConfigFailed = true;
      console.warn("AI synthesis configuration is unavailable.", error);
    } finally {
      updateAiButtonState();
      refreshAiReadyStatus();
    }
  }

  function clearAiGateTimer() {
    if (aiGateTimer !== null) {
      window.clearTimeout(aiGateTimer);
      aiGateTimer = null;
    }
  }

  function scheduleAiButtonUpdate(milliseconds) {
    clearAiGateTimer();

    if (!Number.isFinite(milliseconds) || milliseconds <= 0) return;

    aiGateTimer = window.setTimeout(
      updateAiButtonState,
      Math.min(1000, Math.max(100, milliseconds))
    );
  }

  function aiInitialGateRemainingMs() {
    if (!aiPublicConfig || aiPageLoadedAt === null) return Number.POSITIVE_INFINITY;

    const elapsed = Date.now() - aiPageLoadedAt;
    return Math.max(
      0,
      (aiPublicConfig.initialButtonDelaySeconds * 1000) - elapsed
    );
  }

  function aiCooldownRemainingMs() {
    return Math.max(0, aiCooldownUntil - Date.now());
  }

  function updateAiButtonState() {
    if (!dom.aiButton) return;

    clearAiGateTimer();

    let disabled = true;
    let label = "AI Summary";
    let title = "Run an optional AI synthesis of the top ranked results";
    let nextUpdate = 0;

    if (aiActive) {
      label = "Synthesizing…";
      title = "AI synthesis is currently running";
    } else if (!completedSearchSnapshot?.resultRefIds?.length) {
      title = "Run a normal search before requesting AI synthesis";
    } else if (aiConfigFailed) {
      title = "AI synthesis configuration is unavailable";
    } else if (!aiPublicConfig) {
      title = "Loading AI synthesis configuration";
    } else {
      const initialRemaining = aiInitialGateRemainingMs();
      const cooldownRemaining = aiCooldownRemainingMs();

      if (aiPageLoadedAt === null) {
        title = "AI synthesis becomes available after page load";
      } else if (initialRemaining > 0) {
        const seconds = Math.max(1, Math.ceil(initialRemaining / 1000));
        label = `AI Synthesis · ${seconds}s`;
        title = "AI synthesis becomes available shortly after page load";
        nextUpdate = initialRemaining;
      } else if (cooldownRemaining > 0) {
        const seconds = Math.max(1, Math.ceil(cooldownRemaining / 1000));
        label = `AI Synthesis · ${seconds}s`;
        title = "AI synthesis cooldown is active";
        nextUpdate = cooldownRemaining;
      } else {
        disabled = false;
      }
    }

    dom.aiButton.disabled = disabled;
    dom.aiButton.textContent = label;
    dom.aiButton.title = title;

    if (dom.aiLogToggle) {
      dom.aiLogToggle.disabled = aiActive;
    }

    if (nextUpdate > 0) {
      scheduleAiButtonUpdate(nextUpdate);
    }
  }

  function prepareAiStreamDom() {
    if (!dom.aiOutput) return;

    const stream = document.createElement("div");
    stream.className = "search-ai-panel__stream";
    stream.dataset.aiStream = "";

    const text = document.createElement("span");
    text.dataset.aiStreamText = "";

    const caret = document.createElement("span");
    caret.className = "search-ai-panel__caret";
    caret.dataset.aiCaret = "";
    caret.setAttribute("aria-hidden", "true");

    stream.append(text, caret);
    dom.aiOutput.replaceChildren(stream);
    dom.aiStreamText = text;
    dom.aiCaret = caret;
  }

  function resetAiPanelOutput() {
    aiCanonicalMarkdown = "";
    aiStreamSources = [];

    if (dom.aiPanel) {
      dom.aiPanel.classList.remove("is-error");
    }

    if (dom.aiOutput) {
      dom.aiOutput.hidden = true;
      dom.aiOutput.replaceChildren();
    }

    dom.aiStreamText = null;
    dom.aiCaret = null;

    if (dom.aiSources) {
      dom.aiSources.hidden = true;
      dom.aiSources.replaceChildren();
    }

    if (dom.aiCopy) {
      dom.aiCopy.disabled = true;
    }
  }

  function refreshAiReadyStatus() {
    if (!dom.aiStatus || aiActive || !completedSearchSnapshot) return;

    if (aiConfigFailed) {
      dom.aiStatus.textContent = "AI synthesis is unavailable right now. Normal search is unaffected.";
    } else if (!aiPublicConfig) {
      dom.aiStatus.textContent = "Preparing the optional AI synthesis tool. Normal search is unaffected.";
    } else {
      dom.aiStatus.textContent = "AI synthesis is available after a deliberate click. Normal search remains independent.";
    }
  }

  function hideAiPanel() {
    resetAiPanelOutput();

    if (dom.aiPanel) {
      dom.aiPanel.hidden = true;
    }
  }

  function invalidateAiForSearchChange() {
    aiSearchSerial += 1;
    completedSearchSnapshot = null;

    if (aiController) {
      aiController.abort();
    }

    aiController = null;
    aiActive = false;
    hideAiPanel();
    updateAiButtonState();
  }

  function captureCompletedSearchSnapshot(request, payload) {
    const resultRefIds = Array.isArray(payload?.results)
      ? payload.results
        .map((result) => Number(result?.ref_id))
        .filter((refId) => Number.isInteger(refId) && refId > 0)
      : [];

    completedSearchSnapshot = resultRefIds.length
      ? {
          searchSerial: aiSearchSerial,
          request: JSON.parse(JSON.stringify({ ...request, offset: 0 })),
          resultRefIds
        }
      : null;

    // A completed normal search only makes AI synthesis eligible. It must not
    // reveal the AI response area; that area is user-initiated and appears only
    // when the AI Synthesis button itself is clicked.
    hideAiPanel();
    updateAiButtonState();
  }

  function aiRunIsCurrent(runSerial, searchSerial, controller) {
    return (
      runSerial === aiRunSerial
      && searchSerial === aiSearchSerial
      && controller === aiController
      && completedSearchSnapshot?.searchSerial === searchSerial
    );
  }

  function applyServerCooldownFromResponse(response) {
    const retryAfter = Number(response.headers.get("Retry-After"));
    const remaining = Number(
      response.headers.get("X-WTK-AI-Cooldown-Remaining-Seconds")
    );

    const seconds = Number.isFinite(retryAfter) && retryAfter > 0
      ? retryAfter
      : Number.isFinite(remaining) && remaining > 0
        ? remaining
        : 0;

    if (seconds > 0) {
      aiCooldownUntil = Math.max(aiCooldownUntil, Date.now() + (seconds * 1000));
    }
  }

  async function aiHttpErrorMessage(response) {
    let payload = null;

    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (typeof payload?.detail === "string" && payload.detail.trim()) {
      return payload.detail.trim();
    }

    return `AI synthesis request failed (${response.status}).`;
  }

  function renderAiSources(sources) {
    if (!dom.aiSources || !Array.isArray(sources) || !sources.length) return;

    const heading = document.createElement("p");
    heading.className = "search-ai-panel__sources-title";
    heading.textContent = "Sources used";

    const list = document.createElement("ol");
    list.className = "search-ai-panel__sources-list";

    sources.forEach((source) => {
      const item = document.createElement("li");
      const href = safeHref(source?.url);
      const rank = Number(source?.rank);
      const title = String(source?.title || "Untitled result");
      const label = Number.isInteger(rank) ? `${rank}. ${title}` : title;

      if (href === "#") {
        const text = document.createElement("span");
        text.textContent = label;
        item.append(text);
      } else {
        const link = document.createElement("a");
        link.href = href;
        link.textContent = label;

        if (/^https?:\/\//i.test(href)) {
          link.rel = "noopener noreferrer";
        }

        item.append(link);
      }

      const details = [];
      if (source?.publisher) details.push(String(source.publisher));
      if (source?.published_at) details.push(formatDate(source.published_at));

      if (details.length) {
        const meta = document.createElement("span");
        meta.textContent = ` — ${details.join(" · ")}`;
        item.append(meta);
      }

      list.append(item);
    });

    dom.aiSources.replaceChildren(heading, list);
    dom.aiSources.hidden = false;
  }

  function setAiFailure(message) {
    if (dom.aiPanel) {
      dom.aiPanel.hidden = false;
      dom.aiPanel.classList.add("is-error");
    }

    if (dom.aiCaret) {
      dom.aiCaret.hidden = true;
    }

    if (dom.aiStatus) {
      dom.aiStatus.textContent = message || "AI synthesis could not be completed.";
    }

    if (dom.aiCopy) {
      dom.aiCopy.disabled = true;
    }

    if (!aiCanonicalMarkdown && dom.aiOutput) {
      dom.aiOutput.hidden = true;
    }

    if (dom.aiSources) {
      dom.aiSources.hidden = true;
    }
  }

  function processAiStreamEvent(event, runSerial, searchSerial, controller) {
    if (!aiRunIsCurrent(runSerial, searchSerial, controller)) {
      return "stale";
    }

    if (!event || typeof event !== "object" || typeof event.type !== "string") {
      throw new Error("AI stream returned malformed data.");
    }

    if (event.type === "meta") {
      if (!Array.isArray(event.sources)) {
        throw new Error("AI stream source metadata was malformed.");
      }

      aiStreamSources = event.sources;
      return "continue";
    }

    if (event.type === "delta") {
      if (typeof event.text !== "string") {
        throw new Error("AI stream content was malformed.");
      }

      aiCanonicalMarkdown += event.text;

      if (dom.aiStreamText && event.text) {
        dom.aiStreamText.append(document.createTextNode(event.text));
      }

      if (dom.aiCaret) {
        dom.aiCaret.hidden = false;
      }

      return "continue";
    }

    if (event.type === "error") {
      throw new Error(
        typeof event.message === "string" && event.message.trim()
          ? event.message.trim()
          : "AI synthesis was interrupted."
      );
    }

    if (event.type === "done") {
      if (typeof event.html !== "string") {
        throw new Error("AI stream completion data was malformed.");
      }

      if (dom.aiCaret) {
        dom.aiCaret.hidden = true;
      }

      if (dom.aiOutput) {
        dom.aiOutput.hidden = false;
        dom.aiOutput.innerHTML = event.html;
      }

      dom.aiStreamText = null;
      dom.aiCaret = null;

      if (dom.aiCopy) {
        dom.aiCopy.disabled = !aiCanonicalMarkdown;
      }

      renderAiSources(aiStreamSources);

      if (dom.aiStatus) {
        dom.aiStatus.textContent = "Synthesis complete.";
      }

      return "done";
    }

    throw new Error("AI stream returned an unknown event type.");
  }

  async function consumeAiNdjsonStream(response, runSerial, searchSerial, controller) {
    if (!response.body || typeof response.body.getReader !== "function") {
      throw new Error("Streaming responses are not supported in this browser.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let completed = false;

    const processLine = (line) => {
      const trimmed = line.trim();
      if (!trimmed) return "continue";

      let event;
      try {
        event = JSON.parse(trimmed);
      } catch {
        throw new Error("AI stream returned malformed JSON.");
      }

      return processAiStreamEvent(event, runSerial, searchSerial, controller);
    };

    while (true) {
      if (!aiRunIsCurrent(runSerial, searchSerial, controller)) {
        try {
          await reader.cancel();
        } catch {
          // Cancellation is best-effort.
        }
        return false;
      }

      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const result = processLine(line);

        if (result === "stale") {
          try {
            await reader.cancel();
          } catch {
            // Cancellation is best-effort.
          }
          return false;
        }

        if (result === "done") {
          completed = true;
        }
      }

      if (done) break;
    }

    if (buffer.trim()) {
      const result = processLine(buffer);
      if (result === "done") completed = true;
      if (result === "stale") return false;
    }

    if (!completed) {
      throw new Error("AI synthesis stream ended before completion.");
    }

    return true;
  }

  async function startAiSynthesis() {
    if (
      aiActive
      || aiConfigFailed
      || !aiPublicConfig
      || aiInitialGateRemainingMs() > 0
      || aiCooldownRemainingMs() > 0
      || !completedSearchSnapshot?.resultRefIds?.length
    ) {
      updateAiButtonState();
      return;
    }

    const snapshot = completedSearchSnapshot;
    const expectedRefIds = snapshot.resultRefIds.slice(0, aiPublicConfig.sourceCount);

    if (!expectedRefIds.length) return;

    const runSerial = ++aiRunSerial;
    const searchSerial = snapshot.searchSerial;
    const controller = new AbortController();
    const qualityRating = aiQualityRating();

    aiController = controller;
    aiActive = true;
    aiCanonicalMarkdown = "";
    aiStreamSources = [];

    if (dom.aiPanel) {
      dom.aiPanel.hidden = false;
      dom.aiPanel.classList.remove("is-error");
    }

    if (dom.aiStatus) {
      dom.aiStatus.textContent = `Synthesizing the top ${expectedRefIds.length} ranked result${expectedRefIds.length === 1 ? "" : "s"}…`;
    }

    if (dom.aiSources) {
      dom.aiSources.hidden = true;
      dom.aiSources.replaceChildren();
    }

    if (dom.aiCopy) {
      dom.aiCopy.disabled = true;
    }

    prepareAiStreamDom();
    dom.aiOutput.hidden = false;
    dom.aiCaret.hidden = false;
    updateAiButtonState();

    try {
      const response = await fetch(AI_SYNTHESIS_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/x-ndjson"
        },
        credentials: "same-origin",
        signal: controller.signal,
								body: JSON.stringify({
										search: snapshot.request,
										expected_ref_ids: expectedRefIds,
										quality_rating: qualityRating
								})
      });

      applyServerCooldownFromResponse(response);

      if (!response.ok) {
        throw new Error(await aiHttpErrorMessage(response));
      }

      const completed = await consumeAiNdjsonStream(
        response,
        runSerial,
        searchSerial,
        controller
      );

      if (!completed || !aiRunIsCurrent(runSerial, searchSerial, controller)) {
        return;
      }
    } catch (error) {
      if (error?.name === "AbortError") return;
      if (!aiRunIsCurrent(runSerial, searchSerial, controller)) return;
      setAiFailure(error?.message || "AI synthesis could not be completed.");
    } finally {
      if (controller === aiController) {
        aiController = null;
        aiActive = false;
        updateAiButtonState();
      }
    }
  }

  async function copyAiSynthesis() {
    const text = aiCanonicalMarkdown;
    if (!text || !dom.aiCopy) return;

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.append(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();

        if (!copied) {
          throw new Error("Copy command failed.");
        }
      }

      const copiedRunSerial = aiRunSerial;
      const copiedSearchSerial = aiSearchSerial;

      dom.aiCopy.title = "Copied";
      if (dom.aiStatus) dom.aiStatus.textContent = "Synthesis copied to clipboard.";

      window.setTimeout(() => {
        if (!dom.aiCopy) return;
        dom.aiCopy.title = "Copy synthesis";

        if (
          copiedRunSerial === aiRunSerial
          && copiedSearchSerial === aiSearchSerial
          && !aiActive
          && dom.aiStatus
          && aiCanonicalMarkdown
        ) {
          dom.aiStatus.textContent = "Synthesis complete.";
        }
      }, 1400);
    } catch {
      if (dom.aiStatus) {
        dom.aiStatus.textContent = "The synthesis could not be copied automatically.";
      }
    }
  }

		function toggleAiQualityRating() {
				if (!dom.aiLogToggle || dom.aiLogToggle.disabled) return;

				aiQualityRatingTouched = true;

				setAiQualityRating(
						aiQualityRating() === "plus"
								? "minus"
								: "plus"
				);
		}

  function parseWeight(value, fallback) {
    const number = Number(value);

    if (!Number.isFinite(number)) {
      return fallback;
    }

    return Math.min(20, Math.max(0, number));
  }

  function weightsAreDefault(weights) {
    return Object.keys(DEFAULT_WEIGHTS).every(
      (key) => Math.abs(weights[key] - DEFAULT_WEIGHTS[key]) < 0.000001
    );
  }

  function readUrlState() {
    const params = new URLSearchParams(window.location.search);
    const urlTypes = params.getAll("type").filter((value) => ALL_RECORD_TYPES.includes(value));

    return {
      query: (params.get("query") || params.get("q") || "").trim(),
      recordTypes: urlTypes.length ? urlTypes : [...ALL_RECORD_TYPES],
      publisher: params.get("publisher") || "",
      term: params.get("term") || "",
      inspiringOnly: ["1", "true", "yes"].includes(
        String(params.get("inspiring") || "").toLowerCase()
      ),
      weights: {
        title: parseWeight(params.get("w_title"), DEFAULT_WEIGHTS.title),
        text: parseWeight(params.get("w_text"), DEFAULT_WEIGHTS.text),
        publisher: parseWeight(params.get("w_publisher"), DEFAULT_WEIGHTS.publisher),
        topics: parseWeight(params.get("w_topics"), DEFAULT_WEIGHTS.topics)
      }
    };
  }

  function selectedRecordTypes() {
    return dom.contentTypes
      .filter((input) => input.checked)
      .map((input) => input.value);
  }

  function inspiringOnlyEnabled() {
    return dom.inspiringOnly?.getAttribute("aria-pressed") === "true";
  }

    function setInspiringOnly(enabled) {
        if (!dom.inspiringOnly) return;

        const active = Boolean(enabled);

        dom.inspiringOnly.setAttribute(
            "aria-pressed",
            String(active)
        );

        dom.inspiringOnly.setAttribute(
            "aria-label",
            `Inspiring only: ${active ? "on" : "off"}`
        );

        dom.inspiringOnly.classList.toggle(
            "is-active",
            active
        );

        const state = $(
            "[data-inspiring-state]",
            dom.inspiringOnly
        );

        if (state) {
            state.textContent = active
                ? "On"
                : "Off";
        }
    }

  function syncDefaultWeightLabels() {
    for (const key of Object.keys(DEFAULT_WEIGHTS)) {
      const label = $(`[data-default-weight-label="${key}"]`);
      if (label) {
        label.textContent = `Default ${DEFAULT_WEIGHTS[key]}`;
      }
    }
  }

  function stateFromControls() {
    return {
      query: dom.query.value.trim(),
      recordTypes: selectedRecordTypes(),
      publisher: dom.publisher.value.trim(),
      term: dom.term.value.trim(),
      inspiringOnly: inspiringOnlyEnabled(),
      weights: getAppliedWeights()
    };
  }

  function applyStateToControls(state) {
    dom.query.value = state.query || "";

    const activeTypes = new Set(
      state.recordTypes?.length ? state.recordTypes : ALL_RECORD_TYPES
    );

    dom.contentTypes.forEach((input) => {
      input.checked = activeTypes.has(input.value);
    });

    dom.publisher.value = state.publisher || "";
    dom.term.value = state.term || "";
    setInspiringOnly(state.inspiringOnly);

    setWeightControls(state.weights || DEFAULT_WEIGHTS);
    updateRankingStatus(state.weights || DEFAULT_WEIGHTS);
  }

  function writeUrlState(state, { replace = false } = {}) {
    const url = new URL(window.location.href);
    const params = url.searchParams;

    [
      "query",
      "q",
      "family",
      "type",
      "publisher",
      "term",
      "inspiring",
      "w_title",
      "w_text",
      "w_publisher",
      "w_topics"
    ].forEach((key) => params.delete(key));

    if (state.query) params.set("query", state.query);

    const selectedTypes = state.recordTypes || [...ALL_RECORD_TYPES];
    if (selectedTypes.length && selectedTypes.length < ALL_RECORD_TYPES.length) {
      selectedTypes.forEach((value) => params.append("type", value));
    }

    if (state.publisher) params.set("publisher", state.publisher);
    if (state.term) params.set("term", state.term);
    if (state.inspiringOnly) params.set("inspiring", "1");

    if (!weightsAreDefault(state.weights)) {
      params.set("w_title", String(state.weights.title));
      params.set("w_text", String(state.weights.text));
      params.set("w_publisher", String(state.weights.publisher));
      params.set("w_topics", String(state.weights.topics));
    }

    const method = replace ? "replaceState" : "pushState";
    window.history[method]({}, "", url);
  }

  function requestFromState(state, offset = 0) {
    const selectedTypes = state.recordTypes || [...ALL_RECORD_TYPES];

    return {
      q: state.query,
      filters: {
        families: [],
        record_types: selectedTypes.length === ALL_RECORD_TYPES.length
          ? []
          : selectedTypes,
        publishers: state.publisher ? [state.publisher] : [],
        terms: state.term ? [state.term] : [],
        inspiring_only: Boolean(state.inspiringOnly)
      },
      weights: { ...state.weights },
      limit: PAGE_SIZE,
      offset
    };
  }

  function setWeightControls(weights) {
    for (const key of Object.keys(DEFAULT_WEIGHTS)) {
      const range = $(`#weight-${key}-range`);
      const number = $(`#weight-${key}-number`);
      const value = parseWeight(weights[key], DEFAULT_WEIGHTS[key]);

      if (range) range.value = String(value);
      if (number) number.value = String(value);
    }
  }

  function getWeightControls() {
    const weights = {};

    for (const key of Object.keys(DEFAULT_WEIGHTS)) {
      const number = $(`#weight-${key}-number`);
      weights[key] = parseWeight(number?.value, DEFAULT_WEIGHTS[key]);
    }

    return weights;
  }

  function getAppliedWeights() {
    const urlState = readUrlState();

    if (lastRequest?.weights) {
      return { ...lastRequest.weights };
    }

    return { ...urlState.weights };
  }

  function updateRankingStatus(weights) {
    const custom = !weightsAreDefault(weights);

    dom.rankingStatus.textContent = custom
      ? "Custom ranking"
      : "Default ranking";

    dom.toolsOpen.classList.toggle("is-custom", custom);
  }

  function setInitialState() {
    dom.results.replaceChildren();
    dom.loadMoreWrap.hidden = true;
    dom.status.textContent = "Enter a search above to begin.";
    dom.detail.textContent = "";
    currentResultCount = 0;
  }

  function setLoading({ append = false } = {}) {
    dom.status.textContent = append
      ? "Loading more results…"
      : "Searching…";

    dom.detail.textContent = "";
    dom.loadMoreWrap.hidden = true;

    if (!append) {
      dom.results.innerHTML = Array.from({ length: 3 }, () => `
        <div class="search-skeleton" aria-hidden="true">
          <span></span><span></span><span></span><span></span>
        </div>
      `).join("");
    }
  }

  function setError(message) {
    dom.results.innerHTML = `
      <div class="search-state search-state--error" role="status">
        <strong>Search is temporarily unavailable.</strong>
        <span>${escapeHtml(message)}</span>
      </div>
    `;

    dom.status.textContent = "Search error";
    dom.detail.textContent = "";
    dom.loadMoreWrap.hidden = true;
    currentResultCount = 0;
  }

  function setEmpty(query) {
    dom.results.innerHTML = `
      <div class="search-state" role="status">
        <strong>No results found.</strong>
        <span>
          Try fewer terms, a different spelling, or clear one of the exact filters.
        </span>
      </div>
    `;

    dom.status.textContent = `No results for “${query}”`;
    dom.detail.textContent = "";
    dom.loadMoreWrap.hidden = true;
    currentResultCount = 0;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat("en-US").format(Number(value) || 0);
  }

  function formatDate(value) {
    if (!value) return "";

    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
      return String(value);
    }

    return new Intl.DateTimeFormat("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric"
    }).format(date);
  }

  function displayUrl(value) {
    const href = String(value || "").trim();

    if (!href) return "";
    if (href.startsWith("/")) return href;

    return href.replace(/^https?:\/\//i, "").replace(/\/$/, "");
  }

  function tagNewsHref(tag) {
    const slug = String(tag || "")
      .trim()
      .replace(/^\/+|\/+$/g, "");

    return `/news/category/${encodeURIComponent(slug)}`;
  }


  function snippetHtml(value) {
    return escapeHtml(value || "")
      .replaceAll("\uE000", "<mark>")
      .replaceAll("\uE001", "</mark>");
  }

  function resultMetaHtml(result) {
    const items = [];

    if (result.publisher) {
      const sourceHref = safeHref(result.source_url);

      if (result.record_type === "news" && sourceHref !== "#") {
        items.push(`
          <span>
            <a
              class="search-result__publisher-link"
              href="${escapeHtml(sourceHref)}"
              target="_blank"
              rel="noopener noreferrer">
              ${escapeHtml(result.publisher)}
            </a>
          </span>
        `);
      } else {
        items.push(`<span>${escapeHtml(result.publisher)}</span>`);
      }
    }

    if (result.published_at) {
      items.push(`<span>${escapeHtml(formatDate(result.published_at))}</span>`);
    }

    const visibleText = items
      .map((item) => item.replace(/<[^>]+>/g, "").trim().toLowerCase());

    if (
      result.topic
      && !visibleText.includes(String(result.topic).toLowerCase())
    ) {
      items.push(`<span>${escapeHtml(result.topic)}</span>`);
    }

    if (
      result.section
      && !["news", "videos"].includes(result.section.toLowerCase())
      && !visibleText.includes(result.section.toLowerCase())
    ) {
      items.push(`<span>${escapeHtml(result.section)}</span>`);
    }

    items.push(`<span>Ref ${escapeHtml(result.ref_id)}</span>`);
    return items.join("");
  }


  function parseTimeSeconds(value) {
    const text = String(value || "").trim().toLowerCase();

    if (!text) return 0;

    if (/^\d+(?:\.\d+)?$/.test(text)) {
      return Math.max(0, Math.floor(Number(text)));
    }

    const match = text.match(
      /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/
    );

    if (!match) return 0;

    return (
      Number(match[1] || 0) * 3600
      + Number(match[2] || 0) * 60
      + Number(match[3] || 0)
    );
  }


  function parseYouTubeHref(value) {
    const href = String(value || "").trim();

    if (!href) return null;

    try {
      const url = new URL(href, window.location.origin);
      const host = url.hostname.replace(/^www\./, "").toLowerCase();
      let videoId = "";

      if (host === "youtu.be") {
        videoId = url.pathname.split("/").filter(Boolean)[0] || "";
      } else if (
        host === "youtube.com"
        || host === "m.youtube.com"
        || host === "youtube-nocookie.com"
      ) {
        if (url.pathname === "/watch") {
          videoId = url.searchParams.get("v") || "";
        } else {
          const parts = url.pathname.split("/").filter(Boolean);
          if (["embed", "shorts", "live"].includes(parts[0])) {
            videoId = parts[1] || "";
          }
        }
      }

      if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) {
        return null;
      }

      const start = parseTimeSeconds(
        url.searchParams.get("t")
        || url.searchParams.get("start")
        || url.hash.replace(/^#t=/, "")
      );

      return { videoId, start };
    } catch {
      return null;
    }
  }


  function youtubeResultData(result) {
    if (result?.record_type !== "youtube_chunk") {
      return null;
    }

    const parsed = parseYouTubeHref(result.url);
    const candidateId = String(result.video_id || parsed?.videoId || "").trim();

    if (!/^[A-Za-z0-9_-]{11}$/.test(candidateId)) {
      return null;
    }

    const apiStart = Number(result.timestamp_seconds);
    const start = Number.isFinite(apiStart)
      ? Math.max(0, Math.floor(apiStart))
      : (parsed?.start || 0);

    return {
      videoId: candidateId,
      start,
      title: String(result.title || "PEERS Conscious Media video")
    };
  }


  function youtubeLinkAttributes(result) {
    const video = youtubeResultData(result);

    if (!video) return "";

    return [
      'data-youtube-modal-link="true"',
      `data-video-id="${escapeHtml(video.videoId)}"`,
      `data-video-start="${escapeHtml(video.start)}"`,
      `data-video-title="${escapeHtml(video.title)}"`
    ].join(" ");
  }


  function detailHtmlFromPayload(payload) {
    if (!payload || typeof payload !== "object") {
      return "";
    }

    const displayHtml = String(
      payload.display_html || ""
    ).trim();

    if (displayHtml) {
      return displayHtml;
    }

    /*
     * Legacy/plain-text fallback only. The standard bundle stores Markdown in
     * SQLite and renders it server-side before it reaches this function.
     */
    const text = String(payload.text || "").trim();

    if (!text) {
      return "";
    }

    return `<p>${escapeHtml(text)}</p>`;
  }

  function resultHtml(result) {
    const href = resultHref(result);
    const typeLabel = TYPE_LABELS[result.record_type] || result.record_type;
    const meta = resultMetaHtml(result);
    const youtubeAttrs = youtubeLinkAttributes(result);

    const title = result.title || "Untitled result";
    const refId = Number(result.ref_id);

    const tagHtml = (
      result.record_type === "news"
      && Array.isArray(result.tags)
      && result.tags.length
    )
      ? `
          <div
            class="search-result__tags"
            aria-label="Categories">
            ${result.tags.map((tag) => `
              <a
                class="news-feed-tag search-result__tag"
                href="${escapeHtml(tagNewsHref(tag))}">
                ${escapeHtml(tag)}
              </a>
            `).join("")}
          </div>
        `
      : '<span class="search-result__footer-spacer" aria-hidden="true"></span>';

    return `
      <article class="search-result" data-ref-id="${refId}">
        <div class="search-result__topline">
          <div class="search-result__topline-main">
            <span class="search-result__type">${escapeHtml(typeLabel)}</span>
            <p class="search-result__meta">${meta}</p>
          </div>

          <button
            class="search-result__related-link"
            type="button"
            data-related-modal-link
            aria-haspopup="dialog"
            aria-controls="search-related-modal">
            Related articles
          </button>
        </div>

        <h2 class="search-result__title">
          <a
            href="${escapeHtml(href)}"
            ${youtubeAttrs}>${escapeHtml(title)}</a>
        </h2>

        ${result.snippet ? `
          <p class="search-result__snippet">${snippetHtml(result.snippet)}</p>
        ` : ""}

        <div class="search-result__footer">
          ${tagHtml}

          <button
            class="search-result__toggle"
            type="button"
            aria-expanded="false"
            aria-controls="search-result-detail-${refId}">
            Read full
          </button>
        </div>

        <div
          class="search-result__detail"
          id="search-result-detail-${refId}"
          data-result-detail
          hidden>
        </div>
      </article>
    `;
  }


  async function loadResultDetail(article) {
    const refId = Number(article.dataset.refId);
    const detail = $("[data-result-detail]", article);

    if (!detail || !Number.isFinite(refId)) return;

    if (detailCache.has(refId)) {
      detail.innerHTML = `
        <div class="search-result__detail-markdown">
          ${detailCache.get(refId)}
        </div>
      `;
      detail.dataset.loaded = "true";
      return;
    }

    detail.innerHTML = `
      <p class="search-result__detail-state">Loading full entry…</p>
    `;

    try {
      const response = await fetch(DETAIL_URL(refId), {
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
      });

      let payload = null;

      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      if (!response.ok) {
        const message = typeof payload?.detail === "string"
          ? payload.detail
          : `Entry request failed (${response.status}).`;

        throw new Error(message);
      }

      const renderedHtml = detailHtmlFromPayload(payload);

      detailCache.set(refId, renderedHtml);
      detail.dataset.loaded = "true";

      detail.innerHTML = renderedHtml
        ? `
            <div class="search-result__detail-markdown">
              ${renderedHtml}
            </div>
          `
        : `
            <p class="search-result__detail-state">
              No additional text is available for this entry.
            </p>
          `;
    } catch (error) {
      detail.innerHTML = `
        <p class="search-result__detail-state">
          ${escapeHtml(
            error?.message
            || "The full entry could not be loaded."
          )}
        </p>
      `;
    }
  }


  function setResultExpanded(article, expanded) {
    const detail = $("[data-result-detail]", article);
    const toggle = $(".search-result__toggle", article);

    if (!detail || !toggle) return;

    article.classList.toggle("is-expanded", expanded);
    detail.hidden = !expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
    toggle.textContent = expanded ? "Collapse" : "Read full";

    if (expanded && !detail.dataset.loaded && !detail.dataset.loading) {
      detail.dataset.loading = "true";
      loadResultDetail(article).finally(() => {
        delete detail.dataset.loading;
      });
    }
  }

  function toggleResult(article) {
    const toggle = $(".search-result__toggle", article);
    const expanded = toggle?.getAttribute("aria-expanded") === "true";
    setResultExpanded(article, !expanded);
  }

  function renderResults(payload, { append = false } = {}) {
    const html = payload.results.map(resultHtml).join("");

    if (append) {
      dom.results.insertAdjacentHTML("beforeend", html);
    } else {
      dom.results.innerHTML = html;
    }

    currentResultCount = append
      ? currentResultCount + payload.results.length
      : payload.results.length;

    dom.status.textContent = `${formatNumber(payload.total)} results for “${payload.query}”`;
    dom.detail.textContent = payload.total
      ? `Showing ${formatNumber(currentResultCount)} of ${formatNumber(payload.total)} results`
      : "";

    dom.loadMoreWrap.hidden = !payload.has_more;
    dom.loadMore.disabled = false;

    if (!append && dom.resultsHeading) {
      dom.resultsHeading.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }
  }

  async function runSearch({
    append = false,
    history = "push"
  } = {}) {
    const state = stateFromControls();

    if (!state.query) {
      if (!append) invalidateAiForSearchChange();
      lastRequest = null;
      writeUrlState(state, { replace: history !== "push" });
      setInitialState();
      return;
    }

    if (!append) {
      invalidateAiForSearchChange();
    }

    const offset = append ? currentResultCount : 0;
    const request = requestFromState(state, offset);

    if (!append) {
      writeUrlState(state, { replace: history === "replace" });
    }

    if (activeController) {
      activeController.abort();
    }

    activeController = new AbortController();
    const controller = activeController;

    setLoading({ append });

    try {
      const response = await fetch(SEARCH_URL, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json"
        },
        credentials: "same-origin",
        signal: controller.signal,
        body: JSON.stringify(request)
      });

      let payload = null;

      try {
        payload = await response.json();
      } catch {
        payload = null;
      }

      if (!response.ok) {
        const detail = payload?.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : `Search request failed (${response.status}).`
        );
      }

      if (controller !== activeController) return;

      lastRequest = request;
      updateRankingStatus(request.weights);

      if (!append && payload.total === 0) {
        setEmpty(payload.query);
        completedSearchSnapshot = null;
        hideAiPanel();
        updateAiButtonState();
      } else {
        renderResults(payload, { append });

        if (!append) {
          captureCompletedSearchSnapshot(request, payload);
        }
      }

      document.title = `Search: ${payload.query} | WantToKnow.info`;
    } catch (error) {
      if (error?.name === "AbortError") return;
      setError(error?.message || "The search service did not respond.");
    } finally {
      if (controller === activeController) {
        activeController = null;
      }
    }
  }

  async function loadOptions() {
    try {
      const response = await fetch(OPTIONS_URL, {
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
      });

      if (!response.ok) return;

      const payload = await response.json();

      if (payload.corpus?.active_refs != null) {
        dom.corpusSummary.textContent =
          `${formatNumber(payload.corpus.active_refs)} searchable references across news, `
          + "WTK pages, PEERS Substack, and PEERS Conscious Media transcripts.";
      }

      populateSelect(
        dom.publisher,
        payload.publishers || [],
        "All publishers"
      );
      populateSelect(
        dom.term,
        payload.terms || [],
        "All topics/categories"
      );
    } catch {
      // Filter suggestions are an enhancement; exact typed filters still work.
    }
  }

  function populateSelect(root, items, emptyLabel) {
    if (!root) return;

    const selectedValue = root.value;
    const fragment = document.createDocumentFragment();

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = emptyLabel;
    fragment.appendChild(empty);

    for (const item of items) {
      const value = String(item?.value || "").trim();
      if (!value) continue;

      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      option.title = `${formatNumber(item.count)} searchable references`;
      fragment.appendChild(option);
    }

    root.replaceChildren(fragment);

    if ([...root.options].some((option) => option.value === selectedValue)) {
      root.value = selectedValue;
    }
  }

  function openTools() {
    modalReturnFocus = document.activeElement;
    setWeightControls(getAppliedWeights());

    dom.toolsModal.hidden = false;
    dom.toolsModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    requestAnimationFrame(() => {
      $("#weight-title-range")?.focus();
    });
  }

  function closeTools({ restoreFocus = true } = {}) {
    dom.toolsModal.hidden = true;
    dom.toolsModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");

    if (restoreFocus && modalReturnFocus instanceof HTMLElement) {
      modalReturnFocus.focus();
    }
  }

  function applyTools() {
    const weights = getWeightControls();
    const state = stateFromControls();
    state.weights = weights;

    lastRequest = lastRequest
      ? { ...lastRequest, weights: { ...weights } }
      : { weights: { ...weights } };

    updateRankingStatus(weights);
    closeTools();

    const urlState = {
      ...stateFromControls(),
      weights
    };

    writeUrlState(urlState, { replace: false });

    if (urlState.query) {
      // runSearch reads applied weights from lastRequest and replaces the just-written URL.
      runSearch({ history: "replace" });
    }
  }

  function trapModalFocus(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeTools();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = $$([
      "button:not([disabled])",
      "input:not([disabled])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      'a[href]',
      '[tabindex]:not([tabindex="-1"])'
    ].join(","), dom.toolsModal).filter(
      (element) => element.getClientRects().length
    );

    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function wireWeightControls() {
    for (const key of Object.keys(DEFAULT_WEIGHTS)) {
      const range = $(`#weight-${key}-range`);
      const number = $(`#weight-${key}-number`);

      range?.addEventListener("input", () => {
        if (number) number.value = range.value;
      });

      number?.addEventListener("input", () => {
        const value = parseWeight(number.value, DEFAULT_WEIGHTS[key]);
        if (range) range.value = String(value);
      });

      number?.addEventListener("change", () => {
        const value = parseWeight(number.value, DEFAULT_WEIGHTS[key]);
        number.value = String(value);
        if (range) range.value = String(value);
      });
    }
  }

  function wireGlobalHeaderSearch() {
    $$('[data-global-header] .header-search').forEach((form) => {
      if (form.dataset.portalSearchWired === "true") return;
      form.dataset.portalSearchWired = "true";

      form.addEventListener("submit", (event) => {
        const input = $('input[type="search"]', form);
        const value = input?.value.trim() || "";

        if (!value) return;

        event.preventDefault();
        dom.query.value = value;
        dom.query.focus();
        runSearch({ history: "push" });
        dom.query.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    });
  }

  function openVideoModal(link) {
    if (!dom.videoModal || !dom.videoFrame || !dom.videoTitle) return;

    const videoId = String(link?.dataset.videoId || "").trim();

    if (!/^[A-Za-z0-9_-]{11}$/.test(videoId)) {
      return;
    }

    const start = Math.max(
      0,
      Math.floor(Number(link.dataset.videoStart) || 0)
    );

    const title = String(
      link.dataset.videoTitle
      || "PEERS Conscious Media video"
    );

    modalReturnFocus = document.activeElement;
    dom.videoTitle.textContent = title;

    const params = new URLSearchParams({
      autoplay: "1",
      rel: "0",
      start: String(start)
    });

    dom.videoFrame.src = (
      `https://www.youtube-nocookie.com/embed/${videoId}?${params}`
    );

    dom.videoModal.hidden = false;
    dom.videoModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    requestAnimationFrame(() => {
      dom.videoClose?.focus();
    });
  }


  function closeVideoModal({ restoreFocus = true } = {}) {
    if (!dom.videoModal || !dom.videoFrame) return;

    dom.videoFrame.src = "about:blank";
    dom.videoModal.hidden = true;
    dom.videoModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");

    if (restoreFocus && modalReturnFocus instanceof HTMLElement) {
      modalReturnFocus.focus();
    }
  }


  function trapVideoModalFocus(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeVideoModal();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = $$(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      dom.videoModal
    ).filter((element) => element.getClientRects().length);

    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }


  async function loadRelatedData(refId) {
    if (relatedDataCache.has(refId)) {
      return relatedDataCache.get(refId);
    }

    const response = await fetch(RELATED_URL(refId), {
      headers: { "Accept": "application/json" },
      credentials: "same-origin"
    });

    let payload = null;

    try {
      payload = await response.json();
    } catch {
      payload = null;
    }

    if (!response.ok) {
      const detail = typeof payload?.detail === "string"
        ? payload.detail
        : `Related article request failed (${response.status}).`;

      throw new Error(detail);
    }

    if (!payload?.target || !Array.isArray(payload?.related)) {
      throw new Error("Related article response has an unexpected format.");
    }

    relatedDataCache.set(refId, payload);
    return payload;
  }


  function relatedLabel(value, maxLength = 28) {
    const text = String(value || "Untitled result")
      .replace(/\s+/g, " ")
      .trim();

    if (text.length <= maxLength) {
      return text;
    }

    return `${text.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
  }


  function relatedNodeHref(record) {
    return resultHref(record);
  }

    function relatedVisualizationMode() {
        const params = new URLSearchParams(
            window.location.search
        );

        return params.get("related_view") === "graph"
            ? "graph"
            : "tiles";
    }


    function relatedBrandPalette() {
        const styles = getComputedStyle(
            document.documentElement
        );

        const value = (name, fallback) => (
            styles.getPropertyValue(name).trim()
            || fallback
        );

        return [
            value(
                "--color-brand-lavender",
                "#d8c9ed"
            ),
            value(
                "--color-brand-tan-light",
                "#eee1cd"
            ),
            value(
                "--color-brand-yellow-light",
                "#f5e7a8"
            ),
            value(
                "--color-brand-lavender-soft",
                "#eee7f7"
            ),
            value(
                "--color-brand-tan",
                "#dec9ab"
            ),
            value(
                "--color-brand-orange-light",
                "#efd0aa"
            )
        ];
    }


    function drawRelatedTiles(payload) {
        if (!dom.relatedGraph) {
            return;
        }

        const d3 = window.d3;

        if (!d3) {
            throw new Error(
                "D3.js did not load. "
                + "Check /assets/vendor/d3/d3-7.9.0.min.js."
            );
        }

        const target = payload?.target;

        const related = Array.isArray(
            payload?.related
        )
            ? payload.related.slice(0, 24)
            : [];

        if (!target) {
            throw new Error(
                "The selected result could not be resolved."
            );
        }

        if (!related.length) {
            throw new Error(
                "No related records were available for this result."
            );
        }

        /*
          * Clear whatever visualization was previously present.
          */
        dom.relatedGraph.replaceChildren();

        dom.relatedGraph.dataset.targetRefId =
            String(target.ref_id);

        dom.relatedGraph.classList.add(
            "is-tile-view"
        );

        dom.relatedGraph.classList.remove(
            "is-graph-view"
        );


        /*
          * Measure the actual modal visualization area.
          */
        const bounds =
            dom.relatedGraph.getBoundingClientRect();

        const width = Math.max(
      1,
      Math.floor(bounds.width || dom.relatedGraph.clientWidth || 1)
    );

    const height = Math.max(
      1,
      Math.floor(bounds.height || dom.relatedGraph.clientHeight || 1)
    );

    if (width < 16 || height < 16) {
      throw new Error(
        "The related-content area has no usable layout size. "
        + "Check the related modal CSS height/grid rules."
      );
    }


        /*
          * Weight determines AREA, not width or height.
          *
          * Target is largest.
          * Related records then decrease monotonically.
          *
          * This is deliberately simple. Semantic similarity is
          * already represented by rank, so there is no need for
          * another pseudo-precision metric here.
          */
        const items = [
            {
                ...target,

                tileType: "target",
                rank: 0,

                /*
                  * Large enough to clearly dominate without consuming
                  * a quarter of the modal.
                  */
                tileWeight: 34
            },

            ...related.map(
                (record, index) => ({
                    ...record,

                    tileType: "related",
                    rank: index + 1,

                    /*
                      * Rank 1 = 25
                      * Rank 24 = 2
                      */
                    tileWeight: 25 - index
                })
            )
        ];


        /*
          * D3 treemap guarantees that the complete available
          * rectangle is allocated among the tiles.
          */
        const hierarchy = d3
            .hierarchy({
                children: items
            })
            .sum((item) => (
          Array.isArray(item?.children)
            ? 0
            : (Number(item?.tileWeight) || 1)
        ))
            .sort(
                (a, b) =>
                    (b.value || 0)
                    - (a.value || 0)
            );


        d3
            .treemap()
            .size([
                width,
                height
            ])
            .paddingOuter(0)
            .paddingInner(5)
            .round(true)(
                hierarchy
            );


        const palette =
            relatedBrandPalette();

        const fragment =
            document.createDocumentFragment();


        for (
            const leaf of hierarchy.leaves()
        ) {
            const record = leaf.data;

            const tileWidth = Math.max(
                1,
                leaf.x1 - leaf.x0
            );

            const tileHeight = Math.max(
                1,
                leaf.y1 - leaf.y0
            );

            const isTarget =
                record.tileType === "target";


            /*
              * Target is a real navigation link.
              * Related records are buttons that refocus the modal.
              */
            const tile = document.createElement(
                isTarget ? "a" : "button"
            );

            tile.className = [
                "search-related-tile",

                isTarget
                    ? "search-related-tile--target"
                    : "search-related-tile--child"
            ].join(" ");


            tile.style.left =
                `${leaf.x0}px`;

            tile.style.top =
                `${leaf.y0}px`;

            tile.style.width =
                `${tileWidth}px`;

            tile.style.height =
                `${tileHeight}px`;


            /*
              * Target gets the primary lavender treatment.
              * Children rotate through the rest of the brand palette.
              */
            tile.style.backgroundColor =
                isTarget
                    ? palette[0]
                    : palette[
                            (record.rank - 1)
                            % palette.length
                        ];


            if (isTarget) {
                tile.href =
                    relatedNodeHref(record);

                tile.setAttribute(
                    "aria-label",
                    `Open ${
                        record.title
                        || "selected result"
                    }`
                );
            } else {
                tile.type = "button";

                tile.setAttribute(
                    "aria-label",
                    `Focus related article ${
                        record.rank
                    }: ${
                        record.title
                        || "Untitled result"
                    }`
                );

                tile.addEventListener(
                    "click",
                    (event) => {
                        event.preventDefault();

                        focusRelatedGraph(
                            Number(record.ref_id),
                            {
                                focusTarget: true
                            }
                        );
                    }
                );
            }


            /*
              * Rank / target marker.
              */
            const kicker =
                document.createElement("span");

            kicker.className =
                "search-related-tile__kicker";

            kicker.textContent =
                isTarget
                    ? "Current"
                    : `Related ${record.rank}`;


            /*
              * Main title.
              */
            const title =
                document.createElement("span");

            title.className =
                "search-related-tile__title";

            title.textContent =
                record.title
                || "Untitled result";


            tile.append(
                kicker,
                title
            );


            /*
              * Publisher is useful on sufficiently large tiles.
              * CSS hides it when there isn't room.
              */
            if (record.publisher) {
                const meta =
                    document.createElement("span");

                meta.className =
                    "search-related-tile__meta";

                meta.textContent =
                    record.publisher;

                tile.append(meta);
            }


            fragment.append(tile);
        }


        dom.relatedGraph.append(fragment);
    }


  function renderRelatedVisualization(payload) {
    if (!dom.relatedGraph) return;

    const mode = relatedVisualizationMode();

    if (mode === "graph") {
      dom.relatedGraph.classList.remove("is-tile-view");
      dom.relatedGraph.classList.add("is-graph-view");

      /*
       * Developer-only legacy view.
       * Enable with ?related_view=graph.
       */
      drawRelatedGraph(payload);
      return;
    }

    /*
     * Public/default view.
     */
    drawRelatedTiles(payload);
  }


  function drawRelatedGraph(payload) {
    if (!dom.relatedGraph) return;

    const d3 = window.d3;

    if (!d3) {
      throw new Error(
        "D3.js did not load. Check /assets/vendor/d3/d3-7.9.0.min.js."
      );
    }

    const target = payload?.target;
    const related = Array.isArray(payload?.related)
      ? payload.related.slice(0, 24)
      : [];

    if (!target) {
      throw new Error("The selected result could not be resolved.");
    }

    if (!related.length) {
      throw new Error("No related records were available for this result.");
    }

    /*
     * Responsive golden-mean canvas:
     * desktop = phi : 1
     * mobile  = 1 : phi
     *
     * The spiral exists only in node placement. Relationship edges are
     * independent spokes from the center target to each related record.
     */
    const measuredWidth = dom.relatedGraph.getBoundingClientRect().width;
    const isMobile = measuredWidth > 0 && measuredWidth < 640;

    const width = isMobile ? 742 : 1200;
    const height = isMobile ? 1200 : 742;
    const centerX = width / 2;
    const centerY = height / 2;

    const phi = (1 + Math.sqrt(5)) / 2;
    const spiralB = Math.log(phi) / Math.PI;
    const startAngle = -Math.PI / 2;

    /* Extra clearance for the larger center target. */
        const rMin = isMobile ? 205 : 195;
        const rMax = isMobile ? 505 : 500;

        /*
          * Landscape desktop, portrait mobile.
          */
        const xScale = isMobile ? 0.50 : 1.30;
        const yScale = isMobile ? 1.30 : 0.50;

    /*
     * Resolve the actual brand colors before interpolation. D3 cannot
     * interpolate raw var(--...) strings, but it can interpolate the
     * computed CSS color values.
     */
    const rootStyle = getComputedStyle(document.documentElement);
    const innerColor = rootStyle
      .getPropertyValue("--color-brand-lavender")
      .trim() || "#d7c9ed";
    const outerColor = rootStyle
      .getPropertyValue("--color-brand-tan-light")
      .trim() || "#eee1cd";

    const fillForProgress = d3.interpolateLab(innerColor, outerColor);

    const childNodes = related.map((record, index) => {
      const count = Math.max(1, related.length);
      const t = count === 1 ? 0 : index / (count - 1);

      /*
       * Strongest relationships remain larger and nearer the target.
       * The same golden-ratio spiral geometry is retained from v6.3.
       */
      const radialProgress = Math.pow(t, 0.72);
      const radius = rMin + (rMax - rMin) * radialProgress;
      const angle = startAngle + Math.log(radius / rMin) / spiralB;

      const widthPx = 158 - 66 * t;
      const heightPx = 66 - 27 * t;
      const fontPx = 12.2 - 3.2 * t;

      const charsPerLine = Math.max(
        8,
        Math.floor((widthPx - 18) / (fontPx * 0.56))
      );
      const lineCount = Math.max(
        2,
        Math.floor((heightPx - 12) / (fontPx * 1.16))
      );

      const fillColor = fillForProgress(t);
      const parsedColor = d3.color(fillColor);
      const edgeColor = parsedColor
        ? parsedColor.darker(0.55).formatHex()
        : fillColor;

      return {
        ...record,
        rank: index + 1,
        x: centerX + Math.cos(angle) * radius * xScale,
        y: centerY + Math.sin(angle) * radius * yScale,
        nodeWidth: widthPx,
        nodeHeight: heightPx,
        fontSize: fontPx,
        maxLabelChars: Math.max(14, charsPerLine * lineCount - 1),
        fillColor,
        edgeColor
      };
    });
        

    const targetPoint = {
      ...target,
      rank: 0,
      x: centerX,
      y: centerY
    };

    const edgeWidth = d3
      .scaleLinear()
      .domain([1, Math.max(24, childNodes.length)])
      .range([6.25, 0.9])
      .clamp(true);

    const edgeOpacity = d3
      .scaleLinear()
      .domain([1, Math.max(24, childNodes.length)])
      .range([0.64, 0.20])
      .clamp(true);

    /*
     * Every relationship is target -> child. No child-to-child edge is
     * drawn, so the graph cannot imply relationships between neighboring
     * spiral nodes.
     */
    const edges = childNodes.map((node) => ({
      source: targetPoint,
      target: node,
      rank: node.rank,
      edgeColor: node.edgeColor
    }));

        /*
          * Crop the SVG to the actual graph content rather than the original
          * 1200 × 742 / 742 × 1200 coordinate canvas.
          *
          * This preserves the golden-spiral geometry but removes unused space
          * around the outermost nodes.
          */
        const targetRadius = 72;
        const graphPadding = 18;

        let graphMinX = centerX - targetRadius;
        let graphMaxX = centerX + targetRadius;
        let graphMinY = centerY - targetRadius;
        let graphMaxY = centerY + targetRadius;

        childNodes.forEach((node) => {
            const halfWidth = node.nodeWidth / 2;
            const halfHeight = node.nodeHeight / 2;

            graphMinX = Math.min(
                graphMinX,
                node.x - halfWidth
            );

            graphMaxX = Math.max(
                graphMaxX,
                node.x + halfWidth
            );

            graphMinY = Math.min(
                graphMinY,
                node.y - halfHeight
            );

            graphMaxY = Math.max(
                graphMaxY,
                node.y + halfHeight
            );
        });

        graphMinX -= graphPadding;
        graphMinY -= graphPadding;
        graphMaxX += graphPadding;
        graphMaxY += graphPadding;

        const graphViewWidth =
            graphMaxX - graphMinX;

        const graphViewHeight =
            graphMaxY - graphMinY;

    dom.relatedGraph.replaceChildren();
    dom.relatedGraph.dataset.targetRefId = String(target.ref_id);

        const svg = d3
            .select(dom.relatedGraph)
            .append("svg")
            .attr("class", "search-related-graph")

            .attr("width", "100%")
            .attr("height", "100%")

            .attr(
                "viewBox",
                `${graphMinX} ${graphMinY} ${graphViewWidth} ${graphViewHeight}`
            )

            .attr(
                "preserveAspectRatio",
                "xMidYMid meet"
            )

            .attr("overflow", "hidden")
            .attr("role", "img")
            .attr(
                "aria-label",
                `Related articles for ${
                    target.title || "selected result"
                }`
            );

    svg
      .append("g")
      .attr("class", "search-related-graph__edges")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("class", "search-related-edge")
      .attr("x1", centerX)
      .attr("y1", centerY)
      .attr("x2", (edge) => edge.target.x)
      .attr("y2", (edge) => edge.target.y)
      .attr("stroke", (edge) => edge.edgeColor)
      .attr("stroke-width", (edge) => edgeWidth(edge.rank))
      .attr("stroke-opacity", (edge) => edgeOpacity(edge.rank));

    const nodeLayer = svg
      .append("g")
      .attr("class", "search-related-graph__nodes");

    /* ------------------------------------------------------------------
       Target: the ONLY node that navigates away.
       ------------------------------------------------------------------ */

    const targetLink = nodeLayer
      .append("a")
      .attr("class", "search-related-node search-related-node--target")
      .attr("href", relatedNodeHref(target))
      .attr("aria-label", `Open ${target.title || "selected result"}`)
      .attr("transform", `translate(${centerX},${centerY})`)
      .on("mouseenter.raise", function () {
        d3.select(this).raise();
      })
      .on("focus.raise", function () {
        d3.select(this).raise();
      });

    targetLink
      .append("title")
      .text(`Open: ${target.title || "Untitled result"}`);

    const targetBody = targetLink
      .append("g")
      .attr("class", "search-related-node__body");

    targetBody
      .append("circle")
      .attr("class", "search-related-node__target-circle")
      .attr("r", 72);

        const targetForeign = targetBody
            .append("foreignObject")
            .attr("x", -62)
            .attr("y", -56)
            .attr("width", 124)
            .attr("height", 112);

    const targetContent = targetForeign
      .append("xhtml:div")
      .attr("class", "search-related-node__target-content");

    targetContent
      .append("xhtml:span")
      .attr("class", "search-related-node__target-kicker")
      .text("Open");

    targetContent
      .append("xhtml:span")
      .attr("class", "search-related-node__target-title")
      .text(relatedLabel(target.title, 44));

    /* ------------------------------------------------------------------
       Related nodes: square-cornered buttons that refocus the graph.
       ------------------------------------------------------------------ */

    const childGroups = nodeLayer
      .selectAll("g.search-related-node--child")
      .data(childNodes)
      .join("g")
      .attr("class", "search-related-node search-related-node--child")
      .attr("role", "button")
      .attr("tabindex", 0)
      .attr("focusable", "true")
      .attr(
        "aria-label",
        (node) => (
          `Focus related article ${node.rank}: ${node.title || "Untitled result"}`
        )
      )
      .attr(
        "transform",
        (node) => `translate(${node.x},${node.y})`
      )
      .on("mouseenter.raise", function () {
        /* A hovered node must visually sit above every overlap. */
        d3.select(this).raise();
      })
      .on("focus.raise", function () {
        d3.select(this).raise();
      })
      .on("mouseleave.raise", () => {
        /* Return the target to the top of the normal stacking order. */
        targetLink.raise();
      })
      .on("blur.raise", () => {
        targetLink.raise();
      })
      .on("click", (event, node) => {
        event.preventDefault();
        event.stopPropagation();
        focusRelatedGraph(Number(node.ref_id), { focusTarget: true });
      })
      .on("keydown", (event, node) => {
        if (event.key !== "Enter" && event.key !== " ") return;

        event.preventDefault();
        event.stopPropagation();
        focusRelatedGraph(Number(node.ref_id), { focusTarget: true });
      });

    childGroups
      .append("title")
      .text((node) => {
        const publisher = node.publisher ? ` — ${node.publisher}` : "";
        return `Related ${node.rank}: ${node.title || "Untitled result"}${publisher}`;
      });

    const childBodies = childGroups
      .append("g")
      .attr("class", "search-related-node__body");

    childBodies
      .append("rect")
      .attr("class", "search-related-node__rect")
      .attr("x", (node) => -node.nodeWidth / 2)
      .attr("y", (node) => -node.nodeHeight / 2)
      .attr("width", (node) => node.nodeWidth)
      .attr("height", (node) => node.nodeHeight)
      .attr("rx", 0)
      .attr("ry", 0)
      .attr("fill", (node) => node.fillColor);

    const childForeign = childBodies
      .append("foreignObject")
      .attr("x", (node) => -node.nodeWidth / 2 + 8)
      .attr("y", (node) => -node.nodeHeight / 2 + 6)
      .attr("width", (node) => Math.max(1, node.nodeWidth - 16))
      .attr("height", (node) => Math.max(1, node.nodeHeight - 12));

    childForeign
      .append("xhtml:div")
      .attr("class", "search-related-node__label")
      .style("font-size", (node) => `${node.fontSize}px`)
      .text((node) => relatedLabel(node.title, node.maxLabelChars));

    childBodies
      .append("text")
      .attr("class", "search-related-node__rank")
      .attr("x", (node) => node.nodeWidth / 2 - 7)
      .attr("y", (node) => -node.nodeHeight / 2 + 11)
      .attr("text-anchor", "end")
      .text((node) => node.rank);

    /* Keep the target visible by default. Hover/focus may temporarily raise a child. */
    targetLink.raise();
  }


  async function focusRelatedGraph(refId, { focusTarget = false } = {}) {
    if (!dom.relatedGraph || !dom.relatedTitle) return;

    const numericRefId = Number(refId);

    if (!Number.isInteger(numericRefId) || numericRefId < 1) {
      return;
    }

    relatedRequestSerial += 1;
    const requestSerial = relatedRequestSerial;

    dom.relatedGraph.classList.add("is-loading");

    try {
      const payload = await loadRelatedData(numericRefId);

      if (requestSerial !== relatedRequestSerial) {
        return;
      }

      dom.relatedTitle.textContent = `Related to ${
        payload.target?.title || "selected result"
      }`;

      renderRelatedVisualization(payload);
      dom.relatedGraph.classList.remove("is-loading");

      if (focusTarget) {
        requestAnimationFrame(() => {
          $(".search-related-tile--target, .search-related-node--target", dom.relatedGraph)?.focus();
        });
      }
    } catch (error) {
      if (requestSerial !== relatedRequestSerial) {
        return;
      }

      dom.relatedGraph.classList.remove("is-loading");
      dom.relatedGraph.innerHTML = `
        <p class="search-related-modal__state search-related-modal__state--error">
          ${escapeHtml(
            error?.message
            || "Related articles could not be loaded."
          )}
        </p>
      `;
    }
  }


  async function openRelatedModal(link, article) {
    if (!dom.relatedModal || !dom.relatedGraph || !dom.relatedTitle) return;

    const refId = Number(article?.dataset.refId);

    if (!Number.isInteger(refId) || refId < 1) {
      return;
    }

    relatedModalReturnFocus = link || document.activeElement;

    const title = String(
      $(".search-result__title", article)?.textContent
      || "selected result"
    ).trim();

    dom.relatedTitle.textContent = `Related to ${title}`;
    dom.relatedGraph.innerHTML = `
      <p class="search-related-modal__state">
        Loading related articles…
      </p>
    `;

    dom.relatedModal.hidden = false;
    dom.relatedModal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");

    requestAnimationFrame(() => {
      dom.relatedClose?.focus();
    });

    await focusRelatedGraph(refId, { focusTarget: false });
  }


  function closeRelatedModal({ restoreFocus = true } = {}) {
    if (!dom.relatedModal) return;

    relatedRequestSerial += 1;
    dom.relatedModal.hidden = true;
    dom.relatedModal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");

    if (restoreFocus && relatedModalReturnFocus instanceof HTMLElement) {
      relatedModalReturnFocus.focus();
    }
  }


  function trapRelatedModalFocus(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeRelatedModal();
      return;
    }

    if (event.key !== "Tab") return;

    const focusable = $$(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      dom.relatedModal
    ).filter((element) => element.getClientRects().length);

    if (!focusable.length) return;

    const first = focusable[0];
    const last = focusable[focusable.length - 1];

    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }


  function cacheDom() {
    dom.form = $("#search-form");
    dom.query = $("#search-query");
    dom.contentTypes = $$('input[name="search-content-type"]');
    dom.publisher = $("#search-publisher");
    dom.term = $("#search-term");
    dom.inspiringOnly = $("#search-inspiring-only");
    dom.aiButton = $("#search-ai-summary");
    dom.aiPanel = $("#search-ai-panel");
    dom.aiStatus = $("#search-ai-status");
    dom.aiOutput = $("#search-ai-output");
    dom.aiStreamText = $("[data-ai-stream-text]", dom.aiOutput);
    dom.aiCaret = $("[data-ai-caret]", dom.aiOutput);
    dom.aiSources = $("#search-ai-sources");
    dom.aiCopy = $("#search-ai-copy");
    dom.aiLogToggle = $("#search-ai-log-toggle");
    dom.aiLogSymbol = $("[data-ai-log-symbol]", dom.aiLogToggle);
    dom.status = $("#search-status");
    dom.detail = $("#search-results-detail");
    dom.resultsHeading = $(".search-results-heading");
    dom.results = $("#search-results");
    dom.loadMoreWrap = $("#search-load-more-wrap");
    dom.loadMore = $("#search-load-more");
    dom.corpusSummary = $("[data-corpus-summary]");
    dom.rankingStatus = $("#search-ranking-status");
    dom.toolsOpen = $("#search-tools-open");
    dom.reset = $("#search-reset");
    dom.toolsModal = $("#search-tools-modal");
    dom.toolsReset = $("#search-tools-reset");
    dom.toolsApply = $("#search-tools-apply");
    dom.videoModal = $("#search-video-modal");
    dom.videoFrame = $("#search-video-frame");
    dom.videoTitle = $("#search-video-modal-title");
    dom.videoClose = $(".search-video-modal__close", dom.videoModal);
    dom.relatedModal = $("#search-related-modal");
    dom.relatedGraph = $("#search-related-graph");
    dom.relatedTitle = $("#search-related-modal-title");
    dom.relatedClose = $(".search-related-modal__close", dom.relatedModal);
				dom.aiModel = $("#search-ai-model");
  }

  function wireEvents() {
    dom.form.addEventListener("submit", (event) => {
      event.preventDefault();
      runSearch({ history: "push" });
    });

    dom.query.addEventListener("input", () => {
      if (completedSearchSnapshot || aiActive || !dom.aiPanel?.hidden) {
        invalidateAiForSearchChange();
      }
    });

    dom.aiButton?.addEventListener("click", startAiSynthesis);
    dom.aiCopy?.addEventListener("click", copyAiSynthesis);
    dom.aiLogToggle?.addEventListener("click", toggleAiQualityRating);

    dom.inspiringOnly?.addEventListener("click", () => {
      setInspiringOnly(!inspiringOnlyEnabled());
      runSearch({ history: "push" });
    });

    dom.contentTypes.forEach((input) => {
      input.addEventListener("change", () => {
        if (!selectedRecordTypes().length) {
          input.checked = true;
          return;
        }

        if (dom.query.value.trim()) runSearch({ history: "push" });
      });
    });

    [dom.publisher, dom.term].forEach((input) => {
      input.addEventListener("change", () => {
        if (dom.query.value.trim()) runSearch({ history: "push" });
      });

      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          if (dom.query.value.trim()) runSearch({ history: "push" });
        }
      });
    });


    dom.loadMore.addEventListener("click", () => {
      dom.loadMore.disabled = true;
      runSearch({ append: true, history: "replace" });
    });

    dom.results.addEventListener("click", (event) => {
      const interactive = event.target.closest("a, button");
      const article = event.target.closest(".search-result");

      if (!article) return;

      if (interactive?.matches("[data-related-modal-link]")) {
        event.preventDefault();
        openRelatedModal(interactive, article);
        return;
      }

      if (interactive?.matches("[data-youtube-modal-link]")) {
        event.preventDefault();
        openVideoModal(interactive);
        return;
      }

      if (interactive?.matches(".search-result__toggle")) {
        toggleResult(article);
        return;
      }

      if (interactive) return;
      if (event.target.closest("[data-result-detail]")) return;

      toggleResult(article);
    });

    dom.toolsOpen.addEventListener("click", openTools);
    dom.reset?.addEventListener("click", () => {
      window.location.assign("/search");
    });
    dom.toolsReset.addEventListener("click", () => setWeightControls(DEFAULT_WEIGHTS));
    dom.toolsApply.addEventListener("click", applyTools);

    $$('[data-search-tools-close]', dom.toolsModal).forEach((button) => {
      button.addEventListener("click", () => closeTools());
    });

    dom.toolsModal.addEventListener("keydown", trapModalFocus);

    $$('[data-search-video-close]', dom.videoModal).forEach((button) => {
      button.addEventListener("click", () => closeVideoModal());
    });

    dom.videoModal?.addEventListener("keydown", trapVideoModalFocus);

    $$('[data-search-related-close]', dom.relatedModal).forEach((button) => {
      button.addEventListener("click", () => closeRelatedModal());
    });

    dom.relatedModal?.addEventListener("keydown", trapRelatedModalFocus);

    window.addEventListener("popstate", () => {
      const state = readUrlState();
      invalidateAiForSearchChange();
      lastRequest = { weights: { ...state.weights } };
      applyStateToControls(state);

      if (state.query) {
        runSearch({ history: "replace" });
      } else {
        setInitialState();
      }
    });

    document.addEventListener("keydown", (event) => {
      if (
        event.key === "/"
        && !event.ctrlKey
        && !event.metaKey
        && !event.altKey
        && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)
      ) {
        event.preventDefault();
        dom.query.focus();
      }
    });

    document.addEventListener("wtk:global-ready", wireGlobalHeaderSearch);
    wireWeightControls();
  }

  async function init() {
    cacheDom();

    if (!dom.form || !dom.results || !dom.toolsModal) return;

    syncDefaultWeightLabels();
    wireEvents();
    initializeAiPageGate();
    loadAiConfig();
    await loadOptions();

    const state = readUrlState();
    lastRequest = { weights: { ...state.weights } };
    applyStateToControls(state);

    if (state.query) {
      runSearch({ history: "replace" });
    } else {
      setInitialState();
    }

    // Handles the uncommon case where global.js completed before this module.
    wireGlobalHeaderSearch();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
