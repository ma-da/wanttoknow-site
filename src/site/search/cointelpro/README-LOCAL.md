# COINTELPRO Search App — Local Build

This folder is a near-clone of the existing MKULTRA static search app,
adapted to the canonical COINTELPRO page IDs and JPEG image set.

## Expected final structure

```text
cointelpro/
├── index.html
├── images/
│   ├── 00001.jpg
│   └── ...
├── thumbs/
│   ├── 00001-thumb.jpg
│   └── ...
├── assets/
│   ├── css/
│   │   └── cointelpro-search.css
│   ├── js/
│   │   └── cointelpro-search.js
│   └── data/
│       ├── cointelpro_manifest.json
│       └── cointelpro_page_index.jsonl
└── scripts/
    └── build-cointelpro-index.py
```

## 1. Build browser search data

From WSL:

```bash
python3 \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/scripts/build-cointelpro-index.py \
  --source /mnt/c/datasources/cointelpro-set/enriched/cointelpro_pages_search_baseline_v1.jsonl.gz \
  --app-root /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro
```

## 2. Copy the optimized page images

```bash
mkdir -p \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/images \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/thumbs

rsync -ah --info=progress2 \
  /mnt/c/datasources/cointelpro-set/site/web/pages/ \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/images/

rsync -ah --info=progress2 \
  /mnt/c/datasources/cointelpro-set/site/thumbs/ \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/thumbs/
```

## 3. Verify counts

```bash
find /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/images \
  -maxdepth 1 -type f -name '*.jpg' | wc -l

find /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/thumbs \
  -maxdepth 1 -type f -name '*-thumb.jpg' | wc -l

wc -l \
  /mnt/c/datasources/wanttoknow-site/src/site/search/cointelpro/assets/data/cointelpro_page_index.jsonl
```

For the current corpus, all three should report 14,402.

## 4. Launch the WantToKnow.info local dev server

```bash
cd /mnt/c/datasources/wanttoknow-site
./scripts/start-dev.sh
```

Open the COINTELPRO route reported by your local server, normally:

```text
http://localhost:<port>/search/cointelpro/
```

Do not open index.html directly with `file://`; the browser will block the
JSON/JSONL `fetch()` calls.

## 5. Smoke tests

Try:

- `Black Panther Party`
- `informant`
- `disrupt neutralize`
- `1969`
- a known `document_id`
- `1` or `00001`

Check:

- thumbnails load;
- "Inspect full image" opens the matching 1575px JPG;
- "Read transcription" opens the right OCR text;
- page/document counts animate correctly;
- search snippets highlight the query;
- no errors appear in the browser console.

## JPG vs WebP

JPEG is intentional for this corpus. The page images are already resized and
optimized for web use, and thumbnails are JPEG as well. The app reads filenames
from the generated index, so no WebP conversion is required.
