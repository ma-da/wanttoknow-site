#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
JS_PATH = ROOT / "src/site/assets/js/search.js"
CSS_PATH = ROOT / "src/site/assets/css/search.css"

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
     * desktop = phi : 1
     * mobile  = 1 : phi
     *
     * The spiral exists only in node placement. Relationship edges are
     * independent spokes from the center target to each related record.
     */
    const measuredWidth = dom.relatedGraph.getBoundingClientRect().width;
    const isMobile = measuredWidth > 0 && measuredWidth < 640;

    const width = isMobile ? 742 : 1200;
    const height = isMobile ? 1200 : 742;
    const centerX = width / 2;
    const centerY = height / 2;

    const phi = (1 + Math.sqrt(5)) / 2;
    const spiralB = Math.log(phi) / Math.PI;
    const startAngle = -Math.PI / 2;

    /* Extra clearance for the larger center target. */
    const rMin = isMobile ? 205 : 195;
    const rMax = isMobile ? 505 : 500;
    const xScale = isMobile ? 0.58 : 1.0;
    const yScale = isMobile ? 1.0 : 0.58;

    /*
     * Resolve the actual brand colors before interpolation. D3 cannot
     * interpolate raw var(--...) strings, but it can interpolate the
     * computed CSS color values.
     */
    const rootStyle = getComputedStyle(document.documentElement);
    const innerColor = rootStyle
      .getPropertyValue("--color-brand-lavender")
      .trim() || "#d7c9ed";
    const outerColor = rootStyle
      .getPropertyValue("--color-brand-tan-light")
      .trim() || "#eee1cd";

    const fillForProgress = d3.interpolateLab(innerColor, outerColor);

    const childNodes = related.map((record, index) => {
      const count = Math.max(1, related.length);
      const t = count === 1 ? 0 : index / (count - 1);

      /*
       * Strongest relationships remain larger and nearer the target.
       * The same golden-ratio spiral geometry is retained from v6.3.
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

      const fillColor = fillForProgress(t);
      const parsedColor = d3.color(fillColor);
      const edgeColor = parsedColor
        ? parsedColor.darker(0.55).formatHex()
        : fillColor;

      return {
        ...record,
        rank: index + 1,
        x: centerX + Math.cos(angle) * radius * xScale,
        y: centerY + Math.sin(angle) * radius * yScale,
        nodeWidth: widthPx,
        nodeHeight: heightPx,
        fontSize: fontPx,
        maxLabelChars: Math.max(14, charsPerLine * lineCount - 1),
        fillColor,
        edgeColor
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
      .range([6.25, 0.9])
      .clamp(true);

    const edgeOpacity = d3
      .scaleLinear()
      .domain([1, Math.max(24, childNodes.length)])
      .range([0.64, 0.20])
      .clamp(true);

    /*
     * Every relationship is target -> child. No child-to-child edge is
     * drawn, so the graph cannot imply relationships between neighboring
     * spiral nodes.
     */
    const edges = childNodes.map((node) => ({
      source: targetPoint,
      target: node,
      rank: node.rank,
      edgeColor: node.edgeColor
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

    svg
      .append("g")
      .attr("class", "search-related-graph__edges")
      .selectAll("line")
      .data(edges)
      .join("line")
      .attr("class", "search-related-edge")
      .attr("x1", centerX)
      .attr("y1", centerY)
      .attr("x2", (edge) => edge.target.x)
      .attr("y2", (edge) => edge.target.y)
      .attr("stroke", (edge) => edge.edgeColor)
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
      .attr("transform", `translate(${centerX},${centerY})`)
      .on("mouseenter.raise", function () {
        d3.select(this).raise();
      })
      .on("focus.raise", function () {
        d3.select(this).raise();
      });

    targetLink
      .append("title")
      .text(`Open: ${target.title || "Untitled result"}`);

    const targetBody = targetLink
      .append("g")
      .attr("class", "search-related-node__body");

    targetBody
      .append("circle")
      .attr("class", "search-related-node__target-circle")
      .attr("r", 72);

    const targetForeign = targetBody
      .append("foreignObject")
      .attr("x", -59)
      .attr("y", -52)
      .attr("width", 118)
      .attr("height", 104);

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
      .text(relatedLabel(target.title, 56));

    /* ------------------------------------------------------------------
       Related nodes: square-cornered buttons that refocus the graph.
       ------------------------------------------------------------------ */

    const childGroups = nodeLayer
      .selectAll("g.search-related-node--child")
      .data(childNodes)
      .join("g")
      .attr("class", "search-related-node search-related-node--child")
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
      .on("mouseenter.raise", function () {
        /* A hovered node must visually sit above every overlap. */
        d3.select(this).raise();
      })
      .on("focus.raise", function () {
        d3.select(this).raise();
      })
      .on("mouseleave.raise", () => {
        /* Return the target to the top of the normal stacking order. */
        targetLink.raise();
      })
      .on("blur.raise", () => {
        targetLink.raise();
      })
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
      .attr("rx", 0)
      .attr("ry", 0)
      .attr("fill", (node) => node.fillColor);

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

    childBodies
      .append("text")
      .attr("class", "search-related-node__rank")
      .attr("x", (node) => node.nodeWidth / 2 - 7)
      .attr("y", (node) => -node.nodeHeight / 2 + 11)
      .attr("text-anchor", "end")
      .text((node) => node.rank);

    /* Keep the target visible by default. Hover/focus may temporarily raise a child. */
    targetLink.raise();
  }


'''

CSS_REPLACEMENT = r'''/* Golden-mean related graph ------------------------------------------------ */

.search-related-modal__graph {
  position: relative;
  min-height: 0;
  aspect-ratio: 1.61803398875 / 1;
  padding: 0 var(--space-2);
}

.search-related-modal__graph.is-loading {
  opacity: 0.72;
}

.search-related-modal__state {
  display: grid;
  min-height: 28rem;
  place-items: center;
  margin: 0;
  color: var(--color-text-muted);
  font-size: var(--font-size-sm);
  text-align: center;
}

.search-related-modal__state--error {
  color: var(--color-danger, var(--color-text));
}

.search-related-graph {
  width: 100%;
  height: 100%;
  display: block;
  overflow: visible;
}

.search-related-edge {
  stroke-linecap: round;
  pointer-events: none;
}

.search-related-node {
  outline: none;
}

.search-related-node--target {
  color: inherit;
  text-decoration: none;
  cursor: pointer;
}

.search-related-node--child {
  cursor: pointer;
}

.search-related-node__body {
  transform-box: fill-box;
  transform-origin: center;
  transition:
    transform var(--motion-duration-fast) var(--motion-easing-standard),
    filter var(--motion-duration-fast) var(--motion-easing-standard);
}

.search-related-node:hover .search-related-node__body,
.search-related-node:focus-visible .search-related-node__body,
.search-related-node:focus .search-related-node__body {
  transform: translateY(-6px);
  filter: drop-shadow(0 0.3rem 0.38rem rgba(19, 15, 27, 0.2));
}

/* No resting borders. A thin outline appears only on interaction. */
.search-related-node__target-circle {
  fill: var(--color-brand-lavender);
  stroke: transparent;
  stroke-width: 0;
  vector-effect: non-scaling-stroke;
  transition: stroke-width var(--motion-duration-fast) var(--motion-easing-standard);
}

.search-related-node--target:hover .search-related-node__target-circle,
.search-related-node--target:focus-visible .search-related-node__target-circle,
.search-related-node--target:focus .search-related-node__target-circle {
  stroke: var(--color-brand-purple-dark);
  stroke-width: 1.25;
}

.search-related-node__target-content {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.2rem;
  overflow: hidden;
  color: var(--color-text);
  font-family: var(--font-family-body);
  line-height: 1.08;
  text-align: center;
}

.search-related-node__target-kicker {
  color: var(--color-brand-purple-dark);
  font-family: var(--font-family-mono);
  font-size: 8.5px;
  font-weight: var(--font-weight-bold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.search-related-node__target-title {
  display: block;
  max-width: 100%;
  overflow: hidden;
  font-size: 10.5px;
  font-weight: var(--font-weight-bold);
}

.search-related-node__rect {
  stroke: transparent;
  stroke-width: 0;
  vector-effect: non-scaling-stroke;
  transition:
    stroke var(--motion-duration-fast) var(--motion-easing-standard),
    stroke-width var(--motion-duration-fast) var(--motion-easing-standard);
}

.search-related-node--child:hover .search-related-node__rect,
.search-related-node--child:focus-visible .search-related-node__rect,
.search-related-node--child:focus .search-related-node__rect {
  stroke: var(--color-brand-purple-dark);
  stroke-width: 1.15;
}

.search-related-node__label {
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
}

.search-related-node__rank {
  fill: var(--color-text-muted);
  font-family: var(--font-family-mono);
  font-size: 7px;
  font-weight: var(--font-weight-bold);
  pointer-events: none;
}

'''


def backup(path: Path) -> None:
    backup_path = path.with_name(path.name + ".pre-v6.4")
    if not backup_path.exists():
        shutil.copy2(path, backup_path)


def replace_js(text: str) -> str:
    pattern = re.compile(
        r"  function drawRelatedGraph\(payload\) \{.*?(?=  async function focusRelatedGraph\()",
        re.S,
    )
    updated, count = pattern.subn(JS_REPLACEMENT, text, count=1)
    if count != 1:
        raise RuntimeError("Could not uniquely replace drawRelatedGraph().")
    return updated


def replace_css(text: str) -> str:
    pattern = re.compile(
        r"/\* Golden-mean related graph -+ \*/.*?(?=\.search-related-modal__legend \{)",
        re.S,
    )
    updated, count = pattern.subn(CSS_REPLACEMENT, text, count=1)
    if count != 1:
        raise RuntimeError("Could not uniquely replace the related-graph CSS block.")

    # Tighten vertical modal spacing without disturbing horizontal gutters.
    replacements = [
        (
            ".search-related-modal {\n  position: fixed;\n  inset: 0;\n  z-index: var(--layer-modal);\n  display: grid;\n  place-items: center;\n  padding: var(--space-4);\n}",
            ".search-related-modal {\n  position: fixed;\n  inset: 0;\n  z-index: var(--layer-modal);\n  display: grid;\n  place-items: center;\n  padding: var(--space-2) var(--space-4);\n}",
        ),
        (
            "max-height: calc(100vh - (2 * var(--space-4)));",
            "max-height: calc(100vh - (2 * var(--space-2)));",
        ),
        (
            "padding: var(--space-4) var(--space-4) 0;",
            "padding: var(--space-2) var(--space-4) 0;",
        ),
        (
            "margin: var(--space-3) var(--space-4) 0;",
            "margin: var(--space-1) var(--space-4) 0;",
        ),
        (
            "padding: 0 var(--space-4) var(--space-4);",
            "padding: 0 var(--space-4) var(--space-2);",
        ),
    ]

    for old, new in replacements:
        if old in updated:
            updated = updated.replace(old, new, 1)

    # Tighten mobile vertical padding too.
    updated = updated.replace(
        ".search-related-modal {\n    padding: var(--space-2);\n  }",
        ".search-related-modal {\n    padding: var(--space-1) var(--space-2);\n  }",
        1,
    )
    updated = updated.replace(
        "max-height: calc(100vh - (2 * var(--space-2)));",
        "max-height: calc(100vh - (2 * var(--space-2)));",
        1,
    )
    updated = updated.replace(
        ".search-related-modal__header {\n    padding: var(--space-3) var(--space-3) 0;\n  }",
        ".search-related-modal__header {\n    padding: var(--space-2) var(--space-3) 0;\n  }",
        1,
    )
    updated = updated.replace(
        ".search-related-modal__graph {\n    min-height: 0;\n    aspect-ratio: 1 / 1.61803398875;\n    padding-inline: 0;\n  }",
        ".search-related-modal__graph {\n    min-height: 0;\n    aspect-ratio: 1 / 1.61803398875;\n    padding: 0;\n  }",
        1,
    )

    return updated


def main() -> None:
    for path in (JS_PATH, CSS_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)

    backup(JS_PATH)
    backup(CSS_PATH)

    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")

    JS_PATH.write_text(replace_js(js), encoding="utf-8")
    CSS_PATH.write_text(replace_css(css), encoding="utf-8")

    print("Applied related-graph v6.4 visual refinement.")
    print(f"Updated: {JS_PATH}")
    print(f"Updated: {CSS_PATH}")
    print("Backups: *.pre-v6.4")
    print("No database rebuild or backend restart is required.")


if __name__ == "__main__":
    main()
