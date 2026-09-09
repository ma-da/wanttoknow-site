from pathlib import Path
import markdown

SITE_ROOT = Path(
    "/mnt/c/datasources/wanttoknow-site/src/site"
)

PAGES = [
    {
        "source": Path(
            "/mnt/c/Users/fixin/OneDrive/Desktop/PEERSwork/Business/terms_of_use.md"
        ),
        "output": SITE_ROOT / "terms/index.html",
        "title": "Terms of Use",
        "description": "Terms of use for WantToKnow.info.",
        "canonical": "https://www.wanttoknow.info/terms/",
    },
    {
        "source": Path(
            "/mnt/c/Users/fixin/OneDrive/Desktop/PEERSwork/Business/privacy_policy.md"
        ),
        "output": SITE_ROOT / "about/privacy/index.html",
        "title": "Privacy Policy",
        "description": "Privacy policy for WantToKnow.info.",
        "canonical": "https://www.wanttoknow.info/about/privacy/",
    },
    {
        "source": Path(
            "/mnt/c/Users/fixin/OneDrive/Desktop/PEERSwork/Business/AI_policy.md"
        ),
        "output": SITE_ROOT / "about/ai/index.html",
        "title": "How We Use AI",
        "description": "WantToKnow.info policy and principles for the use of artificial intelligence.",
        "canonical": "https://www.wanttoknow.info/about/ai/",
    },
]


def markdown_to_html(source: Path) -> str:
    text = source.read_text(
        encoding="utf-8"
    )

    return markdown.markdown(
        text,
        extensions=[
            "extra",
            "sane_lists",
        ],
        output_format="html5",
    )


def make_page(
    title: str,
    description: str,
    canonical: str,
    content: str,
) -> str:

    return f"""<!DOCTYPE html>
<html lang="en">

<head>
  <meta charset="utf-8">

  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >

  <meta
    name="theme-color"
    content="#7658f6"
  >

  <meta
    name="color-scheme"
    content="light"
  >

  <title>
    {title} | WantToKnow.info
  </title>

  <meta
    name="description"
    content="{description}"
  >

  <meta
    name="robots"
    content="index, follow, max-image-preview:large, max-snippet:-1"
  >

  <link
    rel="canonical"
    href="{canonical}"
  >

  <link
    rel="icon"
    type="image/x-icon"
    href="/assets/images/favicon.ico"
  >

  <link
    rel="icon"
    type="image/png"
    sizes="32x32"
    href="/assets/images/favicon-32x32.png"
  >

  <link
    rel="apple-touch-icon"
    sizes="180x180"
    href="/assets/images/apple-touch-icon.png"
  >

  <link
    rel="manifest"
    href="/site.webmanifest"
  >

  <link
    rel="stylesheet"
    href="/assets/css/global.css"
  >

  <style>
    .text-page {{
      padding-block:
        clamp(1.75rem, 3vw, 2.75rem);
    }}

    .text-page__content {{
      width: min(100%, 50.625rem);
      margin-inline: auto;
    }}

    .text-page__content > :first-child {{
      margin-top: 0;
    }}

    .text-page__content h1 {{
      font-size:
        clamp(2.75rem, 7vw, 5rem);

      line-height: 0.98;
      letter-spacing: -0.05em;
      text-wrap: balance;
    }}

    .text-page__content h2 {{
      margin-top: 2.5rem;
      font-size:
        clamp(1.6rem, 3vw, 2.3rem);

      line-height: 1.12;
      letter-spacing: -0.025em;
    }}

    .text-page__content h3 {{
      margin-top: 2rem;
    }}

    .text-page__content p,
    .text-page__content li {{
      line-height: 1.75;
    }}

    .text-page__content ul,
    .text-page__content ol {{
      padding-left: 1.5rem;
    }}

    .text-page__content blockquote {{
      margin-inline: 0;
      padding-left: 1.25rem;
      border-left:
        3px solid
        var(--color-border, #d8d2e3);
    }}
  </style>
</head>

<body>

  <a
    class="skip-link"
    href="#main-content"
  >
    Skip to main content
  </a>


  <!-- Dynamic global header -->
  <div
    id="global-header"
    data-global-header
  ></div>


  <main id="main-content">

    <article class="text-page">

      <div
        class="container text-page__content"
      >

{content}

      </div>

    </article>

  </main>


  <!-- Dynamic global footer -->
  <div
    id="global-footer"
    data-global-footer
  ></div>


  <script
    src="/assets/js/global.js"
    defer
  ></script>

</body>
</html>
"""


for page in PAGES:

    source = page["source"]
    output = page["output"]

    print(
        f"Converting: {source.name}"
    )

    if not source.exists():
        print(
            f"  ERROR: source not found: {source}"
        )
        continue

    content = markdown_to_html(
        source
    )

    html = make_page(
        page["title"],
        page["description"],
        page["canonical"],
        content,
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output.write_text(
        html,
        encoding="utf-8",
    )

    print(
        f"  → {output}"
    )