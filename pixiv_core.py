#!/usr/bin/env python3
"""Shared core logic for Pixiv bookmark downloaders.

Config resolution order (first non-empty wins):
  env PIXIV_UID / PIXIV_OUTPUT_DIR
  > ~/.pixiv_bookmarks_downloader.json
  > built-in defaults (output dir only; UID has no default and must be set)

Outputs a metadata.jsonl alongside the downloaded images — one JSON line per
successfully-downloaded work with author/tags/url/local-path info.
"""

import json
import os
import shutil
import subprocess
import sys
import time
from typing import Iterable

OPENCLI = os.path.expanduser("~/.npm-global/bin/opencli")
CONFIG_PATH = os.path.expanduser("~/.pixiv_bookmarks_downloader.json")
DEFAULT_OUTPUT_DIR = os.path.expanduser("~/Pictures/pixiv_bookmarks")
BATCH_SIZE = 48
# Named browser session for `opencli browser <session> ...`. Reusing one name
# keeps the same Chrome tab (and its Pixiv login) alive across calls.
BROWSER_SESSION = os.environ.get("PIXIV_BROWSER_SESSION", "pixivdl").strip() or "pixivdl"

# AI-related tags to exclude (case-insensitive matching).
# Short keywords (<=5 chars) require exact match to avoid false positives
# like "ai" matching "honkaistarrail". Longer keywords use substring match.
AI_TAGS = [
    "ai", "ai生成", "aiイラスト", "ai-generated", "aiart", "ai_art",
    "novelai", "stable_diffusion", "stablediffusion", "midjourney",
    "nijijourney", "ai絵", "ai画像", "aimade", "ai作画", "ai illustration",
    "dall-e", "dalle", "ai-made", "ai art", "ai绘画", "ai绘图",
    "ai_generated", "ai_illustration", "ai生成イラスト",
]


def _load_config_file() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def resolve_config():
    """Return (user_id, output_dir). Exits if UID is missing."""
    cfg = _load_config_file()
    user_id = (os.environ.get("PIXIV_UID") or cfg.get("uid") or "").strip()
    output_dir = (
        os.environ.get("PIXIV_OUTPUT_DIR")
        or cfg.get("output_dir")
        or DEFAULT_OUTPUT_DIR
    ).strip()
    output_dir = os.path.expanduser(output_dir)

    if not user_id.isdigit():
        sys.exit(
            "ERROR: Pixiv UID not configured. Set env PIXIV_UID, "
            f"or add \"uid\" to {CONFIG_PATH}, or launch the GUI to configure it."
        )
    os.makedirs(output_dir, exist_ok=True)
    return user_id, output_dir


class OpenCliError(RuntimeError):
    """An opencli invocation failed or came back with an error envelope."""


