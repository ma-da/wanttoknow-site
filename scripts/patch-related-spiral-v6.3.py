#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import argparse
import re
import shutil

PHI = "1.61803398875"

JS_REPLACEMENT = r'''  function drawRelatedGraph(payload) {
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
     * desktop  = phi : 1
     * mobile   = 1 : phi
     */
    const measuredWidth = dom.relatedGraph.getBoundingClientRect().width;
    const isMobile = measuredWidth > 0 && measuredWidth < 640;

    const width = isMobile ? 742 : 1200;
    const height = isMobile ? 1200 : 742;
    const centerX = width / 2;
    const centerY = height / 2;

    const phi = (1 + Math.sqrt(5)) / 2;

    /*
     * A phi-based logarithmic spiral.  Using phi growth per half-turn gives
     * enough room for 24 labelled rectangles while preserving a clear,
     * single golden-ratio spiral.  The x/y scales rotate the same geometry
     * into landscape on wide screens and portrait on mobile.
     */
    const spiralB = Math.log(phi) / Math.PI;
    const startAngle = -Math.PI / 2;
    const rMin = isMobile ? 180 : 170;
    const rMax = isMobile ? 505 : 500;
    const xScale = isMobile ? 0.58 : 1.0;
    const yScale = isMobile ? 1.0 : 0.58;

    const childNodes = related.map((record, index) => {
      const count = Math.max(1, related.length);
      const t = count === 1 ? 0 : index / (count - 1);

      /*
       * t^0.72 gives the strongest relationships extra breathing room near
       * the center, where their rectangles are also largest.
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

      return {
        ...record,
        rank: index + 1,
        colorIndex: index % 6,
        x: centerX + Math.cos(angle) * radius * xScale,
        y: centerY + Math.sin(angle) * radius * yScale,
        nodeWidth: widthPx,
        nodeHeight: heightPx,
        fontSize: fontPx,
        maxLabelChars: Math.max(14, charsPerLine * lineCount - 1)
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
      .range([7.5, 1.15])
      .clamp(true);

    const edgeOpacity = d3
      .scaleLinear()
      .domain([1, Math.max(24, childNodes.length)])
      .range([0.82, 0.34])
      .clamp(true);

    /*
     * The edges form ONE ordered spiral: target -> rank 1 -> rank 2 -> ...
     * Their thickness encodes similarity rank; it does not imply that the
     * child articles are related to one another.
     */
    const edges = childNodes.map((node, index) => ({
      source: index === 0 ? targetPoint : childNodes[index - 1],
      target: node,
      rank: node.rank,
      colorIndex: node.colorIndex
    }));

    dom.relatedGraph.replaceChildren();
    dom.relatedGraph.dataset.targetRefId = String(target.ref_id);

    const svg = d3
      .select(dom.relatedGraph)
      .append("svg")
      .attr("class", "search-related-graph")
      .attr("viewBox", `0 0 ${width} ${height}`)
      .attr("preserveAspectRatio", "xMidYMid meet")
      .attr("role", "img")
      .attr(
        "aria-label",
        `Related articles for ${target.title || "selected result"}`
      );

    /* Soft guide makes the single spiral legible beneath weighted edges. */
    const spiralLine = d3
      .line()
      .x((node) => node.x)
      .y((node) => node.y)
      .curve(d3.curveCatmullRom.alpha(0.62));

    svg
      .append("path")
      .datum([targetPoint, ...childNodes])
      .attr("class", "search-related-graph__spiral-guide")
      .attr("d", spiralLine);

    svg
      .append("g")
      .attr("class", "search-related-graph__edges")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr(
        "class",
        (edge) => `search-related-edge related-color-${edge.colorIndex}`
      )
      .attr("x1", (edge) => edge.source.x)
      .attr("y1", (edge) => edge.source.y)
      .attr("x2", (edge) => edge.target.x)
      .attr("y2", (edge) => edge.target.y)
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
      .attr("transform", `translate(${centerX},${centerY})`);

    targetLink
      .append("title")
      .text(`Open: ${target.title || "Untitled result"}`);

    const targetBody = targetLink
      .append("g")
      .attr("class", "search-related-node__body");

    targetBody
      .append("circle")
      .attr("class", "search-related-node__target-circle")
      .attr("r", 56);

    const targetForeign = targetBody
      .append("foreignObject")
      .attr("x", -46)
      .attr("y", -42)
      .attr("width", 92)
      .attr("height", 84);

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
       Related nodes: buttons that refocus the graph, never navigation.
       ------------------------------------------------------------------ */

    const childGroups = nodeLayer
      .selectAll("g.search-related-node--child")
      .data(childNodes)
      .join("g")
      .attr(
        "class",
        (node) => (
          `search-related-node search-related-node--child related-color-${node.colorIndex}`
        )
      )
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
      .attr("rx", 8)
      .attr("ry", 8);

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

    /* Small rank marker keeps the TF-IDF ordering explicit. */
    childBodies
      .append("text")
      .attr("class", "search-related-node__rank")
      .attr("x", (node) => node.nodeWidth / 2 - 7)
      .attr("y", (node) => -node.nodeHeight / 2 + 11)
      .attr("text-anchor", "end")
      .text((node) => node.rank);
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

      drawRelatedGraph(payload);
      dom.relatedGraph.classList.remove("is-loading");

      if (focusTarget) {
        requestAnimationFrame(() => {
          $(".search-related-node--target", dom.relatedGraph)?.focus();
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


'''

