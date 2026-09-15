# WantToKnow.info

Source repository for the modern WantToKnow.info website, operated by the **Public Education and Empowerment Resource Service (PEERS)**.

WantToKnow.info is a public-interest information archive and educational website. This repository contains the application code, site source, canonical article data, templates, administrative tools, and build scripts used to generate and operate the site.

## Architecture

The production site intentionally uses a small, direct architecture:

- **nginx** serves the public static site and reverse-proxies application routes.
- **FastAPI / Python** provides the public API and administrative application.
- **SQLite** is used for persistent application data where appropriate.
- **HTML, CSS, and JavaScript** provide the public interface without a large frontend framework.
- **Git / GitHub** records known-good live changes on the `dev` branch.
- Mutable application state is kept outside the Git working tree.

### Production filesystem

The canonical production layout is:

```text
/srv/wanttoknow/
├── site/       canonical Git working tree
├── venv/       shared Python virtual environment
├── data/       persistent application data
└── backups/    rollback and configuration backups
```

Production configuration lives outside the repository:

```text
/etc/wanttoknow/wanttoknow.env
/etc/nginx/sites-available/wanttoknow
/etc/systemd/system/wanttoknow.service
/etc/systemd/system/wtk-admin.service
```

nginx serves the public site from `/srv/wanttoknow/site/src/site`.

Both FastAPI services run from `/srv/wanttoknow/site/backend` and share `/srv/wanttoknow/venv`. The public application listens locally on port `8000`; the administrative application listens locally on port `8002`.

Persistent application state belongs under `/srv/wanttoknow/data`.

There is no production `current` symlink, duplicated release tree, separate admin checkout, or release-specific Python environment.

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

This media behavior is intentionally different from code/content promotion: article image changes become live when the editor presses Publish, while page, data, and code changes are tested live and then committed and pushed to `dev` once verified.

## Live workflow

The production server uses a single canonical Git working tree:

```text
/srv/wanttoknow/site
```

The working tree normally tracks the `dev` branch.

The operational workflow is:

```text
make or publish a change on the live site
        ↓
test the live result
        ↓
review git diff / git status
        ↓
commit the known-good change
        ↓
push to GitHub dev
```

The live site is where changes are first validated. GitHub `dev` records the verified working state afterward.

`main` is not currently part of the routine live-update workflow. Any future change to the branch or deployment strategy should be deliberate and documented before new deployment machinery is introduced.

Because `/srv/wanttoknow/site` is the live working tree:

- keep it clean between tasks;
- review `git diff` before committing;
- avoid broad resets or cleans when unrelated work may exist;
- test affected public and admin functionality before pushing;
- keep mutable databases, logs, secrets, and runtime state outside Git.

### Basic production checks

```bash
git status --short --branch

systemctl is-active nginx
systemctl is-active wanttoknow.service
systemctl is-active wtk-admin.service

curl -fsS http://127.0.0.1:8000/api/health
```

Before changing nginx configuration:

```bash
sudo nginx -t
```

After verified changes are committed and pushed, the production tree should be synchronized with `origin/dev`.

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
