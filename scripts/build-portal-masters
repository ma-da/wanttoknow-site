from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse
import csv
import hashlib
import html as html_lib
import json
import math
import re
import sys

try:
    from bs4 import BeautifulSoup, Comment
except ImportError as exc:
    raise SystemExit("Install dependency: python -m pip install beautifulsoup4 markdownify") from exc

try:
    from markdownify import markdownify as html_to_markdown
except ImportError as exc:
    raise SystemExit("Install dependency: python -m pip install beautifulsoup4 markdownify") from exc

SITE_ROOT = Path(__file__).resolve().parents[1]

DATA_ROOT = (
    SITE_ROOT
    / "src"
    / "site"
    / "data"
)

CORPUS_ROOT = (
    DATA_ROOT
    / "corpus"
)

SUBSTACK_RAW_ROOT = (
    DATA_ROOT
    / "substack_raws"
)

SUBSTACK_POSTS_DIR = (
    SUBSTACK_RAW_ROOT
    / "posts"
)

SUBSTACK_METADATA_CSV = (
    SUBSTACK_RAW_ROOT
    / "posts.csv"
)

YOUTUBE_RAW_ROOT = (
    DATA_ROOT
    / "youtube_raws"
)

YOUTUBE_SOURCE_JSON = (
    YOUTUBE_RAW_ROOT
    / "timestamped_youtube_database.json"
)


SUBSTACK_ORIGIN = (
    "https://wtkconsciousmedia.substack.com"
)

SUBSTACK_PUBLICATION = (
    "WTK Conscious Media"
)

YOUTUBE_CHANNEL_NAME = (
    "PEERS Conscious Media"
)


CHUNK_MIN = 260
CHUNK_TARGET = 290
CHUNK_MAX = 320


FILENAME_RE = re.compile(
    r"^(?P<id>\d+)\.(?P<slug>.+)\.html?$",
    re.I,
)

WORD_RE = re.compile(r"\S+")
WS_RE = re.compile(r"\s+")


def clean(value: Any) -> str:
    return WS_RE.sub(" ", "" if value is None else str(value)).strip()


