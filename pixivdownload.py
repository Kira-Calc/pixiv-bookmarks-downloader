#!/usr/bin/env python3
"""Download Pixiv bookmarks, excluding AI-generated works (tag-based filter)."""

from pixiv_core import run

if __name__ == "__main__":
    run(filter_ai=True)
