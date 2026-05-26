from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MIN_ARTICLE_CHARS = 100
MIN_MONITOR_POLL_SECONDS = 5
MIN_BROWSER_WAIT_SECONDS = 1
MIN_MAILBOX_MAX_MESSAGES = 1
SUPPORTED_ARTICLE_FETCH_MODES = {"auto", "http", "browser"}
SUPPORTED_BROWSER_CHANNELS = {"chromium", "chrome", "msedge"}
SUPPORTED_MODES = {"local_eml", "gmail", "outlook", "imap"}
SUPPORTED_UNMATCHED_TICKER_POLICIES = {"manual_review", "ignore"}


@dataclass(frozen=True)
class SubscriptionEmailConfig:
    mode: str
    input_path: Path
    enabled_services: tuple[str, ...]
    allowed_sender_domains: tuple[str, ...]
    tickers: tuple[str, ...]
    lookback_days: int = 30
    unmatched_ticker_policy: str = "manual_review"
    mailbox_label: str | None = None
    token_path: Path | None = None
    follow_article_links: bool = False
    article_link_domains: tuple[str, ...] = ()
    article_max_links_per_email: int = 1
    article_max_total_per_run: int = 5
    article_fetch_timeout_seconds: int = 15
    article_max_chars: int = 12_000
    article_fetch_mode: str = "auto"
    article_browser_state_dir: Path | None = None
    article_analysis_cache_path: Path | None = None
    article_browser_wait_seconds: int = 5
    article_browser_channel: str = "chrome"
    article_browser_headless: bool = True
    article_browser_cdp_url: str | None = None
    article_login_preflight_required: bool = False
    article_login_preflight_services: tuple[str, ...] = ()
    article_login_preflight_confirmed: bool = False
    article_cache_ttl_hours: int = 168
    article_llm_analysis_enabled: bool = False
    article_llm_model: str = "gpt-5-nano"
    article_llm_timeout_seconds: int = 45
    mailbox_host: str | None = None
    mailbox_port: int = 993
    mailbox_username_env: str = "SUBSCRIPTION_EMAIL_USERNAME"
    mailbox_password_env: str = "SUBSCRIPTION_EMAIL_PASSWORD"
    mailbox_search: str = "UNSEEN"
    mailbox_unseen_only: bool = True
    mailbox_max_messages: int = 10
    mailbox_mark_seen: bool = False
    monitor_poll_seconds: int = 60


def load_subscription_email_config(path: Path, *, repo_root: Path) -> SubscriptionEmailConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("subscription email config must be a JSON object")
    follow_article_links = _boolean(payload, "follow_article_links", False)
    enabled_services = _strings(payload, "enabled_services")
    article_login_preflight_services = _strings(
        payload,
        "article_login_preflight_services",
    )
    require_login_preflight = _boolean(
        payload,
        "article_login_preflight_required",
        False,
    )
    if follow_article_links and "seeking_alpha" in enabled_services:
        require_login_preflight = True
        if "seeking_alpha" not in article_login_preflight_services:
            article_login_preflight_services = (
                *article_login_preflight_services,
                "seeking_alpha",
            )
    config = SubscriptionEmailConfig(
        mode=_string(payload, "mode", "local_eml"),
        input_path=_path(payload, "input_path", repo_root=repo_root),
        enabled_services=enabled_services,
        allowed_sender_domains=_domains(payload, "allowed_sender_domains"),
        tickers=tuple(ticker.upper() for ticker in _strings(payload, "tickers")),
        lookback_days=_integer(payload, "lookback_days", 30),
        unmatched_ticker_policy=_string(payload, "unmatched_ticker_policy", "manual_review"),
        mailbox_label=_optional_string(payload, "mailbox_label"),
        token_path=_optional_path(payload, "token_path", repo_root=repo_root),
        follow_article_links=follow_article_links,
        article_link_domains=_domains(payload, "article_link_domains"),
        article_max_links_per_email=_integer(payload, "article_max_links_per_email", 1),
        article_max_total_per_run=_integer(payload, "article_max_total_per_run", 5),
        article_fetch_timeout_seconds=_integer(payload, "article_fetch_timeout_seconds", 15),
        article_max_chars=_integer(payload, "article_max_chars", 12_000),
        article_fetch_mode=_string(payload, "article_fetch_mode", "auto"),
        article_browser_state_dir=_optional_path(
            payload,
            "article_browser_state_dir",
            repo_root=repo_root,
        ),
        article_analysis_cache_path=(
            _optional_path(payload, "article_analysis_cache_path", repo_root=repo_root)
            or repo_root / "research" / "config" / "article-analysis-cache.local.json"
        ),
        article_browser_wait_seconds=_integer(payload, "article_browser_wait_seconds", 5),
        article_browser_channel=_string(payload, "article_browser_channel", "chrome"),
        article_browser_headless=_boolean(payload, "article_browser_headless", True),
        article_browser_cdp_url=_optional_string(payload, "article_browser_cdp_url"),
        article_login_preflight_required=require_login_preflight,
        article_login_preflight_services=article_login_preflight_services,
        article_cache_ttl_hours=_integer(payload, "article_cache_ttl_hours", 168),
        article_llm_analysis_enabled=_boolean(payload, "article_llm_analysis_enabled", False),
        article_llm_model=_string(payload, "article_llm_model", "gpt-5-nano"),
        article_llm_timeout_seconds=_integer(payload, "article_llm_timeout_seconds", 45),
        mailbox_host=_optional_string(payload, "mailbox_host"),
        mailbox_port=_integer(payload, "mailbox_port", 993),
        mailbox_username_env=_string(
            payload,
            "mailbox_username_env",
            "SUBSCRIPTION_EMAIL_USERNAME",
        ),
        mailbox_password_env=_string(
            payload,
            "mailbox_password_env",
            "SUBSCRIPTION_EMAIL_PASSWORD",
        ),
        mailbox_search=_string(payload, "mailbox_search", "UNSEEN"),
        mailbox_unseen_only=_boolean(payload, "mailbox_unseen_only", True),
        mailbox_max_messages=_integer(payload, "mailbox_max_messages", 10),
        mailbox_mark_seen=_boolean(payload, "mailbox_mark_seen", False),
        monitor_poll_seconds=_integer(payload, "monitor_poll_seconds", 60),
    )
    _validate(config)
    return config