CSS_REPLACEMENT = f'''/* Golden-mean related graph ------------------------------------------------ */

.search-related-modal__graph {{
  position: relative;
  min-height: 0;
  aspect-ratio: {PHI} / 1;
  padding: var(--space-2) var(--space-3) 0;
}}

.search-related-modal__graph.is-loading {{
  opacity: 0.72;
}}

.search-related-modal__state {{
  display: grid;
  min-height: 28rem;
  place-items: center;
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  text-align: center;
}}

.search-related-modal__state--error {{
  color: var(--color-danger, var(--color-text));
}}

.search-related-graph {{
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}}

.search-related-graph__spiral-guide {{
  fill: none;
  stroke: var(--border-color-strong);
  stroke-width: 0.8;
  stroke-linecap: round;
  stroke-linejoin: round;
  opacity: 0.22;
  pointer-events: none;
}}

.search-related-edge {{
  stroke-linecap: round;
  pointer-events: none;
}}

.search-related-edge.related-color-0 {{
  stroke: var(--color-brand-purple);
}}

.search-related-edge.related-color-1 {{
  stroke: var(--color-brand-orange);
}}

.search-related-edge.related-color-2 {{
  stroke: var(--color-brand-purple-dark);
}}

.search-related-edge.related-color-3 {{
  stroke: var(--color-brand-lavender);
}}

.search-related-edge.related-color-4 {{
  stroke: var(--color-brand-yellow);
}}

.search-related-edge.related-color-5 {{
  stroke: var(--color-brand-orange-bright);
}}

.search-related-node {{
  outline: none;
}}

.search-related-node--target {{
  color: inherit;
  text-decoration: none;
  cursor: pointer;
}}

.search-related-node--child {{
  cursor: pointer;
}}

.search-related-node__body {{
  transform-box: fill-box;
  transform-origin: center;
  transition:
    transform var(--motion-duration-fast) var(--motion-easing-standard),
    filter var(--motion-duration-fast) var(--motion-easing-standard);
}}

.search-related-node:hover .search-related-node__body,
.search-related-node:focus-visible .search-related-node__body,
.search-related-node:focus .search-related-node__body {{
  transform: translateY(-5px);
  filter: drop-shadow(0 0.28rem 0.35rem rgba(19, 15, 27, 0.18));
}}

.search-related-node__target-circle {{
  fill: var(--color-brand-purple-dark);
  stroke: var(--color-brand-yellow);
  stroke-width: 4;
}}

.search-related-node--target:hover .search-related-node__target-circle,
.search-related-node--target:focus-visible .search-related-node__target-circle {{
  stroke-width: 5;
}}

.search-related-node__target-content {{
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.22rem;
  overflow: hidden;
  color: #fff;
  font-family: var(--font-family-body);
  line-height: 1.08;
  text-align: center;
}}

.search-related-node__target-kicker {{
  color: var(--color-brand-yellow-light);
  font-family: var(--font-family-mono);
  font-size: 8px;
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}}

.search-related-node__target-title {{
  display: block;
  max-width: 100%;
  overflow: hidden;
  font-size: 9.5px;
  font-weight: var(--font-weight-bold);
}}

.search-related-node__rect {{
  stroke-width: 2.4;
  vector-effect: non-scaling-stroke;
  transition: stroke-width var(--motion-duration-fast) var(--motion-easing-standard);
}}

.search-related-node--child:hover .search-related-node__rect,
.search-related-node--child:focus-visible .search-related-node__rect {{
  stroke-width: 3.2;
}}

.search-related-node--child.related-color-0 .search-related-node__rect {{
  fill: var(--color-brand-lavender-soft);
  stroke: var(--color-brand-purple);
}}

.search-related-node--child.related-color-1 .search-related-node__rect {{
  fill: var(--color-brand-yellow-light);
  stroke: var(--color-brand-orange);
}}

.search-related-node--child.related-color-2 .search-related-node__rect {{
  fill: var(--color-brand-tan-light);
  stroke: var(--color-brand-purple-dark);
}}

.search-related-node--child.related-color-3 .search-related-node__rect {{
  fill: var(--color-brand-lavender);
  stroke: var(--color-brand-purple-dark);
}}

.search-related-node--child.related-color-4 .search-related-node__rect {{
  fill: var(--color-brand-yellow);
  stroke: var(--color-brand-orange);
}}

.search-related-node--child.related-color-5 .search-related-node__rect {{
  fill: var(--color-brand-orange-bright);
  stroke: var(--color-brand-purple-dark);
}}

.search-related-node__label {{
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  color: var(--color-text);
  font-family: var(--font-family-body);
  font-weight: var(--font-weight-semibold);
  line-height: 1.12;
  overflow-wrap: anywhere;
  text-align: center;
  pointer-events: none;
}}

.search-related-node__rank {{
  fill: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: 7px;
  font-weight: var(--font-weight-bold);
  pointer-events: none;
}}

'''

