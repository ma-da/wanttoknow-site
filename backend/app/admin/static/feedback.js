(() => {
  "use strict";

  const state = {
    active: "contact",
    filter: "all",
    csrfToken: "",

    contact: [],
    survey: [],

    contactTotal: 0,
    surveyTotal: 0,

    openCards: new Set(),
  };


  // ==========================================================================
  // DOM
  // ==========================================================================

  const tabs = Array.from(
    document.querySelectorAll(
      "[data-feedback-tab]"
    )
  );

  const searchInput =
    document.getElementById(
      "feedback-search"
    );

  const filterSelect =
    document.getElementById(
      "feedback-filter"
    );

  const contactPanel =
    document.getElementById(
      "contact-panel"
    );

  const surveyPanel =
    document.getElementById(
      "survey-panel"
    );

  const contactList =
    document.getElementById(
      "contact-list"
    );

  const surveyList =
    document.getElementById(
      "survey-list"
    );

  const status =
    document.getElementById(
      "feedback-status"
    );

  const contactTotal =
    document.getElementById(
      "contact-total"
    );

  const surveyTotal =
    document.getElementById(
      "survey-total"
    );

  const visibleTotal =
    document.getElementById(
      "visible-total"
    );


  const pageviewsList =
    document.getElementById(
      "feedback-pageviews"
    );


  const pageviewsTitle =
    document.getElementById(
      "feedback-pageviews-title"
    );


  // ==========================================================================
  // General helpers
  // ==========================================================================

  function make(
    tag,
    className = "",
    text = "",
  ) {
    const node =
      document.createElement(tag);

    if (className) {
      node.className = className;
    }

    if (text !== "") {
      node.textContent =
        String(text);
    }

    return node;
  }


  function formatDate(value) {
    if (!value) {
      return "Unknown date";
    }

    const date =
      new Date(value);

    if (
      Number.isNaN(
        date.getTime()
      )
    ) {
      return String(value);
    }

    return date.toLocaleString();
  }


  function safeUrl(value) {
    if (!value) {
      return null;
    }

    try {
      const parsed =
        new URL(value);

      if (
        parsed.protocol !== "http:" &&
        parsed.protocol !== "https:"
      ) {
        return null;
      }

      return parsed.href;

    } catch {
      return null;
    }
  }


  function searchable(record) {
    try {
      return JSON.stringify(
        record
      ).toLowerCase();

    } catch {
      return "";
    }
  }


  function adminState(record) {
    return record._admin || {
      is_read: false,
      is_archived: false,
      internal_note: "",
      updated_at: null,
      updated_by: null,
    };
  }


  function cardKey(
    source,
    record,
  ) {
    return (
      `${source}:${record._record_key}`
    );
  }


  // ==========================================================================
  // Filtering
  // ==========================================================================

  function filtered(records) {
    const query =
      searchInput.value
        .trim()
        .toLowerCase();

    return records.filter(
      record => {
        const admin =
          adminState(record);

        if (
          query &&
          !searchable(record)
            .includes(query)
        ) {
          return false;
        }

        if (
          state.filter === "unread"
        ) {
          return (
            !admin.is_read &&
            !admin.is_archived
          );
        }

        if (
          state.filter === "archived"
        ) {
          return admin.is_archived;
        }

        /*
         * Normal view excludes archived items.
         * Archived responses remain available
         * through the Archived filter.
         */
        return !admin.is_archived;
      }
    );
  }


  // ==========================================================================
  // Metadata
  // ==========================================================================

  function addMeta(
    parent,
    label,
    value,
  ) {
    if (
      value === null ||
      value === undefined ||
      value === ""
    ) {
      return;
    }

    const item =
      make(
        "span",
        "feedback-meta-item",
      );

    const strong =
      make(
        "strong",
        "",
        `${label}: `
      );

    item.append(
      strong,
      document.createTextNode(
        String(value)
      )
    );

    parent.append(item);
  }


  function addBadges(
    parent,
    record,
  ) {
    const admin =
      adminState(record);

    const badges =
      make(
        "span",
        "feedback-badges",
      );

    if (!admin.is_read) {
      badges.append(
        make(
          "span",
          "feedback-badge feedback-badge--unread",
          "Unread"
        )
      );
    }

    if (admin.is_archived) {
      badges.append(
        make(
          "span",
          "feedback-badge feedback-badge--archived",
          "Archived"
        )
      );
    }

    parent.append(badges);
  }


  // ==========================================================================
  // API
  // ==========================================================================

  async function fetchJson(
    url,
    options = {},
  ) {
    const headers = {
      "Accept": "application/json",
      ...(options.headers || {}),
    };

    const response =
      await fetch(
        url,
        {
          ...options,

          credentials:
            "same-origin",

          headers,
        }
      );

    if (
      response.status === 401
    ) {
      location.href =
        "/admin/login";

      throw new Error(
        "Authentication required"
      );
    }

    if (!response.ok) {
      const payload =
        await response
          .json()
          .catch(
            () => ({})
          );

      throw new Error(
        payload.detail ||
          `Request failed: ${response.status}`
      );
    }

    return response.json();
  }


  async function patchRecord(
    source,
    record,
    payload,
  ) {
    const key =
      record._record_key;

    if (!key) {
      throw new Error(
        "Feedback record has no key."
      );
    }

    const response =
      await fetchJson(
        `/api/admin/feedback/${encodeURIComponent(source)}/${encodeURIComponent(key)}`,
        {
          method: "PATCH",

          headers: {
            "Content-Type":
              "application/json",

            "X-CSRF-Token":
              state.csrfToken,
          },

          body: JSON.stringify(
            payload
          ),
        }
      );

    record._admin =
      response.admin;

    return response.admin;
  }


  // ==========================================================================
  // Triage controls
  // ==========================================================================

  function makeActionButton(
    text,
  ) {
    return make(
      "button",
      "button button-secondary button-small",
      text
    );
  }


  function makeTriageControls(
    source,
    record,
  ) {
    const admin =
      adminState(record);

    const wrapper =
      make(
        "section",
        "feedback-triage",
      );

    const heading =
      make(
        "h3",
        "feedback-triage-title",
        "Admin"
      );

    const actions =
      make(
        "div",
        "feedback-triage-actions",
      );

    const readButton =
      makeActionButton(
        admin.is_read
          ? "Mark unread"
          : "Mark read"
      );

    const archiveButton =
      makeActionButton(
        admin.is_archived
          ? "Unarchive"
          : "Archive"
      );

    actions.append(
      readButton,
      archiveButton
    );


    // ------------------------------------------------------------------------
    // Internal note
    // ------------------------------------------------------------------------

    const noteLabel =
      make(
        "label",
        "feedback-note-label",
      );

    noteLabel.append(
      make(
        "span",
        "",
        "Internal note"
      )
    );

    const textarea =
      make(
        "textarea",
        "admin-field admin-textarea feedback-note",
      );

    textarea.rows = 3;

    textarea.value =
      admin.internal_note || "";

    textarea.placeholder =
      "Private note for administrators…";

    noteLabel.append(
      textarea
    );

    const noteActions =
      make(
        "div",
        "feedback-note-actions",
      );

    const saveButton =
      make(
        "button",
        "button button-primary button-small",
        "Save note"
      );

    const saveStatus =
      make(
        "span",
        "feedback-save-status",
      );

    noteActions.append(
      saveButton,
      saveStatus
    );


    // ------------------------------------------------------------------------
    // Read / unread
    // ------------------------------------------------------------------------

    readButton.addEventListener(
      "click",
      async () => {
        readButton.disabled = true;

        try {
          await patchRecord(
            source,
            record,
            {
              is_read:
                !adminState(record)
                  .is_read,
            }
          );

          status.textContent =
            "Feedback status updated.";

          render();

        } catch (error) {
          status.textContent =
            error.message ||
            "Could not update feedback.";

        } finally {
          readButton.disabled =
            false;
        }
      }
    );


    // ------------------------------------------------------------------------
    // Archive
    // ------------------------------------------------------------------------

    archiveButton.addEventListener(
      "click",
      async () => {
        archiveButton.disabled = true;

        try {
          await patchRecord(
            source,
            record,
            {
              is_archived:
                !adminState(record)
                  .is_archived,
            }
          );

          status.textContent =
            adminState(record)
              .is_archived
              ? "Feedback archived."
              : "Feedback restored.";

          render();

        } catch (error) {
          status.textContent =
            error.message ||
            "Could not update feedback.";

        } finally {
          archiveButton.disabled =
            false;
        }
      }
    );


    // ------------------------------------------------------------------------
    // Internal note
    // ------------------------------------------------------------------------

    saveButton.addEventListener(
      "click",
      async () => {
        saveButton.disabled = true;

        saveStatus.textContent =
          "Saving…";

        try {
          await patchRecord(
            source,
            record,
            {
              internal_note:
                textarea.value,
            }
          );

          textarea.value =
            adminState(record)
              .internal_note || "";

          saveStatus.textContent =
            "Saved";

        } catch (error) {
          saveStatus.textContent =
            error.message ||
            "Save failed";

        } finally {
          saveButton.disabled =
            false;
        }
      }
    );


    wrapper.append(
      heading,
      actions,
      noteLabel,
      noteActions
    );

    if (admin.updated_at) {
      const updated =
        make(
          "p",
          "feedback-triage-updated",
          `Last updated ${formatDate(admin.updated_at)}`
        );

      if (admin.updated_by) {
        updated.append(
          document.createTextNode(
            ` by ${admin.updated_by}`
          )
        );
      }

      wrapper.append(updated);
    }

    return wrapper;
  }


  // ==========================================================================
  // Card foundation
  // ==========================================================================

  function makeCard(
    source,
    record,
  ) {
    const details =
      make(
        "details",
        "feedback-item",
      );

    const admin =
      adminState(record);

    details.classList.toggle(
      "is-unread",
      !admin.is_read
    );

    details.classList.toggle(
      "is-archived",
      admin.is_archived
    );

    const key =
      cardKey(
        source,
        record
      );

    details.dataset.feedbackKey =
      key;

    details.open =
      state.openCards.has(
        key
      );

    details.addEventListener(
      "toggle",
      () => {
        if (details.open) {
          state.openCards.add(
            key
          );

        } else {
          state.openCards.delete(
            key
          );
        }
      }
    );

    return details;
  }


  function makeSummary(
    record,
    title,
    dateValue,
  ) {
    const summary =
      make(
        "summary",
        "feedback-summary",
      );

    const titleArea =
      make(
        "span",
        "feedback-summary-main",
      );

    titleArea.append(
      make(
        "span",
        "feedback-summary-title",
        title
      )
    );

    addBadges(
      titleArea,
      record
    );

    summary.append(
      titleArea,

      make(
        "time",
        "feedback-summary-date",
        formatDate(
          dateValue
        )
      )
    );

    return summary;
  }


  // ==========================================================================
  // Contact cards
  // ==========================================================================

  function renderContactCard(
    record,
  ) {
    const details =
      makeCard(
        "contact",
        record
      );

    const summary =
      makeSummary(
        record,

        record.name ||
          record.email ||
          "Anonymous",

        record.received_at ||
          record.submitted_at
      );

    const content =
      make(
        "div",
        "feedback-item-body",
      );

    const meta =
      make(
        "div",
        "feedback-meta",
      );

    addMeta(
      meta,
      "Type",
      record.contact_type
    );

    addMeta(
      meta,
      "Name",
      record.name
    );

    addMeta(
      meta,
      "Email",
      record.email
    );

    addMeta(
      meta,
      "Subscriber",
      record.subscriber
        ? "Yes"
        : "No"
    );

    addMeta(
      meta,
      "Share comment",
      record.share_comment
        ? "Yes"
        : "No"
    );

    content.append(meta);


    if (record.url) {
      const row =
        make(
          "div",
          "feedback-url",
        );

      row.append(
        make(
          "strong",
          "",
          "URL: "
        )
      );

      const href =
        safeUrl(record.url);

      if (href) {
        const link =
          make(
            "a",
            "",
            record.url
          );

        link.href = href;
        link.target = "_blank";
        link.rel = "noopener";

        row.append(link);

      } else {
        row.append(
          document.createTextNode(
            record.url
          )
        );
      }

      content.append(row);
    }


    content.append(
      make(
        "div",
        "feedback-message",
        record.message ||
          "(No message)"
      )
    );

    content.append(
      makeTriageControls(
        "contact",
        record
      )
    );

    details.append(
      summary,
      content
    );

    return details;
  }


  // ==========================================================================
  // Survey cards
  // ==========================================================================

  function ratingLabel(key) {
    return String(key)
      .replaceAll(
        "_",
        " "
      )
      .replace(
        /\b\w/g,
        char =>
          char.toUpperCase()
      );
  }


  function renderSurveyCard(
    record,
  ) {
    const details =
      makeCard(
        "survey",
        record
      );

    const ratings =
      record.ratings &&
      typeof record.ratings ===
        "object"
        ? record.ratings
        : {};

    const overall =
      ratings.overall ?? "—";

    const summary =
      makeSummary(
        record,
        `Overall: ${overall}/5`,
        record.submitted_at
      );

    const content =
      make(
        "div",
        "feedback-item-body",
      );

    const grid =
      make(
        "div",
        "feedback-rating-grid",
      );

    for (
      const [key, value]
      of Object.entries(ratings)
    ) {
      const item =
        make(
          "div",
          "feedback-rating",
        );

      item.append(
        make(
          "span",
          "",
          ratingLabel(key)
        ),

        make(
          "strong",
          "",
          `${value}/5`
        )
      );

      grid.append(item);
    }

    content.append(grid);


    const comments = [
      [
        "What they loved",
        record.love,
      ],
      [
        "What they disliked",
        record.hate,
      ],
      [
        "What's missing",
        record.missing,
      ],
    ];

    for (
      const [label, value]
      of comments
    ) {
      if (!value) {
        continue;
      }

      const block =
        make(
          "section",
          "feedback-comment",
        );

      block.append(
        make(
          "h3",
          "",
          label
        ),

        make(
          "div",
          "feedback-message",
          value
        )
      );

      content.append(block);
    }


    content.append(
      makeTriageControls(
        "survey",
        record
      )
    );

    details.append(
      summary,
      content
    );

    return details;
  }


  // ==========================================================================
  // Rendering
  // ==========================================================================

  function render() {
    const contact =
      filtered(
        state.contact
      );

    const survey =
      filtered(
        state.survey
      );

    contactList.replaceChildren();
    surveyList.replaceChildren();


    for (
      const record of contact
    ) {
      contactList.append(
        renderContactCard(
          record
        )
      );
    }


    for (
      const record of survey
    ) {
      surveyList.append(
        renderSurveyCard(
          record
        )
      );
    }


    if (!contact.length) {
      contactList.append(
        make(
          "div",
          "admin-empty",
          "No matching contact messages."
        )
      );
    }


    if (!survey.length) {
      surveyList.append(
        make(
          "div",
          "admin-empty",
          "No matching survey responses."
        )
      );
    }


    contactTotal.textContent =
      String(
        state.contactTotal
      );

    surveyTotal.textContent =
      String(
        state.surveyTotal
      );

    visibleTotal.textContent =
      String(
        state.active === "contact"
          ? contact.length
          : survey.length
      );
  }


  function switchTab(name) {
    state.active = name;

    contactPanel.hidden =
      name !== "contact";

    surveyPanel.hidden =
      name !== "survey";

    for (const tab of tabs) {
      tab.classList.toggle(
        "is-active",
        tab.dataset.feedbackTab ===
          name
      );
    }

    render();
  }



  // ==========================================================================
  // Recent pageviews
  // ==========================================================================

  async function loadPageviews() {
    if (!pageviewsList) {
      return;
    }

    try {
      const payload =
        await fetchJson(
          "/api/admin/analytics/pages?limit=100"
        );

      const records =
        payload.records || [];

      if (pageviewsTitle) {
        const daily =
          Number(
            payload.daily_total || 0
          ).toLocaleString();

        const grand =
          Number(
            payload.grand_total || 0
          ).toLocaleString();

        pageviewsTitle.textContent =
          `Recent Visits ${daily}  Total Visits ${grand}`;
      }

      pageviewsList.replaceChildren();

      if (!records.length) {
        pageviewsList.append(
          make(
            "div",
            "admin-empty",
            "No page visits yet."
          )
        );

        return;
      }

      for (const record of records) {
        const row =
          make(
            "div",
            "feedback-pageview-row",
          );

        const daily =
          make(
            "span",
            "feedback-pageview-number",
            record.daily_visits ?? 0
          );

        const link =
          make(
            "a",
            "feedback-pageview-path",
            record.path || "/"
          );

        link.href =
          record.path || "/";

        link.target = "_blank";
        link.rel = "noopener";

        const total =
          make(
            "span",
            "feedback-pageview-number",
            record.total_visits ?? 0
          );

        row.append(
          daily,
          link,
          total
        );

        pageviewsList.append(row);
      }

    } catch (error) {
      pageviewsList.textContent =
        error.message ||
        "Page visits unavailable.";
    }
  }



  async function loadSession() {
    const payload =
      await fetchJson(
        "/api/admin/session"
      );

    state.csrfToken =
      payload.csrf_token ||
      payload.csrfToken ||
      "";

    if (!state.csrfToken) {
      throw new Error(
        "Admin CSRF token unavailable."
      );
    }
  }


  // ==========================================================================
  // Loading
  // ==========================================================================

  async function load() {
    status.textContent =
      "Loading feedback…";

    try {
      const [
        contactPayload,
        surveyPayload,
      ] = await Promise.all([
        fetchJson(
          "/api/admin/feedback/contact?limit=250"
        ),

        fetchJson(
          "/api/admin/feedback/survey?limit=250"
        ),
      ]);

      state.contact =
        contactPayload.records || [];

      state.survey =
        surveyPayload.records || [];

      state.contactTotal =
        contactPayload.total || 0;

      state.surveyTotal =
        surveyPayload.total || 0;


      const warnings = [];

      if (
        contactPayload.errors
      ) {
        warnings.push(
          `${contactPayload.errors} contact record(s) could not be read`
        );
      }

      if (
        surveyPayload.errors
      ) {
        warnings.push(
          `${surveyPayload.errors} survey record(s) could not be read`
        );
      }

      status.textContent =
        warnings.length
          ? warnings.join(". ")
          : "Newest responses first.";

      render();

    } catch (error) {
      status.textContent =
        error.message ||
        "Feedback could not be loaded.";
    }
  }


  // ==========================================================================
  // Events
  // ==========================================================================

  for (const tab of tabs) {
    tab.addEventListener(
      "click",
      () => {
        switchTab(
          tab.dataset.feedbackTab
        );
      }
    );
  }


  searchInput.addEventListener(
    "input",
    render
  );


  filterSelect.addEventListener(
    "change",
    () => {
      state.filter =
        filterSelect.value;

      render();
    }
  );


  async function start() {
    try {
      await loadSession();

    } catch (error) {
      status.textContent =
        error.message ||
        "Admin session could not be loaded.";

      return;
    }

    await Promise.all([
      load(),
      loadPageviews(),
    ]);
  }


  start();
})();
