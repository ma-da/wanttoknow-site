class WtkNewsletterFeed extends HTMLElement {
  connectedCallback() {
    if (this.dataset.loaded === "true") return;
    this.dataset.loaded = "true";
    this.classList.add("newsletter-archive__list");
    this.load();
  }

  async load() {
    const limit = Math.max(
      1,
      Math.min(Number.parseInt(this.getAttribute("limit") || "8", 10) || 8, 20),
    );

    try {
      const response = await fetch("/data/newsletters.json", {cache: "no-cache"});
      if (!response.ok) throw new Error(`Newsletter feed failed (${response.status})`);

      const data = await response.json();
      const records = Array.isArray(data?.newsletters)
        ? [...data.newsletters]
            .sort(
              (a, b) =>
                String(b.issue_date || "").localeCompare(String(a.issue_date || "")) ||
                String(b.newsletter_id || "").localeCompare(String(a.newsletter_id || "")),
            )
            .slice(0, limit)
        : [];

      this.replaceChildren();

      if (!records.length) {
        const link = document.createElement("a");
        link.className = "support-secondary-link";
        link.href = "/newsletter-archive.html";
        link.textContent = "View newsletter archive";
        this.append(link);
        return;
      }

						for (const record of records) {
								const issueDate = String(
										record.issue_date || ""
								).trim();

								if (
										!/^\d{4}-\d{2}-\d{2}$/.test(issueDate)
								) {
										continue;
								}

								const newsletterId = String(
										record.newsletter_id || issueDate
								).trim();

								if (!newsletterId) {
										continue;
								}

								const headlines = Array.isArray(
										record.headlines
								)
										? record.headlines
														.map(value =>
																String(value || "").trim()
														)
														.filter(Boolean)
														.slice(0, 3)
										: [];

								if (!headlines.length) {
										continue;
								}

								const link =
										document.createElement("a");

								link.className =
										"newsletter-archive__item";

								link.href =
										`/newsletter-archive.html?issue=${
												encodeURIComponent(newsletterId)
										}`;

								const headline =
										document.createElement("span");

								headline.className =
										"newsletter-archive__title";

								headline.textContent =
										headlines.join(", ");

								const time =
										document.createElement("time");

								time.dateTime = issueDate;
								time.textContent =
										this.formatDate(issueDate);

								link.append(
										headline,
										time
								);

								this.append(link);
						}
    } catch (error) {
      this.replaceChildren();
      const link = document.createElement("a");
      link.className = "support-secondary-link";
      link.href = "/newsletter-archive.html";
      link.textContent = "View newsletter archive";
      this.append(link);
    }
  }

  formatDate(value) {
    const parts = value.split("-").map(Number);
    if (parts.length !== 3 || parts.some(Number.isNaN)) return value;

    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return new Intl.DateTimeFormat("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(date);
  }
}

if (!customElements.get("wtk-newsletter-feed")) {
  customElements.define("wtk-newsletter-feed", WtkNewsletterFeed);
}
