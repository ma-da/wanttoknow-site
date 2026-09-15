(() => {
  "use strict";

  const state = {
    active: "contact",
    contact: [],
    survey: [],
    contactTotal: 0,
    surveyTotal: 0,
  };

  const tabs = Array.from(
    document.querySelectorAll(
      "[data-feedback-tab]"
    )
  );

  const searchInput =
    document.getElementById(
      "feedback-search"
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


  function filtered(records) {
    const query =
      searchInput.value
        .trim()
        .toLowerCase();

    if (!query) {
      return records;
    }

    return records.filter(
      record =>
        searchable(record)
          .includes(query)
    );
  }


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


  function renderContactCard(
    record,
  ) {
    const details =
      make(
        "details",
        "feedback-item",
      );

    const summary =
      make(
        "summary",
        "feedback-summary",
      );

    const heading =
      make(
        "span",
        "feedback-summary-title",
        record.name ||
          record.email ||
          "Anonymous"
      );

    const date =
      make(
        "time",
        "feedback-summary-date",
        formatDate(
          record.received_at ||
          record.submitted_at
        )
      );

    summary.append(
      heading,
      date
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

    const message =
      make(
        "div",
        "feedback-message",
        record.message ||
          "(No message)"
      );

    content.append(message);

    details.append(
      summary,
      content
    );

    return details;
  }


  function ratingLabel(key) {
    return String(key)
      .replaceAll("_", " ")
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
      make(
        "details",
        "feedback-item",
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
      make(
        "summary",
        "feedback-summary",
      );

    summary.append(
      make(
        "span",
        "feedback-summary-title",
        `Overall: ${overall}/5`
      ),
      make(
        "time",
        "feedback-summary-date",
        formatDate(
          record.submitted_at
        )
      )
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

    details.append(
      summary,
      content
    );

    return details;
  }


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


  async function fetchJson(url) {
    const response =
      await fetch(
        url,
        {
          credentials:
            "same-origin",
          headers: {
            "Accept":
              "application/json",
          },
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


  load();
})();
