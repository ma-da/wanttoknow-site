/* ==========================================================================
   WantToKnow.info News Feed Web Component

   Examples:
   <wtk-news-feed limit="8"></wtk-news-feed>

   <wtk-news-feed
     tags="ufos"
     limit="6"
     sort="newest">
   </wtk-news-feed>

   <wtk-news-feed
     tags="governmentcorruption,civilliberties"
     tag-mode="all"
     limit="10"
     sort="posted">
   </wtk-news-feed>
   ========================================================================== */

const ARTICLE_INDEX_CACHE = new Map();

let newsFeedInstanceCount = 0;


/* ==========================================================================
   Shared data loading
   ========================================================================== */

async function loadJsonl(url) {
  if (ARTICLE_INDEX_CACHE.has(url)) {
    return ARTICLE_INDEX_CACHE.get(url);
  }

  const request = fetch(url)
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(
          `Unable to load article index: ${response.status} ${response.statusText}`
        );
      }

      const text = await response.text();
      const articles = [];

      const lines = text.split(/\r?\n/);

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();

        if (!line) {
          continue;
        }

        try {
          articles.push(JSON.parse(line));
        } catch (error) {
          console.warn(
            `[wtk-news-feed] Invalid JSON on line ${i + 1}`,
            error
          );
        }
      }

      return articles;
    })
    .catch((error) => {
      ARTICLE_INDEX_CACHE.delete(url);
      throw error;
    });

  ARTICLE_INDEX_CACHE.set(url, request);

  return request;
}


/* ==========================================================================
   Formatting helpers
   ========================================================================== */

const PUBLISHER_ACRONYMS = new Map([
  ["abc", "ABC"],
  ["bbc", "BBC"],
  ["cbc", "CBC"],
  ["cbs", "CBS"],
  ["cnn", "CNN"],
  ["npr", "NPR"],
  ["nbc", "NBC"],
  ["pbs", "PBS"],
  ["reuters", "Reuters"],
  ["usa", "USA"],
  ["us", "US"]
]);


function humanizePublisher(slug) {
  if (!slug) {
    return "Unknown publisher";
  }

  return String(slug)
    .split("-")
    .filter(Boolean)
    .map((word) => {
      const lower = word.toLowerCase();

      if (PUBLISHER_ACRONYMS.has(lower)) {
        return PUBLISHER_ACRONYMS.get(lower);
      }

      return lower.charAt(0).toUpperCase() + lower.slice(1);
    })
    .join(" ");
}


function humanizeTag(tag) {
  if (!tag) {
    return "";
  }

  /*
   * This prettifies tags containing - or _.
   *
   * Legacy slugs such as "governmentcorruption" cannot be separated
   * intelligently without a category-label lookup table. The slug is
   * therefore preserved rather than guessed incorrectly.
   */
  return String(tag)
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}


function formatDate(isoDate) {
  if (!isoDate) {
    return "";
  }

  const parts = String(isoDate).split("-").map(Number);

  if (parts.length !== 3 || parts.some(Number.isNaN)) {
    return isoDate;
  }

  const [year, month, day] = parts;

  /*
   * Use UTC explicitly so YYYY-MM-DD does not accidentally display
   * as the previous day in US time zones.
   */
  const date = new Date(Date.UTC(year, month - 1, day));

  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  }).format(date);
}


function makeElement(tagName, className = "") {
  const element = document.createElement(tagName);

  if (className) {
    element.className = className;
  }

  return element;
}

/* ==========================================================================
   Generated sacred-geometry thumbnail fallbacks
   ========================================================================== */

/*
 * Hard-coded SVG fragments.
 *
 * Two different patterns are layered for each article, with deterministic
 * rotation/scale based on the article ID.
 *
 * They are geometric rather than literal reproductions of any one symbol.
 */
