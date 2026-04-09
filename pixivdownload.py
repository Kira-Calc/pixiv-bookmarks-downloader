#!/usr/bin/env python3
"""Download all Pixiv bookmarks, excluding AI-generated works."""

import subprocess
import json
import os
import shutil
import time
import sys
import glob

OPENCLI = os.path.expanduser("~/.npm-global/bin/opencli")
OUTPUT_DIR = os.path.expanduser("~/Pictures/pixiv_bookmarks")
TEMP_DIR = os.path.join(OUTPUT_DIR, "_temp_downloads")
USER_ID = "63970351"
BATCH_SIZE = 48

# AI-related tags to exclude (case-insensitive matching)
AI_TAGS = [
    "ai", "ai生成", "aiイラスト", "ai-generated", "aiart", "ai_art",
    "novelai", "stable_diffusion", "stablediffusion", "midjourney",
    "nijijourney", "ai絵", "ai画像", "aimade", "ai作画", "ai illustration",
    "dall-e", "dalle", "ai-made", "ai art", "ai绘画", "ai绘图",
    "ai_generated", "ai_illustration", "ai生成イラスト",
]

def run_eval(js_code, timeout=30):
    """Run JS in browser via opencli operate eval."""
    result = subprocess.run(
        [OPENCLI, "operate", "eval", js_code],
        capture_output=True, text=True, timeout=timeout
    )
    return result.stdout.strip()

def fetch_bookmarks_page(offset):
    """Fetch a page of bookmarks via Pixiv AJAX API."""
    js = f"""
    fetch('https://www.pixiv.net/ajax/user/{USER_ID}/illusts/bookmarks?tag=&offset={offset}&limit={BATCH_SIZE}&rest=show')
      .then(r => r.json())
      .then(d => {{
        const works = d.body.works.map(w => ({{
          id: w.id, title: w.title, pages: w.pageCount,
          tags: w.tags
        }}));
        document.title = JSON.stringify({{total: d.body.total, works}});
      }})
      .catch(e => {{ document.title = JSON.stringify({{error: e.message}}); }});
    'fetching...'
    """
    run_eval(js)
    time.sleep(3)
    result = run_eval("document.title")
    try:
        return json.loads(result)
    except:
        return None

def is_ai_generated(tags):
    """Check if any tag matches AI-related keywords.

    Short keywords (<=5 chars) require exact match to avoid false positives
    like "ai" matching "honkaistarrail". Longer keywords use substring match.
    """
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

def download_illust(illust_id):
    """Download an illustration using opencli."""
    temp = os.path.join(TEMP_DIR, str(illust_id))
    os.makedirs(temp, exist_ok=True)
    try:
        result = subprocess.run(
            [OPENCLI, "pixiv", "download", str(illust_id), "--output", temp],
            capture_output=True, text=True, timeout=60
        )
        return result.returncode == 0
    except:
        return False

def organize_files(illust_id, title):
    """Move downloaded files: single image -> root, multi -> subfolder."""
    src_dir = os.path.join(TEMP_DIR, str(illust_id), str(illust_id))
    if not os.path.exists(src_dir):
        src_dir = os.path.join(TEMP_DIR, str(illust_id))

    # Find all image files recursively
    images = []
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.zip')):
                images.append(os.path.join(root, f))

    if not images:
        return 0

    if len(images) == 1:
        # Single image: move directly to output dir
        ext = os.path.splitext(images[0])[1]
        # Use illust_id as filename to avoid conflicts
        dst = os.path.join(OUTPUT_DIR, f"{illust_id}{ext}")
        shutil.move(images[0], dst)
    else:
        # Multiple images: create subfolder
        safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()[:50]
        folder_name = f"{illust_id}_{safe_title}" if safe_title else str(illust_id)
        dst_dir = os.path.join(OUTPUT_DIR, folder_name)
        os.makedirs(dst_dir, exist_ok=True)
        for img in images:
            shutil.move(img, os.path.join(dst_dir, os.path.basename(img)))

    return len(images)

def main():
    # Full scan mode: disables incremental stop, walks entire bookmark list.
    # Useful for backfilling works missed by prior filter bugs.
    full_scan = "--full" in sys.argv or os.environ.get("FULL_SCAN") == "1"
    if full_scan:
        print("=== FULL SCAN MODE — incremental optimization disabled ===")

    # First, navigate to pixiv so we can use fetch (eval-based, compatible with outdated Browser Bridge)
    print("Opening Pixiv...")
    current = run_eval("location.href")
    if "pixiv.net" not in current:
        run_eval("location.href='https://www.pixiv.net/'")
        time.sleep(4)

    # Load already-downloaded IDs first (for incremental fetch)
    existing = set()
    for f in os.listdir(OUTPUT_DIR):
        if f.startswith("_") or f.endswith(".py") or f.endswith(".log"):
            continue
        fid = f.split("_")[0].split(".")[0]
        if fid.isdigit():
            existing.add(fid)
    print(f"Local existing: {len(existing)} works")

    # Fetch bookmarks incrementally — stop when a full page is all already-downloaded
    print(f"Fetching bookmarks for user {USER_ID}...")
    all_works = []
    offset = 0
    total = None

    while True:
        print(f"  Fetching offset {offset}...", end=" ", flush=True)
        data = fetch_bookmarks_page(offset)
        if not data or "error" in data:
            print(f"Error: {data}")
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

        # Incremental stop: if the entire page is already downloaded, older pages will be too
        if not full_scan and existing and all(str(w["id"]) in existing for w in works):
            print("  Full page already downloaded — stopping enumeration (incremental mode)")
            break

        offset += BATCH_SIZE
        if offset >= total:
            break
        time.sleep(1)

    print(f"\nTotal bookmarks fetched: {len(all_works)}")

    # Filter out AI works
    filtered = []
    ai_count = 0
    for w in all_works:
        if is_ai_generated(w["tags"]):
            ai_count += 1
            print(f"  [SKIP AI] {w['id']} - {w['title']} | tags: {', '.join(w['tags'][:5])}")
        else:
            filtered.append(w)

    print(f"\nFiltered: {len(filtered)} works to download ({ai_count} AI works excluded)")

    # existing set already loaded above
    remaining = [w for w in filtered if str(w["id"]) not in existing]
    print(f"Already downloaded: {len(filtered) - len(remaining)}, remaining: {len(remaining)}")

    # Download
    os.makedirs(TEMP_DIR, exist_ok=True)
    success = 0
    fail = 0

    for i, w in enumerate(remaining):
        illust_id = w["id"]
        title = w["title"]
        pages = w["pages"]
        print(f"[{i+1}/{len(remaining)}] Downloading {illust_id} ({pages}p) - {title}...", end=" ", flush=True)

        if download_illust(illust_id):
            count = organize_files(illust_id, title)
            print(f"OK ({count} images)")
            success += 1
        else:
            print("FAILED")
            fail += 1

        # Clean temp for this work
        temp_path = os.path.join(TEMP_DIR, str(illust_id))
        if os.path.exists(temp_path):
            shutil.rmtree(temp_path)

        # Rate limit: small delay
        if (i + 1) % 10 == 0:
            time.sleep(1)

    # Cleanup
    if os.path.exists(TEMP_DIR):
        shutil.rmtree(TEMP_DIR)

    print(f"\n=== Done ===")
    print(f"Success: {success}, Failed: {fail}")
    print(f"Output: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
