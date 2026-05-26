#!/usr/bin/env python3
"""Download all Pixiv bookmarks (no AI filter)."""

from pixiv_core import run

if __name__ == "__main__":
    run(filter_ai=False)