const GEOMETRY_PATTERNS = [


  /* 02 — flower / sixfold circles */
  `
    <circle cx="50" cy="50" r="15"/>
    <circle cx="50" cy="35" r="15"/>
    <circle cx="63" cy="42.5" r="15"/>
    <circle cx="63" cy="57.5" r="15"/>
    <circle cx="50" cy="65" r="15"/>
    <circle cx="37" cy="57.5" r="15"/>
    <circle cx="37" cy="42.5" r="15"/>
    <circle cx="50" cy="50" r="31"/>
  `,

  /* 03 — nested hexagons */
  `
    <polygon points="50,10 84,30 84,70 50,90 16,70 16,30"/>
    <polygon points="50,20 75,35 75,65 50,80 25,65 25,35"/>
    <polygon points="50,31 66,40 66,60 50,69 34,60 34,40"/>
    <path d="M50 10 V90 M16 30 L84 70 M84 30 L16 70"/>
  `,

  /* 04 — eight-point star */
  `
    <circle cx="50" cy="50" r="36"/>
    <polygon points="50,12 61,39 88,50 61,61 50,88 39,61 12,50 39,39"/>
    <polygon points="23,23 50,35 77,23 65,50 77,77 50,65 23,77 35,50"/>
  `,

  /* 05 — vesica structure */
  `
    <circle cx="39" cy="50" r="27"/>
    <circle cx="61" cy="50" r="27"/>
    <circle cx="50" cy="50" r="38"/>
    <path d="M50 12 V88"/>
    <path d="M12 50 H88"/>
  `,

  /* 06 — radial node lattice */
  `
    <circle cx="50" cy="50" r="8"/>
    <circle cx="50" cy="19" r="7"/>
    <circle cx="77" cy="34" r="7"/>
    <circle cx="77" cy="66" r="7"/>
    <circle cx="50" cy="81" r="7"/>
    <circle cx="23" cy="66" r="7"/>
    <circle cx="23" cy="34" r="7"/>
    <path d="
      M50 19 L77 66 L23 66 Z
      M50 81 L23 34 L77 34 Z
      M23 34 L77 66
      M77 34 L23 66
      M50 19 L50 81
    "/>
  `,

  /* 08 — nested triangle field */
  `
    <path d="M50 10 L86 75 L14 75 Z"/>
    <path d="M50 90 L18 31 L82 31 Z"/>
    <path d="M50 25 L72 64 L28 64 Z"/>
    <path d="M50 75 L34 45 L66 45 Z"/>
    <circle cx="50" cy="50" r="36"/>
  `,

  /* 09 — radial mandala */
  `
    <circle cx="50" cy="50" r="38"/>
    <circle cx="50" cy="50" r="27"/>
    <circle cx="50" cy="50" r="15"/>
    <path d="
      M50 12 V88
      M12 50 H88
      M23 23 L77 77
      M77 23 L23 77
      M35 15 L65 85
      M65 15 L35 85
      M15 35 L85 65
      M85 35 L15 65
    "/>
  `,

  /* 10 — wireframe cube */
  `
    <polygon points="50,10 82,29 82,67 50,86 18,67 18,29"/>
    <polygon points="50,24 70,36 70,60 50,72 30,60 30,36"/>
    <path d="
      M50 10 L50 24
      M82 29 L70 36
      M82 67 L70 60
      M50 86 L50 72
      M18 67 L30 60
      M18 29 L30 36
      M30 36 L70 60
      M70 36 L30 60
    "/>
  `,

  /* 11 — spiral / orbital */
  `
    <circle cx="50" cy="50" r="37"/>
    <path d="
      M50 50
      C50 39 61 37 66 43
      C75 54 65 68 51 68
      C32 68 24 47 34 33
      C47 15 76 22 82 45
      C89 72 63 91 38 83
    "/>
    <circle cx="50" cy="50" r="4"/>
  `,

  /* 12 — nested diamonds */
  `
    <polygon points="50,9 91,50 50,91 9,50"/>
    <polygon points="50,20 80,50 50,80 20,50"/>
    <polygon points="50,31 69,50 50,69 31,50"/>
    <path d="
      M50 9 V91
      M9 50 H91
      M21 21 L79 79
      M79 21 L21 79
    "/>
  `,

  /* 13 — seed circles */
  `
    <circle cx="50" cy="50" r="34"/>
    <circle cx="50" cy="36" r="14"/>
    <circle cx="62" cy="43" r="14"/>
    <circle cx="62" cy="57" r="14"/>
    <circle cx="50" cy="64" r="14"/>
    <circle cx="38" cy="57" r="14"/>
    <circle cx="38" cy="43" r="14"/>
  `,

  /* 15 — orbital ellipse lattice */
  `
    <circle cx="50" cy="50" r="37"/>
    <ellipse cx="50" cy="50" rx="37" ry="15"/>
    <ellipse cx="50" cy="50" rx="37" ry="15"
      transform="rotate(60 50 50)"/>
    <ellipse cx="50" cy="50" rx="37" ry="15"
      transform="rotate(120 50 50)"/>
    <circle cx="50" cy="50" r="5"/>
  `,

  /* 16 — geometric web */
  `
    <circle cx="50" cy="50" r="39"/>
    <polygon points="50,11 84,30 84,70 50,89 16,70 16,30"/>
    <polygon points="50,11 84,70 16,70"/>
    <polygon points="50,89 16,30 84,30"/>
    <path d="
      M16 30 L84 70
      M84 30 L16 70
      M50 11 L50 89
    "/>
  `
];


