from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from subscription_email.article_types import FetchedArticle, html_to_text
from subscription_email.config import SubscriptionEmailConfig

DEFAULT_STATE_DIR = Path("research/config/browser-sessions")
DEFAULT_BROWSER_CHANNEL = "chrome"
PROVIDER_LOGIN_URLS = {
    "seeking_alpha": "https://seekingalpha.com/account/login",
    "tradevision": "https://www.tradevision.io/login",
    "zacks": "https://www.zacks.com/my-account/",
}
PROVIDER_DOMAINS = {
    "seeking_alpha": ("seekingalpha.com", "email.seekingalpha.com"),
    "tradevision": ("tradevision.io", "tradevision.com"),
    "zacks": ("zacks.com", "zacksalerts.com"),
}


class BrowserSessionUnavailableError(RuntimeError):
    """Raised when browser-session fetching is requested but unavailable."""


@dataclass(frozen=True)
class BrowserSessionFetchConfig:
    state_dir: Path
    wait_seconds: int
    browser_channel: str
    headless: bool


def provider_for_url(url: str) -> str | None:
    domain = urlsplit(url).netloc.lower()
    for provider, domains in PROVIDER_DOMAINS.items():
        if any(domain == item or domain.endswith(f".{item}") for item in domains):
            return provider
    return None


def provider_login_url(provider: str) -> str:
    try:
        return PROVIDER_LOGIN_URLS[provider]
    except KeyError as exc:
        raise ValueError(f"unknown article provider: {provider}") from exc


def browser_state_path(
    *,
    provider: str,
    repo_root: Path,
    state_dir: Path | None = None,
) -> Path:
    resolved = state_dir or repo_root / DEFAULT_STATE_DIR
    return resolved / f"{provider}.json"


def browser_fetch_config(
    config: SubscriptionEmailConfig,
    *,
    repo_root: Path | None = None,
) -> BrowserSessionFetchConfig | None:
    if config.article_browser_state_dir is None:
        if repo_root is None:
            return None
        state_dir = repo_root / DEFAULT_STATE_DIR
    else:
        state_dir = config.article_browser_state_dir
    return BrowserSessionFetchConfig(
        state_dir=state_dir,
        wait_seconds=config.article_browser_wait_seconds,
        browser_channel=config.article_browser_channel,
        headless=config.article_browser_headless,
    )


def fetch_with_browser_session(
    url: str,
    *,
    config: SubscriptionEmailConfig,
    timeout_seconds: int,
) -> FetchedArticle:
    fetch_config = browser_fetch_config(config)
    if fetch_config is None:
        raise BrowserSessionUnavailableError("article_browser_state_dir is not configured")
    provider = provider_for_url(url)
    if provider is None:
        raise BrowserSessionUnavailableError(f"no browser-session provider for {url}")
    state_path = fetch_config.state_dir / f"{provider}.json"
    if not state_path.is_file():
        raise BrowserSessionUnavailableError(f"missing browser session state: {state_path}")
    return _fetch_with_playwright(
        url,
        state_path=state_path,
        timeout_seconds=timeout_seconds,
        wait_seconds=fetch_config.wait_seconds,
        browser_channel=fetch_config.browser_channel,
        headless=fetch_config.headless,
    )


def save_browser_session(
    *,
    provider: str,
    state_dir: Path,
    login_url: str | None = None,
    browser_channel: str = DEFAULT_BROWSER_CHANNEL,
    profile_dir: Path | None = None,
) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / f"{provider}.json"
    resolved_profile_dir = profile_dir or state_dir / "profiles" / provider
    resolved_profile_dir.mkdir(parents=True, exist_ok=True)
    playwright = _playwright_sync_api()
    with playwright.sync_playwright() as runtime:
        context = runtime.chromium.launch_persistent_context(
            resolved_profile_dir.as_posix(),
            headless=False,
            **_launch_options(browser_channel),
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(login_url or provider_login_url(provider))
        print("Log in in the browser window, then return here and press Enter.")
        input()
        context.storage_state(path=state_path.as_posix())
        context.close()
    return state_path


def _fetch_with_playwright(
    url: str,
    *,
    state_path: Path,
    timeout_seconds: int,
    wait_seconds: int,
    browser_channel: str,
    headless: bool,
) -> FetchedArticle:
    playwright = _playwright_sync_api()
    timeout_ms = timeout_seconds * 1000
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(
            headless=headless,
            **_launch_options(browser_channel),
        )
        context = browser.new_context(storage_state=state_path.as_posix())
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(wait_seconds * 1000)
        html = page.content()
        resolved_url = page.url
        browser.close()
    title, text = html_to_text(html)
    return FetchedArticle(
        url=resolved_url,
        status_code=0 if response is None else int(response.status),
        title=title,
        text=text,
    )


def _launch_options(browser_channel: str) -> dict[str, object]:
    options: dict[str, object] = {
        "args": ["--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    if browser_channel != "chromium":
        options["channel"] = browser_channel
    return options


def _playwright_sync_api() -> Any:
    try:
        return import_module("playwright.sync_api")
    except ImportError as exc:
        raise BrowserSessionUnavailableError(
            "Install browser support with: .\\.venv\\Scripts\\python -m pip install .[web]"
        ) from exc
