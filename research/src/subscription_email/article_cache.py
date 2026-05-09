from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

CACHE_SCHEMA_VERSION = "0.1.0"
SAFE_ANALYSIS_KEYS = frozenset(
    {
        "catalysts",
        "direction",
        "fetched_at",
        "status",
        "text_hash",
        "tickers",
        "title_hash",
        "url",
    }
)


def load_article_analysis_cache(path: Path | None) -> dict[str, dict[str, object]]:
    if path is None or not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    articles = payload.get("articles")
    if not isinstance(articles, dict):
        return {}
    return {
        str(url): cached
        for url, value in articles.items()
        if isinstance(value, dict)
        for cached in [_safe_analysis(value)]
        if cached is not None
    }


def write_article_analysis_cache(
    path: Path | None,
    cache: Mapping[str, Mapping[str, object]],
) -> None:
    if path is None:
        return
    articles = {
        str(url): safe
        for url, analysis in sorted(cache.items())
        for safe in [_safe_analysis(analysis)]
        if safe is not None
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": CACHE_SCHEMA_VERSION,
                "articles": articles,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def cacheable_analysis(
    analysis: Mapping[str, object],
    *,
    fetched_at: str,
) -> dict[str, object] | None:
    safe = _safe_analysis({**analysis, "fetched_at": fetched_at})
    if safe is None:
        return None
    return safe


def _safe_analysis(value: Mapping[str, object]) -> dict[str, object] | None:
    status = value.get("status")
    url = value.get("url")
    title_hash = value.get("title_hash")
    text_hash = value.get("text_hash")
    direction = value.get("direction")
    tickers = _string_list(value.get("tickers"))
    catalysts = _string_list(value.get("catalysts"))
    if not all(isinstance(item, str) and item for item in (status, url, title_hash, text_hash)):
        return None
    if direction not in {"BULLISH", "BEARISH", "NEUTRAL"}:
        return None
    output: dict[str, object] = {
        "status": status,
        "url": url,
        "title_hash": title_hash,
        "tickers": tickers,
        "direction": direction,
        "catalysts": catalysts,
        "text_hash": text_hash,
    }
    fetched_at = value.get("fetched_at")
    if isinstance(fetched_at, str) and fetched_at:
        output["fetched_at"] = fetched_at
    return {key: output[key] for key in output if key in SAFE_ANALYSIS_KEYS}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item]
