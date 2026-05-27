from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "research" / "config" / "live-refresh.local.json"
LOCAL_SQLITE_URLS = {
    "sqlite:///./agency_local.db",
    "sqlite+aiosqlite:///./agency_local.db",
}


def check_operational_preflight(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env: Mapping[str, str] | None = None,
    today: date | None = None,
) -> dict[str, object]:
    values = os.environ if env is None else env
    current_day = today or date.today()
    config = _read_json_object(config_path)
    checks = [
        _config_end_check(config_path, config, current_day),
        _scheduler_check(values),
        _database_check(values),
        _subscription_email_check(config_path, config, values),
    ]
    blocker_count = sum(1 for check in checks if check["status"] == "BLOCK")
    warning_count = sum(1 for check in checks if check["status"] == "WARN")
    state = "blocked" if blocker_count else "warning" if warning_count else "ready"
    return {
        "ready": blocker_count == 0,
        "state": state,
        "status_label": _status_label(state),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "checks": checks,
    }


def _config_end_check(
    config_path: Path,
    config: Mapping[str, object] | None,
    today: date,
) -> dict[str, str]:
    if config is None:
        return _check(
            "Live refresh date",
            "BLOCK",
            f"Live refresh config is missing or unreadable: {_display_path(config_path)}",
            f"Create or repair {_display_path(config_path)} before starting the app.",
        )
    end_value = str(config.get("end") or "").strip()
    try:
        config_end = date.fromisoformat(end_value)
    except ValueError:
        return _check(
            "Live refresh date",
            "BLOCK",
            f"Live refresh config end date is invalid: {end_value or 'not set'}",
            f"Set config end to {today.isoformat()} before starting the app.",
        )
    if config_end < today:
        return _check(
            "Live refresh date",
            "BLOCK",
            f"Live refresh config ends at {config_end.isoformat()}, before today.",
            f"Set research/config/live-refresh.local.json end to {today.isoformat()}.",
        )
    return _check(
        "Live refresh date",
        "PASS",
        f"Live refresh config covers {config_end.isoformat()}.",
        "No config date change needed.",
    )


def _scheduler_check(env: Mapping[str, str]) -> dict[str, str]:
    value = str(env.get("AGENCY_SCHEDULER_ENABLED") or "").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return _check(
            "Automatic scheduler",
            "BLOCK",
            "AGENCY_SCHEDULER_ENABLED disables automatic lane refresh and runtime cycles.",
            "Set AGENCY_SCHEDULER_ENABLED=true before live operation.",
        )
    return _check(
        "Automatic scheduler",
        "PASS",
        "Automatic scheduler is enabled or using the app default.",
        "No scheduler action needed.",
    )


def _database_check(env: Mapping[str, str]) -> dict[str, str]:
    url = str(env.get("DATABASE_URL") or "").strip()
    allow_local = _truthy(env.get("AGENCY_ALLOW_LOCAL_DB_FALLBACK"))
    if not url or _is_local_sqlite(url):
        if allow_local:
            return _check(
                "Database persistence",
                "PASS",
                "The local SQLite fallback is explicitly allowed for this run.",
                "Use this only for local development or paper rehearsals.",
            )
        return _check(
            "Database persistence",
            "WARN",
            "The app will use the local SQLite fallback; this is not shared durable storage.",
            "Set DATABASE_URL for Postgres, or set AGENCY_ALLOW_LOCAL_DB_FALLBACK=true intentionally.",
        )
    return _check(
        "Database persistence",
        "PASS",
        "DATABASE_URL points to configured persistence.",
        "No database action needed.",
    )


def _subscription_email_check(
    config_path: Path,
    config: Mapping[str, object] | None,
    env: Mapping[str, str],
) -> dict[str, str]:
    if config is None:
        return _check(
            "Subscription email analyzer",
            "PASS",
            "Subscription email config cannot be evaluated until live refresh config exists.",
            "Repair live refresh config first.",
        )
    datasets = _strings(config.get("datasets"))
    config_value = str(config.get("subscription_email_config") or "").strip()
    if "subscription_emails" not in datasets and not config_value:
        return _check(
            "Subscription email analyzer",
            "PASS",
            "Subscription email analysis is not enabled in the live refresh config.",
            "No subscription email action needed.",
        )
    email_config_path = _resolve_path(config_value, base=config_path.parent)
    if email_config_path is None or not email_config_path.is_file():
        return _check(
            "Subscription email analyzer",
            "WARN",
            "Subscription email config is missing, so paid email analysis cannot run.",
            "Create subscription-email.local.json or remove subscription_emails from this run.",
        )
    email_config = _read_json_object(email_config_path)
    if email_config is None:
        return _check(
            "Subscription email analyzer",
            "WARN",
            "Subscription email config is unreadable.",
            "Repair the subscription email config and rerun preflight.",
        )
    if email_config.get("article_login_preflight_required") is True:
        return _check(
            "Subscription email analyzer",
            "WARN",
            "Article login preflight is required before Seeking Alpha-style links can be analyzed.",
            "Open email login refresh, complete the visible login, then rerun email analysis.",
        )
    missing = _missing_mailbox_credentials(email_config, env)
    if missing:
        return _check(
            "Subscription email analyzer",
            "WARN",
            f"Mailbox credentials are missing: {', '.join(missing)}.",
            "Add mailbox credentials or run the login refresh flow before email analysis.",
        )
    return _check(
        "Subscription email analyzer",
        "PASS",
        "Subscription email analyzer configuration is available.",
        "No email analyzer action needed.",
    )


def _missing_mailbox_credentials(
    email_config: Mapping[str, object],
    env: Mapping[str, str],
) -> list[str]:
    mode = str(email_config.get("mode") or "local_eml").strip().lower()
    if mode not in {"gmail", "outlook", "imap"}:
        return []
    username_env = str(email_config.get("mailbox_username_env") or "SUBSCRIPTION_EMAIL_USERNAME")
    password_env = str(email_config.get("mailbox_password_env") or "SUBSCRIPTION_EMAIL_PASSWORD")
    return [name for name in (username_env, password_env) if not str(env.get(name) or "").strip()]


def _read_json_object(path: Path) -> Mapping[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _resolve_path(value: str, *, base: Path) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    if (base / path).is_file():
        return base / path
    return REPO_ROOT / path


def _strings(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if str(item).strip()}


def _is_local_sqlite(url: str) -> bool:
    normalized = url.strip().lower().replace("\\", "/")
    return normalized in LOCAL_SQLITE_URLS or normalized.endswith("/agency_local.db")


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _status_label(state: str) -> str:
    return {
        "blocked": "Preflight Blocked",
        "warning": "Preflight Needs Review",
        "ready": "Preflight Ready",
    }[state]


def _check(name: str, status: str, detail: str, action: str) -> dict[str, str]:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "action": action,
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check local live-operation preflight.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--allow-warnings", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    summary = check_operational_preflight(config_path=args.config)
    print(json.dumps(summary, sort_keys=True))
    if summary["blocker_count"] or (summary["warning_count"] and not args.allow_warnings):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
