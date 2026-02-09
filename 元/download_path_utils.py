"""Utility helpers for resolving download directories."""
from __future__ import annotations

import os
from typing import Iterable, Tuple


def resolve_download_dir(default_dir: str, override: str | None) -> str:
    """Return an absolute directory path for downloads.

    If *override* is a truthy, non-empty string it is expanded/absolutized and
    ensured to exist. Otherwise the default directory is used.
    """

    candidate = (override or "").strip()
    target = os.path.abspath(default_dir if not candidate else os.path.expanduser(candidate))
    os.makedirs(target, exist_ok=True)
    return target


def parse_downloader_args(args: Iterable[str], default_dir: str) -> Tuple[str, str, str]:
    """Parse CLI args for the Playwright downloader."""

    args = list(args)
    if len(args) not in (2, 3):
        raise ValueError("Chrome pathとユーザーデータディレクトリは必須です。")

    chrome_path, user_data_dir = args[0], args[1]
    override = args[2] if len(args) == 3 else ""
    download_dir = resolve_download_dir(default_dir, override)
    return chrome_path, user_data_dir, download_dir


__all__ = ["resolve_download_dir", "parse_downloader_args"]