def _run_opencli(args, timeout: int) -> str:
    try:
        result = subprocess.run(
            [OPENCLI, *args], capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        raise OpenCliError(f"opencli not found at {OPENCLI}")
    except subprocess.TimeoutExpired:
        raise OpenCliError(f"opencli timed out after {timeout}s: {' '.join(args[:3])}")

    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip()
    # opencli prints usage errors ("error: unknown command ...") to stdout and
    # still exits 0, so the return code alone can't tell us the call was bad.
    if result.returncode != 0 or out.startswith("error:") or err.startswith("error:"):
        raise OpenCliError(out or err or f"exit code {result.returncode}")
    return out


def run_eval(js_code: str, timeout: int = 60) -> str:
    """Run JS in the bound page and return its result as text.

    opencli >= 1.8 exposes this as `opencli browser <session> eval <js>`
    (it replaced the old `opencli operate eval`), awaits returned promises,
    and prints the resolved value straight to stdout.
    """
    return _run_opencli(["browser", BROWSER_SESSION, "eval", js_code], timeout)


def open_url(url: str, timeout: int = 120) -> str:
    return _run_opencli(["browser", BROWSER_SESSION, "open", url], timeout)


def ensure_pixiv_tab() -> None:
    """Make sure the browser session has a Pixiv page bound to it."""
    try:
        current = run_eval("location.href", timeout=30)
    except OpenCliError:
        current = ""
    if "pixiv.net" not in current:
        open_url("https://www.pixiv.net/")


def fetch_bookmarks_page(user_id: str, offset: int):
    """Fetch a page of bookmarks via the Pixiv AJAX API, run in page context."""
    js = (
        "fetch('https://www.pixiv.net/ajax/user/%s/illusts/bookmarks"
        "?tag=&offset=%d&limit=%d&rest=show', {credentials: 'include'})"
        ".then(r => r.json())"
        ".then(d => {"
        " if (d.error) throw new Error(d.message || 'pixiv api returned error');"
        " return JSON.stringify({total: d.body.total, works: d.body.works.map(w => ({"
        "id: w.id, title: w.title, pages: w.pageCount, tags: w.tags || [],"
        "userId: w.userId, userName: w.userName, illustType: w.illustType,"
        "createDate: w.createDate, updateDate: w.updateDate,"
        "xRestrict: w.xRestrict, url: w.url}))});"
        " })"
        ".catch(e => JSON.stringify({error: String((e && e.message) || e)}))"
    ) % (user_id, offset, BATCH_SIZE)

    try:
        result = run_eval(js)
    except OpenCliError as e:
        return {"error": str(e)}
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        return {"error": f"unparsable eval output: {result[:200]!r}"}


def is_ai_generated(tags: Iterable[str]) -> bool:
    for tag in tags:
        tag_lower = tag.lower().strip()
        for ai_tag in AI_TAGS:
            if len(ai_tag) <= 5:
                if ai_tag == tag_lower:
                    return True
            else:
                if ai_tag in tag_lower:
                    return True
    return False


def download_illust(illust_id: str, temp_dir: str) -> bool:
    """Download an illustration using opencli."""
    temp = os.path.join(temp_dir, str(illust_id))
    os.makedirs(temp, exist_ok=True)
    try:
        result = subprocess.run(
            [OPENCLI, "pixiv", "download", str(illust_id), "--output", temp],
            capture_output=True, text=True, timeout=60,
        )
        return result.returncode == 0
    except subprocess.SubprocessError:
        return False


def organize_files(illust_id, title: str, output_dir: str, temp_dir: str):
    """Move downloaded files: single image -> root, multi -> subfolder.

    Returns (image_count, local_path) where local_path is the file or folder
    placed under output_dir. Returns (0, None) when no files were found.
    """
    src_dir = os.path.join(temp_dir, str(illust_id), str(illust_id))
    if not os.path.exists(src_dir):
        src_dir = os.path.join(temp_dir, str(illust_id))

    images = []
    for root, _dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith((
                '.png', '.jpg', '.jpeg', '.gif', '.webp',
                '.mp4', '.webm', '.zip',
            )):
                images.append(os.path.join(root, f))

    if not images:
        return 0, None

    if len(images) == 1:
        ext = os.path.splitext(images[0])[1]
        dst = os.path.join(output_dir, f"{illust_id}{ext}")
        shutil.move(images[0], dst)
        return 1, dst

    safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:50]
    folder_name = f"{illust_id}_{safe_title}" if safe_title else str(illust_id)
    dst_dir = os.path.join(output_dir, folder_name)
    os.makedirs(dst_dir, exist_ok=True)
    for img in images:
        shutil.move(img, os.path.join(dst_dir, os.path.basename(img)))
    return len(images), dst_dir


def append_metadata(metadata_path: str, work: dict, local_path: str, image_count: int) -> None:
    """Append one JSON line describing a successfully-downloaded work."""
    record = {
        "id": work.get("id"),
        "title": work.get("title"),
        "author_id": work.get("userId"),
        "author_name": work.get("userName"),
        "tags": work.get("tags", []),
        "pages": work.get("pages"),
        "illust_type": work.get("illustType"),
        "create_date": work.get("createDate"),
        "update_date": work.get("updateDate"),
        "x_restrict": work.get("xRestrict"),
        "thumbnail_url": work.get("url"),
        "pixiv_url": f"https://www.pixiv.net/artworks/{work.get('id')}",
        "local_path": local_path,
        "image_count": image_count,
        "downloaded_at": int(time.time()),
    }
    try:
        with open(metadata_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"  [WARN] metadata write failed: {e}")


