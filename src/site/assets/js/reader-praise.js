(() => {
  "use strict";

  const TRIGGER_SELECTOR = "[data-reader-praise-open]";
  const DATA_URL = "/data/reader-praise.json";

  let dialog = null;
  let list = null;
  let status = null;
  let loaded = false;
  let returnFocus = null;

  function make(tag, className = "") {
    const el = document.createElement(tag);
    if (className) el.className = className;
    return el;
  }

  function buildDialog() {
    if (dialog) return dialog;

    dialog = make("dialog", "reader-praise-modal");
    dialog.setAttribute("aria-labelledby", "reader-praise-title");

    const shell = make("div", "reader-praise-modal__shell");
    const header = make("header", "reader-praise-modal__header");
    const headingWrap = make("div");

    const eyebrow = make("p", "eyebrow");
    eyebrow.textContent = "Feedback from the Community";

    const title = make("h2");
    title.id = "reader-praise-title";
    title.textContent = "What people are saying";

    const close = make("button", "reader-praise-modal__close");
    close.type = "button";
    close.setAttribute("aria-label", "Close reader praise");
    close.textContent = "×";

    status = make("p", "reader-praise-modal__status");
    status.setAttribute("aria-live", "polite");
    status.textContent = "Loading reader messages…";

    list = make("div", "reader-praise-list");

    headingWrap.append(eyebrow, title);
    header.append(headingWrap, close);
    shell.append(header, status, list);
    dialog.append(shell);
    document.body.append(dialog);

    close.addEventListener("click", () => dialog.close());

    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });

    dialog.addEventListener("close", () => {
      document.documentElement.classList.remove("has-reader-praise-modal");
      if (returnFocus instanceof HTMLElement) returnFocus.focus();
      returnFocus = null;
    });

    return dialog;
  }

  async function loadPraise() {
    if (loaded) return;

    const response = await fetch(DATA_URL, {
      headers: { "Accept": "application/json" }
    });

    if (!response.ok) {
      throw new Error(`Reader praise request failed: ${response.status}`);
    }

    const data = await response.json();
    const entries = Array.isArray(data.entries) ? data.entries : [];

    const fragment = document.createDocumentFragment();

    for (const entry of entries) {
      const item = make("article", "reader-praise-entry");
      const text = make("p", "reader-praise-entry__text");

      // textContent is intentional: supplied reader comments are displayed
      // verbatim and never interpreted as HTML.
      text.textContent = String(entry.text ?? "");

      item.append(text);
      fragment.append(item);
    }

    list.replaceChildren(fragment);
    status.textContent = `${entries.length} messages from WantToKnow.info readers`;
    loaded = true;
  }

  async function openPraise(trigger) {
    returnFocus = trigger instanceof HTMLElement ? trigger : document.activeElement;
    buildDialog();

    if (!dialog.open) {
      document.documentElement.classList.add("has-reader-praise-modal");
      dialog.showModal();
    }

    if (loaded) return;

    try {
      await loadPraise();
    } catch (error) {
      console.error(error);
      status.textContent = "Reader praise could not be loaded.";
    }
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(TRIGGER_SELECTOR);
    if (!trigger) return;

    event.preventDefault();
    openPraise(trigger);
  });
})();