/*
 * Deterministic hash.
 * The same article always receives the same visual.
 */
function geometryHash(value) {
  const text = String(value ?? "");

  let hash = 2166136261;

  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);

    hash = Math.imul(
      hash,
      16777619
    );
  }

  return hash >>> 0;
}


/*
 * Small deterministic PRNG.
 */
function geometryRandom(seed) {

  let value = seed >>> 0;

  return () => {

    value += 0x6D2B79F5;

    let result = value;

    result = Math.imul(
      result ^ (result >>> 15),
      result | 1
    );

    result ^= result +
      Math.imul(
        result ^ (result >>> 7),
        result | 61
      );

    return (
      (
        result ^ (result >>> 14)
      ) >>> 0
    ) / 4294967296;
  };
}


/* ==========================================================================
   Viewport-triggered shimmer
   ========================================================================== */

let geometryShimmerObserver = null;


function observeGeometryShimmer(element) {

  /*
   * Respect reduced-motion preferences.
   */
  if (
    window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches
  ) {
    return;
  }


  if (!geometryShimmerObserver) {

    geometryShimmerObserver =
      new IntersectionObserver(
        (entries, observer) => {

          for (const entry of entries) {

            if (!entry.isIntersecting) {
              continue;
            }

            entry.target.classList.add(
              "is-shimmering"
            );

            /*
             * Shimmer once per appearance/page load,
             * rather than constantly flashing while scrolling.
             */
            observer.unobserve(
              entry.target
            );
          }
        },

        {
          /*
           * Shrinks the active viewport from the bottom.
           *
           * The element triggers when it rises to roughly
           * 48% of viewport height — just above center.
           */
          root: null,
          rootMargin: "0px 0px -52% 0px",
          threshold: 0.01
        }
      );
  }


  geometryShimmerObserver.observe(
    element
  );
}


/* ==========================================================================
   Build generated fallback
   ========================================================================== */

function buildGeometryFallback(
  fallback,
  article
) {

  /*
   * Do not build the same fallback twice.
   */
  if (fallback.dataset.geometryReady) {
    return;
  }

  fallback.dataset.geometryReady = "true";


  const seed = geometryHash(
    article.id ??
    article.slug ??
    article.title
  );

  const random = geometryRandom(
    seed
  );


  /* Select one of eight background families */

  const backgroundIndex =
    Math.floor(random() * 8);


  fallback.classList.add(
    "geometry-thumb",
    `geometry-bg-${backgroundIndex}`
  );


  /* Select two different geometric patterns */

  const firstIndex =
    Math.floor(
      random() *
      GEOMETRY_PATTERNS.length
    );

  let secondIndex =
    Math.floor(
      random() *
      GEOMETRY_PATTERNS.length
    );

  if (secondIndex === firstIndex) {
    secondIndex =
      (secondIndex + 5) %
      GEOMETRY_PATTERNS.length;
  }


  const rotationA =
    Math.round(
      random() * 60 - 30
    );

  const rotationB =
    Math.round(
      random() * 90 - 45
    );

  const scaleA =
    (
      0.82 +
      random() * 0.22
    ).toFixed(3);

  const scaleB =
    (
      0.68 +
      random() * 0.24
    ).toFixed(3);


  const svg =
    document.createElementNS(
      "http://www.w3.org/2000/svg",
      "svg"
    );


  svg.setAttribute(
    "viewBox",
    "0 0 100 100"
  );

  svg.setAttribute(
    "aria-hidden",
    "true"
  );

  svg.classList.add(
    "news-feed-geometry"
  );


  /*
   * SVG contents are selected only from the hard-coded
   * GEOMETRY_PATTERNS array above.
   */
  svg.innerHTML = `
    <g
      class="geometry-layer geometry-layer-primary"
      transform="
        translate(50 50)
        rotate(${rotationA})
        scale(${scaleA})
        translate(-50 -50)
      ">
      ${GEOMETRY_PATTERNS[firstIndex]}
    </g>

    <g
      class="geometry-layer geometry-layer-secondary"
      transform="
        translate(50 50)
        rotate(${rotationB})
        scale(${scaleB})
        translate(-50 -50)
      ">
      ${GEOMETRY_PATTERNS[secondIndex]}
    </g>
  `;


  fallback.replaceChildren(
    svg
  );


  observeGeometryShimmer(
    fallback
  );
}