HTML_INTRO = '''      <p class="search-related-modal__intro">
        Related results follow a golden-ratio spiral from strongest to weakest.
        Select a rectangle to make it the new center target; select the circular
        center target to open that item. Edge thickness shows TF-IDF rank, not
        a relationship between neighboring child nodes.
      </p>'''

HTML_LEGEND = '''      <div class="search-related-modal__legend" aria-hidden="true">
        <span>Center circle opens the current target.</span>
        <span>Related rectangles refocus the graph.</span>
      </div>'''


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    if a < 0:
        raise RuntimeError(f"Could not find start marker for {label}: {start!r}")
    b = text.find(end, a)
    if b < 0:
        raise RuntimeError(f"Could not find end marker for {label}: {end!r}")
    return text[:a] + replacement + text[b:]


def patch(repo: Path, make_backup: bool) -> None:
    js_path = repo / "src/site/assets/js/search.js"
    css_path = repo / "src/site/assets/css/search.css"
    html_path = repo / "src/site/search/index.html"

    for path in (js_path, css_path, html_path):
        if not path.is_file():
            raise FileNotFoundError(path)
        if make_backup:
            shutil.copy2(path, path.with_suffix(path.suffix + ".pre-v6.3"))

    js = js_path.read_text(encoding="utf-8")
    js = replace_between(
        js,
        "  function drawRelatedGraph(",
        "  function closeRelatedModal(",
        JS_REPLACEMENT,
        "related JS",
    )
    js_path.write_text(js, encoding="utf-8")

    css = css_path.read_text(encoding="utf-8")
    css = replace_between(
        css,
        ".search-related-modal__graph {",
        ".search-related-modal__legend {",
        CSS_REPLACEMENT,
        "related graph CSS",
    )

    css = re.sub(
        r"(?ms)^  \.search-related-modal__graph \{\n"
        r"    min-height: 24rem;\n"
        r"    padding-inline: 0;\n"
        r"  \}",
        "  .search-related-modal__graph {\n"
        "    min-height: 0;\n"
        f"    aspect-ratio: 1 / {PHI};\n"
        "    padding-inline: 0;\n"
        "  }",
        css,
        count=1,
    )
    css_path.write_text(css, encoding="utf-8")

    html = html_path.read_text(encoding="utf-8")
    html, intro_count = re.subn(
        r'(?ms)^\s*<p class="search-related-modal__intro">.*?</p>',
        "\n" + HTML_INTRO,
        html,
        count=1,
    )
    if intro_count != 1:
        raise RuntimeError("Could not replace related modal intro")

    html, legend_count = re.subn(
        r'(?ms)^\s*<div class="search-related-modal__legend" aria-hidden="true">.*?</div>',
        "\n" + HTML_LEGEND,
        html,
        count=1,
    )
    if legend_count != 1:
        raise RuntimeError("Could not replace related modal legend")

    html_path.write_text(html, encoding="utf-8")

    print("Patched:")
    print(f"  {js_path}")
    print(f"  {css_path}")
    print(f"  {html_path}")
    print("\nRelated spiral v6.3 patch complete.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="WantToKnow repo root (default: current directory)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create .pre-v6.3 backup copies",
    )
    args = parser.parse_args()
    patch(args.repo.resolve(), not args.no_backup)


if __name__ == "__main__":
    main()
