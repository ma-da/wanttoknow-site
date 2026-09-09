class WtkPathwaysMenu extends HTMLElement {
		constructor() {
				super();

				this.items = [];
				this.activeIndex = -1;
				this.controls = [];
				this.panel = null;

				/*
					* Horizontal topic-menu scrolling.
					*/
				this.controlsScroller = null;
				this.topScroller = null;
				this.topScrollerTrack = null;

				this.topScrollerResizeObserver = null;
				this.topScrollerSyncFrame = null;
		}

  connectedCallback() {
    if (this.dataset.initialized === "true") return;
    this.dataset.initialized = "true";
    this.load();
  }
		
		disconnectedCallback() {
				if (this.topScrollerResizeObserver) {
						this.topScrollerResizeObserver.disconnect();
						this.topScrollerResizeObserver = null;
				}

				if (this.topScrollerSyncFrame !== null) {
						cancelAnimationFrame(this.topScrollerSyncFrame);
						this.topScrollerSyncFrame = null;
				}
		}		

  async load() {
    const src = this.getAttribute("src") || "/data/elements/pathways-menu-clean.json";

    this.innerHTML = `
      <div class="pathways-menu__status" role="status">
        Loading topic menu…
      </div>
    `;

    try {
      const response = await fetch(src, {
        headers: { Accept: "application/json" }
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status} loading ${src}`);
      }

      const data = await response.json();

      if (!Array.isArray(data?.items) || !data.items.length) {
        throw new Error("Pathways menu JSON contains no items.");
      }

      this.items = data.items;
      this.renderShell(data.id || "pathways-menu");
    } catch (error) {
      console.error("Pathways menu failed to load:", error);
      this.innerHTML = `
        <p class="pathways-menu__status pathways-menu__status--error" role="alert">
          The topic menu could not be loaded.
        </p>
      `;
    }
  }

		renderShell(menuId) {
				this.replaceChildren();

				this.style.setProperty(
						"--pathways-menu-count",
						String(this.items.length)
				);


				/* ----------------------------------------------------------
							Main navigation
							---------------------------------------------------------- */

				const nav = document.createElement("nav");

				nav.className = "pathways-menu";

				nav.setAttribute(
						"aria-label",
						"Explore WantToKnow.info topics"
				);


				/* ----------------------------------------------------------
							Top scrollbar
							---------------------------------------------------------- */

				const topScroller =
						document.createElement("div");

				topScroller.className =
						"pathways-menu__top-scroll";

				/*
					* This scrollbar is a redundant visual control.
					* The actual topic buttons remain keyboard accessible.
					*/
				topScroller.setAttribute(
						"aria-hidden",
						"true"
				);

				topScroller.tabIndex = -1;


				const topScrollerTrack =
						document.createElement("div");

				topScrollerTrack.className =
						"pathways-menu__top-scroll-track";

				topScroller.append(topScrollerTrack);


				/* ----------------------------------------------------------
							Topic controls
							---------------------------------------------------------- */

				const controls =
						document.createElement("div");

				controls.className =
						"pathways-menu__controls";

				controls.setAttribute(
						"role",
						"group"
				);

				controls.setAttribute(
						"aria-label",
						"Topic menus"
				);


				const panelId =
						`${menuId}-panel`;


				this.controls = this.items.map(
						(item, index) => {

								const button =
										document.createElement("button");

								button.type = "button";

								button.className =
										"pathways-menu__control";

								button.id =
										`${menuId}-control-${index + 1}`;

								button.dataset.index =
										String(index);

								button.setAttribute(
										"aria-expanded",
										"false"
								);

								button.setAttribute(
										"aria-controls",
										panelId
								);

								button.textContent =
										item.label
										|| item.title
										|| `Topic ${index + 1}`;


								button.addEventListener(
										"click",
										() => this.toggle(index)
								);


								button.addEventListener(
										"keydown",
										(event) => {
												this.handleControlKeydown(
														event,
														index
												);
										}
								);


								controls.append(button);

								return button;
						}
				);


				/* ----------------------------------------------------------
							Disclosure panel
							---------------------------------------------------------- */

				const panel =
						document.createElement("div");

				panel.className =
						"pathways-menu__panel";

				panel.id = panelId;

				panel.setAttribute(
						"role",
						"region"
				);

				panel.hidden = true;


				/* ----------------------------------------------------------
							Assemble
							---------------------------------------------------------- */

				nav.append(
						topScroller,
						controls,
						panel
				);

				this.append(nav);


				/* ----------------------------------------------------------
							Store element references
							---------------------------------------------------------- */

				this.panel = panel;

				this.controlsScroller =
						controls;

				this.topScroller =
						topScroller;

				this.topScrollerTrack =
						topScrollerTrack;


				/* ----------------------------------------------------------
							Activate synchronized scrolling
							---------------------------------------------------------- */

				this.setupTopScroller();
		}
		
		setupTopScroller() {
				const controls =
						this.controlsScroller;

				const topScroller =
						this.topScroller;

				const track =
						this.topScrollerTrack;


				if (
						!controls
						|| !topScroller
						|| !track
				) {
						return;
				}


				/* ----------------------------------------------------------
							Top scrollbar → topic row
							---------------------------------------------------------- */

				topScroller.addEventListener(
						"scroll",
						() => {
								controls.scrollLeft =
										topScroller.scrollLeft;
						},
						{
								passive: true
						}
				);


				/* ----------------------------------------------------------
							Topic row → top scrollbar
							---------------------------------------------------------- */

				controls.addEventListener(
						"scroll",
						() => {
								topScroller.scrollLeft =
										controls.scrollLeft;
						},
						{
								passive: true
						}
				);


				/* ----------------------------------------------------------
							Keep track width correct when layout changes
							---------------------------------------------------------- */

				if (this.topScrollerResizeObserver) {
						this.topScrollerResizeObserver.disconnect();
				}


				this.topScrollerResizeObserver =
						new ResizeObserver(() => {
								this.scheduleTopScrollerSync();
						});


				this.topScrollerResizeObserver.observe(
						controls
				);


				/* Initial measurement */

				this.scheduleTopScrollerSync();


				/*
					* Fonts can slightly alter button dimensions after
					* the initial layout, so measure once more when fonts
					* have finished loading.
					*/

				if (document.fonts?.ready) {
						document.fonts.ready.then(() => {
								if (this.isConnected) {
										this.scheduleTopScrollerSync();
								}
						});
				}
		}

		scheduleTopScrollerSync() {
				if (
						this.topScrollerSyncFrame !== null
				) {
						return;
				}


				this.topScrollerSyncFrame =
						requestAnimationFrame(() => {

								this.topScrollerSyncFrame = null;

								this.syncTopScroller();
						});
		}

		syncTopScroller() {
				const controls =
						this.controlsScroller;

				const topScroller =
						this.topScroller;

				const track =
						this.topScrollerTrack;


				if (
						!controls
						|| !topScroller
						|| !track
				) {
						return;
				}


				/*
					* The invisible track must be exactly as wide
					* as the complete topic-button row.
					*/

				track.style.width =
						`${controls.scrollWidth}px`;


				/*
					* Preserve the actual topic row's current position.
					*/

				topScroller.scrollLeft =
						controls.scrollLeft;
		}		

  toggle(index) {
    if (this.activeIndex === index) {
      this.close();
      return;
    }

    this.open(index);
  }

  open(index) {
    const item = this.items[index];
    if (!item || !this.panel) return;

    this.controls.forEach((button, buttonIndex) => {
      const isActive = buttonIndex === index;
      button.setAttribute("aria-expanded", String(isActive));
      button.classList.toggle("is-active", isActive);
    });

    this.panel.replaceChildren(this.renderItem(item));
    this.panel.setAttribute("aria-labelledby", this.controls[index].id);
    this.panel.hidden = false;
    this.activeIndex = index;
  }

  close() {
    if (!this.panel) return;

    this.controls.forEach((button) => {
      button.setAttribute("aria-expanded", "false");
      button.classList.remove("is-active");
    });

    this.panel.hidden = true;
    this.panel.removeAttribute("aria-labelledby");
    this.panel.replaceChildren();
    this.activeIndex = -1;
  }

  handleControlKeydown(event, index) {
    let nextIndex = null;

    if (event.key === "ArrowRight") {
      nextIndex = (index + 1) % this.controls.length;
    } else if (event.key === "ArrowLeft") {
      nextIndex = (index - 1 + this.controls.length) % this.controls.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = this.controls.length - 1;
    } else if (event.key === "Escape" && this.activeIndex !== -1) {
      event.preventDefault();
      this.close();
      this.controls[index]?.focus();
      return;
    }

    if (nextIndex !== null) {
      event.preventDefault();
      this.controls[nextIndex]?.focus();
    }
  }

		renderItem(item) {
				const wrapper = document.createElement("div");
				wrapper.className = "pathways-menu__panel-inner";

				/*
					* Add an item-specific modifier class so individual
					* pathway panels can receive layout adjustments.
					*/
				const itemName =
						String(item.label || item.title || "")
								.trim()
								.toLowerCase()
								.replace(/[^a-z0-9]+/g, "-")
								.replace(/^-|-$/g, "");

				if (itemName) {
						wrapper.classList.add(
								`pathways-menu__panel-inner--${itemName}`
						);
				}

				const columns = document.createElement("div");
				columns.className = "pathways-menu__columns";

				for (const column of item.columns || []) {
						const columnElement = document.createElement("div");
						columnElement.className = "pathways-menu__column";

						for (const block of column.blocks || []) {
								const rendered = this.renderBlock(block);

								if (rendered) {
										columnElement.append(rendered);
								}
						}

						columns.append(columnElement);
				}

				wrapper.append(columns);

				return wrapper;
		}

		renderBlock(block) {
				switch (block?.type) {
						case "heading":
								return this.renderHeading(block);

						case "paragraph":
								return this.renderParagraph(block);

						case "link":
								return this.renderStandaloneLink(block);

						case "news_feed":
								return this.renderNewsFeed(block);

						case "image":
								return this.renderImage(block);

						case "dot_animation":
								return this.renderDotAnimation(block);

						case "social_links":
								return this.renderSocialLinks(block);

						default:
								return null;
				}
		}

  renderHeading(block) {
    const level = block.level === 2 ? 2 : 3;
    const heading = document.createElement(`h${level}`);
    heading.className = `pathways-menu__heading pathways-menu__heading--h${level}`;
    heading.textContent = block.text || "";
    return heading;
  }

		renderParagraph(block) {
				const paragraph = document.createElement("p");
				paragraph.className = "pathways-menu__paragraph";

				if (typeof block.text === "string") {
						paragraph.textContent = block.text;
						return paragraph;
				}

				for (const segment of block.content || []) {
						if (segment.type === "text") {
								paragraph.append(
										document.createTextNode(segment.text || "")
								);
						} else if (segment.type === "link") {
								paragraph.append(
										this.createLink(
												segment,
												"pathways-menu__inline-link"
										)
								);
						}
				}

				return paragraph;
		}

		renderStandaloneLink(block) {
				const link = this.createLink(block, "pathways-menu__link");

				const label = document.createElement("span");
				label.className = "pathways-menu__link-label";
				label.textContent = block.label || "";

				link.replaceChildren(label);

				return link;
		}

		renderNewsFeed(block) {
				const feed = document.createElement("wtk-news-feed");

				feed.className = "pathways-menu__news-feed";

				// ------------------------------------------------------------
				// Category/tag-driven feed
				// ------------------------------------------------------------

				if (Array.isArray(block.tags) && block.tags.length) {
						const tags = block.tags
								.map((tag) => String(tag).trim())
								.filter(Boolean);

						if (tags.length) {
								feed.setAttribute("tags", tags.join(","));
								feed.setAttribute("tag-mode", "any");
						}
				}

				// ------------------------------------------------------------
				// Fixed editorial article list
				//
				// Used for "Key ... Articles from the Archive".
				// The news-feed component preserves the supplied ID order.
				// ------------------------------------------------------------

				const hasIds =
						Array.isArray(block.ids)
						&& block.ids.length > 0;

				if (hasIds) {
						const ids = block.ids
								.map((id) => String(id).trim())
								.filter(Boolean);

						if (ids.length) {
								feed.setAttribute("ids", ids.join(","));
						}
				}

				// ------------------------------------------------------------
				// Result limit
				// ------------------------------------------------------------

				const limit =
						Number.isInteger(block.limit) && block.limit > 0
								? block.limit
								: 4;

				feed.setAttribute("limit", String(limit));

				// ------------------------------------------------------------
				// Sorting
				//
				// Do NOT apply sort to fixed ID lists because ID order is
				// intentionally editorial.
				// ------------------------------------------------------------

				if (!hasIds) {
						const allowedSorts = new Set([
								"newest",
								"oldest",
								"posted",
								"priority"
						]);

						const sort =
								allowedSorts.has(block.sort)
										? block.sort
										: "newest";

						feed.setAttribute("sort", sort);
				}

				// ------------------------------------------------------------
				// Pathway-menu feeds are compact embeds.
				// Their surrounding heading supplies context, so don't show
				// the normal feed toolbar/count.
				// ------------------------------------------------------------

				feed.setAttribute("hide-sort", "");
				feed.setAttribute("hide-count", "");

				// ------------------------------------------------------------
				// Accessibility
				// ------------------------------------------------------------

				if (block.label) {
						feed.setAttribute(
								"aria-label",
								String(block.label)
						);
				}

				return feed;
		}

  renderImage(block) {
    const image = document.createElement("img");
    image.className = "pathways-menu__image";
    image.src = this.safeUrl(block.src, "");
    image.alt = block.alt || "";
    image.loading = "lazy";
    image.decoding = "async";
    return image;
  }
		
		renderDotAnimation(block) {
				const art =
						document.createElement("wtk-dot-art");

				art.className =
						"pathways-menu__dot-art";

				art.setAttribute(
						"src",
						this.safeUrl(
								block.src,
								"/data/elements/database-dot-art.json"
						)
				);

				const requestedFps =
						Number(block.fps);

				const fps =
						Number.isFinite(requestedFps)
								? Math.min(
												30,
												Math.max(1, requestedFps)
										)
								: 15;

				art.setAttribute(
						"fps",
						String(fps)
				);


				/*
					* Optional background override.
					* Leave absent to preserve the original artwork.
					*/

				if (block.background) {
						art.setAttribute(
								"background",
								String(block.background)
						);
				}


				/*
					* Load the animation renderer only if/when
					* a dot-animation block is actually rendered.
					*/

				import(
						"/assets/js/components/dot-art.js"
				).catch((error) => {
						console.error(
								"Unable to load dot-art component:",
								error
						);
				});

				return art;
		}		

  renderSocialLinks(block) {
    const row = document.createElement("div");
    row.className = "pathways-menu__social-links";
    row.setAttribute("aria-label", "WantToKnow.info social links");

    for (const item of block.items || []) {
      const link = this.createLink(item, "pathways-menu__social-link", true);
      link.setAttribute("aria-label", item.platform || "Social link");

      const images = document.createElement("span");
      images.className = "pathways-menu__social-images";

      const defaultImage = document.createElement("img");
      defaultImage.className = "pathways-menu__social-default";
      defaultImage.src = this.safeUrl(item.image, "");
      defaultImage.alt = "";
      defaultImage.setAttribute("aria-hidden", "true");
      images.append(defaultImage);

      if (item.imageColor) {
        const colorImage = document.createElement("img");
        colorImage.className = "pathways-menu__social-color";
        colorImage.src = this.safeUrl(item.imageColor, "");
        colorImage.alt = "";
        colorImage.setAttribute("aria-hidden", "true");
        images.append(colorImage);
      }

      link.append(images);
      row.append(link);
    }

    return row;
  }

  createLink(item, className, newTab = false) {
    const link = document.createElement("a");
    link.className = className;
    link.href = this.safeUrl(item.url, "#");

    if (item.label) {
      link.append(document.createTextNode(item.label));
    }

    if (newTab && this.isExternal(link.href)) {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    }

    return link;
  }

  makeArrow() {
    const arrow = document.createElement("span");
    arrow.className = "pathways-menu__link-arrow";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "→";
    return arrow;
  }

  safeUrl(value, fallback = "#") {
    if (!value) return fallback;

    try {
      const parsed = new URL(String(value), window.location.origin);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : fallback;
    } catch {
      return fallback;
    }
  }

  isExternal(value) {
    try {
      return new URL(value, window.location.origin).origin !== window.location.origin;
    } catch {
      return false;
    }
  }
}

if (!customElements.get("wtk-pathways-menu")) {
  customElements.define("wtk-pathways-menu", WtkPathwaysMenu);
}