/* ==========================================================================
   Component
   ========================================================================== */

class WtkNewsFeed extends HTMLElement {
  static get observedAttributes() {
    return [
      "tags",
      "tag-mode",
      "limit",
      "sort",
						"min-priority"
    ];
  }


  constructor() {
    super();

    newsFeedInstanceCount += 1;

    this.instanceId = newsFeedInstanceCount;
    this.articles = [];
    this.loaded = false;
    this.mounted = false;

    this.listElement = null;
    this.statusElement = null;
    this.sortFieldset = null;
  }


  connectedCallback() {
    if (!this.mounted) {
      this.mount();
      this.mounted = true;
    }

    this.load();
  }


  attributeChangedCallback(name, oldValue, newValue) {
    if (oldValue === newValue || !this.loaded) {
      return;
    }

    if (name === "sort") {
      this.syncSortControls();
    }

    this.renderArticles();
  }

		enableDragScroll(element) {

				let pointerDown = false;
				let pointerId = null;

				let startY = 0;
				let startScrollTop = 0;

				let moved = false;
				let suppressClick = false;

				const DRAG_THRESHOLD = 4;


				element.addEventListener(
						"pointerdown",
						(event) => {

								/*
									* Touch already has excellent native swipe scrolling.
									* This code is specifically adding desktop mouse dragging.
									*/
								if (
										event.pointerType !== "mouse" ||
										event.button !== 0
								) {
										return;
								}

								pointerDown = true;
								pointerId = event.pointerId;

								startY = event.clientY;
								startScrollTop = element.scrollTop;

								moved = false;

						}
				);


				element.addEventListener(
						"pointermove",
						(event) => {

								if (
										!pointerDown ||
										event.pointerId !== pointerId
								) {
										return;
								}

								const distance =
										event.clientY - startY;


								/*
									* Don't treat a tiny mouse movement during
									* a normal link click as a drag.
									*/
								if (
										!moved &&
										Math.abs(distance) <
												DRAG_THRESHOLD
								) {
										return;
								}


								if (!moved) {

										moved = true;

										element.classList.add(
												"is-dragging"
										);

										/*
											* Capture only after the mouse has moved
											* far enough to qualify as a real drag.
											*
											* Normal clicks therefore remain native
											* anchor clicks.
											*/
										if (
												!element.hasPointerCapture(
														event.pointerId
												)
										) {
												element.setPointerCapture(
														event.pointerId
												);
										}
								}


								/*
									* Stop selection/native dragging once this
									* has become a real scrolling gesture.
									*/
								event.preventDefault();


								element.scrollTop =
										startScrollTop - distance;
						}
				);


				const endDrag = (event) => {

						if (!pointerDown) {
								return;
						}

						/*
							* If significant movement occurred, the click
							* generated immediately after pointerup should
							* not follow an article link.
							*/
						suppressClick = moved;

						pointerDown = false;
						moved = false;


						element.classList.remove(
								"is-dragging"
						);


						if (
								pointerId !== null &&
								element.hasPointerCapture(pointerId)
						) {
								element.releasePointerCapture(
										pointerId
								);
						}

						pointerId = null;
				};


				element.addEventListener(
						"pointerup",
						endDrag
				);


				element.addEventListener(
						"pointercancel",
						endDrag
				);


				/*
					* Firefox and other browsers can otherwise
					* initiate normal HTML image/link dragging.
					*/
				element.addEventListener(
						"dragstart",
						(event) => {
								event.preventDefault();
						}
				);


				/*
					* Preserve normal clicks, but cancel the click
					* generated at the end of a real drag.
					*/
				element.addEventListener(
						"click",
						(event) => {

								if (!suppressClick) {
										return;
								}

								event.preventDefault();
								event.stopPropagation();

								suppressClick = false;
						},
						true
				);
		}

