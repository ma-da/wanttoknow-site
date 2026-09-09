const DOT_ART_DATA_CACHE = new Map();

class WtkDotArt extends HTMLElement {
  constructor() {
    super();

    this.canvas = null;
    this.context = null;
    this.data = null;
    this.dots = [];
    this.params = null;
    this.phases = null;

    this.animationFrameId = null;
    this.resizeObserver = null;
    this.motionQuery = null;

    this.startedAt = 0;
    this.lastDrawTime = 0;
    this.running = false;
  }

  connectedCallback() {
    if (this.dataset.initialized === "true") {
      return;
    }

    this.dataset.initialized = "true";
    this.setAttribute("aria-hidden", "true");

    this.canvas = document.createElement("canvas");
    this.canvas.className = "dot-art__canvas";
    this.canvas.setAttribute("aria-hidden", "true");

    this.replaceChildren(this.canvas);

    this.context = this.canvas.getContext("2d");

    if (!this.context) {
      return;
    }

    this.motionQuery = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    );

    this.motionQuery.addEventListener(
      "change",
      this.handleMotionPreferenceChange
    );

    this.resizeObserver = new ResizeObserver(() => {
      if (!this.resizeCanvas()) {
        return;
      }

      if (this.data) {
        if (this.motionQuery.matches) {
          this.drawStaticFrame();
        } else {
          this.drawFrame(performance.now());
        }
      }
    });

    this.resizeObserver.observe(this);

