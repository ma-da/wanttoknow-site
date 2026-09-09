(() => {
  "use strict";

  const DATA_URL = "/data/elements/headerFooter.json";

  const $ = (selector, root = document) =>
    root.querySelector(selector);

  const $$ = (selector, root = document) =>
    [...root.querySelectorAll(selector)];

  const escapeHtml = (value = "") =>
    String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");

  const safeHref = (value = "/") => {
    const href = String(value).trim();

    if (
      href.startsWith("/")
      || href.startsWith("#")
      || /^https?:\/\//i.test(href)
    ) {
      return escapeHtml(href);
    }

    return "/";
  };

  async function loadHeaderFooterData() {
    const response = await fetch(DATA_URL, {
      credentials: "same-origin",
      cache: "default"
    });

    if (!response.ok) {
      throw new Error(
        `Could not load ${DATA_URL}: ${response.status}`
      );
    }

    return response.json();
  }

  function menuLink(item) {
    return `
      <a
        class="menu-shift-link"
        href="${safeHref(item.href)}">
        <span>${escapeHtml(item.label)}</span>
      </a>
    `;
  }

  function renderHeader(data) {
    const root = $("[data-global-header]");
    if (!root) return;

    const { brand, search, topics, menu } = data;

    const topicLinks = topics.items
      .map(menuLink)
      .join("");

    const priorityLinks = menu.priority
      .map((item) => `
        <a
          class="site-menu-priority-link${item.accent ? " site-menu-priority-link-accent" : ""}"
          href="${safeHref(item.href)}">

          <span class="site-menu-priority-label">
            ${escapeHtml(item.label)}
          </span>

          <span>
            ${escapeHtml(item.description)}
          </span>

          <strong aria-hidden="true">→</strong>
        </a>
      `)
      .join("");

    const menuColumns = menu.columns
      .map((column, index) => {
        const headingId =
          `site-menu-column-${index}`;

        return `
          <nav
            class="site-menu-column"
            aria-labelledby="${headingId}">

            <h3 id="${headingId}">
              ${escapeHtml(column.heading)}
            </h3>

            ${column.items.map(menuLink).join("")}
          </nav>
        `;
      })
      .join("");

    root.innerHTML = `
      <header
        class="site-header"
        data-site-header>

        <div class="header-bar">
          <div class="container header-bar-inner">

														<a
																class="brand"
																href="${safeHref(brand.home)}"
																aria-label="${escapeHtml(brand.ariaLabel)}">

																<span
																		class="brand-mark"
																		aria-hidden="true">

																		<svg
																				viewBox="0 0 24 24"
																				focusable="false">
																				<circle cx="11" cy="11" r="6.5"></circle>
																				<path d="M16 16L21 21"></path>
																		</svg>

																</span>

																<span class="brand-name">
																		${escapeHtml(brand.name)}
																</span>

														</a>

            <form
              class="header-search header-search-desktop"
              action="${safeHref(search.action)}"
              method="get"
              role="search">

              <label
                class="visually-hidden"
                for="site-search-desktop">
                ${escapeHtml(search.ariaLabel)}
              </label>

              <input
                id="site-search-desktop"
                name="${escapeHtml(search.parameter)}"
                type="search"
                placeholder="${escapeHtml(search.desktopPlaceholder)}"
                autocomplete="off">

              <button
                type="submit"
                aria-label="Search">

                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24">
                  <circle
                    cx="10.8"
                    cy="10.8"
                    r="6.7">
                  </circle>
                  <path
                    d="m16 16 4.2 4.2">
                  </path>
                </svg>
              </button>
            </form>

            <button
              class="topics-toggle"
              id="topics-toggle"
              type="button"
              aria-expanded="false"
              aria-controls="topics-dropdown"
              aria-haspopup="true">

              <span>
                ${escapeHtml(topics.label)}
              </span>

              <svg
                aria-hidden="true"
                viewBox="0 0 16 16">
                <path d="m3 6 5 5 5-5"></path>
              </svg>
            </button>

            <button
              class="menu-toggle"
              type="button"
              aria-expanded="false"
              aria-controls="site-menu"
              aria-haspopup="dialog"
              aria-label="Open site menu">

              <svg
                aria-hidden="true"
                viewBox="0 0 24 24">
                <path
                  d="M3 6h18M3 12h18M3 18h18">
                </path>
              </svg>
            </button>

          </div>
        </div>

        <div class="mobile-search-row">
          <div class="container">

            <form
              class="header-search header-search-mobile"
              action="${safeHref(search.action)}"
              method="get"
              role="search">

              <label
                class="visually-hidden"
                for="site-search-mobile">
                ${escapeHtml(search.ariaLabel)}
              </label>

              <input
                id="site-search-mobile"
                name="${escapeHtml(search.parameter)}"
                type="search"
                placeholder="${escapeHtml(search.mobilePlaceholder)}"
                autocomplete="off">

              <button
                type="submit"
                aria-label="Search">

                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24">
                  <circle
                    cx="10.8"
                    cy="10.8"
                    r="6.7">
                  </circle>
                  <path
                    d="m16 16 4.2 4.2">
                  </path>
                </svg>
              </button>
            </form>

          </div>
        </div>

        <div
          class="topics-dropdown"
          id="topics-dropdown"
          hidden>

          <div
            class="container topics-dropdown-inner">

            <div class="topics-dropdown-heading">

              <strong>
                ${escapeHtml(topics.heading)}
              </strong>

              <a href="${safeHref(topics.viewAll.href)}">
                ${escapeHtml(topics.viewAll.label)}
                <span aria-hidden="true">→</span>
              </a>

            </div>

            <nav
              class="topic-menu-list"
              aria-label="Primary topics">

              ${topicLinks}

            </nav>

          </div>
        </div>

      </header>

      <div
        class="site-menu"
        id="site-menu"
        role="dialog"
        aria-modal="true"
        aria-label="Site menu"
        aria-hidden="true"
        hidden>

        <div class="site-menu-shell">

          <div class="site-menu-topbar">
            <div
              class="container site-menu-topbar-inner">

														<a
																class="brand"
																href="${safeHref(brand.home)}"
																aria-label="${escapeHtml(brand.ariaLabel)}">

																<span
																		class="brand-mark"
																		aria-hidden="true">

																		<svg
																				viewBox="0 0 24 24"
																				focusable="false">
																				<circle cx="11" cy="11" r="6.5"></circle>
																				<path d="M16 16L21 21"></path>
																		</svg>

																</span>

																<span class="brand-name">
																		${escapeHtml(brand.name)}
																</span>

														</a>

              <button
                class="site-menu-close"
                type="button"
                aria-label="Close site menu">

                <svg
                  aria-hidden="true"
                  viewBox="0 0 24 24">
                  <path
                    d="M5 5l14 14M19 5 5 19">
                  </path>
                </svg>
              </button>

            </div>
          </div>

          <div class="site-menu-scroll">
            <div
              class="container site-menu-content">

              <nav
                class="site-menu-priority"
                aria-label="Support and contact">

                ${priorityLinks}

              </nav>

              <div class="site-menu-grid">

                <nav
                  class="site-menu-column site-menu-column-topics"
                  aria-labelledby="menu-topics-heading">

                  <h3 id="menu-topics-heading">
                    Topics
                  </h3>

                  <div class="site-menu-topic-grid">
                    ${topicLinks}
                  </div>

                </nav>

                ${menuColumns}

              </div>
            </div>
          </div>

        </div>
      </div>
    `;
  }

  function renderFooter(data) {
    const root = $("[data-global-footer]");
    if (!root) return;

    const { brand, footer } = data;

    const columns = footer.columns
      .map((column) => `
        <div class="footer-column">

          <h2>
            ${escapeHtml(column.heading)}
          </h2>

          <ul class="footer-links">
            ${column.items
              .map((item) => `
                <li>
                  <a href="${safeHref(item.href)}">
                    ${escapeHtml(item.label)}
                  </a>
                </li>
              `)
              .join("")}
          </ul>

        </div>
      `)
      .join("");

    const legal = footer.legal
      .map((item) => `
        <a href="${safeHref(item.href)}">
          ${escapeHtml(item.label)}
        </a>
      `)
      .join(" · ");

    root.innerHTML = `
      <footer class="site-footer">

        <div class="container">

          <div class="footer-grid">

            <div class="footer-brand">

														<a
																class="brand"
																href="${safeHref(brand.home)}"
																aria-label="${escapeHtml(brand.ariaLabel)}">

																<span
																		class="brand-mark"
																		aria-hidden="true">

																		<svg
																				viewBox="0 0 24 24"
																				focusable="false">
																				<circle cx="11" cy="11" r="6.5"></circle>
																				<path d="M16 16L21 21"></path>
																		</svg>

																</span>

																<span class="brand-name">
																		${escapeHtml(brand.name)}
																</span>

														</a>

              <p>
                ${escapeHtml(brand.footerDescription)}
              </p>

            </div>

            ${columns}

          </div>

          <div class="footer-bottom">

            <span>
              ©
              <span id="current-year">
                ${new Date().getFullYear()}
              </span>
              ${escapeHtml(footer.copyright)}
            </span>

            <span>
              ${legal}
            </span>

          </div>

        </div>

      </footer>
    `;
  }

  function initHeaderNavigation() {
    const siteHeader = $("[data-site-header]");
    const topicsButton = $("#topics-toggle");
    const topicsDropdown = $("#topics-dropdown");
    const menuButton = $(".menu-toggle");
    const siteMenu = $("#site-menu");
    const siteMenuClose = $(".site-menu-close");

    if (!siteHeader) return;

    let menuReturnFocus = null;
    let menuHideTimer = 0;

    let lastScrollY = window.scrollY;
    let scrollTicking = false;
    let scrollDirection = 0;
    let scrollDistance = 0;

    const headerHideDistance = 32;
    const headerShowDistance = 14;

    const menuTransitionMs =
      window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches
        ? 0
        : 280;

    function topicsAreOpen() {
      return (
        topicsButton?.getAttribute(
          "aria-expanded"
        ) === "true"
      );
    }

    function setTopics(open) {
      if (
        !topicsButton
        || !topicsDropdown
      ) {
        return;
      }

      topicsButton.setAttribute(
        "aria-expanded",
        String(open)
      );

      topicsDropdown.hidden =
        !open;

      siteHeader.classList.toggle(
        "has-panel-open",
        open
      );
    }

    function getMenuFocusable() {
      if (!siteMenu) return [];

      return $$(
        'a[href], '
          + 'button:not([disabled]), '
          + 'input:not([disabled]), '
          + '[tabindex]:not([tabindex="-1"])',
        siteMenu
      ).filter(
        (element) =>
          !element.hidden
          && element.getClientRects().length
      );
    }

    function openSiteMenu() {
      if (
        !siteMenu
        || !menuButton
      ) {
        return;
      }

      setTopics(false);
      clearTimeout(menuHideTimer);

      menuReturnFocus =
        document.activeElement;

      siteMenu.hidden =
        false;

      siteMenu.setAttribute(
        "aria-hidden",
        "false"
      );

      menuButton.setAttribute(
        "aria-expanded",
        "true"
      );

      document.body.classList.add(
        "menu-open"
      );

      requestAnimationFrame(() => {
        siteMenu.classList.add(
          "is-open"
        );
      });

      requestAnimationFrame(() => {
        siteMenuClose?.focus();
      });
    }

    function closeSiteMenu({
      restoreFocus = true
    } = {}) {
      if (
        !siteMenu
        || !menuButton
        || siteMenu.hidden
      ) {
        return;
      }

      siteMenu.classList.remove(
        "is-open"
      );

      siteMenu.setAttribute(
        "aria-hidden",
        "true"
      );

      menuButton.setAttribute(
        "aria-expanded",
        "false"
      );

      document.body.classList.remove(
        "menu-open"
      );

      menuHideTimer =
        window.setTimeout(
          () => {
            siteMenu.hidden =
              true;
          },
          menuTransitionMs
        );

      if (
        restoreFocus
        && menuReturnFocus
          instanceof HTMLElement
      ) {
        requestAnimationFrame(
          () => {
            menuReturnFocus.focus();
          }
        );
      }
    }

    topicsButton?.addEventListener(
      "click",
      () => {
        setTopics(
          !topicsAreOpen()
        );
      }
    );

    topicsDropdown?.addEventListener(
      "click",
      (event) => {
        if (
          event.target.closest("a")
        ) {
          setTopics(false);
        }
      }
    );

    document.addEventListener(
      "click",
      (event) => {
        if (
          topicsAreOpen()
          && !siteHeader.contains(
            event.target
          )
        ) {
          setTopics(false);
        }
      }
    );

    menuButton?.addEventListener(
      "click",
      openSiteMenu
    );

    siteMenuClose?.addEventListener(
      "click",
      () => closeSiteMenu()
    );

    siteMenu?.addEventListener(
      "click",
      (event) => {
        if (
          event.target.closest("a")
        ) {
          closeSiteMenu({
            restoreFocus: false
          });
        }
      }
    );

    document.addEventListener(
      "keydown",
      (event) => {
        if (
          event.key === "Escape"
        ) {
          if (
            siteMenu
            && !siteMenu.hidden
          ) {
            event.preventDefault();
            closeSiteMenu();
            return;
          }

          if (topicsAreOpen()) {
            event.preventDefault();
            setTopics(false);
            topicsButton?.focus();
          }
        }

        if (
          event.key === "Tab"
          && siteMenu
          && !siteMenu.hidden
        ) {
          const focusable =
            getMenuFocusable();

          if (!focusable.length) {
            return;
          }

          const first =
            focusable[0];

          const last =
            focusable[
              focusable.length - 1
            ];

          if (
            event.shiftKey
            && document.activeElement
              === first
          ) {
            event.preventDefault();
            last.focus();
          } else if (
            !event.shiftKey
            && document.activeElement
              === last
          ) {
            event.preventDefault();
            first.focus();
          }
        }
      }
    );

    function updateHeaderOnScroll() {
      const currentY =
        Math.max(
          0,
          window.scrollY
        );

      const delta =
        currentY - lastScrollY;

      const direction =
        delta === 0
          ? scrollDirection
          : Math.sign(delta);

      const overlayOpen =
        (
          siteMenu
          && !siteMenu.hidden
        )
        || topicsAreOpen();

      if (
        direction
        && direction
          !== scrollDirection
      ) {
        scrollDirection =
          direction;

        scrollDistance =
          0;
      }

      scrollDistance +=
        Math.abs(delta);

      if (
        overlayOpen
        || currentY <= 24
      ) {
        siteHeader.classList.remove(
          "is-hidden"
        );

        scrollDistance = 0;
      } else if (
        scrollDirection > 0
        && currentY > 96
        && scrollDistance
          >= headerHideDistance
      ) {
        siteHeader.classList.add(
          "is-hidden"
        );

        scrollDistance = 0;
      } else if (
        scrollDirection < 0
        && scrollDistance
          >= headerShowDistance
      ) {
        siteHeader.classList.remove(
          "is-hidden"
        );

        scrollDistance = 0;
      }

      lastScrollY =
        currentY;

      scrollTicking =
        false;
    }

    window.addEventListener(
      "scroll",
      () => {
        if (scrollTicking) {
          return;
        }

        scrollTicking =
          true;

        requestAnimationFrame(
          updateHeaderOnScroll
        );
      },
      { passive: true }
    );
  }

  function initSharing() {
    const canonicalUrl =
      $("link[rel='canonical']")?.href
      || window.location.href;

    const shareTitle =
      document.title;

    const shareDescription =
      $("meta[name='description']")
        ?.content
      || "Explore WantToKnow.info.";

    const shareStatus =
      $("#shareStatus");

    function announce(
      message,
      timeout = 2600
    ) {
      if (!shareStatus) return;

      shareStatus.textContent =
        message;

      clearTimeout(
        announce.timer
      );

      announce.timer =
        window.setTimeout(
          () => {
            shareStatus.textContent =
              "";
          },
          timeout
        );
    }

    async function copyText(text) {
      if (
        navigator.clipboard?.writeText
        && window.isSecureContext
      ) {
        await navigator.clipboard.writeText(
          text
        );

        return;
      }

      const field =
        document.createElement(
          "textarea"
        );

      field.value =
        text;

      field.readOnly =
        true;

      Object.assign(
        field.style,
        {
          position: "fixed",
          left: "-9999px",
          opacity: "0"
        }
      );

      document.body.appendChild(
        field
      );

      field.select();

      const copied =
        document.execCommand(
          "copy"
        );

      field.remove();

      if (!copied) {
        throw new Error(
          "Copy failed"
        );
      }
    }

    const encodedUrl =
      encodeURIComponent(
        canonicalUrl
      );

    const encodedTitle =
      encodeURIComponent(
        shareTitle
      );

    const shareFB =
      $("#shareFB");

    if (shareFB) {
      shareFB.href =
        "https://www.facebook.com/"
        + "sharer/sharer.php?u="
        + encodedUrl;
    }

    const shareTwitter =
      $("#shareTwitter");

    if (shareTwitter) {
      shareTwitter.href =
        "https://twitter.com/"
        + "intent/tweet?url="
        + encodedUrl
        + "&text="
        + encodedTitle;
    }

    const nativeShareBtn =
      $("#nativeShareBtn");

    if (
      navigator.share
      && nativeShareBtn
    ) {
      nativeShareBtn.hidden =
        false;

      nativeShareBtn.addEventListener(
        "click",
        async () => {
          try {
            await navigator.share({
              title: shareTitle,
              text: shareDescription,
              url: canonicalUrl
            });
          } catch (error) {
            if (
              error?.name
              !== "AbortError"
            ) {
              announce(
                "Sharing is unavailable "
                + "in this browser."
              );
            }
          }
        }
      );
    }

    $("#shareCopy")?.addEventListener(
      "click",
      async () => {
        try {
          await copyText(
            canonicalUrl
          );

          announce(
            "Link copied."
          );
        } catch {
          announce(
            "Could not copy automatically. "
              + "Copy the address from "
              + "your browser."
          );
        }
      }
    );

    window.WTK = Object.freeze({
      canonicalUrl,
      shareTitle,
      shareDescription,
      announce,
      copyText
    });
  }

  async function init() {
    try {
      const data =
        await loadHeaderFooterData();

      renderHeader(data);
      renderFooter(data);

      initHeaderNavigation();
      initSharing();

      document.dispatchEvent(
        new CustomEvent(
          "wtk:global-ready",
          {
            detail: data
          }
        )
      );
    } catch (error) {
      console.error(
        "Global header/footer "
          + "failed to initialize:",
        error
      );
    }
  }

  init();
})();