  /* ------------------------------------------------------------------------
     Configuration
     ------------------------------------------------------------------------ */

  get sourceUrl() {
    return this.getAttribute("src") || "/data/article-index.jsonl";
  }


  get selectedTags() {
    const value = this.getAttribute("tags") || "";

    return value
      .split(",")
      .map((tag) => tag.trim().toLowerCase())
      .filter(Boolean);
  }

		get selectedIds() {
				const value =
						this.getAttribute("ids") || "";

				return value
						.split(",")
						.map((id) => id.trim())
						.filter(Boolean);
		}

  get tagMode() {
    return this.getAttribute("tag-mode") === "all"
      ? "all"
      : "any";
  }


  get limit() {
    const value = Number.parseInt(
      this.getAttribute("limit") || "10",
      10
    );

    return Number.isFinite(value) && value > 0
      ? value
      : 10;
  }


  get sortMode() {
    const value = this.getAttribute("sort") || "newest";

    if (["newest", "oldest", "posted", "priority"].includes(value)) {
      return value;
    }

    return "newest";
  }

		get sortOptions() {
				const allowed = new Set([
						"newest",
						"oldest",
						"posted",
						"priority"
				]);

				const requested =
						(
								this.getAttribute("sort-options")
								|| "newest,oldest,posted,priority"
						)
								.split(",")
								.map((value) => value.trim())
								.filter(
										(value) =>
												allowed.has(value)
								);

				return requested.length
						? requested
						: [
										"newest",
										"oldest",
										"posted",
										"priority"
								];
		}

  /* ------------------------------------------------------------------------
     Initial DOM
     ------------------------------------------------------------------------ */

		mount() {
				const shell = makeElement(
						"section",
						"news-feed"
				);

				shell.setAttribute(
						"aria-label",
						this.getAttribute("aria-label") ||
								"News articles"
				);


				/* Toolbar */

				const toolbar = makeElement(
						"div",
						"news-feed-toolbar"
				);


				this.statusElement = makeElement(
						"div",
						"news-feed-count"
				);

				this.statusElement.setAttribute(
						"aria-live",
						"polite"
				);

				this.statusElement.textContent =
						"Loading articles…";
						
				if (
						this.hasAttribute("hide-count")
				) {
						this.statusElement.hidden = true;
				}

				if (
						this.hasAttribute("hide-sort") &&
						this.hasAttribute("hide-count")
				) {
						toolbar.hidden = true;
				}				

				toolbar.append(
						this.statusElement
				);


				if (!this.hasAttribute("hide-sort")) {

						this.sortFieldset =
								this.createSortControls();

						toolbar.append(
								this.sortFieldset
						);
				}


				/* Article list */

				this.listElement = makeElement(
						"div",
						"news-feed-list"
				);

				/*
					* Desktop drag-scrolling is only needed for
					* the independently scrolling homepage feeds.
					*
					* Related Articles, Latest News, category pages,
					* etc. should retain completely normal link behavior.
					*/
				if (
						this.classList.contains(
								"home-news-feed"
						)
				) {
						this.enableDragScroll(
								this.listElement
						);
				}


				shell.append(
						toolbar,
						this.listElement
				);

				this.replaceChildren(
						shell
				);
		}


  createSortControls() {
    const fieldset = makeElement(
      "fieldset",
      "news-feed-sort"
    );

    const legend = makeElement(
      "legend",
      "visually-hidden"
    );

    legend.textContent = "Sort news articles";

    fieldset.append(legend);

				const optionLabels = new Map([
						["newest", "Newest"],
						["oldest", "Oldest"],
						["posted", "Date Posted"],
						["priority", "Priority"]
				]);

				const options =
						this.sortOptions.map(
								(value) => [
										value,
										optionLabels.get(value)
								]
						);

    const groupName =
      `wtk-news-feed-sort-${this.instanceId}`;

    for (const [value, labelText] of options) {
      const label = makeElement(
        "label",
        "news-feed-sort-option"
      );

      const input = document.createElement("input");

      input.type = "radio";
      input.name = groupName;
      input.value = value;
      input.checked = this.sortMode === value;

      const text = document.createElement("span");

      text.textContent = labelText;

      label.append(
        input,
        text
      );

      fieldset.append(label);
    }

    fieldset.addEventListener("change", (event) => {
      const input = event.target;

      if (
        input instanceof HTMLInputElement &&
        input.type === "radio"
      ) {
        this.setAttribute("sort", input.value);
      }
    });

    return fieldset;
  }


