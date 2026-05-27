from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from subscription_email.article_types import (
    FetchedArticle,
    html_to_text,
    looks_like_readable_article,
)
from subscription_email.config import SubscriptionEmailConfig

DEFAULT_STATE_DIR = Path("research/config/browser-sessions")
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
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
CDP_CONNECT_RETRY_SECONDS = 10.0
CDP_CONNECT_SLEEP_SECONDS = 0.5
DEFAULT_CDP_PORT = "9222"


class BrowserSessionUnavailableError(RuntimeError):
    """Raised when browser-session fetching is requested but unavailable."""


@dataclass(frozen=True)
class BrowserSessionFetchConfig:
    state_dir: Path
    wait_seconds: int
    browser_channel: str
    headless: bool
    cdp_url: str | None = None


@dataclass(frozen=True)
class ArticleLoginPreflightResult:
    provider: str
    login_url: str
    mode: str
    confirmed: bool
    state_path: Path | None = None
    verification_url: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "login_url": self.login_url,
            "mode": self.mode,
            "confirmed": self.confirmed,
            "state_path": None if self.state_path is None else self.state_path.as_posix(),
            "verification_url": (
                None if self.verification_url is None else _safe_url_label(self.verification_url)
            ),
        }


class BrowserArticleSession:
    """Reusable browser context for paid article links in one ingest run."""

    def __init__(self, *, config: SubscriptionEmailConfig) -> None:
        fetch_config = browser_fetch_config(config)
        if fetch_config is None:
            raise BrowserSessionUnavailableError("browser article session is not configured")
        self._config = fetch_config
        self._runtime_manager: Any | None = None
        self._runtime: Any | None = None
        self._attached_browser: Any | None = None
        self._attached_context: Any | None = None
        self._contexts: dict[str, Any] = {}

    def __enter__(self) -> BrowserArticleSession:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback
        self.close()

    def fetch(self, url: str, timeout_seconds: int) -> FetchedArticle:
        provider = provider_for_url(url)
        if provider is None:
            raise BrowserSessionUnavailableError(f"no browser-session provider for {url}")
        state_exists = self._state_path(provider).is_file() or self._attached_context_active()
        context = self._context(provider)
        page = context.new_page()
        try:
            if not self._config.headless and not state_exists:
                self._confirm_manual_login_for_url(
                    page,
                    provider=provider,
                    url=url,
                )
            article = _fetch_page_article(
                page,
                url,
                timeout_seconds=timeout_seconds,
                wait_seconds=self._config.wait_seconds,
            )
            if _looks_like_login(article) and not self._config.headless:
                article = self._retry_after_manual_login(
                    page,
                    provider=provider,
                    url=url,
                    timeout_seconds=timeout_seconds,
                )
            self._save_state(provider, context)
            return article
        finally:
            with suppress(Exception):
                page.close()

    def close(self) -> None:
        for provider, context in list(self._contexts.items()):
            with suppress(Exception):
                self._save_state(provider, context)
            if not self._attached_context_active():
                with suppress(Exception):
                    context.close()
        self._contexts.clear()
        if self._runtime is not None:
            with suppress(Exception):
                self._runtime.stop()
        self._runtime = None
        self._runtime_manager = None

    def _context(self, provider: str) -> Any:
        context = self._contexts.get(provider)
        if context is None:
            context = self._launch_context(provider)
            self._contexts[provider] = context
        return context

    def _launch_context(self, provider: str) -> Any:
        if self._config.cdp_url is not None:
            return self._connect_to_existing_chrome(provider)
        profile_dir = self._config.state_dir / "profiles" / provider
        profile_dir.mkdir(parents=True, exist_ok=True)
        context = self._runtime_instance().chromium.launch_persistent_context(
            profile_dir.as_posix(),
            headless=self._config.headless,
            **_launch_options(self._config.browser_channel),
        )
        self._load_state(provider, context)
        if not self._config.headless:
            self._prepare_visible_window(provider, context)
        return context

    def _connect_to_existing_chrome(self, provider: str) -> Any:
        del provider
        if self._attached_context is not None:
            return self._attached_context
        if self._config.cdp_url is None:
            raise BrowserSessionUnavailableError("article_browser_cdp_url is not configured")
        browser = self._runtime_instance().chromium.connect_over_cdp(self._config.cdp_url)
        contexts = list(browser.contexts)
        if not contexts:
            raise BrowserSessionUnavailableError(
                "connected Chrome has no browser context; open a normal tab first"
            )
        self._attached_browser = browser
        self._attached_context = contexts[0]
        return self._attached_context

    def _runtime_instance(self) -> Any:
        if self._runtime is None:
            manager = _playwright_sync_api().sync_playwright()
            self._runtime_manager = manager
            self._runtime = manager.start()
        return self._runtime

    def _load_state(self, provider: str, context: Any) -> None:
        state_path = self._state_path(provider)
        if not state_path.is_file():
            return
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        cookies = payload.get("cookies") if isinstance(payload, dict) else None
        if isinstance(cookies, list) and cookies:
            with suppress(Exception):
                context.add_cookies(cookies)

    def _save_state(self, provider: str, context: Any) -> None:
        if self._attached_context_active():
            return
        self._config.state_dir.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=self._state_path(provider).as_posix())

    def _state_path(self, provider: str) -> Path:
        return self._config.state_dir / f"{provider}.json"

    def _attached_context_active(self) -> bool:
        return self._attached_context is not None or self._attached_browser is not None

    def _prepare_visible_window(self, provider: str, context: Any) -> None:
        pages = list(context.pages)
        anchor = pages[0] if pages else context.new_page()
        for page in pages[1:]:
            with suppress(Exception):
                page.close()
        if self._state_path(provider).is_file():
            return
        anchor.goto(
            provider_login_url(provider),
            wait_until="domcontentloaded",
            timeout=max(self._config.wait_seconds, 1) * 1000,
        )
        print(
            f"Chrome is open for {provider}. The first email article URL will be used "
            "to verify login before any article text is analyzed."
        )

    def _confirm_manual_login_for_url(
        self,
        page: Any,
        *,
        provider: str,
        url: str,
    ) -> None:
        login_page = _new_context_page(page) or page
        print(
            f"{_provider_label(provider)} article access needs a logged-in browser session. "
            "Log in or clear human verification in Chrome, then return here."
        )
        if login_page.url in {"", "about:blank"}:
            login_page.goto(
                provider_login_url(provider),
                wait_until="domcontentloaded",
                timeout=max(self._config.wait_seconds, 1) * 1000,
            )
        input()
        _assert_provider_login_confirmed(
            login_page,
            provider=provider,
            wait_seconds=self._config.wait_seconds,
            verification_url=url,
            output=print,
        )
        if login_page is not page:
            with suppress(Exception):
                login_page.close()

    def _retry_after_manual_login(
        self,
        page: Any,
        *,
        provider: str,
        url: str,
        timeout_seconds: int,
    ) -> FetchedArticle:
        login_page = _new_context_page(page) or page
        print(
            f"The {provider} article opened to a login or human-verification page. "
            "Opening the provider login page now."
        )
        login_page.goto(
            provider_login_url(provider),
            wait_until="domcontentloaded",
            timeout=max(self._config.wait_seconds, 1) * 1000,
        )
        print(
            "Log in there, clear any human-verification prompt, then return here."
        )
        input()
        _assert_provider_login_confirmed(
            login_page,
            provider=provider,
            wait_seconds=self._config.wait_seconds,
            verification_url=url,
            output=print,
        )
        if login_page is not page:
            with suppress(Exception):
                login_page.close()
        return _fetch_page_article(
            page,
            url,
            timeout_seconds=timeout_seconds,
            wait_seconds=self._config.wait_seconds,
        )


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
        state_dir = (repo_root or DEFAULT_REPO_ROOT) / DEFAULT_STATE_DIR
    else:
        state_dir = config.article_browser_state_dir
    return BrowserSessionFetchConfig(
        state_dir=state_dir,
        wait_seconds=config.article_browser_wait_seconds,
        browser_channel=config.article_browser_channel,
        headless=config.article_browser_headless,
        cdp_url=config.article_browser_cdp_url,
    )


