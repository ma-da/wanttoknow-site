(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);

  const canonicalUrl =
    window.WTK?.canonicalUrl
    || $("link[rel='canonical']")?.href
    || window.location.href;

  const shareTitle =
    window.WTK?.shareTitle
    || document.title;

  const shareDescription =
    window.WTK?.shareDescription
    || $("meta[name='description']")?.content
    || "Explore WantToKnow.info.";

  const announce =
    window.WTK?.announce
    || (() => {});

  const copyText =
    window.WTK?.copyText
    || (async (value) => {
      await navigator.clipboard.writeText(value);
    });

  // ==========================================================================
  // Substack RSS renderer
  // ==========================================================================

  const substackContainer =
    $("#substack-posts");

  const rssUrl =
    $("#latest-articles")?.dataset.rssFeed
    || "https://wtkconsciousmedia.substack.com/feed";

  const fallbackImage =
    `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(`
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675">
        <defs>
          <linearGradient id="g" x1="0" x2="1">
            <stop stop-color="#ded6ff"/>
            <stop offset="1" stop-color="#7658f6"/>
          </linearGradient>
        </defs>
        <rect width="1200" height="675" fill="url(#g)"/>
        <circle cx="950" cy="100" r="180" fill="#ffd76a" opacity=".75"/>
        <text x="80" y="330" font-family="Arial,sans-serif" font-size="82" font-weight="700" fill="#17141f">WantToKnow.info</text>
        <text x="82" y="405" font-family="Arial,sans-serif" font-size="38" fill="#47414f">Conscious Media</text>
      </svg>
    `)}`;

  const dateFormatter =
    new Intl.DateTimeFormat(
      "en-US",
      {
        month: "long",
        day: "numeric",
        year: "numeric"
      }
    );

  function safeHttpUrl(value, fallback = "#") {
    try {
      const parsed =
        new URL(value, window.location.origin);

      return ["http:", "https:"].includes(parsed.protocol)
        ? parsed.href
        : fallback;
    } catch {
      return fallback;
    }
  }

  function safeImageUrl(
    value,
    fallback = fallbackImage
  ) {
    if (
      String(value).startsWith("data:image/")
    ) {
      return String(value);
    }

    return safeHttpUrl(value, fallback);
  }

  function plainText(value = "") {
    const template =
      document.createElement("template");

    template.innerHTML =
      String(value);

    return (
      template.content.textContent || ""
    )
      .replace(/\s+/g, " ")
      .trim();
  }

  function firstImageFromHtml(value = "") {
    const template =
      document.createElement("template");

    template.innerHTML =
      String(value);

    return (
      template.content
        .querySelector("img")
        ?.getAttribute("src")
      || ""
    );
  }

  function xmlText(item, selector) {
    return (
      item.querySelector(selector)
        ?.textContent
        ?.trim()
      || ""
    );
  }

  function parseRss(text) {
    const xml =
      new DOMParser()
        .parseFromString(
          text,
          "application/xml"
        );

    if (xml.querySelector("parsererror")) {
      throw new Error("Invalid RSS response");
    }

    return [
      ...xml.querySelectorAll("item")
    ].map((item) => {
      const description =
        xmlText(item, "description");

      const encodedNodes =
        item.getElementsByTagNameNS(
          "*",
          "encoded"
        );

      const content =
        encodedNodes[0]
          ?.textContent
          ?.trim()
        || description;

      const enclosure =
        item.querySelector("enclosure[url]")
          ?.getAttribute("url")
        || "";

      const media =
        item.getElementsByTagNameNS(
          "*",
          "content"
        )[0]
          ?.getAttribute("url")
        || "";

      return {
        title:
          xmlText(item, "title"),

        url:
          xmlText(item, "link"),

        publishedAt:
          xmlText(item, "pubDate"),

        excerpt:
          plainText(
            description || content
          ).slice(0, 240),

        image:
          enclosure
          || media
          || firstImageFromHtml(content)
      };
    });
  }

  function normalizeJson(data) {
    const posts =
      Array.isArray(data)
        ? data
        : (
          Array.isArray(data?.posts)
            ? data.posts
            : []
        );

    return posts.map((post) => ({
      title:
        post.title || "Untitled article",

      url:
        post.url
        || post.link
        || "https://wtkconsciousmedia.substack.com/",

      publishedAt:
        post.publishedAt
        || post.pubDate
        || post.date
        || "",

      excerpt:
        plainText(
          post.excerpt
          || post.description
          || post.summary
          || ""
        ).slice(0, 240),

      image:
        post.image
        || post.thumbnail
        || post.enclosure?.url
        || ""
    }));
  }

  function createPostCard(post) {
    const article =
      document.createElement("article");

    article.className =
      "substack-card";

    const href =
      safeHttpUrl(
        post.url,
        "https://wtkconsciousmedia.substack.com/"
      );

    const imageLink =
      document.createElement("a");

    Object.assign(
      imageLink,
      {
        className: "substack-image-link",
        href,
        target: "_blank",
        rel: "noopener noreferrer"
      }
    );

    imageLink.setAttribute(
      "aria-label",
      `Read ${post.title || "article"}`
    );

    const image =
      document.createElement("img");

    Object.assign(
      image,
      {
        className: "substack-image",
        src: safeImageUrl(
          post.image,
          fallbackImage
        ),
        alt: "",
        width: 720,
        height: 405,
        loading: "lazy",
        decoding: "async"
      }
    );

    image.addEventListener(
      "error",
      () => {
        image.src = fallbackImage;
      },
      { once: true }
    );

    imageLink.appendChild(image);

    const body =
      document.createElement("div");

    body.className =
      "substack-card-body";

    const date =
      new Date(post.publishedAt);

    if (!Number.isNaN(date.getTime())) {
      const p =
        document.createElement("p");

      p.className =
        "substack-date";

      p.textContent =
        dateFormatter.format(date);

      body.appendChild(p);
    }

    const heading =
      document.createElement("h3");

    heading.className =
      "substack-title";

    const titleLink =
      document.createElement("a");

    Object.assign(
      titleLink,
      {
        href,
        target: "_blank",
        rel: "noopener noreferrer"
      }
    );

    titleLink.textContent =
      post.title || "Untitled article";

    heading.appendChild(titleLink);
    body.appendChild(heading);

    const excerpt =
      document.createElement("p");

    excerpt.className =
      "substack-excerpt";

    excerpt.textContent =
      post.excerpt
      || "Read the latest article from WantToKnow.info.";

    body.appendChild(excerpt);

    const readMore =
      document.createElement("a");

    Object.assign(
      readMore,
      {
        className:
          "text-link substack-read-more",
        href,
        target: "_blank",
        rel: "noopener noreferrer"
      }
    );

    readMore.innerHTML =
      "Read article "
      + "<span aria-hidden='true'>→</span>";

    body.appendChild(readMore);

    article.append(
      imageLink,
      body
    );

    return article;
  }

  async function fetchFeedSource(url) {
    const response =
      await fetch(
        url,
        {
          headers: {
            Accept:
              "application/rss+xml, "
              + "application/xml, "
              + "application/json;q=.9, "
              + "text/xml;q=.8"
          },

          credentials:
            url.startsWith("/")
              ? "same-origin"
              : "omit"
        }
      );

    if (!response.ok) {
      throw new Error(
        `Feed request failed: ${response.status}`
      );
    }

    const text =
      await response.text();

    const trimmed =
      text.trim();

    return (
      trimmed.startsWith("{")
      || trimmed.startsWith("[")
    )
      ? normalizeJson(
          JSON.parse(trimmed)
        )
      : parseRss(text);
  }

  async function loadSubstackPosts() {
    if (!substackContainer) return;

    try {
      let posts;

      try {
        posts =
          await fetchFeedSource(
            "/api/substack"
          );
      } catch {
        posts =
          await fetchFeedSource(rssUrl);
      }

      if (!posts.length) {
        throw new Error(
          "RSS feed contained no posts"
        );
      }

      substackContainer.replaceChildren(
        ...posts
          .slice(0, 6)
          .map(createPostCard)
      );
    } catch (error) {
      console.error(
        "Substack RSS load failed:",
        error
      );

      const message =
        document.createElement("div");

      message.className =
        "substack-error";

      message.innerHTML =
        "<p>We couldn’t load the latest articles right now. "
        + '<a href="https://wtkconsciousmedia.substack.com/" '
        + 'target="_blank" rel="noopener noreferrer">'
        + "View them directly on Substack</a>.</p>";

      substackContainer.replaceChildren(
        message
      );
    } finally {
      substackContainer.setAttribute(
        "aria-busy",
        "false"
      );
    }
  }

  loadSubstackPosts();

  // ==========================================================================
  // Homepage Instagram image sharing
  //
  // The QR below encodes https://www.wanttoknow.info/ and therefore remains
  // deliberately homepage-only. Do not reuse this block on article/topic pages
  // until QR generation is made dynamic.
  // ==========================================================================

  const modal =
    $("#instagramShareModal");

  const modalClose =
    $("#instagramModalClose");

  const instagramButton =
    $("#instagramShareBtn");

  const shareImageButton =
    $("#shareInstagramImage");

  const downloadImageButton =
    $("#downloadInstagramImage");

  const copyCaptionButton =
    $("#copyInstagramCaption");

  let shareBlob = null;
  let shareObjectUrl = "";
  let lastFocusedElement = null;

  const instagramCaption =
    `${shareTitle}\n\n`
    + `${shareDescription}\n\n`
    + canonicalUrl;

  const qrDataUrl =
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAASgAAAEoCAIAAABkZftOAAAFk0lEQVR4nO3dQa5jtRZA0V9fTAGJJvMfFU0kBhEmgCWMfNh2WKtZerpJJdly48j2j8/n8z/g3/X/+g3Af5HwICA8CAgPAsKDgPAgIDwICA8CwoOA8CAgPAgIDwLCg4DwICA8CAgPAsKDgPAgIDwICA8CwoOA8CAgPAgIDwLCg4DwICA8CAgPAsKDgPAgIDwI/DT9Ar/8/Ov0Sxzx+x+//eW/r97/6u9Xdj+H3efvOvV+dj+f138Pp1jxICA8CAgPAsKDgPAgIDwICA8C43O8lek5ycr0PO3U3O+Ual6365XP5xQrHgSEBwHhQUB4EBAeBIQHAeFBIJvjrZyaq1T72ab3od22z216vvfK72GXFQ8CwoOA8CAgPAgIDwLCg4DwIHDdHO82u3Ok1+da33pO5m2seBAQHgSEBwHhQUB4EBAeBIQHAXO8w6bvzdt93dXzv3Wf2yuseBAQHgSEBwHhQUB4EBAeBIQHgevmeK/Mhabvzav2Ae7O/aa/r1d+D7useBAQHgSEBwHhQUB4EBAeBIQHgWyO963nMZ6a11V/vzL9/G/9PaxY8SAgPAgIDwLCg4DwICA8CAgPAj8+n0/9Hq5W7UNbeWVu9q376E6x4kFAeBAQHgSEBwHhQUB4EBAeBMbneNNzsOnzKlduO1fzlNvmgbumv5dTrHgQEB4EhAcB4UFAeBAQHgSEB4Hr5njVPrHp9zl9LuWuU+//1PNvY44HX0h4EBAeBIQHAeFBQHgQEB4EsnM1q3veXt+/V73u9P7JXdV+zlOseBAQHgSEBwHhQUB4EBAeBIQHgZ/qN/B33Tave2U/YfX/Wj3n1Pd42z7PXVY8CAgPAsKDgPAgIDwICA8CwoPAM3O83blNdY7l9D6uU687Pd879TlPf57V92XFg4DwICA8CAgPAsKDgPAgIDwIZPfjrUzvB9s1fQ5k9fxqzvnKPjrnasIXEh4EhAcB4UFAeBAQHgSEB4Hr9uNNz3mquVl1D9u0286rXLltTmjFg4DwICA8CAgPAsKDgPAgIDwIjO/HW3lln9Wp+dvrz7nt/e+q9nOuWPEgIDwICA8CwoOA8CAgPAgIDwLXnau5Ut3/tuuVcyNXbrtnr/peplnxICA8CAgPAsKDgPAgIDwICA8C183xbpvz7Lrtfr+V2+acp7zy+VvxICA8CAgPAsKDgPAgIDwICA8C4/fjVec9vm56rjh93+Du6556/iu/HyseBIQHAeFBQHgQEB4EhAcB4UEgux9v17feqza9X/E21TmW9uMBwoOC8CAgPAgIDwLCg4DwIPD8uZqnnlP9/cpt54i+Mj+87XNeseJBQHgQEB4EhAcB4UFAeBAQHgSe2Y9Xue3evOr5u6bnja88f8WKBwHhQUB4EBAeBIQHAeFBQHgQGL8f77b9Wiu7c5tX9n2tVHO/6f2KK9XnvGLFg4DwICA8CAgPAsKDgPAgIDwIjM/xVr71nrTd50+f2/mt+/Smv5dpVjwICA8CwoOA8CAgPAgIDwLCg0A2x1uZPmdy12338q3cdt/dK/v6KlY8CAgPAsKDgPAgIDwICA8CwoPAdXO82+zOu6bnddV88pRTc85TqrmfFQ8CwoOA8CAgPAgIDwLCg4DwIGCO9w/ddp9bdd7m6+dkVvNDKx4EhAcB4UFAeBAQHgSEBwHhQeC6Od4r5yKuTO/H2zU935u+3++280JPseJBQHgQEB4EhAcB4UFAeBAQHgSyOd5tc5WV2+ZIt50/WX0+1T7AU6x4EBAeBIQHAeFBQHgQEB4EhAeBH5/Pp34P8J9jxYOA8CAgPAgIDwLCg4DwICA8CAgPAsKDgPAgIDwICA8CwoOA8CAgPAgIDwLCg4DwICA8CAgPAsKDgPAgIDwICA8CwoOA8CAgPAgIDwLCg4DwICA8CPwJ8l5LrNDOiIgAAAAASUVORK5CYII=";

  function roundedRect(
    ctx,
    x,
    y,
    width,
    height,
    radius
  ) {
    const r =
      Math.min(
        radius,
        width / 2,
        height / 2
      );

    ctx.beginPath();
    ctx.moveTo(x + r, y);

    ctx.arcTo(
      x + width,
      y,
      x + width,
      y + height,
      r
    );

    ctx.arcTo(
      x + width,
      y + height,
      x,
      y + height,
      r
    );

    ctx.arcTo(
      x,
      y + height,
      x,
      y,
      r
    );

    ctx.arcTo(
      x,
      y,
      x + width,
      y,
      r
    );

    ctx.closePath();
  }

  function wrapCanvasText(
    ctx,
    text,
    maxWidth
  ) {
    const words =
      text.split(/\s+/);

    const lines = [];
    let line = "";

    for (const word of words) {
      const test =
        line
          ? `${line} ${word}`
          : word;

      if (
        ctx.measureText(test).width > maxWidth
        && line
      ) {
        lines.push(line);
        line = word;
      } else {
        line = test;
      }
    }

    if (line) {
      lines.push(line);
    }

    return lines;
  }

  function loadImage(src) {
    return new Promise(
      (resolve, reject) => {
        const image =
          new Image();

        image.onload =
          () => resolve(image);

        image.onerror =
          reject;

        image.src =
          src;
      }
    );
  }

  async function drawQr(
    ctx,
    x,
    y,
    size
  ) {
    const image =
      await loadImage(qrDataUrl);

    ctx.fillStyle =
      "#fff";

    roundedRect(
      ctx,
      x,
      y,
      size,
      size,
      24
    );

    ctx.fill();

    const inset = 18;

    ctx.drawImage(
      image,
      x + inset,
      y + inset,
      size - inset * 2,
      size - inset * 2
    );
  }

  async function createInstagramCard() {
    const canvas =
      document.createElement("canvas");

    canvas.width = 1080;
    canvas.height = 1350;

    const ctx =
      canvas.getContext(
        "2d",
        { alpha: false }
      );

    if (!ctx) {
      throw new Error(
        "Canvas unavailable"
      );
    }

    const gradient =
      ctx.createLinearGradient(
        0,
        0,
        1080,
        1350
      );

    gradient.addColorStop(
      0,
      "#f7f3ff"
    );

    gradient.addColorStop(
      0.56,
      "#ded6ff"
    );

    gradient.addColorStop(
      1,
      "#7658f6"
    );

    ctx.fillStyle =
      gradient;

    ctx.fillRect(
      0,
      0,
      1080,
      1350
    );

    ctx.globalAlpha = 0.78;

    ctx.fillStyle =
      "#ffd76a";

    ctx.beginPath();

    ctx.arc(
      930,
      110,
      220,
      0,
      Math.PI * 2
    );

    ctx.fill();

    ctx.fillStyle =
      "#f2703b";

    ctx.beginPath();

    ctx.arc(
      70,
      1230,
      175,
      0,
      Math.PI * 2
    );

    ctx.fill();

    ctx.globalAlpha = 1;

    ctx.fillStyle =
      "rgba(255,255,255,.9)";

    roundedRect(
      ctx,
      72,
      70,
      936,
      1210,
      42
    );

    ctx.fill();

    ctx.strokeStyle =
      "rgba(91,63,224,.22)";

    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.fillStyle =
      "#7658f6";

    ctx.beginPath();

    ctx.arc(
      142,
      152,
      38,
      0,
      Math.PI * 2
    );

    ctx.fill();

    ctx.fillStyle =
      "#fff";

    ctx.font =
      "700 42px Arial,sans-serif";

    ctx.textAlign =
      "center";

    ctx.textBaseline =
      "middle";

    ctx.fillText(
      "?",
      142,
      154
    );

    ctx.textAlign =
      "left";

    ctx.fillStyle =
      "#17141f";

    ctx.font =
      "700 38px Arial,sans-serif";

    ctx.fillText(
      "WantToKnow.info",
      200,
      154
    );

    ctx.fillStyle =
      "#df5622";

    ctx.font =
      "700 24px Arial,sans-serif";

    ctx.fillText(
      "QUESTION DEEPLY. VERIFY CAREFULLY.",
      112,
      265
    );

    const cardTitle =
      $(".hero-title")
        ?.textContent
        ?.replace(/\s+/g, " ")
        .trim()
      || "See the hidden story. Find the hope.";

    ctx.fillStyle =
      "#17141f";

    ctx.font =
      "700 78px Arial,sans-serif";

    let y = 375;

    for (
      const line
      of wrapCanvasText(
        ctx,
        cardTitle,
        820
      ).slice(0, 5)
    ) {
      ctx.fillText(
        line,
        112,
        y
      );

      y += 92;
    }

    const lede =
      $(".hero-lede")
        ?.textContent
        ?.replace(/\s+/g, " ")
        .trim()
      || shareDescription;

    ctx.fillStyle =
      "#47414f";

    ctx.font =
      "400 33px Arial,sans-serif";

    y += 30;

    for (
      const line
      of wrapCanvasText(
        ctx,
        lede,
        820
      ).slice(0, 4)
    ) {
      ctx.fillText(
        line,
        112,
        y
      );

      y += 47;
    }

    await drawQr(
      ctx,
      688,
      930,
      270
    );

    ctx.fillStyle =
      "#17141f";

    ctx.font =
      "700 28px Arial,sans-serif";

    ctx.fillText(
      "SCAN TO EXPLORE",
      112,
      1020
    );

    ctx.fillStyle =
      "#5b3fe0";

    ctx.font =
      "700 31px Arial,sans-serif";

    ctx.fillText(
      "wanttoknow.info",
      112,
      1070
    );

    ctx.fillStyle =
      "#706a78";

    ctx.font =
      "400 25px Arial,sans-serif";

    wrapCanvasText(
      ctx,
      canonicalUrl.replace(
        /^https?:\/\//,
        ""
      ),
      500
    )
      .slice(0, 2)
      .forEach(
        (line, index) => {
          ctx.fillText(
            line,
            112,
            1120 + index * 36
          );
        }
      );

    return new Promise(
      (resolve, reject) => {
        canvas.toBlob(
          (blob) => {
            if (blob) {
              resolve(blob);
            } else {
              reject(
                new Error(
                  "Image creation failed"
                )
              );
            }
          },
          "image/png",
          0.95
        );
      }
    );
  }

  function openModal() {
    if (!modal) return;

    lastFocusedElement =
      document.activeElement;

    modal.classList.add(
      "is-open"
    );

    modal.setAttribute(
      "aria-hidden",
      "false"
    );

    document.body.classList.add(
      "modal-open"
    );

    modalClose?.focus();
  }

  function closeModal() {
    if (!modal) return;

    modal.classList.remove(
      "is-open"
    );

    modal.setAttribute(
      "aria-hidden",
      "true"
    );

    document.body.classList.remove(
      "modal-open"
    );

    lastFocusedElement
      ?.focus
      ?.();
  }

  async function prepareInstagramImage() {
    openModal();

    if (shareBlob) return;

    let preview =
      $("#instagramPreviewWrap");

    if (preview) {
      preview.className =
        "share-preview share-preview-loading";

      preview.textContent =
        "Creating preview…";
    }

    try {
      shareBlob =
        await createInstagramCard();

      shareObjectUrl =
        URL.createObjectURL(
          shareBlob
        );

      const image =
        new Image();

      image.id =
        "instagramPreviewWrap";

      image.className =
        "share-preview";

      image.alt =
        "Instagram-ready WantToKnow.info preview with QR code";

      image.src =
        shareObjectUrl;

      preview?.replaceWith(image);
    } catch (error) {
      console.error(error);

      preview =
        $("#instagramPreviewWrap");

      if (preview) {
        preview.textContent =
          "The preview could not be generated. Please try again.";
      }
    }
  }

  instagramButton?.addEventListener(
    "click",
    prepareInstagramImage
  );

  modalClose?.addEventListener(
    "click",
    closeModal
  );

  modal?.addEventListener(
    "click",
    (event) => {
      if (event.target === modal) {
        closeModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (
        event.key === "Escape"
        && modal?.classList.contains(
          "is-open"
        )
      ) {
        closeModal();
      }
    }
  );

  shareImageButton?.addEventListener(
    "click",
    async () => {
      if (!shareBlob) return;

      const file =
        new File(
          [shareBlob],
          "wanttoknow-instagram-share.png",
          {
            type: "image/png"
          }
        );

      try {
        if (
          navigator.share
          && navigator.canShare
            ?.({ files: [file] })
        ) {
          await navigator.share({
            files: [file],
            title: shareTitle,
            text: instagramCaption
          });
        } else {
          downloadImageButton
            ?.click();

          announce(
            "Image downloaded. "
              + "Upload it to Instagram.",
            4000
          );
        }
      } catch (error) {
        if (
          error?.name !== "AbortError"
        ) {
          announce(
            "Image sharing is unavailable. "
              + "Downloading instead.",
            4000
          );

          downloadImageButton
            ?.click();
        }
      }
    }
  );

  downloadImageButton?.addEventListener(
    "click",
    () => {
      if (
        !shareBlob
        || !shareObjectUrl
      ) {
        return;
      }

      const link =
        document.createElement("a");

      link.href =
        shareObjectUrl;

      link.download =
        "wanttoknow-instagram-share.png";

      document.body.appendChild(link);

      link.click();
      link.remove();
    }
  );

  copyCaptionButton?.addEventListener(
    "click",
    async () => {
      try {
        await copyText(
          instagramCaption
        );

        announce(
          "Instagram caption copied."
        );
      } catch {
        announce(
          "Could not copy the caption automatically."
        );
      }
    }
  );

  window.addEventListener(
    "pagehide",
    () => {
      if (shareObjectUrl) {
        URL.revokeObjectURL(
          shareObjectUrl
        );
      }
    },
    { once: true }
  );
})();