  syncSortControls() {
    if (!this.sortFieldset) {
      return;
    }

    const radios =
      this.sortFieldset.querySelectorAll(
        'input[type="radio"]'
      );

    for (const radio of radios) {
      radio.checked =
        radio.value === this.sortMode;
    }
  }


  /* ------------------------------------------------------------------------
     Data
     ------------------------------------------------------------------------ */

  async load() {
    try {
      this.articles = await loadJsonl(
        this.sourceUrl
      );

      this.loaded = true;

      this.renderArticles();

    } catch (error) {
      console.error(
        "[wtk-news-feed]",
        error
      );

      this.statusElement.textContent =
        "Unable to load news.";

      this.listElement.replaceChildren();

      const message = makeElement(
        "p",
        "news-feed-error"
      );

      message.textContent =
        "The news feed could not be loaded.";

      this.listElement.append(message);
    }
  }


  /* ------------------------------------------------------------------------
     Filtering and sorting
     ------------------------------------------------------------------------ */

		get minPriority() {
				const value = Number(
						this.getAttribute("min-priority")
				);

				return Number.isFinite(value)
						? value
						: null;
		}

  getFilteredArticles() {
    const wantedTags = this.selectedTags;

    let results = this.articles.slice();
				if (this.minPriority !== null) {
						results = results.filter(
								(article) =>
										Number(article.priority || 0) >= this.minPriority
						);
				}
				
				const wantedIds =
						this.selectedIds;

				if (wantedIds.length) {

						const articlesById =
								new Map(
										results.map(
												(article) => [
														String(article.id),
														article
												]
										)
								);

						/*
							* Explicit ID selections preserve the
							* supplied order. This is important for
							* Related Articles, where order represents
							* closeness/relevance.
							*/
						return wantedIds
								.map(
										(id) =>
												articlesById.get(id)
								)
								.filter(Boolean);
				}				

    if (wantedTags.length) {
      results = results.filter((article) => {
        const articleTags = new Set(
          (article.tags || []).map(
            (tag) => String(tag).toLowerCase()
          )
        );

        if (this.tagMode === "all") {
          return wantedTags.every(
            (tag) => articleTags.has(tag)
          );
        }

        return wantedTags.some(
          (tag) => articleTags.has(tag)
        );
      });
    }

				if (this.sortMode === "priority") {
						results.sort((a, b) => {
								const priorityDifference =
										Number(b.priority || 0) - Number(a.priority || 0);

								if (priorityDifference !== 0) {
										return priorityDifference;
								}

								const dateComparison =
										String(b.date || "")
												.localeCompare(String(a.date || ""));

								if (dateComparison !== 0) {
										return dateComparison;
								}

								return Number(b.id) - Number(a.id);
						});

				} else if (this.sortMode === "oldest") {

						results.sort((a, b) => {
								const dateComparison =
										String(a.date || "")
												.localeCompare(String(b.date || ""));

								if (dateComparison !== 0) {
										return dateComparison;
								}

								return Number(a.id) - Number(b.id);
						});

				} else if (this.sortMode === "posted") {

						results.sort((a, b) => {

								const postedComparison =
										String(b.posted_date || "")
												.localeCompare(
														String(a.posted_date || "")
												);

								if (postedComparison !== 0) {
										return postedComparison;
								}

								return Number(b.id) - Number(a.id);
						});

				} else {

						results.sort((a, b) => {
								const dateComparison =
										String(b.date || "")
												.localeCompare(String(a.date || ""));

								if (dateComparison !== 0) {
										return dateComparison;
								}

								return Number(b.id) - Number(a.id);
						});

				}

    return results;
  }


  /* ------------------------------------------------------------------------
     Rendering
     ------------------------------------------------------------------------ */