def _validate(config: SubscriptionEmailConfig) -> None:
    if config.mode not in SUPPORTED_MODES:
        raise ValueError(f"unsupported subscription email mode: {config.mode}")
    known_services = {"seeking_alpha", "tradevision", "zacks"}
    unknown = sorted(set(config.enabled_services).difference(known_services))
    if unknown:
        raise ValueError(f"unknown subscription email service(s): {unknown}")
    if config.lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    if config.unmatched_ticker_policy not in SUPPORTED_UNMATCHED_TICKER_POLICIES:
        raise ValueError("unmatched_ticker_policy must be manual_review or ignore")
    _validate_article_config(config)
    _validate_mailbox_config(config)


def _validate_article_config(config: SubscriptionEmailConfig) -> None:
    if config.article_max_links_per_email < 0:
        raise ValueError("article_max_links_per_email must be >= 0")
    if config.article_max_total_per_run < 0:
        raise ValueError("article_max_total_per_run must be >= 0")
    if config.article_fetch_timeout_seconds < 1:
        raise ValueError("article_fetch_timeout_seconds must be >= 1")
    if config.article_max_chars < MIN_ARTICLE_CHARS:
        raise ValueError("article_max_chars must be >= 100")
    if config.article_fetch_mode not in SUPPORTED_ARTICLE_FETCH_MODES:
        raise ValueError("article_fetch_mode must be auto, http, or browser")
    if config.article_browser_wait_seconds < MIN_BROWSER_WAIT_SECONDS:
        raise ValueError("article_browser_wait_seconds must be >= 1")
    if config.article_browser_channel not in SUPPORTED_BROWSER_CHANNELS:
        raise ValueError("article_browser_channel must be chromium, chrome, or msedge")
    unknown_preflight = sorted(
        set(config.article_login_preflight_services).difference(config.enabled_services)
    )
    if unknown_preflight:
        raise ValueError(
            "article_login_preflight_services must be enabled service names: "
            f"{unknown_preflight}"
        )
    if config.article_llm_timeout_seconds < 1:
        raise ValueError("article_llm_timeout_seconds must be >= 1")
    if config.article_cache_ttl_hours < 1:
        raise ValueError("article_cache_ttl_hours must be >= 1")


def _validate_mailbox_config(config: SubscriptionEmailConfig) -> None:
    if config.mailbox_port < 1:
        raise ValueError("mailbox_port must be >= 1")
    if config.mode == "imap" and config.mailbox_host is None:
        raise ValueError("mailbox_host is required when mode is imap")
    if config.mailbox_max_messages < MIN_MAILBOX_MAX_MESSAGES:
        raise ValueError("mailbox_max_messages must be >= 1")
    if config.monitor_poll_seconds < MIN_MONITOR_POLL_SECONDS:
        raise ValueError("monitor_poll_seconds must be >= 5")


def _string(payload: dict[str, Any], key: str, default: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or value.strip() == "":
        raise TypeError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    text = value.strip()
    return text or None


def _strings(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError(f"{key} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def _domains(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    return tuple(item.lower().lstrip("@") for item in _strings(payload, key))


def _integer(payload: dict[str, Any], key: str, default: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    return int(value)


def _boolean(payload: dict[str, Any], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise TypeError(f"{key} must be a boolean")
    return value


def _path(payload: dict[str, Any], key: str, *, repo_root: Path) -> Path:
    value = _string(payload, key, "")
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _optional_path(payload: dict[str, Any], key: str, *, repo_root: Path) -> Path | None:
    value = _optional_string(payload, key)
    if value is None:
        return None
    path = Path(value)
    return path if path.is_absolute() else repo_root / path
