from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, cast


class ScraplingUnavailableError(RuntimeError):
    """Raised when optional Scrapling support is requested but not installed."""


@dataclass(frozen=True)
class ScrapedPage:
    url: str
    status_code: int | None
    title: str | None
    text: str


def scrapling_available() -> bool:
    try:
        import_module("scrapling")
    except ImportError:
        return False
    return True


def parse_html(html: str, *, url: str = "") -> ScrapedPage:
    selector = _selector(html, url=url)
    return ScrapedPage(
        url=url,
        status_code=None,
        title=_title(selector),
        text=_text(selector),
    )


def fetch_page(url: str, *, timeout: int = 20) -> ScrapedPage:
    scrapling = _scrapling()
    response = scrapling.Fetcher.get(url, timeout=timeout, follow_redirects="safe")
    return ScrapedPage(
        url=str(getattr(response, "url", url)),
        status_code=cast(int | None, getattr(response, "status", None)),
        title=_title(response),
        text=_text(response),
    )


def _scrapling() -> Any:
    try:
        return import_module("scrapling")
    except ImportError as exc:
        raise ScraplingUnavailableError(
            "Install the optional web extra to enable Scrapling: pip install .[web]"
        ) from exc


def _selector(html: str, *, url: str) -> Any:
    scrapling = _scrapling()
    return scrapling.Selector(html, url=url)


def _title(selector: Any) -> str | None:
    value = selector.css("title::text").get(None)
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _text(selector: Any) -> str:
    value = selector.get_all_text(separator="\n", strip=True)
    return str(value).strip()