def fetch_with_browser_session(
    url: str,
    *,
    config: SubscriptionEmailConfig,
    timeout_seconds: int,
) -> FetchedArticle:
    fetch_config = browser_fetch_config(config)
    if fetch_config is None:
        raise BrowserSessionUnavailableError("browser article session is not configured")
    provider = provider_for_url(url)
    if provider is None:
        raise BrowserSessionUnavailableError(f"no browser-session provider for {url}")
    if fetch_config.cdp_url is not None:
        with BrowserArticleSession(config=config) as session:
            return session.fetch(url, timeout_seconds)
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


def article_login_preflight_providers(
    config: SubscriptionEmailConfig,
    providers: Sequence[str] | None = None,
) -> tuple[str, ...]:
    if (
        not config.follow_article_links
        or config.article_max_links_per_email == 0
        or config.article_max_total_per_run == 0
    ):
        return ()
    configured = tuple(providers or config.article_login_preflight_services)
    if not configured:
        configured = tuple(
            provider
            for provider in config.enabled_services
            if provider in PROVIDER_LOGIN_URLS
        )
    return tuple(
        dict.fromkeys(provider for provider in configured if provider in PROVIDER_LOGIN_URLS)
    )


def ensure_interactive_article_login(
    config: SubscriptionEmailConfig,
    *,
    providers: Sequence[str] | None = None,
    verification_urls: Mapping[str, str] | None = None,
    input_func: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> tuple[ArticleLoginPreflightResult, ...]:
    targets = article_login_preflight_providers(config, providers)
    if not targets:
        return ()
    fetch_config = browser_fetch_config(config)
    if fetch_config is None:
        raise BrowserSessionUnavailableError("browser article session is not configured")
    if fetch_config.cdp_url is not None:
        return _ensure_login_with_attached_chrome(
            fetch_config,
            targets,
            verification_urls=dict(verification_urls or {}),
            input_func=input_func,
            output=output,
        )
    return tuple(
        _ensure_login_with_persistent_context(
            fetch_config,
            provider,
            verification_url=(verification_urls or {}).get(provider),
            input_func=input_func,
            output=output,
        )
        for provider in targets
    )


def _ensure_login_with_attached_chrome(
    config: BrowserSessionFetchConfig,
    providers: tuple[str, ...],
    *,
    verification_urls: dict[str, str],
    input_func: Callable[[str], str],
    output: Callable[[str], None],
) -> tuple[ArticleLoginPreflightResult, ...]:
    manager = _playwright_sync_api().sync_playwright()
    runtime = manager.start()
    try:
        first_login_url = provider_login_url(providers[0])
        browser = _connect_or_start_cdp_browser(
            runtime,
            config,
            first_login_url=first_login_url,
            output=output,
            input_func=input_func,
        )
        contexts = list(browser.contexts)
        if not contexts:
            raise BrowserSessionUnavailableError(
                "connected Chrome has no browser context; open a normal tab first"
            )
        context = contexts[0]
        results: list[ArticleLoginPreflightResult] = []
        for provider in providers:
            login_url = provider_login_url(provider)
            page = context.new_page()
            try:
                page.goto(
                    login_url,
                    wait_until="domcontentloaded",
                    timeout=max(config.wait_seconds, 1) * 1000,
                )
                provider_label = _provider_label(provider)
                output(
                    f"Opened {provider_label} login in your Chrome window. Log in there, "
                    "clear any human-verification prompt, confirm provider content loads "
                    "normally, then return here."
                )
                input_func(
                    "Press Enter only after you are fully logged in and ready for "
                    "the email agent..."
                )
                verification_url = verification_urls.get(provider)
                _assert_provider_login_confirmed(
                    page,
                    provider=provider,
                    wait_seconds=config.wait_seconds,
                    verification_url=verification_url,
                    output=output,
                )
                results.append(
                    ArticleLoginPreflightResult(
                        provider=provider,
                        login_url=login_url,
                        mode="attached_chrome_cdp",
                        confirmed=True,
                        verification_url=verification_url,
                    )
                )
            finally:
                with suppress(Exception):
                    page.close()
        return tuple(results)
    finally:
        with suppress(Exception):
            runtime.stop()


def _connect_or_start_cdp_browser(
    runtime: Any,
    config: BrowserSessionFetchConfig,
    *,
    first_login_url: str,
    output: Callable[[str], None],
    input_func: Callable[[str], str] | None = None,
) -> Any:
    try:
        return runtime.chromium.connect_over_cdp(str(config.cdp_url))
    except Exception as first_exc:
        output(
            f"Chrome DevTools was not reachable at {config.cdp_url}; opening your "
            "regular installed Chrome with local agent access now."
        )
        try:
            _start_cdp_browser(config, first_login_url)
        except Exception as start_exc:
            message = (
                f"could not open regular Chrome for {config.cdp_url}; start Chrome "
                "with local remote debugging and retry the email agent"
            )
            raise BrowserSessionUnavailableError(message) from start_exc
        browser, last_exc = _connect_to_cdp_until_deadline(runtime, config, first_exc)
        if browser is not None:
            return browser
        if input_func is not None:
            output(
                "Chrome still did not expose the local agent port. If Chrome was "
                "already open before this refresh, close all Chrome windows now; "
                "then press Enter and the agent will reopen regular Chrome with "
                "the required local access."
            )
            input_func("Press Enter after closing Chrome, or Ctrl+C to cancel...")
            try:
                _start_cdp_browser(config, first_login_url)
            except Exception as restart_exc:
                message = (
                    f"could not reopen regular Chrome for {config.cdp_url}; start "
                    "Chrome with local remote debugging and retry the email agent"
                )
                raise BrowserSessionUnavailableError(message) from restart_exc
            browser, last_exc = _connect_to_cdp_until_deadline(runtime, config, last_exc)
            if browser is not None:
                return browser
        message = (
            f"could not connect to Chrome DevTools at {config.cdp_url} after "
            "opening regular Chrome. Close existing Chrome windows and press the "
            "dashboard login refresh again, or start Chrome with local remote "
            "debugging before running the email agent."
        )
        output(message)
        raise BrowserSessionUnavailableError(message) from last_exc


def _connect_to_cdp_until_deadline(
    runtime: Any,
    config: BrowserSessionFetchConfig,
    first_exc: Exception,
) -> tuple[Any | None, Exception]:
    deadline = time.monotonic() + CDP_CONNECT_RETRY_SECONDS
    last_exc: Exception = first_exc
    while time.monotonic() <= deadline:
        try:
            return runtime.chromium.connect_over_cdp(str(config.cdp_url)), last_exc
        except Exception as retry_exc:
            last_exc = retry_exc
            time.sleep(CDP_CONNECT_SLEEP_SECONDS)
    return None, last_exc


def _start_cdp_browser(config: BrowserSessionFetchConfig, first_login_url: str) -> None:
    executable = _browser_executable(config.browser_channel)
    command = [
        executable,
        f"--remote-debugging-port={_cdp_port(config.cdp_url)}",
        "--remote-debugging-address=127.0.0.1",
        "--new-window",
        "--start-maximized",
        first_login_url,
    ]
    if _use_dedicated_article_login_profile():
        user_data_dir = config.state_dir / "profiles" / "attached-chrome"
        user_data_dir.mkdir(parents=True, exist_ok=True)
        command.insert(3, f"--user-data-dir={user_data_dir}")
    kwargs: dict[str, object] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def _use_dedicated_article_login_profile() -> bool:
    value = os.environ.get("AGENCY_ARTICLE_LOGIN_DEDICATED_PROFILE", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _browser_executable(browser_channel: str) -> str:
    candidates = _browser_executable_candidates(browser_channel)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in _browser_command_candidates(browser_channel):
        resolved = shutil.which(name)
        if resolved is not None:
            return resolved
    return _browser_command_candidates(browser_channel)[0]


def _browser_executable_candidates(browser_channel: str) -> tuple[str, ...]:
    program_files = os.environ.get("PROGRAMFILES", "")
    program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if browser_channel == "msedge":
        return (
            str(Path(program_files) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(program_files_x86) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
            str(Path(local_app_data) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
        )
    if browser_channel == "chrome":
        return (
            str(Path(program_files) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(program_files_x86) / "Google" / "Chrome" / "Application" / "chrome.exe"),
            str(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        )
    return ()


def _browser_command_candidates(browser_channel: str) -> tuple[str, ...]:
    if browser_channel == "msedge":
        return ("msedge",)
    if browser_channel == "chrome":
        return ("chrome", "google-chrome")
    return ("chromium", "chromium-browser")


def _cdp_port(cdp_url: str | None) -> str:
    parsed = urlsplit(cdp_url or "")
    if parsed.port is None:
        return DEFAULT_CDP_PORT
    return str(parsed.port)


def _provider_label(provider: str) -> str:
    return provider.replace("_", " ").title()


def _ensure_login_with_persistent_context(
    config: BrowserSessionFetchConfig,
    provider: str,
    *,
    verification_url: str | None,
    input_func: Callable[[str], str],
    output: Callable[[str], None],
) -> ArticleLoginPreflightResult:
    config.state_dir.mkdir(parents=True, exist_ok=True)
    state_path = config.state_dir / f"{provider}.json"
    profile_dir = config.state_dir / "profiles" / provider
    profile_dir.mkdir(parents=True, exist_ok=True)
    login_url = provider_login_url(provider)
    playwright = _playwright_sync_api()
    with playwright.sync_playwright() as runtime:
        context = runtime.chromium.launch_persistent_context(
            profile_dir.as_posix(),
            headless=False,
            **_launch_options(config.browser_channel),
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(
            login_url,
            wait_until="domcontentloaded",
            timeout=max(config.wait_seconds, 1) * 1000,
        )
        provider_label = _provider_label(provider)
        output(
            f"Opened {provider_label} login in Chrome. Log in there, clear any "
            "human-verification prompt, confirm provider content loads normally, "
            "then return here."
        )
        input_func(
            "Press Enter only after you are fully logged in and ready for the email agent..."
        )
        _assert_provider_login_confirmed(
            page,
            provider=provider,
            wait_seconds=config.wait_seconds,
            verification_url=verification_url,
            output=output,
        )
        context.storage_state(path=state_path.as_posix())
        context.close()
    return ArticleLoginPreflightResult(
        provider=provider,
        login_url=login_url,
        mode="persistent_browser_profile",
        confirmed=True,
        state_path=state_path,
        verification_url=verification_url,
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
        _assert_provider_login_confirmed(
            page,
            provider=provider,
            wait_seconds=5,
            verification_url=None,
            output=print,
        )
        context.storage_state(path=state_path.as_posix())
        context.close()
    return state_path


def _assert_provider_login_confirmed(
    page: Any,
    *,
    provider: str,
    wait_seconds: int,
    verification_url: str | None = None,
    output: Callable[[str], None],
) -> None:
    provider_label = _provider_label(provider)
    if verification_url:
        output(
            f"Verifying {provider_label} login with an article link extracted from "
            f"the selected email batch: {_safe_url_label(verification_url)}"
        )
        page.goto(
            verification_url,
            wait_until="domcontentloaded",
            timeout=max(wait_seconds, 1) * 1000,
        )
        with suppress(Exception):
            page.wait_for_timeout(max(wait_seconds, 1) * 1000)
    deadline = time.monotonic() + max(float(wait_seconds), 1.0)
    article = _article_from_page(page, None)
    while _looks_like_login(article) and time.monotonic() < deadline:
        with suppress(Exception):
            page.wait_for_timeout(500)
        article = _article_from_page(page, None)
    if _looks_like_login(article):
        raise BrowserSessionUnavailableError(
            f"{provider_label} login was not verified; the email agent will not open "
            "article links. Finish login/human verification in Chrome, confirm the "
        "provider page is usable, then run the email agent again."
        )
    output(f"{provider_label} login verified; article links may now be opened.")


def _safe_url_label(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, "", ""))


def _new_context_page(page: Any) -> Any | None:
    context = getattr(page, "context", None)
    if context is None:
        return None
    with suppress(Exception):
        return context.new_page()
    return None


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
        response = _goto_for_article_content(page, url, timeout_ms=timeout_ms)
        with suppress(Exception):
            page.wait_for_timeout(wait_seconds * 1000)
        article = _article_from_page(page, response)
        browser.close()
    return article


def _fetch_page_article(
    page: Any,
    url: str,
    *,
    timeout_seconds: int,
    wait_seconds: int,
) -> FetchedArticle:
    response = _goto_for_article_content(
        page,
        url,
        timeout_ms=timeout_seconds * 1000,
    )
    with suppress(Exception):
        page.wait_for_timeout(wait_seconds * 1000)
    return _article_from_page(page, response)


def _goto_for_article_content(page: Any, url: str, *, timeout_ms: int) -> Any | None:
    try:
        return page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except Exception as exc:
        if _is_navigation_timeout(exc):
            return None
        raise


def _is_navigation_timeout(exc: Exception) -> bool:
    error_name = exc.__class__.__name__.lower()
    message = str(exc).lower()
    return "timeout" in error_name and ("goto" in message or "navigation" in message)


def _article_from_page(page: Any, response: Any | None) -> FetchedArticle:
    title, text = html_to_text(page.content())
    return FetchedArticle(
        url=page.url,
        status_code=0 if response is None else int(response.status),
        title=title,
        text=text,
    )


def _looks_like_login(article: FetchedArticle) -> bool:
    if int(article.status_code) in {401, 403}:
        return True
    if looks_like_readable_article(article):
        return False
    text = " ".join(article.text.split()).lower()
    markers = (
        "access to this page has been denied",
        "before we continue",
        "confirm you are a human",
        "sign in to continue",
        "sign in",
        "log in",
        "not a bot",
        "press & hold",
        "press and hold",
        "subscribe to continue",
        "create an account",
        "security code",
    )
    return any(marker in text for marker in markers)


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
