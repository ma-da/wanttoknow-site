(() => {
  "use strict";

  const QUALIFY_MS = 16_000;

  let remainingMs = QUALIFY_MS;
  let startedAt = null;
  let recorded = false;

  function startTimer() {
    if (
      recorded ||
      document.visibilityState !== "visible" ||
      startedAt !== null
    ) {
      return;
    }

    startedAt = performance.now();
  }

  function pauseTimer() {
    if (startedAt === null) {
      return;
    }

    remainingMs -= (
      performance.now() -
      startedAt
    );

    startedAt = null;
  }

  async function recordPageview() {
    if (recorded) {
      return;
    }

    recorded = true;

    try {
      await fetch(
        "/api/pageview",
        {
          method: "POST",

          headers: {
            "Content-Type":
              "application/json",
          },

          body: JSON.stringify({
            path: window.location.pathname,
          }),

          keepalive: true,
        }
      );

    } catch {
      /*
       * Analytics failure must never
       * interfere with the page.
       */
    }
  }

  function checkTimer() {
    if (
      recorded ||
      document.visibilityState !== "visible"
    ) {
      return;
    }

    if (startedAt === null) {
      startTimer();
    }

    const elapsed =
      performance.now() -
      startedAt;

    if (
      remainingMs - elapsed <= 0
    ) {
      recordPageview();
      return;
    }

    window.setTimeout(
      checkTimer,
      Math.min(
        remainingMs - elapsed,
        1000
      )
    );
  }

  document.addEventListener(
    "visibilitychange",
    () => {
      if (
        document.visibilityState ===
        "visible"
      ) {
        startTimer();
        checkTimer();

      } else {
        pauseTimer();
      }
    }
  );

  startTimer();
  checkTimer();
})();