def wc(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
            n += 1
    return n


def first(mapping: dict[str, Any] | None, *names: str) -> Any:
    if not mapping:
        return None
    lowered = {str(k).casefold(): v for k, v in mapping.items()}
    for name in names:
        value = lowered.get(name.casefold())
        if value is not None and clean(value):
            return value
    return None


def iso(value: Any) -> str | None:
    text = clean(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return text


def load_post_metadata(path: Path | None):
    by_id, by_slug = {}, {}
    if path is None:
        return by_id, by_slug
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            pid = first(row, "post_id", "post id", "id")
            slug = first(row, "slug", "post_slug", "post slug")
            if pid:
                by_id[clean(pid)] = row
            if slug:
                by_slug[clean(slug)] = row
    return by_id, by_slug


def humanize(slug: str) -> str:
    small = {"a","an","and","as","at","but","by","for","from","in","of","on","or","the","to","with"}
    acr = {"ai":"AI","cia":"CIA","fbi":"FBI","ufo":"UFO","uap":"UAP","us":"US"}
    out = []
    for i, word in enumerate(re.split(r"[-_]+", slug)):
        low = word.casefold()
        if low in acr:
            out.append(acr[low])
        elif i and low in small:
            out.append(low)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def yt_url(video_id: str, seconds: float | int | None = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    return base if seconds is None else f"{base}&t={max(0, int(float(seconds)))}s"


def yt_id(url: str) -> str | None:
    p = urlparse(url)
    host, path = p.netloc.casefold(), p.path.strip("/")
    if "youtu.be" in host:
        return path.split("/", 1)[0] or None
    if "youtube.com" in host or "youtube-nocookie.com" in host:
        if path == "watch":
            return parse_qs(p.query).get("v", [None])[0]
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] in {"embed", "shorts", "live"}:
            return parts[1]
    return None


def extract_media(soup: BeautifulSoup):
    images, embeds, seen_i, seen_v = [], [], set(), set()
    for img in soup.find_all("img"):
        src = clean(img.get("src") or img.get("data-src"))
        if not src or src in seen_i:
            continue
        seen_i.add(src)
        images.append({
            "url": src,
            "alt": clean(img.get("alt")) or None,
            "title": clean(img.get("title")) or None,
            "width": img.get("width"),
            "height": img.get("height"),
        })
    for wrapper in soup.select('[data-component-name="Youtube2ToDOM"]'):
        vid, start = None, 0
        raw = wrapper.get("data-attrs")
        if raw:
            try:
                attrs = json.loads(html_lib.unescape(raw))
                vid = attrs.get("videoId")
                start = attrs.get("startTime") or 0
            except Exception:
                pass
        iframe = wrapper.find("iframe")
        if not vid and iframe and iframe.get("src"):
            vid = yt_id(iframe["src"])
        if vid:
            key = (vid, int(float(start or 0)))
            if key not in seen_v:
                seen_v.add(key)
                embeds.append({"video_id": vid, "start_seconds": key[1], "url": yt_url(vid, key[1])})
    return images, embeds


def clean_substack_html(source: str) -> BeautifulSoup:
    soup = BeautifulSoup(source, "html.parser")
    for comment in soup.find_all(string=lambda x: isinstance(x, Comment)):
        comment.extract()
    for node in soup.find_all(["script", "style", "noscript", "button"]):
        node.decompose()
    for node in soup.select(".image-link-expand, .pencraft.icon-container"):
        node.decompose()
    for wrapper in list(soup.select('[data-component-name="Youtube2ToDOM"]')):
        vid, start = None, 0
        raw = wrapper.get("data-attrs")
        if raw:
            try:
                attrs = json.loads(html_lib.unescape(raw))
                vid = attrs.get("videoId")
                start = attrs.get("startTime") or 0
            except Exception:
                pass
        iframe = wrapper.find("iframe")
        if not vid and iframe and iframe.get("src"):
            vid = yt_id(iframe["src"])
        if vid:
            p = soup.new_tag("p")
            a = soup.new_tag("a", href=yt_url(vid, start))
            a.string = f"YouTube video: {vid}"
            p.append(a)
            wrapper.replace_with(p)
    for iframe in soup.find_all("iframe"):
        iframe.decompose()
    return soup


def md_from_soup(soup: BeautifulSoup) -> str:
    md = html_to_markdown(str(soup), heading_style="ATX", bullets="-")
    md = md.replace("\r\n", "\n")
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def links_from_soup(soup: BeautifulSoup):
    out, seen = [], set()
    for a in soup.find_all("a"):
        href = clean(a.get("href"))
        if not href:
            continue
        label = clean(a.get_text(" ", strip=True))
        key = (href, label)
        if key not in seen:
            seen.add(key)
            out.append({"url": href, "label": label})
    return out


def substack_record(path: Path, posts_dir: Path, by_id, by_slug):
    m = FILENAME_RE.match(path.name)
    if not m:
        raise RuntimeError(f"Unexpected Substack filename: {path.name}")
    pid, slug = m.group("id"), m.group("slug")
    source = path.read_text(encoding="utf-8", errors="replace")
    raw = BeautifulSoup(source, "html.parser")
    images, embeds = extract_media(raw)
    soup = clean_substack_html(source)
    meta = by_id.get(pid) or by_slug.get(slug)
    csv_title = first(meta, "title", "post_title", "post title")
    if csv_title:
        title, title_source = clean(csv_title), "metadata_csv"
    elif soup.find("title") and clean(soup.find("title").get_text(" ", strip=True)):
        title, title_source = clean(soup.find("title").get_text(" ", strip=True)), "html_title"
    elif soup.find("h1") and clean(soup.find("h1").get_text(" ", strip=True)):
        title, title_source = clean(soup.find("h1").get_text(" ", strip=True)), "html_h1"
    else:
        title, title_source = humanize(slug), "filename_slug"
    published = iso(first(meta, "post_date", "post date", "published_at", "published at", "publication_date", "date"))
    updated = iso(first(meta, "updated_at", "updated at", "last_updated_at", "last updated at"))
    canonical = clean(first(meta, "canonical_url", "canonical url", "url", "post_url", "post url")) or f"{SUBSTACK_ORIGIN}/p/{slug}"
    markdown = md_from_soup(soup)
    text = clean(soup.get_text(" ", strip=True))
    flags = []
    if title_source == "filename_slug": flags.append("title_derived_from_filename")
    if not published: flags.append("missing_published_at")
    if not text: flags.append("empty_content")
    return {
        "schema_version": 1,
        "record_type": "substack",
        "id": f"substack:{pid}",
        "post_id": pid,
        "slug": slug,
        "title": title,
        "title_source": title_source,
        "subtitle": clean(first(meta, "subtitle", "post_subtitle", "description")) or None,
        "url": canonical,
        "published_at": published,
        "updated_at": updated,
        "authors": [],
        "topics": [],
        "tags": [],
        "content_markdown": markdown,
        "content_text": text,
        "word_count": wc(text),
        "images": images,
        "youtube_embeds": embeds,
        "links": links_from_soup(soup),
        "source": {"platform": "substack", "publication": SUBSTACK_PUBLICATION, "source_file": str(path.relative_to(posts_dir.parent)).replace("\\", "/")},
        "content_sha256": sha(markdown),
        "priority": None,
        "qc_flags": flags,
    }


def build_substack(posts_dir: Path, metadata_csv: Path | None):
    by_id, by_slug = load_post_metadata(metadata_csv)
    records = [substack_record(p, posts_dir, by_id, by_slug) for p in sorted(posts_dir.glob("*.htm*"), key=lambda x: x.name.casefold())]
    ids = [x["id"] for x in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate Substack IDs detected")
    return records


def substack_index(r):
    return {
        "id": r["id"], "record_type": "substack", "post_id": r["post_id"], "slug": r["slug"],
        "title": r["title"], "subtitle": r["subtitle"], "url": r["url"], "published_at": r["published_at"],
        "topics": r["topics"], "tags": r["tags"], "word_count": r["word_count"],
        "image_url": r["images"][0]["url"] if r["images"] else None, "priority": r["priority"], "qc_flags": r["qc_flags"],
    }


def seconds(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def fmt_time(value: float) -> str:
    total = int(max(0, value)); h, rem = divmod(total, 3600); m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def word_stream(timestamps):
    stream = []
    for i, snippet in enumerate(timestamps or []):
        text = clean(snippet.get("text")); start = seconds(snippet.get("seconds_offset")); dur = seconds(snippet.get("duration_seconds"))
        if not text: continue
        for token in WORD_RE.findall(text):
            stream.append({"word": token, "snippet_index": i, "seconds": start, "duration": dur})
    return stream


def chunk_sizes(total: int) -> list[int]:
    """
    Divide a transcript into balanced chunks with a HARD maximum
    of CHUNK_MAX words.

    CHUNK_TARGET is preferred and CHUNK_MIN is a soft minimum.
    If 260–320 words is mathematically impossible, shorter chunks
    are allowed. Chunks may NEVER exceed CHUNK_MAX.
    """

    if total <= 0:
        return []

    # At least this many chunks are required to guarantee
    # that no chunk exceeds CHUNK_MAX.
    minimum_chunks = math.ceil(
        total / CHUNK_MAX
    )

    # Prefer a chunk count near the target size.
    target_chunks = max(
        1,
        round(total / CHUNK_TARGET),
    )

    chunk_count = max(
        minimum_chunks,
        target_chunks,
    )

    # Spread words as evenly as possible.
    base, remainder = divmod(
        total,
        chunk_count,
    )

    sizes = [
        base + (1 if i < remainder else 0)
        for i in range(chunk_count)
    ]

    # Hard invariant.
    if max(sizes) > CHUNK_MAX:
        raise RuntimeError(
            f"Chunking invariant failed: "
            f"generated {max(sizes)}-word chunk "
            f"with CHUNK_MAX={CHUNK_MAX}"
        )

    return sizes


def yt_chunks(video):
    vid = clean(video.get("video_id"))
    if not vid: raise RuntimeError("YouTube record missing video_id")
    stream = word_stream(video.get("timestamps") or [])
    chunks, offset = [], 0
    for idx, size in enumerate(chunk_sizes(len(stream))):
        words = stream[offset:offset + size]; offset += size
        if not words: continue
        first_word, last_word = words[0], words[-1]
        text = " ".join(x["word"] for x in words)
        flags = []
        if len(words) < CHUNK_MIN:
            flags.append(
                "short_chunk_unavoidable"
            )

        if len(words) > CHUNK_MAX:
            raise RuntimeError(
                f"{vid}: chunk {idx + 1} contains "
                f"{len(words)} words; hard maximum is "
                f"{CHUNK_MAX}"
            )
        chunks.append({
            "id": f"youtube:{vid}:chunk:{idx + 1:04d}",
            "record_type": "youtube_chunk",
            "video_id": vid,
            "chunk_index": idx,
            "word_count": len(words),
            "timestamp_seconds": int(first_word["seconds"]),
            "timestamp_formatted": fmt_time(first_word["seconds"]),
            "timestamp_url": yt_url(vid, first_word["seconds"]),
            "end_seconds": round(last_word["seconds"] + last_word["duration"], 3),
            "source_snippet_start": first_word["snippet_index"],
            "source_snippet_end": last_word["snippet_index"],
            "text": text,
            "text_sha256": sha(text),
            "qc_flags": flags,
        })
    if offset != len(stream):
        raise RuntimeError(f"{vid}: chunking lost words ({offset} != {len(stream)})")
    return chunks


def youtube_record(video):
    vid = clean(video.get("video_id")); chunks = yt_chunks(video); transcript = clean(video.get("full_transcript"))
    timestamps = video.get("timestamps") or []
    timestamp_text = " ".join(clean(x.get("text")) for x in timestamps if clean(x.get("text")))
    flags = []
    if not transcript: flags.append("missing_full_transcript")
    if not timestamps: flags.append("missing_timestamps")
    if any("short_chunk_unavoidable" in x["qc_flags"] for x in chunks): flags.append("contains_short_chunk")
    return {
        "schema_version": 1,
        "record_type": "youtube",
        "id": f"youtube:{vid}",
        "video_id": vid,
        "title": clean(video.get("title")),
        "url": clean(video.get("video_url")) or yt_url(vid),
        "published_at": iso(video.get("published_at")),
        "channel": {"name": YOUTUBE_CHANNEL_NAME, "channel_id": clean(video.get("channel_id")) or None},
        "description": clean(video.get("description")) or None,
        "playlists": video.get("playlists") or [],
        "topics": video.get("topics") or [],
        "caption_type": clean(video.get("caption_type")) or None,
        "caption_language": clean(video.get("caption_language")) or None,
        "full_transcript": transcript,
        "full_transcript_word_count": wc(transcript),
        "timestamp_transcript_word_count": wc(timestamp_text),
        "timestamp_snippet_count": len(timestamps),
        "transcript_chunks": chunks,
        "chunk_count": len(chunks),
        "source": {"platform": "youtube"},
        "priority": video.get("priority"),
        "qc_flags": flags,
    }


def build_youtube(path: Path):
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list): raise RuntimeError("YouTube source must be a JSON array")
    records, chunks = [], []
    for video in raw:
        record = youtube_record(video); records.append(record)
        for chunk in record["transcript_chunks"]:
            chunks.append({
                **chunk,
                "video_title": record["title"],
                "video_url": record["url"],
                "published_at": record["published_at"],
                "caption_type": record["caption_type"],
                "caption_language": record["caption_language"],
                "playlists": record["playlists"],
                "topics": record["topics"],
                "priority": record["priority"],
            })
    if len({x["id"] for x in records}) != len(records): raise RuntimeError("Duplicate YouTube video IDs")
    if len({x["id"] for x in chunks}) != len(chunks): raise RuntimeError("Duplicate YouTube chunk IDs")
    return records, chunks


def youtube_index(r):
    return {
        "id": r["id"], "record_type": "youtube", "video_id": r["video_id"], "title": r["title"], "url": r["url"],
        "published_at": r["published_at"], "playlists": r["playlists"], "topics": r["topics"],
        "caption_type": r["caption_type"], "caption_language": r["caption_language"],
        "word_count": r["full_transcript_word_count"], "chunk_count": r["chunk_count"],
        "priority": r["priority"], "qc_flags": r["qc_flags"],
    }


def qc_summary(records):
    c = Counter(flag for r in records for flag in (r.get("qc_flags") or []))
    return dict(sorted(c.items()))



def args():
    parser = ArgumentParser(
        description=(
            "Build Substack and YouTube canonical master corpora."
        )
    )

    parser.add_argument(
        "--site-root",
        type=Path,
        default=SITE_ROOT,
        help=(
            "WantToKnow.info repository root. "
            "Default raw/input paths are derived from this."
        ),
    )

    parser.add_argument(
        "--posts-dir",
        type=Path,
        default=None,
        help="Optional Substack HTML directory override.",
    )

    parser.add_argument(
        "--posts-csv",
        type=Path,
        default=None,
        help="Optional Substack posts.csv override.",
    )

    parser.add_argument(
        "--youtube-json",
        type=Path,
        default=None,
        help="Optional timestamped YouTube JSON override.",
    )

    return parser.parse_args()


def main():
    a = args()
    site = a.site_root

    # Derive all normal paths from the selected site root. This keeps
    # --site-root useful for alternate/test copies of the repository.
    data_root = (
        site
        / "src"
        / "site"
        / "data"
    )

    corpus = (
        data_root
        / "corpus"
    )

    substack_raw_root = (
        data_root
        / "substack_raws"
    )

    youtube_raw_root = (
        data_root
        / "youtube_raws"
    )

    posts = (
        a.posts_dir
        or (
            substack_raw_root
            / "posts"
        )
    )

    posts_csv = (
        a.posts_csv
        or (
            substack_raw_root
            / "posts.csv"
        )
    )

    youtube_src = (
        a.youtube_json
        or (
            youtube_raw_root
            / "timestamped_youtube_database.json"
        )
    )

    report_path = (
        site
        / "reports"
        / "build"
        / "portal-masters-build.json"
    )

    # Required phase-1 inputs.
    if not posts.exists():
        raise FileNotFoundError(
            f"Missing Substack posts directory: {posts}"
        )

    if not posts.is_dir():
        raise NotADirectoryError(
            f"Substack posts path is not a directory: {posts}"
        )

    if not posts_csv.exists():
        raise FileNotFoundError(
            f"Missing Substack metadata CSV: {posts_csv}"
        )

    if not youtube_src.exists():
        raise FileNotFoundError(
            f"Missing YouTube source JSON: {youtube_src}"
        )

    substack = build_substack(
        posts,
        posts_csv,
    )

    youtube, chunks = build_youtube(
        youtube_src
    )

    paths = {
        "substack_master":
            corpus / "substack-master-v1.jsonl",

        "substack_index":
            corpus / "substack-index-v1.jsonl",

        "youtube_master":
            corpus / "youtube-master-v1.jsonl",

        "youtube_index":
            corpus / "youtube-index-v1.jsonl",

        "youtube_chunks":
            corpus / "youtube-chunks-v1.jsonl",
    }

    write_jsonl(
        paths["substack_master"],
        substack,
    )

    write_jsonl(
        paths["substack_index"],
        (
            substack_index(record)
            for record in substack
        ),
    )

    write_jsonl(
        paths["youtube_master"],
        youtube,
    )

    write_jsonl(
        paths["youtube_index"],
        (
            youtube_index(record)
            for record in youtube
        ),
    )

    write_jsonl(
        paths["youtube_chunks"],
        chunks,
    )

    # Strict chunk validation: > CHUNK_MAX is always an error.
    oversized = [
        chunk["id"]
        for chunk in chunks
        if chunk["word_count"] > CHUNK_MAX
    ]

    under_unflagged = [
        chunk["id"]
        for chunk in chunks
        if (
            chunk["word_count"] < CHUNK_MIN
            and "short_chunk_unavoidable"
            not in chunk["qc_flags"]
        )
    ]

    unavoidable_short = [
        chunk["id"]
        for chunk in chunks
        if "short_chunk_unavoidable"
        in chunk["qc_flags"]
    ]

    report = {
        "build_type":
            "portal-content-masters",

        "built_at":
            now_iso(),

        "sources": {
            "posts_dir":
                str(posts),

            "posts_csv":
                str(posts_csv),

            "youtube_json":
                str(youtube_src),
        },

        "outputs": {
            key:
                str(value)
            for key, value in paths.items()
        },

        "substack": {
            "posts":
                len(substack),

            "words":
                sum(
                    record["word_count"]
                    for record in substack
                ),

            "images":
                sum(
                    len(record["images"])
                    for record in substack
                ),

            "youtube_embeds":
                sum(
                    len(record["youtube_embeds"])
                    for record in substack
                ),

            "qc_flags":
                qc_summary(substack),
        },

        "youtube": {
            "videos":
                len(youtube),

            "chunks":
                len(chunks),

            "full_transcript_words":
                sum(
                    record["full_transcript_word_count"]
                    for record in youtube
                ),

            "timestamp_words":
                sum(
                    record["timestamp_transcript_word_count"]
                    for record in youtube
                ),

            "qc_flags":
                qc_summary(youtube),

            "chunk_validation": {
                "minimum_soft":
                    CHUNK_MIN,

                "target":
                    CHUNK_TARGET,

                "maximum_hard":
                    CHUNK_MAX,

                "over_max":
                    len(oversized),

                "over_max_ids":
                    oversized[:50],

                "under_min_without_flag":
                    len(under_unflagged),

                "under_min_unflagged_ids":
                    under_unflagged[:50],

                "unavoidable_short":
                    len(unavoidable_short),
            },
        },
    }

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    if oversized:
        raise RuntimeError(
            f"Hard chunk maximum violated; "
            f"{len(oversized)} chunks exceed "
            f"{CHUNK_MAX} words. "
            f"See {report_path}"
        )

    if under_unflagged:
        raise RuntimeError(
            f"Short-chunk validation failed; "
            f"{len(under_unflagged)} chunks are below "
            f"{CHUNK_MIN} without short_chunk_unavoidable. "
            f"See {report_path}"
        )

    print()
    print("======================================")
    print("PORTAL MASTER BUILD COMPLETE")
    print("======================================")
    print(f"Substack posts:          {len(substack):,}")
    print(f"Substack metadata CSV:   {posts_csv}")
    print(f"YouTube videos:          {len(youtube):,}")
    print(f"YouTube chunks:          {len(chunks):,}")
    print(f"Chunks >{CHUNK_MAX}:           {len(oversized):,}")
    print(
        f"Unflagged chunks <{CHUNK_MIN}: "
        f"{len(under_unflagged):,}"
    )
    print(
        f"Unavoidable short chunks:"
        f"{len(unavoidable_short):,}"
    )

    print()
    print("Outputs:")

    for path in paths.values():
        print(f"  {path}")

    print()
    print(f"Build report: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"\nPORTAL MASTER BUILD FAILED\n{exc}", file=sys.stderr)
        raise