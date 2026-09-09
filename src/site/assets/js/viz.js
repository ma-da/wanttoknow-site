/* ========================================================================== 
   WantToKnow.info Archive Visualization

   Requires D3 v7 and the following aggregate data files:
     - archive_stats.json
     - news-category-map.json

   The widget is intentionally instance-scoped. Multiple [data-archive-viz]
   sections can exist on a page without sharing state.
   ========================================================================== */

(() => {
  "use strict";

  const d3 = window.d3;

  if (!d3) {
    console.error("Archive visualization requires D3 v7.");
    return;
  }

  const NUMBER = new Intl.NumberFormat("en-US");
  const PERCENT = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });

  const VIEW_COPY = {
    publishers: {
      kicker: "Sources",
      title: "Articles by publisher",
      description: "Publishers most frequently represented in the archive.",
      note: "Top 100 publishing groups are shown; the remainder are combined.",
    },
    categories: {
      kicker: "Subjects",
      title: "Articles by category",
      description: "A proportional map of the archive's editorial categories.",
      note: "Articles may appear in more than one category, so category totals overlap.",
    },
    eras: {
      kicker: "Timeline",
      title: "The archive across eras",
      description: "The share of dated articles published in four broad periods.",
      note: "Percentages are calculated from archive_stats.json year totals.",
    },
    topics: {
      kicker: "Knowledge map",
      title: "Topics and the categories they encompass",
      description: "The site's top-level topics, with every mapped category linked beneath them.",
      note: "Categories with secondary topic relationships appear in each relevant topic.",
    },
  };

  const TOPICS = [
    { slug: "inspiring", label: "Inspiring" },
    { slug: "health", label: "Health + Medicine" },
    { slug: "money", label: "Money + Power" },
    { slug: "media", label: "Media" },
    { slug: "tech", label: "Privacy + Technology" },
    { slug: "government", label: "Government + Intelligence" },
    { slug: "war", label: "War + Security" },
    { slug: "mind-control", label: "Mind Control" },
    { slug: "abuse-and-trafficking", label: "Abuse + Trafficking" },
    { slug: "science-and-environment", label: "Environment + Science" },
    { slug: "consciousness", label: "Reality + Consciousness" },
    { slug: "ufo", label: "UFO/UAP Disclosure" },
    { slug: "deep-history", label: "Deep History" },
  ];

  const ERA_DEFINITIONS = [
    { key: "pre-2000", label: "Earlier archive", range: "Before 2000", min: -Infinity, max: 1999 },
    { key: "2000s", label: "2000s", range: "2000–2009", min: 2000, max: 2009 },
    { key: "2010s", label: "2010s", range: "2010–2019", min: 2010, max: 2019 },
    { key: "2020s", label: "2020s", range: "2020–present", min: 2020, max: Infinity },
  ];

/* --------------------------------------------------------------------------
   Visualization color system

   Brand purple remains the visual anchor. Supporting colors lean toward
   earth, water, and mineral tones: aqua, teal, sage, clay, ochre, rust,
   moss, sandstone, muted blue, and plum.
   -------------------------------------------------------------------------- */

const VIZ_PALETTE = [
  "#7658f6", // brand purple
  "#2f9da6", // aqua
  "#c76545", // terracotta
  "#6f8f72", // sage
  "#d09a43", // ochre
  "#377f82", // deep aqua / teal
  "#a95848", // clay
  "#7d8448", // olive
  "#557f9d", // dusty blue
  "#866480", // muted plum
  "#b7845c", // sandstone
  "#9b643f", // warm earth
  "#4f7564", // forest sage
  "#c17d5b", // soft rust
  "#6f68a6", // mineral violet
  "#8a7655", // taupe
];



/*
 * Era colors should remain especially distinct because there are
 * only four segments and users need to distinguish them immediately.
 */
