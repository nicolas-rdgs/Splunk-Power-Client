"""Fetch GitHub repo stats (latest tag, stars, forks) and expose them to templates.

Result is stored at ``config.extra.repo`` and rendered by
``_mkdocs/overrides/partials/source.html``. Cached to ``.cache/repo_info.json``
for 1h so ``mkdocs serve`` doesn't refetch on every reload.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE_TTL_SECONDS = 3600
CACHE_PATH = Path(".cache/repo_info.json")


def _format_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".rstrip("0").rstrip(".")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".rstrip("0").rstrip(".")
    return str(n)


def _fetch_json(url: str) -> dict | list | None:
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def _load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    if time.time() - CACHE_PATH.stat().st_mtime > CACHE_TTL_SECONDS:
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return None


def _save_cache(data: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data))


def on_config(config, **_):
    repo_url = config.get("repo_url") or ""
    if "github.com" not in repo_url:
        return config

    slug = repo_url.split("github.com/", 1)[1].strip("/")

    info = _load_cache()
    if info is None:
        repo = _fetch_json(f"https://api.github.com/repos/{slug}") or {}
        tags = _fetch_json(f"https://api.github.com/repos/{slug}/tags") or []
        info = {
            "version": tags[0]["name"] if tags else None,
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
        }
        if info["stars"] is not None:
            _save_cache(info)

    config["extra"]["repo"] = {
        "version": info.get("version"),
        "stars": _format_number(info["stars"])
        if info.get("stars") is not None
        else None,
        "forks": _format_number(info["forks"])
        if info.get("forks") is not None
        else None,
    }
    return config
