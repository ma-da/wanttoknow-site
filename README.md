# WantToKnow.info

Source repository for the modern WantToKnow.info website, operated by the **Public Education and Empowerment Resource Service (PEERS)**.

WantToKnow.info is a public-interest information archive and educational website. This repository contains the application code, site source, canonical article data, templates, administrative tools, and build scripts used to generate and operate the site.

## Architecture

The site is intentionally built around a small, auditable stack:

- **nginx** serves the public static site and reverse-proxies application routes.
- **FastAPI / Python** provides backend services.
- **SQLite** is used for local/admin application data where appropriate.
- **HTML, CSS, and JavaScript** provide the public interface without a large frontend framework.
- **Git / GitHub** provides source history and the promotion path from development to production.
- Large media collections and runtime state are kept outside normal Git history.

The public site is served from an atomic `current` release symlink. A deployment creates and validates a new release first, then switches `current` in one operation. If post-switch smoke tests fail, the deployer restores the previous release.

The public Python environment is durable at `/srv/wanttoknow/runtime/.venv` and is intentionally independent of individual releases. Releases contain site/application source and release-specific derived data rather than a duplicate virtual environment.

## Repository layout

The important top-level paths are:

```text
backend/          FastAPI application and admin backend
config/           Site/application configuration
scripts/          Build, audit, migration, and deployment utilities
src/
  site/           Public website source and canonical site data
  content/        Source content used by site builders
  data/           Additional source data
  templates/      Source templates
templates/        Project-level templates where applicable
```

Within `src/site/`:

```text
assets/           CSS, JavaScript, graphics, and other public assets
data/             Canonical and derived site data
news/             Generated news/article pages
search/           Search portals and related resources
topics/           Topic landing/index pages
```

## Canonical news data

The canonical news/article source is:

```text
src/site/data/wtk_articles_master.jsonl
```

Derived article indexes, relationship data, archive statistics, topic/category pages, and static news pages are generated from canonical source data by scripts in `scripts/`.

Generated outputs should not be hand-edited when an authoritative source or builder exists.

## Article administration

The internal article editor uses SQLite as its editable working state.

Typical editorial flow:

```text
Edit or create article
        ↓
Save Draft
        ↓
SQLite working state only
        ↓
Publish
        ↓
validate + rebuild article outputs
        ↓
commit/push source changes to dev
```

A publication is fail-closed. Before publishing, the admin verifies that its Git worktree is clean and synchronized with `origin/dev`. Unrelated source changes are not silently included in article publication commits.

### Article images

Article images use stable filenames and live in a single canonical public media tree:

```text
src/site/assets/images/article-images/{article_id}i.jpg
src/site/assets/images/article-thumbs/{article_id}-thumb.jpg
```

They are deliberately excluded from normal Git history and from repeated release copies.

While editing, a new upload may exist temporarily in private staging. When **Publish** succeeds, the processed image is atomically added, replaced, or removed in the live canonical media directory. The public URL remains stable.

This media behavior is intentionally different from code/content promotion: article image changes become live when the editor presses Publish, while page/data/code changes continue through `dev → main → deployment`.

## Branch and release workflow

The normal source promotion path is:

```text
admin/editorial work
        ↓
dev
        ↓
review and testing
        ↓
Pull Request
        ↓
main
        ↓
production deployment
```

### `dev`

`dev` is the integration branch.

Production-admin article publications create narrow, auditable commits on `dev`. Other tested site development can also be integrated here before release.

### `main`

`main` is the only Git branch from which a live site release may be built.

Changes should reach `main` through a deliberate merge or Pull Request from `dev`. Direct force-pushes to `main` should be disabled.

### Deployment

The production deployment script:

1. fetches `origin/main`;
2. identifies the exact main commit to deploy;
3. creates a fresh candidate release from that commit;
4. attaches durable media resources without duplicating their bytes;
5. rebuilds article-derived and search-derived outputs from the exact `main` source;
6. validates the candidate;
7. atomically switches the public `current` symlink;
8. restarts the public FastAPI service;
9. performs local and HTTPS smoke tests; and
10. automatically restores the previous release if post-switch validation fails.

A deployment record inside each release identifies the exact Git commit used.

## Generated and durable files

The repository intentionally does not track every file used at runtime.

Examples generally excluded from Git include:

- Python virtual environments and caches;
- admin SQLite databases, sessions, credentials, and runtime state;
- generated news HTML;
- large article-image and thumbnail collections;
- large MKULTRA image collections;
- release-local generated search databases and related-content maps;
- temporary publication workspaces and rollback files;
- historical local backup files.

This keeps Git focused on material needed to reconstruct and understand the application rather than using it as a binary backup system.

## Development

Create and activate a Python virtual environment using the dependency set appropriate to the current backend, then run the FastAPI application from the backend directory.

A common local development pattern is:

```bash
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The repository also contains build and development helper scripts under `scripts/`. Review a script before running it against canonical data, especially migration and patch utilities.

## Build and search pipeline

Production releases rebuild derived article and search artifacts from the exact `origin/main` source:

```bash
python scripts/build-news-derived.py
python scripts/build-search-corpus.py
python scripts/build-search-db.py
python scripts/build-related-map.py
python scripts/build-news-articles.py --all
python scripts/build-category-pages.py
python scripts/build-topic-pages.py
```

The search pipeline is intentionally reproducible. Canonical JSONL corpora and the persistent universal reference registry are retained in Git; the SQLite FTS5 database and universal related-content map are derived per release.

The public FastAPI search router resolves its search database and related-content map relative to the active release. As a result, an atomic release rollback also rolls back the search index to the version built for that release.

Large article images and MKULTRA image collections remain durable shared media and are not duplicated into every release.

## Portable maintenance utilities

Repository utilities should derive their normal repository paths from their own location or accept a `--site-root` / `--repo` override. Machine-specific paths such as `/mnt/c/...` must not be required for production builds.

Utilities that consume source material stored outside the repository must require that source explicitly. For example:

```bash
python scripts/update-posted-dates.py --posted-csv /path/to/Article-Posted.csv
python scripts/build-markdown-pages.py --source-dir /path/to/policy-markdown
```

These external-input maintenance utilities are not part of the automatic production deployment pipeline.

## Security model

Operational secrets must never be committed.

In particular, Git should not contain:

- access keys or session data;
- `.env` files;
- private SSH keys;
- TLS/private key material;
- production SQLite runtime databases;
- admin authentication configuration;
- temporary image uploads or publication workspaces.

The public FastAPI application binds only to localhost and is exposed through nginx. Admin application ports should likewise remain bound to localhost and be exposed only through the intended authenticated HTTPS route.

Before committing, review:

```bash
git status
git diff
git diff --cached
```

## Rollback

Deployments retain the previous release target so the `current` symlink can be switched back quickly.

Application rollback and media history are separate concerns. Article media is maintained in its canonical media storage and is not duplicated into every release.

## Contributing / maintenance

For normal maintenance:

1. work on `dev`;
2. keep the tree clean and commits focused;
3. test changes before promotion;
4. merge `dev` to `main` deliberately;
5. deploy the exact `origin/main` commit;
6. confirm the public smoke tests after deployment.

Avoid editing generated output directly when the same change belongs in canonical data, templates, CSS/JS source, or a builder.

## License and content

Website code, archived source material, editorial summaries, and third-party source content may have different rights and reuse requirements. Do not assume that the presence of material in this repository grants unrestricted rights to redistribute underlying third-party content.

For information about WantToKnow.info and PEERS, see the public website.