    this.load();
  }

  disconnectedCallback() {
    this.stop();

    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }

    if (this.motionQuery) {
      this.motionQuery.removeEventListener(
        "change",
        this.handleMotionPreferenceChange
      );
    }
  }

  handleMotionPreferenceChange = () => {
    if (!this.data) {
      return;
    }

    if (this.motionQuery.matches) {
      this.stop();
      this.drawStaticFrame();
    } else {
      this.start();
    }
  };

  async load() {
    const src = this.getAttribute("src");

    if (!src) {
      console.error("wtk-dot-art requires a src attribute.");
      return;
    }

    try {
      let promise = DOT_ART_DATA_CACHE.get(src);

      if (!promise) {
        promise = fetch(src, {
          headers: {
            Accept: "application/json"
          }
        }).then((response) => {
          if (!response.ok) {
            throw new Error(
              `HTTP ${response.status} loading ${src}`
            );
          }

          return response.json();
        });

        DOT_ART_DATA_CACHE.set(src, promise);
      }

      this.data = await promise;

      if (!this.isConnected) {
        return;
      }

      this.dots = Array.isArray(this.data?.dots)
        ? this.data.dots
        : [];

      this.params = this.data?.params || {};

      if (!this.dots.length) {
        throw new Error(
          "Dot-art data contains no dots."
        );
      }

      this.preparePhases();
      this.resizeCanvas();

      if (this.motionQuery.matches) {
        this.drawStaticFrame();
      } else {
        this.start();
      }
    } catch (error) {
      DOT_ART_DATA_CACHE.delete(src);
      console.error("Dot-art animation failed:", error);
      this.dataset.error = "true";
    }
  }

  get targetFps() {
    const requested = Number(
      this.getAttribute("fps")
    );

    if (!Number.isFinite(requested)) {
      return 15;
    }

    return Math.min(
      30,
      Math.max(1, requested)
    );
  }

  resizeCanvas() {
    if (!this.canvas) {
      return false;
    }

    const rect = this.getBoundingClientRect();

    if (!rect.width || !rect.height) {
      return false;
    }

    const dpr = Math.min(
      window.devicePixelRatio || 1,
      2
    );

    const width =
      Math.round(rect.width * dpr);

    const height =
      Math.round(rect.height * dpr);

    if (
      this.canvas.width !== width
      || this.canvas.height !== height
    ) {
      this.canvas.width = width;
      this.canvas.height = height;
    }

    return true;
  }

  preparePhases() {
    const mode =
      this.params.animMode || "spiral";

    const phases =
      new Float32Array(this.dots.length);

    let minimum = Infinity;
    let maximum = -Infinity;

    for (
      let index = 0;
      index < this.dots.length;
      index += 1
    ) {
      const dot = this.dots[index];

      const phase =
        this.phaseOf(
          mode,
          dot.x,
          dot.y
        );

      phases[index] = phase;

      if (phase < minimum) {
        minimum = phase;
      }

      if (phase > maximum) {
        maximum = phase;
      }
    }

    const range =
      maximum - minimum || 1;

    for (
      let index = 0;
      index < phases.length;
      index += 1
    ) {
      phases[index] =
        (phases[index] - minimum)
        / range;
    }

    this.phases = phases;
  }

  phaseOf(mode, x, y) {
    if (mode === "horizontal") {
      return x;
    }

    if (mode === "vertical") {
      return y;
    }

    if (mode === "diagonal") {
      return (x + y) * 0.5;
    }

    if (mode === "radial") {
      const dx = x - 0.5;
      const dy = y - 0.5;

      return Math.sqrt(
        dx * dx + dy * dy
      );
    }

    const dx = x - 0.5;
    const dy = y - 0.5;

    const radius =
      Math.sqrt(
        dx * dx + dy * dy
      );

    const angle =
      Math.atan2(dy, dx)
      / (Math.PI * 2)
      + 0.5;

    return radius * 1.4 + angle * 0.5;
  }

  start() {
    if (
      this.running
      || !this.data
      || this.motionQuery?.matches
    ) {
      return;
    }

    this.running = true;
    this.startedAt = performance.now();
    this.lastDrawTime = 0;

    this.animationFrameId =
      requestAnimationFrame(
        this.frame
      );
  }

  stop() {
    this.running = false;

    if (this.animationFrameId !== null) {
      cancelAnimationFrame(
        this.animationFrameId
      );

      this.animationFrameId = null;
    }
  }

  frame = (now) => {
    if (!this.running) {
      this.animationFrameId = null;
      return;
    }

    this.animationFrameId =
      requestAnimationFrame(
        this.frame
      );

    const interval =
      1000 / this.targetFps;

    if (
      now - this.lastDrawTime
      < interval
    ) {
      return;
    }

    this.lastDrawTime =
      now
      - (
        (now - this.lastDrawTime)
        % interval
      );

    this.drawFrame(now);
  };

  drawStaticFrame() {
    this.draw({
      elapsed: 0,
      animate: false
    });
  }

  drawFrame(now) {
    this.draw({
      elapsed:
        (now - this.startedAt) / 1000,
      animate: true
    });
  }

  draw({ elapsed, animate }) {
    if (
      !this.canvas
      || !this.context
      || !this.params
      || !this.phases
      || !this.dots.length
    ) {
      return;
    }

    if (!this.resizeCanvas()) {
      return;
    }

    const context = this.context;
    const params = this.params;

    const width = this.canvas.width;
    const height = this.canvas.height;

    const side =
      Math.min(width, height)
      * (1 - 0.08 * 2);

    const offsetX =
      (width - side) / 2;

    const offsetY =
      (height - side) / 2;

    context.clearRect(
      0,
      0,
      width,
      height
    );

    const background =
      this.getAttribute("background")
      || params.background;

    if (
      background
      && background !== "transparent"
    ) {
      context.fillStyle = background;

      context.fillRect(
        0,
        0,
        width,
        height
      );
    }

    const sigma =
      Math.max(
        0.015,
        (params.wavelength ?? 0.44)
          * 0.5
          * (
            1.05
            - (params.sharpness ?? 0.55)
          )
      );

    const period =
      1 + 2 * sigma;

    const speed =
      params.speed ?? 0.15;

    const time =
      (
        (elapsed * speed)
        % period
        + period
      ) % period;

    const crest =
      time - sigma;

    const dotSize =
      params.dotSize ?? 1.4;

    const baseRadius =
      dotSize * (side / 600);

    const baseColor =
      this.parseHexColor(
        params.color || "#ffffff"
      );

    for (
      let index = 0;
      index < this.dots.length;
      index += 1
    ) {
      const dot = this.dots[index];

      let wave = 0;

      if (animate) {
        const difference =
          this.phases[index] - crest;

        wave =
          Math.exp(
            -(
              difference
              * difference
            )
            / (sigma * sigma)
          );
      }

      const scale =
        1 + wave * 1.3;

      const restOpacity =
        params.restOpacity ?? 0.4;

      const opacity =
        restOpacity
        + wave * (1 - restOpacity);

      const x =
        offsetX + dot.x * side;

      const y =
        offsetY + dot.y * side;

      const radius =
        baseRadius
        * (dot.s ?? 1)
        * scale;

      let red =
        baseColor[0];

      let green =
        baseColor[1];

      let blue =
        baseColor[2];

      if (
        params.sampleFromSource
        && Array.isArray(dot.c)
      ) {
        const brightness =
          1 + wave * 0.6;

        red =
          Math.min(
            255,
            dot.c[0] * brightness
          ) | 0;

        green =
          Math.min(
            255,
            dot.c[1] * brightness
          ) | 0;

        blue =
          Math.min(
            255,
            dot.c[2] * brightness
          ) | 0;
      }

      context.fillStyle =
        `rgba(${red},${green},${blue},${opacity})`;

      if (
        params.dotShape === "square"
      ) {
        context.fillRect(
          x - radius,
          y - radius,
          radius * 2,
          radius * 2
        );
      } else {
        context.beginPath();

        context.arc(
          x,
          y,
          radius,
          0,
          Math.PI * 2
        );

        context.fill();
      }
    }
  }

  parseHexColor(value) {
    const normalized =
      String(value)
        .replace("#", "")
        .padEnd(6, "0")
        .slice(0, 6);

    return [
      parseInt(
        normalized.slice(0, 2),
        16
      ) || 0,

      parseInt(
        normalized.slice(2, 4),
        16
      ) || 0,

      parseInt(
        normalized.slice(4, 6),
        16
      ) || 0
    ];
  }
}

if (!customElements.get("wtk-dot-art")) {
  customElements.define(
    "wtk-dot-art",
    WtkDotArt
  );
}