def collect_existing_ids(output_dir: str) -> set:
    existing = set()
    for f in os.listdir(output_dir):
        if f.startswith("_") or f.endswith((".py", ".log", ".jsonl", ".json")):
            continue
        fid = f.split("_")[0].split(".")[0]
        if fid.isdigit():
            existing.add(fid)
    return existing


def run(filter_ai: bool) -> None:
    user_id, output_dir = resolve_config()
    temp_dir = os.path.join(output_dir, "_temp_downloads")
    metadata_path = os.path.join(output_dir, "metadata.jsonl")

    full_scan = "--full" in sys.argv or os.environ.get("FULL_SCAN") == "1"
    if full_scan:
        print("=== FULL SCAN MODE — incremental optimization disabled ===")
    print(f"UID: {user_id}")
    print(f"Output: {output_dir}")
    print(f"AI filter: {'on' if filter_ai else 'off'}")

    print("Opening Pixiv...")
    try:
        ensure_pixiv_tab()
    except OpenCliError as e:
        sys.exit(
            f"ERROR: cannot drive the browser via opencli: {e}\n"
            "Check that opencli is installed and the Browser Bridge Chrome "
            "extension is connected (`opencli browser "
            f"{BROWSER_SESSION} open https://www.pixiv.net/`)."
        )

    existing = collect_existing_ids(output_dir)
    print(f"Local existing: {len(existing)} works")

    print(f"Fetching bookmarks for user {user_id}...")
    all_works = []
    offset = 0
    total = None
    while True:
        print(f"  Fetching offset {offset}...", end=" ", flush=True)
        data = fetch_bookmarks_page(user_id, offset)
        if not data or "error" in data:
            reason = data.get("error") if data else "no response from browser eval"
            print(f"Error: {reason}")
            if offset == 0:
                print(
                    "  Hint: if this says 'unknown command', opencli's CLI surface "
                    "changed again — check `opencli browser --help`. If it mentions "
                    "auth, log in to Pixiv in the bridged Chrome window first."
                )
            break
        if total is None:
            total = data["total"]
            print(f"(Total: {total})")
        works = data.get("works", [])
        if not works:
            print("no more works")
            break
        all_works.extend(works)
        print(f"got {len(works)}, cumulative: {len(all_works)}")

        if not full_scan and existing and all(str(w["id"]) in existing for w in works):
            print("  Full page already downloaded — stopping enumeration (incremental mode)")
            break
        offset += BATCH_SIZE
        if offset >= total:
            break
        time.sleep(1)
    print(f"\nTotal bookmarks fetched: {len(all_works)}")

    if filter_ai:
        filtered = []
        ai_count = 0
        for w in all_works:
            if is_ai_generated(w["tags"]):
                ai_count += 1
                print(f"  [SKIP AI] {w['id']} - {w['title']} | tags: {', '.join(w['tags'][:5])}")
            else:
                filtered.append(w)
        print(f"\nFiltered: {len(filtered)} works to download ({ai_count} AI works excluded)")
    else:
        filtered = all_works
        print(f"\nTotal: {len(filtered)} works to download (no AI filter)")

    remaining = [w for w in filtered if str(w["id"]) not in existing]
    print(f"Already downloaded: {len(filtered) - len(remaining)}, remaining: {len(remaining)}")

    os.makedirs(temp_dir, exist_ok=True)
    success = 0
    fail = 0
    for i, w in enumerate(remaining):
        illust_id = w["id"]
        title = w["title"]
        pages = w["pages"]
        print(
            f"[{i+1}/{len(remaining)}] Downloading {illust_id} ({pages}p) - {title}...",
            end=" ", flush=True,
        )
        if download_illust(illust_id, temp_dir):
            count, local_path = organize_files(illust_id, title, output_dir, temp_dir)
            if count > 0:
                append_metadata(metadata_path, w, local_path, count)
                print(f"OK ({count} images)")
                success += 1
            else:
                print("FAILED (no files)")
                fail += 1
        else:
            print("FAILED")
            fail += 1

        temp_path = os.path.join(temp_dir, str(illust_id))
        if os.path.exists(temp_path):
            shutil.rmtree(temp_path)

        if (i + 1) % 10 == 0:
            time.sleep(1)

    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    print(f"\n=== Done ===")
    print(f"Success: {success}, Failed: {fail}")
    print(f"Output: {output_dir}")
    print(f"Metadata: {metadata_path}")