const ERA_COLORS = [
  "#7658f6", // brand purple
  "#2f9da6", // aqua
  "#c76545", // terracotta
  "#6f8f72", // sage
];

  document.querySelectorAll("[data-archive-viz]").forEach(initArchiveViz);

		function initArchiveViz(root) {
				const stage = root.querySelector("[data-viz-stage]");

				const controls = [
						...root.querySelectorAll(
								".archive-viz__control[data-viz-view]"
						)
				];

				if (!stage) return;

				const initialView =
						root.dataset.vizView &&
						VIEW_COPY[root.dataset.vizView]
								? root.dataset.vizView
								: controls[0]?.dataset.vizView || "publishers";

				const state = {
						root,
						stage,
						controls,
						stats: null,
						categoryMap: null,
						view: initialView,
						resizeFrame: null,
						tooltip: createTooltip(root),

						config: {
								statsUrl:
										root.dataset.statsUrl ||
										"/data/archive_stats.json",

								categoryMapUrl:
										root.dataset.categoryMapUrl ||
										"/data/news-category-map.json",

								topicUrlTemplate:
										root.dataset.topicUrlTemplate ||
										"/topics/{slug}/",

								categoryUrlTemplate:
										root.dataset.categoryUrlTemplate ||
										"/news/category/{slug}/",
						},
				};

				/* Sync button appearance with the configured initial view. */
				updateControls(state);

				/* Change views when a control is clicked. */
				controls.forEach((button) => {
						button.addEventListener("click", () => {
								setView(
										state,
										button.dataset.vizView
								);
						});
				});

				const resizeObserver = new ResizeObserver(() => {
						if (!state.stats || state.view === "topics") {
								return;
						}

						cancelAnimationFrame(state.resizeFrame);

						state.resizeFrame = requestAnimationFrame(() => {
								render(state);
						});
				});

				resizeObserver.observe(stage);

				loadData(state);
		}

  async function loadData(state) {
    try {
      const [stats, categoryMap] = await Promise.all([
        fetchJson(state.config.statsUrl),
        fetchJson(state.config.categoryMapUrl),
      ]);

      validateStats(stats);
      validateCategoryMap(categoryMap);

      state.stats = stats;
      state.categoryMap = categoryMap;

      fillSummary(state);
      state.stage.setAttribute("aria-busy", "false");
      render(state);
    } catch (error) {
      console.error("Archive visualization failed to load:", error);
      state.stage.setAttribute("aria-busy", "false");
      state.stage.innerHTML = `
        <div class="archive-viz__error" role="alert">
          <strong>Archive visualization unavailable.</strong>
          <span>${escapeHtml(error.message)}</span>
        </div>
      `;
    }
  }

  async function fetchJson(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      throw new Error(`Could not load ${url} (${response.status}).`);
    }
    return response.json();
  }

  function validateStats(stats) {
    const required = [
      "article_count",
      "date_range",
      "category_count",
      "publisher_group_count",
      "categories",
      "publishing_groups",
      "articles_by_year",
    ];

    required.forEach((key) => {
      if (!(key in stats)) throw new Error(`archive_stats.json is missing “${key}”.`);
    });
  }

  function validateCategoryMap(categoryMap) {
    if (!categoryMap || Array.isArray(categoryMap) || typeof categoryMap !== "object") {
      throw new Error("news-category-map.json must contain a JSON object.");
    }
  }

  function fillSummary(state) {
    const { stats, root } = state;
    const years = Object.keys(stats.articles_by_year).map(Number).filter(Number.isFinite);
    const yearSpan = years.length ? `${Math.min(...years)}–${Math.max(...years)}` : "—";

    setText(root, '[data-viz-stat="articles"]', NUMBER.format(stats.article_count));
    setText(root, '[data-viz-stat="categories"]', NUMBER.format(stats.category_count));
    setText(root, '[data-viz-stat="publishers"]', NUMBER.format(stats.publisher_group_count));
    setText(root, '[data-viz-stat="years"]', yearSpan);
  }

		function setView(state, view) {
				if (!VIEW_COPY[view]) {
						return;
				}

				if (view === state.view) {
						return;
				}

				state.view = view;

				updateControls(state);
				updateViewCopy(state);
				render(state);
		}

  function render(state) {
    if (!state.stats || !state.categoryMap) return;

    updateViewCopy(state);
    hideTooltip(state.tooltip);
    state.stage.replaceChildren();

    switch (state.view) {
      case "categories":
        renderCategories(state);
        break;
      case "eras":
        renderEras(state);
        break;
      case "topics":
        renderTopics(state);
        break;
      case "publishers":
      default:
        renderPublishers(state);
        break;
    }
  }

  function updateViewCopy(state) {
    const copy = VIEW_COPY[state.view];
    setText(state.root, "[data-viz-kicker]", copy.kicker);
    setText(state.root, "[data-viz-title]", copy.title);
    setText(state.root, "[data-viz-description]", copy.description);
    setText(state.root, "[data-viz-note]", copy.note);
  }
		
		function contrastText(background) {
				const rgb = d3.rgb(background);

				const luminance =
						(0.299 * rgb.r +
								0.587 * rgb.g +
								0.114 * rgb.b) /
						255;

				return luminance > 0.58 ? "#17141f" : "#ffffff";
		}

