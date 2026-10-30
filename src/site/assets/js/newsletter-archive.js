(() => {
  "use strict";

  const select = document.getElementById("newsletter-archive-select");
  const frame = document.getElementById("newsletter-archive-frame");
  const status = document.getElementById("newsletter-archive-status");

  if (!select || !frame) return;

  let records = [];
  let resizeObserver = null;

  function formatDate(value) {
    const parts = String(value || "").split("-").map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return value;

    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return new Intl.DateTimeFormat("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(date);
  }

  function selectedIssueFromUrl() {
    return new URL(window.location.href).searchParams.get("issue") || "";
  }

  function recordId(record) {
    return String(record?.newsletter_id || record?.issue_date || "").trim();
  }

  function recordForIdentifier(identifier) {
    const exact = records.find(record => recordId(record) === identifier);
    if (exact) return exact;

    const dateMatches = records.filter(
      record => String(record?.issue_date || "").trim() === identifier,
    );
    return dateMatches.length === 1 ? dateMatches[0] : null;
  }

  function sourceFor(record) {
    const newsletterId = recordId(record);

    if (record?.legacy_url) {
      const url = new URL(String(record.legacy_url), window.location.origin);
      if (!/^https?:$/.test(url.protocol)) throw new Error("Invalid legacy newsletter URL");
      return url.href;
    }

    return `/api/newsletters/${encodeURIComponent(newsletterId)}/html`;
  }

  function setStatus(message = "") {
    if (status) status.textContent = message;
  }

  function resizeFrame() {
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }

    try {
      const doc = frame.contentDocument;
      if (!doc) return;

      const resize = () => {
        const bodyHeight = doc.body?.scrollHeight || 0;
        const rootHeight = doc.documentElement?.scrollHeight || 0;
        const height = Math.max(bodyHeight, rootHeight, 640);
        frame.style.height = `${height}px`;
      };

      resize();
      window.setTimeout(resize, 100);
      window.setTimeout(resize, 600);

      if ("ResizeObserver" in window && doc.body) {
        resizeObserver = new ResizeObserver(resize);
        resizeObserver.observe(doc.body);
      }
    } catch {
      // Legacy newsletters may be cross-origin on staging. Let the iframe
      // retain its generous fallback height and its own scrolling in that case.
      frame.style.height = "80vh";
    }
  }

  function showIssue(newsletterId, {push = false} = {}) {
    const record = recordForIdentifier(newsletterId);
    if (!record) return;

    const selectedId = recordId(record);
    const issueDate = String(record.issue_date || "").trim();
    const title = String(record.title || "WantToKnow.info Newsletter").trim();

    select.value = selectedId;
    frame.style.height = "80vh";
    frame.src = sourceFor(record);
    frame.title = `${title} — ${formatDate(issueDate)}`;
    setStatus("");

    const url = new URL(window.location.href);
    url.searchParams.set("issue", selectedId);
    if (push) {
      window.history.pushState({issue: selectedId}, "", url);
    } else {
      window.history.replaceState({issue: selectedId}, "", url);
    }
  }

  async function initialize() {
    try {
      const response = await fetch("/data/newsletters.json", {cache: "no-cache"});
      if (!response.ok) throw new Error(`Unable to load newsletters (${response.status})`);

      const data = await response.json();
      records = Array.isArray(data?.newsletters)
        ? data.newsletters.filter(
            item => /^\d{4}-\d{2}-\d{2}$/.test(String(item?.issue_date || "")),
          )
        : [];

      records.sort(
        (a, b) =>
          String(b.issue_date || "").localeCompare(String(a.issue_date || "")) ||
          recordId(b).localeCompare(recordId(a)),
      );

      select.replaceChildren();
						for (const record of records) {
								const option =
										document.createElement("option");

								option.value =
										recordId(record);

								const headlines = Array.isArray(
										record.headlines
								)
										? record.headlines
														.map(value =>
																String(value || "").trim()
														)
														.filter(Boolean)
														.slice(0, 3)
										: [];

								option.textContent =
										headlines.length
												? headlines.join(", ")
												: String(
																record.title ||
																"WantToKnow.info Newsletter"
														).trim();

								select.append(option);
						}

      if (!records.length) {
        select.disabled = true;
        setStatus("No published newsletters yet.");
        return;
      }

      const requested = selectedIssueFromUrl();
      const initialRecord = requested ? recordForIdentifier(requested) : null;
      const initial = initialRecord ? recordId(initialRecord) : recordId(records[0]);

      showIssue(initial);
    } catch (error) {
      select.disabled = true;
      setStatus(error instanceof Error ? error.message : "Unable to load newsletter archive.");
    }
  }

  select.addEventListener("change", () => {
    showIssue(select.value, {push: true});
  });

  frame.addEventListener("load", resizeFrame);

  window.addEventListener("popstate", () => {
    const issue = selectedIssueFromUrl();
    if (issue && recordForIdentifier(issue)) {
      showIssue(issue);
    }
  });

  initialize();
})();