/* ==========================================================================
   Pathways randomized dot field
   ========================================================================== */

function initPathwaysDotField() {
  const pathways = document.querySelector(".pathways");

  if (!pathways || pathways.querySelector(".pathways-dot-field")) {
    return;
  }

  const canvas = document.createElement("canvas");
  canvas.className = "pathways-dot-field";
  canvas.setAttribute("aria-hidden", "true");

  pathways.prepend(canvas);

  const context = canvas.getContext("2d");

  if (!context) {
    canvas.remove();
    return;
  }

  /*
   * Random seed changes on each page load, but remains stable while
   * resizing so the dots don't visibly reshuffle.
   */
  const seed =
    window.crypto?.getRandomValues
      ? crypto.getRandomValues(new Uint32Array(1))[0]
      : Math.floor(Math.random() * 4294967295);

  /*
   * Chances that a normal gray grid dot gets replaced by a brand color.
   *
   * 7% purple
   * 2.5% orange
   * 0.8% black
   *
   * Everything else stays gray.
   */
  const PURPLE_CHANCE = 0.07;
  const ORANGE_CHANCE = 0.025;
  const BLACK_CHANCE = 0.008;
  const WHITE_CHANCE = 0.61;

  /*
   * Deterministic pseudo-random value for each grid coordinate.
   * This makes the distribution random-looking without changing
   * whenever the canvas redraws.
   */
  function randomForCell(column, row) {
    let value =
      Math.imul(column + 1, 374761393) +
      Math.imul(row + 1, 668265263) +
      seed;

    value = Math.imul(value ^ (value >>> 13), 1274126177);
    value ^= value >>> 16;

    return (value >>> 0) / 4294967296;
  }

		function getGridSpacing() {
				const rootFontSize =
						parseFloat(
								getComputedStyle(document.documentElement).fontSize
						) || 16;

				const minimum = 1.3 * rootFontSize;
				const preferred = window.innerWidth * 0.016;
				const maximum = 2.3 * rootFontSize;

				return (
						Math.min(
								maximum,
								Math.max(minimum, preferred)
						) / 7
				);
		}

  function getBrandColor(property, fallback) {
    const value = getComputedStyle(document.documentElement)
      .getPropertyValue(property)
      .trim();

    return value || fallback;
  }

  function draw() {
    const rect = pathways.getBoundingClientRect();

    if (!rect.width || !rect.height) {
      return;
    }

    const pixelRatio = Math.min(
      window.devicePixelRatio || 1,
      2
    );

    canvas.width = Math.round(rect.width * pixelRatio);
    canvas.height = Math.round(rect.height * pixelRatio);

    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;

    context.setTransform(
      pixelRatio,
      0,
      0,
      pixelRatio,
      0,
      0
    );

    context.clearRect(
      0,
      0,
      rect.width,
      rect.height
    );

    const spacing = getGridSpacing();

    const gray = "rgb(165, 165, 165)";
    const black = "#000";

    const purple = getBrandColor(
      "--color-brand-purple",
      "#9852c7"
    );

    const orange = getBrandColor(
      "--color-brand-orange",
      "#d77b35"
    );

    const columns = Math.ceil(rect.width / spacing) + 1;
    const rows = Math.ceil(rect.height / spacing) + 1;

    /*
     * Half-spacing offset prevents dots from sitting directly
     * against the section boundaries.
     */
    const offset = spacing / 2;

    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
								const random = randomForCell(column, row);

								let color = gray;
								let radius = 0.45;

								if (random < WHITE_CHANCE) {
										continue;
								} else if (
										random < WHITE_CHANCE + BLACK_CHANCE
								) {
										color = black;
										radius = 0.7;
								} else if (
										random <
										WHITE_CHANCE +
										BLACK_CHANCE +
										ORANGE_CHANCE
								) {
										color = orange;
										radius = 0.6;
								} else if (
										random <
										WHITE_CHANCE +
										BLACK_CHANCE +
										ORANGE_CHANCE +
										PURPLE_CHANCE
								) {
										color = purple;
										radius = 0.55;
								}

        const x = offset + column * spacing;
        const y = offset + row * spacing;

        context.beginPath();
        context.arc(
          x,
          y,
          radius,
          0,
          Math.PI * 2
        );

        context.fillStyle = color;
        context.fill();
      }
    }
  }

  let resizeFrame = null;

  const resizeObserver = new ResizeObserver(() => {
    if (resizeFrame) {
      cancelAnimationFrame(resizeFrame);
    }

    resizeFrame = requestAnimationFrame(draw);
  });

  resizeObserver.observe(pathways);

  draw();
}


/*
 * Do not build the decorative canvas until:
 *
 * 1. the complete page has loaded, including images
 * 2. the browser has some idle time
 */

function schedulePathwaysDotField() {
  const initialize = () => {
    if ("requestIdleCallback" in window) {
      window.requestIdleCallback(
        initPathwaysDotField,
        { timeout: 1500 }
      );
    } else {
      window.setTimeout(
        initPathwaysDotField,
        250
      );
    }
  };

  if (document.readyState === "complete") {
    initialize();
  } else {
    window.addEventListener(
      "load",
      initialize,
      { once: true }
    );
  }
}

schedulePathwaysDotField();