  renderArticles() {
    const filtered = this.getFilteredArticles();

    const visible = filtered.slice(
      0,
      this.limit
    );

    this.listElement.replaceChildren();


    if (!filtered.length) {
      this.statusElement.textContent =
        "0 articles";

      const empty = makeElement(
        "p",
        "news-feed-empty"
      );

      empty.textContent =
        "No articles match this selection.";

      this.listElement.append(empty);

      return;
    }


    this.statusElement.textContent =
      `${filtered.length.toLocaleString()} ${
        filtered.length === 1
          ? "article"
          : "articles"
      }`;


    const fragment =
      document.createDocumentFragment();

    for (const article of visible) {
      fragment.append(
        this.createArticleRow(article)
      );
    }

    this.listElement.append(fragment);
  }


  createArticleRow(article) {
    const row = makeElement(
      "article",
      "news-feed-item"
    );

    const articleUrl =
      `/news/${encodeURIComponent(article.slug)}`;


				/* Thumbnail */

				const thumbLink = makeElement(
						"a",
						"news-feed-thumb"
				);

				thumbLink.href = articleUrl;

				/*
					* Headline remains the primary keyboard link.
					*/
				thumbLink.tabIndex = -1;

				thumbLink.setAttribute(
						"aria-hidden",
						"true"
				);


				/* Empty fallback canvas */

				const fallback = makeElement(
						"span",
						"news-feed-thumb-fallback"
				);

				fallback.setAttribute(
						"aria-hidden",
						"true"
				);

				thumbLink.append(
						fallback
				);


				/*
					* Build the generated artwork only if the real
					* article thumbnail cannot be loaded.
					*/
				const showGeneratedFallback = () => {

						buildGeometryFallback(
								fallback,
								article
						);
				};


				if (article.id) {

						const image =
								document.createElement("img");


						image.src =
								`/assets/images/article-thumbs/` +
								`${article.id}-thumb.jpg`;

						image.alt = "";
						image.loading = "lazy";
						image.decoding = "async";

						image.draggable = false;


						image.addEventListener(
								"error",
								() => {

										image.remove();

										showGeneratedFallback();
								},
								{
										once: true
								}
						);


						thumbLink.append(
								image
						);

				} else {

						/*
							* Extremely defensive fallback if an article
							* somehow lacks an ID.
							*/
						showGeneratedFallback();
				}

				const publisher =
						humanizePublisher(article.publisher);

				fallback.textContent =
						publisher.charAt(0).toUpperCase() || "W";

				fallback.setAttribute(
						"aria-hidden",
						"true"
				);

				thumbLink.append(fallback);


				/* Thumbnail filename is derived directly from article ID */

				if (article.id) {

						const image =
								document.createElement("img");

						image.src =
								`/assets/images/article-thumbs/` +
								`${article.id}-thumb.jpg`;

						image.alt = "";
						image.loading = "lazy";
						image.decoding = "async";

						/*
							* If the article has no thumbnail file,
							* simply remove the broken image and reveal
							* the fallback underneath.
							*/
						image.addEventListener(
								"error",
								() => image.remove(),
								{ once: true }
						);

						thumbLink.append(image);
				}

    /* Content */

    const content = makeElement(
      "div",
      "news-feed-content"
    );


    const meta = makeElement(
      "div",
      "news-feed-meta"
    );

    const publisherElement = makeElement(
      "span",
      "news-feed-publisher"
    );

    publisherElement.textContent = publisher;

    meta.append(publisherElement);


    if (article.date) {
      const time =
        document.createElement("time");

      time.dateTime = article.date;
      time.textContent =
        formatDate(article.date);

      meta.append(time);
    }


    /* Title */

    const heading = makeElement(
      "h3",
      "news-feed-title"
    );

    const titleLink =
      document.createElement("a");

    titleLink.href = articleUrl;
    titleLink.textContent =
      article.title || "Untitled article";

    heading.append(titleLink);


    content.append(
      meta,
      heading
    );


    /* Tags */

    if (
      Array.isArray(article.tags) &&
      article.tags.length
    ) {
      const tags = makeElement(
        "div",
        "news-feed-tags"
      );

      tags.setAttribute(
        "aria-label",
        "Article categories"
      );

      for (const tag of article.tags) {
        const link =
          document.createElement("a");

        link.className = "news-feed-tag";

        link.href =
          `/news/category/${encodeURIComponent(tag)}`;

        link.textContent =
          humanizeTag(tag);

        tags.append(link);
      }

      content.append(tags);
    }


    row.append(
      thumbLink,
      content
    );

    return row;
  }
}


if (!customElements.get("wtk-news-feed")) {
  customElements.define(
    "wtk-news-feed",
    WtkNewsFeed
  );
}