function updateControls(state) {
  state.controls.forEach((button) => {
    const active =
      button.dataset.vizView === state.view;

    button.classList.toggle(
      "is-active",
      active
    );

    button.setAttribute(
      "aria-pressed",
      String(active)
    );
  });
}		

  /* ------------------------------------------------------------------------
     View 1: Publishers
     ------------------------------------------------------------------------ */

  function renderPublishers(state) {
    const all = Object.entries(state.stats.publishing_groups)
      .map(([slug, item]) => ({ slug, name: item.name || slug, count: Number(item.count) || 0 }))
      .sort((a, b) => d3.descending(a.count, b.count));

    const top = all.slice(0, 100);
    const otherCount = d3.sum(all.slice(100), (d) => d.count);
    if (otherCount > 0) top.push({ slug: "other", name: "All other publishers", count: otherCount, other: true });

    const width = Math.max(320, Math.floor(state.stage.clientWidth - 8));
    const mobile = width < 620;
    const margin = {
      top: 10,
      right: mobile ? 54 : 72,
      bottom: 30,
      left: mobile ? 122 : 190,
    };
    const rowHeight = mobile ? 27 : 29;
    const height = margin.top + margin.bottom + top.length * rowHeight;
    const innerWidth = width - margin.left - margin.right;

    const svg = d3
      .select(state.stage)
      .append("svg")
      .attr("class", "archive-viz__publisher-chart")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img")
      .attr("aria-label", "Horizontal bar chart showing the publishers most represented in the archive.");

    const x = d3.scaleLinear().domain([0, d3.max(top, (d) => d.count)]).nice().range([0, innerWidth]);
    const y = d3.scaleBand().domain(top.map((d) => d.name)).range([margin.top, height - margin.bottom]).padding(0.23);

    svg
      .append("g")
      .attr("class", "viz-grid")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisBottom(x).ticks(mobile ? 3 : 5).tickSize(-(height - margin.top - margin.bottom)).tickFormat(""));

    const rows = svg
      .append("g")
      .selectAll("g")
      .data(top)
      .join("g")
      .attr("class", "viz-publisher-row")
      .attr("tabindex", 0)
      .attr("transform", (d) => `translate(0,${y(d.name)})`)
      .on("pointerenter focus", (event, d) => {
        showTooltip(state.tooltip, `<strong>${escapeHtml(d.name)}</strong>${NUMBER.format(d.count)} articles`, event);
      })
      .on("pointermove", (event) => moveTooltip(state.tooltip, event))
      .on("pointerleave blur", () => hideTooltip(state.tooltip));

    rows
      .append("text")
      .attr("class", "viz-publisher-label")
      .attr("x", margin.left - 10)
      .attr("y", y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .attr("text-anchor", "end")
      .text((d) => truncate(d.name, mobile ? 20 : 30));

    rows
      .append("rect")
      .attr("class", (d) => `viz-publisher-bar${d.other ? " is-other" : ""}`)
      .attr("x", margin.left)
      .attr("y", 0)
      .attr("width", (d) => x(d.count))
      .attr("height", y.bandwidth());

    rows
      .append("text")
      .attr("class", "viz-publisher-value")
      .attr("x", (d) => margin.left + x(d.count) + 7)
      .attr("y", y.bandwidth() / 2)
      .attr("dy", "0.35em")
      .text((d) => NUMBER.format(d.count));

    svg
      .append("g")
      .attr("class", "viz-axis")
      .attr("transform", `translate(${margin.left},${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(mobile ? 3 : 5).tickSizeOuter(0));
  }

  /* ------------------------------------------------------------------------
     View 2: Categories
     ------------------------------------------------------------------------ */

  function renderCategories(state) {
    const data = Object.entries(state.stats.categories)
      .map(([slug, count]) => ({
        slug,
        label: state.categoryMap[slug]?.label || humanizeSlug(slug),
        count: Number(count) || 0,
      }))
      .sort((a, b) => d3.descending(a.count, b.count));

    const width = Math.max(320, Math.floor(state.stage.clientWidth - 8));
    const height = Math.max(520, Math.min(760, Math.round(width * 0.66)));

    const hierarchy = d3
      .hierarchy({ children: data })
      .sum((d) => d.count || 0)
      .sort((a, b) => b.value - a.value);

    d3.treemap().size([width, height]).paddingInner(2).round(true)(hierarchy);

				const color = d3
						.scaleOrdinal()
						.domain(data.map((d) => d.slug))
						.range(VIZ_PALETTE);

    const svg = d3
      .select(state.stage)
      .append("svg")
      .attr("class", "archive-viz__treemap")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("role", "img")
      .attr("aria-label", "Treemap showing archive categories sized by article count.");

    const nodes = svg
      .selectAll("a")
      .data(hierarchy.leaves())
      .join("a")
      .attr("class", "viz-category-node")
      .attr("href", (d) => buildUrl(state.config.categoryUrlTemplate, d.data.slug))
      .attr("aria-label", (d) => `${d.data.label}: ${NUMBER.format(d.data.count)} articles`)
      .attr("transform", (d) => `translate(${d.x0},${d.y0})`)
      .on("pointerenter focus", (event, d) => {
        showTooltip(
          state.tooltip,
          `<strong>${escapeHtml(d.data.label)}</strong>${NUMBER.format(d.data.count)} category assignments`,
          event,
        );
      })
      .on("pointermove", (event) => moveTooltip(state.tooltip, event))
      .on("pointerleave blur", () => hideTooltip(state.tooltip));

				nodes
						.append("rect")
						.attr("width", (d) => Math.max(0, d.x1 - d.x0))
						.attr("height", (d) => Math.max(0, d.y1 - d.y0))
						.attr("fill", (d) => color(d.data.slug));

    nodes.each(function (d) {
      const w = d.x1 - d.x0;
      const h = d.y1 - d.y0;
      if (w < 68 || h < 34) return;

      const group = d3.select(this);
      const label = truncate(d.data.label, Math.max(8, Math.floor(w / 7.5)));

						const tileColor = color(d.data.slug);
						const labelColor = contrastText(tileColor);

						group
								.append("text")
								.attr("class", "viz-category-label")
								.attr("x", 7)
								.attr("y", 15)
								.attr("fill", labelColor)
								.text(label);

						if (h >= 50 && w >= 78) {
								group
										.append("text")
										.attr("class", "viz-category-count")
										.attr("x", 7)
										.attr("y", 30)
										.attr("fill", labelColor)
										.attr("opacity", 0.78)
										.text(NUMBER.format(d.data.count));
						}
    });
  }

  /* ------------------------------------------------------------------------
     View 3: Eras
     ------------------------------------------------------------------------ */

  function renderEras(state) {
    const years = Object.entries(state.stats.articles_by_year)
      .map(([year, count]) => ({ year: Number(year), count: Number(count) || 0 }))
      .filter((d) => Number.isFinite(d.year))
      .sort((a, b) => d3.ascending(a.year, b.year));

    const total = d3.sum(years, (d) => d.count);
    const eraData = ERA_DEFINITIONS.map((era, index) => {
      const members = years.filter((d) => d.year >= era.min && d.year <= era.max);
      const count = d3.sum(members, (d) => d.count);
      return {
        ...era,
        index,
        count,
        percent: total ? (count / total) * 100 : 0,
        years: members,
      };
    });

    const layout = d3.select(state.stage).append("div").attr("class", "archive-viz__era-layout");
    const chartWrap = layout.append("div").attr("class", "archive-viz__era-chart");
    const size = 420;
    const radius = size / 2;

    const svg = chartWrap
      .append("svg")
      .attr("viewBox", `0 0 ${size} ${size}`)
      .attr("role", "img")
      .attr("aria-label", "Donut chart showing the percentage of archive articles from four eras.")
      .append("g")
      .attr("transform", `translate(${radius},${radius})`);

    const pie = d3.pie().sort(null).value((d) => d.count).padAngle(0.012);
    const arc = d3.arc().innerRadius(radius * 0.57).outerRadius(radius * 0.91).cornerRadius(4);

    svg
      .selectAll("path")
      .data(pie(eraData))
      .join("path")
      .attr("class", "viz-era-segment")
      .attr("d", arc)
      .attr("fill", (d) => ERA_COLORS[d.data.index])
      .attr("tabindex", 0)
      .attr("aria-label", (d) => `${d.data.range}: ${PERCENT.format(d.data.percent)} percent`)
      .on("pointerenter focus", (event, d) => {
        showTooltip(
          state.tooltip,
          `<strong>${escapeHtml(d.data.range)}</strong>${PERCENT.format(d.data.percent)}% · ${NUMBER.format(d.data.count)} articles`,
          event,
        );
      })
      .on("pointermove", (event) => moveTooltip(state.tooltip, event))
      .on("pointerleave blur", () => hideTooltip(state.tooltip));

    svg
      .append("text")
      .attr("class", "viz-era-center-value")
      .attr("y", -4)
      .text(NUMBER.format(total));

    svg
      .append("text")
      .attr("class", "viz-era-center-label")
      .attr("y", 18)
      .text("dated articles");

    const legend = layout.append("div").attr("class", "archive-viz__era-legend");
    const maxYearCount = d3.max(years, (d) => d.count) || 1;

    const items = legend
      .selectAll("div.archive-viz__era-item")
      .data(eraData)
      .join("div")
      .attr("class", "archive-viz__era-item");

    items
      .append("span")
      .attr("class", "archive-viz__era-swatch")
      .style("background", (d) => ERA_COLORS[d.index]);

    const copy = items.append("div");
    copy.append("span").attr("class", "archive-viz__era-name").text((d) => d.label);
    copy.append("span").attr("class", "archive-viz__era-range").text((d) => d.range);

    const value = items.append("div").attr("class", "archive-viz__era-value");
    value.append("strong").text((d) => `${PERCENT.format(d.percent)}%`);
    value.append("span").text((d) => `${NUMBER.format(d.count)} articles`);

    items
      .append("div")
      .attr("class", "archive-viz__era-years")
      .attr("aria-hidden", "true")
      .selectAll("span")
      .data((d) => d.years)
      .join("span")
      .attr("class", "archive-viz__era-year-bar")
      .style("height", (d) => `${Math.max(4, (d.count / maxYearCount) * 40)}px`)
      .style("background", (d, i, nodes) => ERA_COLORS[nodes[i].parentNode.parentNode.__data__.index]);
  }

  /* ------------------------------------------------------------------------
     View 4: Topics
     ------------------------------------------------------------------------ */

  function renderTopics(state) {
    const categoryCounts = state.stats.categories;
				const topicData = TOPICS.map((topic, index) => {
						const categories = Object.entries(state.categoryMap)
								.filter(([, item]) =>
										item.topic === topic.slug ||
										(item.secondary_topics || []).includes(topic.slug)
								)
								.map(([slug, item]) => ({
										slug,
										label: item.label || humanizeSlug(slug),
										count: Number(categoryCounts[slug]) || 0,
										primary: item.topic === topic.slug,
								}))
								.filter((d) => d.count > 0)
								.sort(
										(a, b) =>
												d3.descending(a.count, b.count) ||
												d3.ascending(a.label, b.label)
								);

						return {
								...topic,
								index,
								categories,
						};
				}).sort(
						(a, b) =>
								d3.descending(a.categories.length, b.categories.length) ||
								d3.ascending(a.label, b.label)
				);

    const map = d3.select(state.stage).append("div").attr("class", "archive-viz__topic-map");

    const cards = map
      .selectAll("article")
      .data(topicData)
      .join("article")
      .attr("class", "archive-viz__topic-card")
      .style("--topic-accent", (d) => VIZ_PALETTE[d.index]);

    const headings = cards.append("div").attr("class", "archive-viz__topic-heading");

    headings
      .append("a")
      .attr("class", "archive-viz__topic-link")
      .attr("href", (d) => buildUrl(state.config.topicUrlTemplate, d.slug))
      .text((d) => d.label);

    headings
      .append("span")
      .attr("class", "archive-viz__topic-count")
      .text((d) => `${d.categories.length} ${d.categories.length === 1 ? "category" : "categories"}`);

    cards
      .append("div")
      .attr("class", "archive-viz__category-links")
      .selectAll("a")
      .data((d) => d.categories.map((category) => ({ ...category, topicIndex: d.index })))
      .join("a")
      .attr("class", "archive-viz__category-link")
      .attr("href", (d) => buildUrl(state.config.categoryUrlTemplate, d.slug))
      .attr("title", (d) => `${d.label} — ${NUMBER.format(d.count)} articles${d.primary ? "" : " · secondary topic"}`)
      .html((d) => `${escapeHtml(d.label)} <span class="archive-viz__category-count">${NUMBER.format(d.count)}</span>`);

    const mapped = new Set();
    topicData.forEach((topic) => topic.categories.forEach((category) => mapped.add(category.slug)));
				const unmapped = Object.keys(categoryCounts)
						.filter(
								(slug) =>
										!mapped.has(slug)
										&& slug !== "general"
						);

    if (unmapped.length) {
      map
        .append("div")
        .attr("class", "archive-viz__topic-unmapped")
        .html(
          `<strong>Not assigned to a top-level topic:</strong> ${unmapped
            .map((slug) => `<a href="${escapeHtml(buildUrl(state.config.categoryUrlTemplate, slug))}">${escapeHtml(state.categoryMap[slug]?.label || humanizeSlug(slug))}</a>`)
            .join(", ")}`,
        );
    }
  }

  /* ------------------------------------------------------------------------
     Utilities
     ------------------------------------------------------------------------ */

  function createTooltip(root) {
    let tooltip = root.querySelector(".archive-viz__tooltip");
    if (tooltip) return tooltip;

    tooltip = document.createElement("div");
    tooltip.className = "archive-viz__tooltip";
    tooltip.setAttribute("role", "status");
    document.body.appendChild(tooltip);
    return tooltip;
  }

  function showTooltip(tooltip, html, event) {
    tooltip.innerHTML = html;
    tooltip.classList.add("is-visible");
    moveTooltip(tooltip, event);
  }

  function moveTooltip(tooltip, event) {
    if (!event || !("clientX" in event)) return;

    const gap = 14;
    const rect = tooltip.getBoundingClientRect();
    let left = event.clientX + gap;
    let top = event.clientY + gap;

    if (left + rect.width > window.innerWidth - 8) left = event.clientX - rect.width - gap;
    if (top + rect.height > window.innerHeight - 8) top = event.clientY - rect.height - gap;

    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
  }

  function hideTooltip(tooltip) {
    tooltip.classList.remove("is-visible");
  }

  function setText(root, selector, value) {
    const element = root.querySelector(selector);
    if (element) element.textContent = value;
  }

  function buildUrl(template, slug) {
    return template.replace("{slug}", encodeURIComponent(slug));
  }

  function humanizeSlug(slug) {
    return slug
      .replace(/[_-]+/g, " ")
      .replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function truncate(value, maxLength) {
    if (value.length <= maxLength) return value;
    return `${value.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
})();
