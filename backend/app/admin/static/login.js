(() => {
  "use strict";

  const form = document.getElementById("admin-login-form");
  const accessKey = document.getElementById("access-key");
  const keyFile = document.getElementById("key-file");
  const status = document.getElementById("login-status");

  function requestedNext() {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("next") || "/admin/articles";
    if (!value.startsWith("/admin") || value.startsWith("//")) {
      return "/admin/articles";
    }
    return value;
  }

  function setStatus(message, isError = false) {
    status.textContent = message;
    if (isError) status.dataset.error = "true";
    else delete status.dataset.error;
  }

  async function authenticate(secret) {
    const value = String(secret || "").trim();
    if (!value) {
      setStatus("Choose a valid key file or enter an access key.", true);
      return;
    }

    setStatus("Checking access…");
    form.querySelector("button").disabled = true;
    keyFile.disabled = true;

    try {
      const response = await fetch("/api/admin/login", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        cache: "no-store",
        body: JSON.stringify({
          access_key: value,
          next: requestedNext(),
        }),
      });

      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(body?.detail || "Access denied");
      }

      accessKey.value = "";
      keyFile.value = "";
      window.location.assign(body?.redirect || requestedNext());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Unable to sign in", true);
      form.querySelector("button").disabled = false;
      keyFile.disabled = false;
      accessKey.focus();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    authenticate(accessKey.value);
  });

  keyFile.addEventListener("change", async () => {
    const file = keyFile.files?.[0];
    if (!file) return;
    if (file.size > 4096) {
      setStatus("Key file is unexpectedly large.", true);
      keyFile.value = "";
      return;
    }

    try {
      const text = await file.text();
      await authenticate(text);
    } catch {
      setStatus("Unable to read key file.", true);
      keyFile.value = "";
    }
  });
})();
