from __future__ import annotations

import csv
import json
import os
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENT_ROOT = REPO_ROOT.parent / "email news agent"
DEFAULT_CONFIG_NAME = "config.yaml"
DEFAULT_RUN_CONFIG_NAME = "data/agency_config.yaml"
DEFAULT_AGENCY_UNIVERSE_CONFIG_NAME = "data/agency_active_universe.csv"
DEFAULT_AGENCY_UNIVERSE_STATUS_NAME = "data/agency_active_universe_status.json"
DEFAULT_ENV_NAME = ".env"
DEFAULT_PARQUET_PATH = REPO_ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet"
DEFAULT_MANIFEST_PATH = REPO_ROOT / "research" / "data" / "manifests" / "subscription_emails.json"
DEFAULT_SUMMARY_ROOT = REPO_ROOT / "research" / "results" / "latest-subscription-emails"
DEFAULT_MINI_CYCLE_STATUS_PATH = DEFAULT_SUMMARY_ROOT / "subscription-email-mini-cycle-status.json"
TERMINAL_RELEVANT = {"processed_relevant"}
TERMINAL_ANALYZED = {"processed_relevant", "irrelevant_seen"}
TERMINAL_FAILED = {"failed_access", "failed_extract", "failed_llm", "failed_telegram"}
ACTIVE_PROCESSING = {"processing"}


@dataclass(frozen=True)
class PortfolioNewsAgentConfig:
    root: Path
    config_path: Path
    env_path: Path
    database_path: Path | None
    browser_cdp_url: str | None
    browser_profile_dir: Path | None
    openai_model: str | None
    prompt_version: str


def portfolio_news_agent_root() -> Path:
    return Path(os.environ.get("AGENCY_PORTFOLIO_NEWS_AGENT_ROOT") or DEFAULT_AGENT_ROOT)


def portfolio_news_agent_config_path(root: Path | None = None) -> Path:
    root = root or portfolio_news_agent_root()
    value = os.environ.get("AGENCY_PORTFOLIO_NEWS_AGENT_CONFIG") or DEFAULT_CONFIG_NAME
    return _resolve_agent_path(root, value)


def portfolio_news_agent_run_config_path(root: Path | None = None) -> Path:
    root = root or portfolio_news_agent_root()
    value = os.environ.get("AGENCY_PORTFOLIO_NEWS_AGENT_RUN_CONFIG") or DEFAULT_RUN_CONFIG_NAME
    return _resolve_agent_path(root, value)


def ensure_portfolio_news_agent_agency_config(
    *,
    root: Path | None = None,
    repo_root: Path | None = None,
    as_of: date | None = None,
) -> Path:
    root = root or portfolio_news_agent_root()
    source_path = portfolio_news_agent_config_path(root)
    run_config_path = portfolio_news_agent_run_config_path(root)
    if not source_path.exists():
        return source_path
    universe_export = export_agency_active_universe_for_portfolio_news_agent(
        root=root,
        repo_root=repo_root or REPO_ROOT,
        as_of=as_of,
    )
    portfolio_file = _agent_config_path_text(root, Path(str(universe_export["path"])))
    source_text = source_path.read_text(encoding="utf-8-sig")
    run_config_text = _with_agency_runtime_overrides(
        source_text,
        portfolio_file=portfolio_file,
    )
    run_config_path.parent.mkdir(parents=True, exist_ok=True)
    run_config_path.write_text(run_config_text, encoding="utf-8")
    return run_config_path


def export_agency_active_universe_for_portfolio_news_agent(
    *,
    root: Path | None = None,
    repo_root: Path | None = None,
    as_of: date | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    root = root or portfolio_news_agent_root()
    repo_root = repo_root or REPO_ROOT
    as_of = as_of or date.today()
    output_path = output_path or _resolve_agent_path(root, DEFAULT_AGENCY_UNIVERSE_CONFIG_NAME)
    status_path = _resolve_agent_path(root, DEFAULT_AGENCY_UNIVERSE_STATUS_NAME)
    rows, issues = _agency_active_universe_portfolio_rows(repo_root, as_of=as_of)
    _write_universe_portfolio_csv(output_path, rows)
    payload = {
        "schema_version": "0.1.0",
        "source": "trading_agency_active_universe",
        "source_path": str(_universe_membership_path(repo_root)),
        "path": str(output_path),
        "as_of": as_of.isoformat(),
        "active_universe_count": len(rows),
        "sample_tickers": [str(row["symbol"]) for row in rows[:10]],
        "issues": issues,
        "generated_at": _utc_now_dt().isoformat(),
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def portfolio_news_agent_env_path(root: Path | None = None) -> Path:
    root = root or portfolio_news_agent_root()
    value = os.environ.get("AGENCY_PORTFOLIO_NEWS_AGENT_ENV") or DEFAULT_ENV_NAME
    return _resolve_agent_path(root, value)


def portfolio_news_agent_python(root: Path | None = None) -> str:
    root = root or portfolio_news_agent_root()
    value = os.environ.get("AGENCY_PORTFOLIO_NEWS_AGENT_PYTHON")
    if value:
        return value
    return str(root / ".venv" / "Scripts" / "python.exe")


def load_portfolio_news_agent_status(
    *,
    root: Path | None = None,
    endpoint_checker: Callable[[str], bool] | None = None,
) -> dict[str, object]:
    config = load_portfolio_news_agent_config(root=root)
    if config is None:
        return _not_configured_status(root or portfolio_news_agent_root())

    browser_ready = (
        bool(config.browser_cdp_url)
        and (endpoint_checker or _is_cdp_endpoint_available)(str(config.browser_cdp_url))
    )
    db_status = _read_database_status(config.database_path) if config.database_path else {}
    return _with_mini_cycle_status(
        _status_from_database(config, browser_ready=browser_ready, db_status=db_status),
        _read_json_object(DEFAULT_MINI_CYCLE_STATUS_PATH),
    )


def load_portfolio_news_agent_config(
    *,
    root: Path | None = None,
) -> PortfolioNewsAgentConfig | None:
    root = root or portfolio_news_agent_root()
    config_path = portfolio_news_agent_config_path(root)
    env_path = portfolio_news_agent_env_path(root)
    if not root.exists() or not config_path.exists():
        return None
    payload = _read_simple_yaml(config_path)
    database_path = _optional_path(root, payload.get("database_path"))
    browser_profile_dir = _optional_path(root, payload.get("browser_profile_dir"))
    return PortfolioNewsAgentConfig(
        root=root,
        config_path=config_path,
        env_path=env_path,
        database_path=database_path,
        browser_cdp_url=_optional_text(payload.get("browser_cdp_url")),
        browser_profile_dir=browser_profile_dir,
        openai_model=_optional_text(payload.get("openai_model")),
        prompt_version=_optional_text(payload.get("prompt_version")) or "v1",
    )


def export_portfolio_news_agent_events(
    *,
    root: Path | None = None,
    repo_root: Path | None = None,
    as_of: date | None = None,
    parquet_path: Path = DEFAULT_PARQUET_PATH,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    summary_root: Path = DEFAULT_SUMMARY_ROOT,
) -> dict[str, object]:
    config = load_portfolio_news_agent_config(root=root)
    if config is None or config.database_path is None or not config.database_path.exists():
        return {
            "status": "not_configured",
            "event_rows": 0,
            "detail": "Portfolio News Agent DB is not available.",
        }
    repo_root = repo_root or REPO_ROOT
    as_of = as_of or date.today()
    active_tickers, universe_issues = _agency_active_universe_tickers(repo_root, as_of=as_of)
    previous_source_ids = _existing_source_ids(parquet_path)
    raw_rows = _portfolio_news_event_rows(config.database_path)
    filtered_rows = [
        row for row in raw_rows if str(row.get("ticker") or "").strip().upper() in active_tickers
    ]
    rows = _dedupe_event_rows(filtered_rows)
    ignored_out_of_universe = len(raw_rows) - len(filtered_rows)
    removed_existing_out_of_universe = _remove_out_of_universe_subscription_email_rows(
        parquet_path,
        active_tickers,
    )
    affected_rows = [
        row for row in rows if str(row.get("source_id") or "") not in previous_source_ids
    ]
    affected_tickers = _ticker_list(affected_rows)
    if rows:
        from subscription_email.storage import write_event_frame

        write_event_frame(parquet_path, pd.DataFrame(rows))
    _write_subscription_email_manifest(
        manifest_path=manifest_path,
        parquet_path=parquet_path,
        fetched_at=_utc_now_dt(),
        issues=_portfolio_news_manifest_issues(
            rows=rows,
            universe_issues=universe_issues,
            ignored_out_of_universe=ignored_out_of_universe,
            removed_existing_out_of_universe=removed_existing_out_of_universe,
        ),
    )
    summary = _portfolio_news_export_summary(
        config,
        rows,
        affected_tickers=affected_tickers,
        affected_event_rows=len(affected_rows),
        active_universe_count=len(active_tickers),
        ignored_out_of_universe_event_rows=ignored_out_of_universe,
        removed_existing_out_of_universe_event_rows=removed_existing_out_of_universe,
        universe_issues=universe_issues,
    )
    summary_root.mkdir(parents=True, exist_ok=True)
    (summary_root / "subscription-email-ingest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "exported",
        "event_rows": len(rows),
        "affected_event_rows": len(affected_rows),
        "affected_tickers": affected_tickers,
        "active_universe_count": len(active_tickers),
        "ignored_out_of_universe_event_rows": ignored_out_of_universe,
        "removed_existing_out_of_universe_event_rows": removed_existing_out_of_universe,
        "parquet_path": str(parquet_path),
        "manifest_path": str(manifest_path),
    }


def _status_from_database(
    config: PortfolioNewsAgentConfig,
    *,
    browser_ready: bool,
    db_status: Mapping[str, object],
) -> dict[str, object]:
    latest_run = _mapping(db_status.get("latest_run"))
    status_counts = _mapping(db_status.get("link_status_counts"))
    link_total = _int(db_status.get("link_total"))
    analyzed = sum(_int(status_counts.get(status)) for status in TERMINAL_ANALYZED)
    relevant = sum(_int(status_counts.get(status)) for status in TERMINAL_RELEVANT)
    failed = sum(_int(status_counts.get(status)) for status in TERMINAL_FAILED)
    failed_access = _int(status_counts.get("failed_access"))
    processing = sum(_int(status_counts.get(status)) for status in ACTIVE_PROCESSING)
    queued = _int(status_counts.get("queued"))
    current_processing = _mapping(db_status.get("current_processing_link"))
    current_article_url = _first_text(
        current_processing.get("canonical_url"),
        current_processing.get("source_url"),
    )
    current_article_status_detail = _first_text(current_processing.get("status_detail"))
    emails = _int(latest_run.get("emails_found")) or _int(db_status.get("message_total"))
    summaries = _int(db_status.get("summary_total"))
    latest_status = str(latest_run.get("status") or "")
    updated_at = str(
        latest_run.get("finished_at")
        or latest_run.get("started_at")
        or db_status.get("latest_attempt_at")
        or ""
    )
    label, status_class, detail, next_action = _portfolio_news_status_text(
        browser_ready=browser_ready,
        has_database=bool(db_status),
        latest_status=latest_status,
        link_total=link_total,
        analyzed=analyzed,
        relevant=relevant,
        failed=failed,
        failed_access=failed_access,
        processing=processing,
        queued=queued,
        summaries=summaries,
        current_article_url=current_article_url,
    )
    percent = 0 if link_total <= 0 else round((analyzed / link_total) * 100)
    return {
        "source_agent": "portfolio_news_agent",
        "state": latest_status or ("browser_ready" if browser_ready else "browser_not_ready"),
        "status_label": label,
        "status_class": status_class,
        "processed_email_count": emails,
        "article_links_found": link_total,
        "linked_content_attempted": max(0, link_total - queued),
        "linked_content_succeeded": analyzed,
        "linked_content_failed": failed,
        "linked_content_processing": processing,
        "linked_content_skipped": queued,
        "cache_hits": 0,
        "login_required": 0 if browser_ready else max(1, link_total) if link_total else 0,
        "unavailable": _int(status_counts.get("failed_access")),
        "summary_count": summaries,
        "relevant_article_count": relevant,
        "updated_at": updated_at or "not recorded",
        "detail": detail,
        "next_action": next_action,
        "current_action_label": _portfolio_news_current_action_label(
            processing=processing,
            current_article_url=current_article_url,
        ),
        "current_article_url": current_article_url,
        "current_article_status_detail": current_article_status_detail,
        "progress_label": _portfolio_news_progress_label(
            link_total,
            analyzed,
            queued,
            failed,
            processing,
        ),
        "progress_percent": max(0, min(100, percent)),
        "progress_style": f"width: {max(0, min(100, percent))}%",
        "refresh_action_url": "/scheduler/subscription-emails/login-refresh",
        "refresh_button_label": "Open SA browser and verify login",
        "continue_action_url": "/scheduler/subscription-emails/continue-after-login",
        "continue_button_label": "Analyze unread SA emails",
        "agent_root": str(config.root),
        "agent_database_path": "" if config.database_path is None else str(config.database_path),
        "browser_cdp_url": config.browser_cdp_url or "",
        "browser_ready": browser_ready,
    }


def _portfolio_news_status_text(
    *,
    browser_ready: bool,
    has_database: bool,
    latest_status: str,
    link_total: int,
    analyzed: int,
    relevant: int,
    failed: int,
    failed_access: int,
    processing: int,
    queued: int,
    summaries: int,
    current_article_url: str,
) -> tuple[str, str, str, str]:
    if not browser_ready:
        if has_database and link_total and failed_access:
            return (
                "SA article access needs login or challenge",
                "warn",
                (
                    f"Portfolio News Agent found {link_total} Seeking Alpha article link(s), "
                    f"but {failed_access} failed at article access. The dedicated browser "
                    "endpoint is not reachable now, or Seeking Alpha asked for a fresh login/challenge."
                ),
                (
                    "Open SA browser and verify login, complete any Seeking Alpha challenge, "
                    "then run Analyze unread SA emails again."
                ),
            )
        if has_database and link_total:
            return (
                "SA browser closed after email run",
                "warn",
                (
                    f"Portfolio News Agent has run data for {link_total} article link(s), "
                    "but the dedicated browser endpoint is not reachable right now."
                ),
                "Open SA browser and verify login before running article analysis again.",
            )
        return (
            "SA browser login session not connected",
            "warn",
            (
                "Portfolio News Agent is configured, but the dedicated Chrome/Edge "
                "session is not reachable through its local browser endpoint."
            ),
            "Click Open SA browser and verify login, then log in to Seeking Alpha there.",
        )
    if not has_database:
        return (
            "SA browser ready; no email run recorded",
            "warn",
            "The Portfolio News Agent browser is reachable, but its SQLite run DB has no rows yet.",
            "Click Analyze unread SA emails to scan Gmail, open article tabs, and run LLM analysis.",
        )
    if latest_status == "running":
        active_article = (
            f" Current article: {current_article_url}." if current_article_url else ""
        )
        return (
            "Portfolio News Agent running",
            "warn",
            (
                f"Email/article run is active. {analyzed}/{link_total} article link(s) "
                f"are analyzed and {processing} are opening/analyzing now.{active_article}"
            ),
            "Wait for the run to finish; this panel will update from the agent DB.",
        )
    if failed:
        return (
            "Portfolio News Agent needs attention",
            "warn",
            (
                f"Portfolio News Agent analyzed {analyzed}/{link_total} article link(s), "
                f"created {summaries} stock summary row(s), and recorded {failed} failure(s)."
            ),
            "Review failed link details in the agent DB, then rerun Analyze unread SA emails.",
        )
    if queued:
        return (
            "SA email links queued for analysis",
            "warn",
            f"{queued} Seeking Alpha article link(s) are queued; {analyzed} are already analyzed.",
            "Click Analyze unread SA emails to finish queued article analysis.",
        )
    if link_total:
        return (
            "SA email evidence analyzed",
            "pass",
            (
                f"Portfolio News Agent analyzed {analyzed}/{link_total} article link(s), "
                f"found {relevant} relevant article(s), and saved {summaries} LLM stock summary row(s)."
            ),
            "Use the Portfolio News Agent article summaries as subscription-email evidence.",
        )
    return (
        "SA browser ready; no unread article links found",
        "pass",
        "Portfolio News Agent is reachable, but the latest run did not find article links to analyze.",
        "Leave the browser open; run Analyze unread SA emails when new Seeking Alpha mail arrives.",
    )


def _portfolio_news_progress_label(
    link_total: int,
    analyzed: int,
    queued: int,
    failed: int,
    processing: int = 0,
) -> str:
    if link_total <= 0:
        return "No SA article links recorded"
    suffix = []
    if processing:
        suffix.append(f"{processing} opening/analyzing")
    if queued:
        suffix.append(f"{queued} queued")
    if failed:
        suffix.append(f"{failed} failed")
    extra = f" ({', '.join(suffix)})" if suffix else ""
    return f"{analyzed}/{link_total} SA article links analyzed{extra}"


def _portfolio_news_current_action_label(
    *,
    processing: int,
    current_article_url: str,
) -> str:
    if processing <= 0:
        return "No article is being opened right now."
    if current_article_url:
        return f"Opening/analyzing Seeking Alpha article: {current_article_url}"
    return f"{processing} Seeking Alpha article link(s) are opening/analyzing now."


def _not_configured_status(root: Path) -> dict[str, object]:
    return {
        "source_agent": "portfolio_news_agent",
        "state": "not_configured",
        "status_label": "Portfolio News Agent not connected",
        "status_class": "warn",
        "processed_email_count": 0,
        "article_links_found": 0,
        "linked_content_attempted": 0,
        "linked_content_succeeded": 0,
        "linked_content_failed": 0,
        "linked_content_processing": 0,
        "linked_content_skipped": 0,
        "cache_hits": 0,
        "login_required": 0,
        "unavailable": 0,
        "summary_count": 0,
        "updated_at": "not recorded",
        "detail": f"Expected Portfolio News Agent repo at {root}.",
        "next_action": "Set AGENCY_PORTFOLIO_NEWS_AGENT_ROOT or clone the email agent repo.",
        "current_action_label": "No article is being opened right now.",
        "current_article_url": "",
        "current_article_status_detail": "",
        "progress_label": "Portfolio News Agent DB not connected",
        "progress_percent": 0,
        "progress_style": "width: 0%",
        "refresh_action_url": "/scheduler/subscription-emails/login-refresh",
        "refresh_button_label": "Open SA browser and verify login",
        "continue_action_url": "",
        "continue_button_label": "",
        "agent_root": str(root),
        "agent_database_path": "",
        "browser_cdp_url": "",
        "browser_ready": False,
    }


def _read_database_status(database_path: Path | None) -> dict[str, object]:
    if database_path is None or not database_path.exists():
        return {}
    try:
        with sqlite3.connect(database_path) as connection:
            connection.row_factory = sqlite3.Row
            latest_run = _fetch_one(
                connection,
                """
                SELECT *
                FROM runs
                ORDER BY id DESC
                LIMIT 1
                """,
            )
            link_counts = _fetch_pairs(
                connection,
                """
                SELECT status, COUNT(*) AS count
                FROM gmail_article_links
                GROUP BY status
                """,
            )
            latest_attempt = _fetch_one(
                connection,
                """
                SELECT MAX(last_attempt_at) AS latest_attempt_at
                FROM gmail_article_links
                """,
            )
            current_processing = _fetch_one(
                connection,
                """
                SELECT source_url, canonical_url, status_detail, last_attempt_at
                FROM gmail_article_links
                WHERE status = 'processing'
                ORDER BY last_attempt_at DESC, id DESC
                LIMIT 1
                """,
            )
            return {
                "latest_run": latest_run,
                "link_status_counts": link_counts,
                "link_total": _fetch_scalar(connection, "SELECT COUNT(*) FROM gmail_article_links"),
                "message_total": _fetch_scalar(connection, "SELECT COUNT(*) FROM gmail_messages"),
                "summary_total": _fetch_scalar(connection, "SELECT COUNT(*) FROM article_asset_summaries"),
                "latest_attempt_at": (latest_attempt or {}).get("latest_attempt_at"),
                "current_processing_link": current_processing,
            }
    except sqlite3.Error as exc:
        return {
            "latest_run": {"status": "db_error", "error": str(exc)},
            "link_status_counts": {},
            "link_total": 0,
            "message_total": 0,
            "summary_total": 0,
            "latest_attempt_at": "",
            "current_processing_link": {},
        }


def _portfolio_news_event_rows(database_path: Path) -> list[dict[str, object]]:
    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT
              s.*,
              a.canonical_url,
              a.source_url AS article_source_url,
              a.headline,
              a.article_date,
              a.content_hash,
              l.source_url AS email_source_url,
              l.status AS link_status,
              gm.gmail_message_id AS raw_gmail_message_id,
              gm.sender,
              gm.subject,
              gm.received_at
            FROM article_asset_summaries s
            JOIN articles a ON a.id = s.article_id
            JOIN gmail_article_links l ON l.id = s.gmail_article_link_id
            JOIN gmail_messages gm ON gm.id = s.gmail_message_id
            ORDER BY s.created_at, s.symbol
            """
        ).fetchall()
    return [_event_row(dict(row)) for row in rows]


def _event_row(row: Mapping[str, object]) -> dict[str, object]:
    symbol = str(row.get("symbol") or "").upper()
    confidence = _float(row.get("confidence"), default=0.7)
    direction = _direction_from_sentiment(str(row.get("inferred_sentiment") or ""))
    created_at = _timestamp_text(
        _first_text(row.get("created_at"), row.get("article_date"), row.get("received_at"))
    )
    source_url = _first_text(row.get("canonical_url"), row.get("article_source_url"), row.get("email_source_url"))
    headline = _first_text(row.get("headline"), row.get("subject"), f"Seeking Alpha article for {symbol}")
    action_relevance = _first_text(row.get("action_relevance"), "portfolio_attention")
    theme = _first_text(row.get("theme"), "unclear")
    summary = _first_text(row.get("short_summary"), "Seeking Alpha article analyzed.")
    return {
        "ticker": symbol,
        "service": "seeking_alpha",
        "services": ["seeking_alpha"],
        "event_type": "portfolio_news_article_thesis",
        "event_types": ["portfolio_news_article_thesis"],
        "direction": direction,
        "title": f"Seeking Alpha Email: {symbol}: {headline}",
        "source_refs": [
            {
                "service": "seeking_alpha",
                "source_id": (
                    f"portfolio_news_agent:{row.get('gmail_article_link_id')}:{symbol}:"
                    f"{row.get('prompt_version')}"
                ),
                "source_url": source_url,
                "message_id_hash": str(
                    row.get("raw_gmail_message_id") or row.get("gmail_message_id") or ""
                ),
            }
        ],
        "source": "subscription-email",
        "source_tier": "PAID_SUB_EMAIL",
        "source_id": (
            f"portfolio_news_agent:{row.get('gmail_article_link_id')}:{symbol}:"
            f"{row.get('prompt_version')}"
        ),
        "source_url": source_url,
        "message_id_hash": str(row.get("raw_gmail_message_id") or row.get("gmail_message_id") or ""),
        "sender_domain": _sender_domain(str(row.get("sender") or "")),
        "received_at": _timestamp_text(_first_text(row.get("received_at"), created_at)),
        "linked_content_status": "article_analyzed",
        "linked_content_url": source_url,
        "linked_content_title_hash": _first_text(row.get("content_hash"), str(row.get("article_id") or "")),
        "linked_content_summary": f"Linked content thesis: {summary}",
        "linked_content_direction": direction,
        "linked_content_thesis": summary,
        "linked_content_catalysts": [action_relevance, theme],
        "linked_content_risk_flags": _risk_flags(direction, action_relevance),
        "linked_content_key_points": _key_points(row),
        "linked_content_tickers": [symbol],
        "linked_content_decision_use": (
            f"Use as Seeking Alpha portfolio article evidence for {symbol}; "
            f"action relevance: {action_relevance}."
        ),
        "linked_content_signal_strength": _signal_strength(confidence),
        "linked_content_context_chars": None,
        "linked_content_confidence": confidence,
        "timestamp_observed": created_at,
        "timestamp_as_of": created_at,
        "freshness": "FRESH",
        "confidence": confidence,
        "verification_level": "CONFIRMED",
    }


def _dedupe_event_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    deduped: dict[str, dict[str, object]] = {}
    for row in rows:
        normalized = dict(row)
        deduped[_event_dedupe_key(normalized)] = normalized
    return list(deduped.values())


def _event_dedupe_key(row: Mapping[str, object]) -> str:
    ticker = str(row.get("ticker") or "").strip().upper()
    source_url = _normalize_url_for_key(str(row.get("source_url") or ""))
    if ticker and source_url and source_url.startswith(("http://", "https://")):
        return f"url:{ticker}:{source_url}"
    return f"source:{row.get('source_id')}"


def _normalize_url_for_key(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return url
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), host, path, "", ""))


def _portfolio_news_export_summary(
    config: PortfolioNewsAgentConfig,
    rows: Sequence[Mapping[str, object]],
    *,
    affected_tickers: Sequence[str] = (),
    affected_event_rows: int = 0,
    active_universe_count: int = 0,
    ignored_out_of_universe_event_rows: int = 0,
    removed_existing_out_of_universe_event_rows: int = 0,
    universe_issues: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    return {
        "config_path": str(config.config_path),
        "mode": "portfolio_news_agent_db_bridge",
        "verdict": "ok" if rows else "no_article_summaries",
        "processed_emails": 0,
        "news_rows": 0,
        "activity_rows": 0,
        "event_rows": len(rows),
        "affected_event_rows": affected_event_rows,
        "affected_tickers": list(affected_tickers),
        "active_universe_count": active_universe_count,
        "ignored_out_of_universe_event_rows": ignored_out_of_universe_event_rows,
        "removed_existing_out_of_universe_event_rows": (
            removed_existing_out_of_universe_event_rows
        ),
        "universe_issues": [dict(issue) for issue in universe_issues],
        "linked_content": {
            "attempted": len(rows),
            "succeeded": len(rows),
            "failed": 0,
            "skipped": 0,
            "cache_hits": 0,
            "login_required": 0,
            "unavailable": 0,
        },
        "service_counts": {"seeking_alpha": len(rows)} if rows else {},
        "recent_evidence": [
            {
                "ticker": row.get("ticker"),
                "direction": row.get("direction"),
                "linked_content_status": row.get("linked_content_status"),
                "thesis": row.get("linked_content_thesis"),
                "decision_use": row.get("linked_content_decision_use"),
            }
            for row in rows[-10:]
        ],
        "fetched_at": _utc_now_dt().isoformat(),
        "source_agent": "portfolio_news_agent",
    }


def _write_subscription_email_manifest(
    *,
    manifest_path: Path,
    parquet_path: Path,
    fetched_at: datetime,
    issues: list[dict[str, object]],
) -> None:
    from subscription_email.storage import write_manifest

    write_manifest(manifest_path, parquet_path, fetched_at=fetched_at, issues=issues)


def _portfolio_news_manifest_issues(
    *,
    rows: Sequence[Mapping[str, object]],
    universe_issues: Sequence[Mapping[str, object]],
    ignored_out_of_universe: int,
    removed_existing_out_of_universe: int,
) -> list[dict[str, object]]:
    issues = [dict(issue) for issue in universe_issues]
    if ignored_out_of_universe:
        issues.append(
            {
                "severity": "info",
                "message": (
                    f"Ignored {ignored_out_of_universe} Portfolio News Agent summary row(s) "
                    "because their symbols are outside the agency active universe."
                ),
            }
        )
    if removed_existing_out_of_universe:
        issues.append(
            {
                "severity": "info",
                "message": (
                    f"Removed {removed_existing_out_of_universe} old subscription-email "
                    "evidence row(s) because their symbols are outside the agency active universe."
                ),
            }
        )
    if not rows:
        issues.append({"severity": "info", "message": "No article summaries exported."})
    return issues


def _remove_out_of_universe_subscription_email_rows(
    parquet_path: Path,
    active_tickers: set[str],
) -> int:
    if not parquet_path.exists():
        return 0
    try:
        frame = pd.read_parquet(parquet_path)
    except Exception:
        return 0
    if frame.empty or "ticker" not in frame.columns:
        return 0
    tickers = _string_column(frame, "ticker").str.upper()
    remove_mask = (tickers != "") & ~tickers.isin(active_tickers)
    removed = int(remove_mask.sum())
    if not removed:
        return 0
    frame.loc[~remove_mask].to_parquet(
        parquet_path,
        engine="pyarrow",
        compression="snappy",
        index=False,
    )
    return removed


def _string_column(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="string")
    return frame[column].fillna("").astype(str).str.strip()


def _agency_active_universe_tickers(
    repo_root: Path,
    *,
    as_of: date,
) -> tuple[set[str], list[dict[str, object]]]:
    rows, issues = _agency_active_universe_portfolio_rows(repo_root, as_of=as_of)
    tickers = {
        str(row.get("symbol") or "").strip().upper()
        for row in rows
        if str(row.get("symbol") or "").strip()
    }
    return tickers, issues


def _agency_active_universe_portfolio_rows(
    repo_root: Path,
    *,
    as_of: date,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    path = _universe_membership_path(repo_root)
    if not path.is_file():
        return [], [{"severity": "error", "message": f"Missing active-universe file: {path}"}]
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        return [], [{"severity": "error", "message": f"Could not read active-universe file: {exc}"}]
    if "ticker" not in frame.columns or "start_date" not in frame.columns:
        return [], [{"severity": "error", "message": "Active-universe file needs ticker and start_date columns."}]

    as_of_ts = pd.Timestamp(as_of, tz="UTC")
    start_dates = _series_timestamps(frame["start_date"])
    end_dates = _series_timestamps(frame["end_date"]) if "end_date" in frame.columns else None
    mask = start_dates.notna() & (start_dates <= as_of_ts)
    if end_dates is not None:
        mask &= end_dates.isna() | (end_dates > as_of_ts)
    if "timestamp_as_of" in frame.columns:
        knowledge_dates = _series_timestamps(frame["timestamp_as_of"])
        mask &= knowledge_dates.isna() | (knowledge_dates <= as_of_ts)

    active = frame.loc[mask].copy()
    if active.empty:
        return [], [{"severity": "error", "message": f"No active-universe tickers matched {as_of.isoformat()}."}]

    active["__symbol"] = active["ticker"].map(lambda value: str(value).strip().upper())
    active = active[active["__symbol"] != ""]
    output: list[dict[str, object]] = []
    for symbol, group in active.groupby("__symbol", sort=True):
        memberships = _joined_text(group.get("index_name", []))
        output.append(
            {
                "symbol": symbol,
                "name": symbol,
                "asset_type": "equity",
                "sector": "",
                "industry": memberships,
                "priority": 1,
            }
        )
    issues: list[dict[str, object]] = []
    if not output:
        issues.append({"severity": "error", "message": "Active-universe file had no valid ticker symbols."})
    return output, issues


def _write_universe_portfolio_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    fieldnames = ("symbol", "name", "asset_type", "sector", "industry", "priority")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _series_timestamps(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True)


def _joined_text(values: object) -> str:
    try:
        iterator = iter(values)  # type: ignore[arg-type]
    except TypeError:
        return ""
    items = sorted(
        {
            str(value).strip()
            for value in iterator
            if str(value).strip() and str(value).lower() != "nan"
        }
    )
    return "; ".join(items)


def _universe_membership_path(repo_root: Path) -> Path:
    return repo_root / "research" / "data" / "parquet" / "universe_membership.parquet"


def _existing_source_ids(parquet_path: Path) -> set[str]:
    if not parquet_path.exists():
        return set()
    try:
        frame = pd.read_parquet(parquet_path, columns=["source_id"])
    except Exception:
        return set()
    if "source_id" not in frame.columns:
        return set()
    return {
        str(value)
        for value in frame["source_id"].dropna().tolist()
        if str(value).strip()
    }


def _ticker_list(rows: Sequence[Mapping[str, object]]) -> list[str]:
    return sorted(
        {
            str(row.get("ticker") or "").strip().upper()
            for row in rows
            if str(row.get("ticker") or "").strip()
        }
    )


def _read_json_object(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _with_mini_cycle_status(
    status: Mapping[str, object],
    mini_status: Mapping[str, object],
) -> dict[str, object]:
    output = dict(status)
    ticker_statuses = _mapping_list(mini_status.get("ticker_statuses"))
    affected_tickers = _string_list(mini_status.get("affected_tickers"))
    state = str(mini_status.get("state") or "").strip()
    status_label = _first_text(mini_status.get("status_label"))
    affected_label = _affected_tickers_label(affected_tickers)
    output.setdefault("affected_tickers", [])
    output.setdefault("affected_tickers_label", "Affected tickers: none")
    output.setdefault("mini_cycle_state", "")
    output.setdefault("mini_cycle_status_label", "")
    output.setdefault("mini_cycle_ticker_rows", [])
    if not mini_status:
        return output
    output["affected_tickers"] = affected_tickers
    output["affected_tickers_label"] = affected_label
    output["mini_cycle_state"] = state
    output["mini_cycle_status_label"] = status_label
    output["mini_cycle_updated_at"] = _first_text(mini_status.get("updated_at"))
    output["mini_cycle_detail"] = _first_text(mini_status.get("detail"))
    output["mini_cycle_ticker_rows"] = ticker_statuses
    if (affected_tickers or ticker_statuses) and _int(output.get("linked_content_processing")) <= 0:
        output["current_action_label"] = _mini_cycle_current_action(
            state=state,
            status_label=status_label,
            affected_label=affected_label,
            ticker_statuses=ticker_statuses,
        )
    return output


def _affected_tickers_label(tickers: Sequence[str]) -> str:
    if not tickers:
        return "Affected tickers: none"
    shown = ", ".join(tickers[:8])
    extra = len(tickers) - 8
    if extra > 0:
        shown = f"{shown}, +{extra} more"
    return f"Affected tickers: {shown}"


def _mini_cycle_current_action(
    *,
    state: str,
    status_label: str,
    affected_label: str,
    ticker_statuses: Sequence[Mapping[str, object]],
) -> str:
    running = [
        str(row.get("ticker") or "")
        for row in ticker_statuses
        if str(row.get("state") or "") == "running" and str(row.get("ticker") or "")
    ]
    if running:
        return f"Mini analysis running for {', '.join(running)}. {affected_label}."
    if status_label:
        return f"{status_label}. {affected_label}."
    if state:
        return f"{state.replace('_', ' ').title()}. {affected_label}."
    return affected_label


def _read_simple_yaml(path: Path) -> dict[str, object]:
    payload: dict[str, object] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line or raw_line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = _strip_quotes(value.strip())
    return payload


def _with_agency_runtime_overrides(source_text: str, *, portfolio_file: str | None = None) -> str:
    lines = source_text.splitlines()
    output: list[str] = []
    replaced_portfolio_file = False
    replaced_telegram = False
    for line in lines:
        key = _top_level_key(line)
        if key == "portfolio_file" and portfolio_file:
            output.append(f'portfolio_file: "{_yaml_scalar(portfolio_file)}"')
            replaced_portfolio_file = True
        elif key == "telegram_enabled":
            output.append("telegram_enabled: false")
            replaced_telegram = True
        else:
            output.append(line)
    if portfolio_file and not replaced_portfolio_file:
        if output and output[-1].strip():
            output.append("")
        output.append(f'portfolio_file: "{_yaml_scalar(portfolio_file)}"')
    if not replaced_telegram:
        if output and output[-1].strip():
            output.append("")
        output.append("telegram_enabled: false")
    return "\n".join(output).rstrip() + "\n"


def _top_level_key(line: str) -> str | None:
    if not line or line[0].isspace() or ":" not in line:
        return None
    key = line.split(":", 1)[0].strip()
    if not key or key.startswith("#"):
        return None
    return key


def _resolve_agent_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _agent_config_path_text(root: Path, path: Path) -> str:
    try:
        text = str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        text = str(path)
    return text.replace("\\", "/")


def _optional_path(root: Path, value: object) -> Path | None:
    text = _optional_text(value)
    if not text:
        return None
    return _resolve_agent_path(root, text)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _yaml_scalar(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _is_cdp_endpoint_available(cdp_url: str) -> bool:
    try:
        with urlopen(f"{cdp_url.rstrip('/')}/json/version", timeout=1) as response:
            return 200 <= response.status < 400
    except Exception:
        return False


def _fetch_one(connection: sqlite3.Connection, query: str) -> dict[str, object]:
    row = connection.execute(query).fetchone()
    return {} if row is None else dict(row)


def _fetch_pairs(connection: sqlite3.Connection, query: str) -> dict[str, int]:
    return {
        str(row["status"]): int(row["count"])
        for row in connection.execute(query).fetchall()
    }


def _fetch_scalar(connection: sqlite3.Connection, query: str) -> int:
    row = connection.execute(query).fetchone()
    return 0 if row is None else int(row[0] or 0)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        text
        for text in (str(item).strip().upper() for item in value)
        if text
    ]


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: object, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _timestamp_text(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.isoformat(timespec="seconds")


def _direction_from_sentiment(sentiment: str) -> str:
    value = sentiment.strip().lower()
    if "bearish" in value:
        return "BEARISH"
    if "bullish" in value:
        return "BULLISH"
    if value == "mixed":
        return "MIXED"
    return "NEUTRAL"


def _sender_domain(sender: str) -> str:
    if "@" in sender:
        return sender.rsplit("@", 1)[1].strip().lower()
    return "seekingalpha.com"


def _risk_flags(direction: str, action_relevance: str) -> list[str]:
    flags: list[str] = []
    if direction == "BEARISH":
        flags.append("bearish_article_thesis")
    if action_relevance in {"risk_warning", "valuation", "thesis_change"}:
        flags.append(action_relevance)
    return flags


def _key_points(row: Mapping[str, object]) -> list[str]:
    output = [
        f"Sentiment: {_first_text(row.get('inferred_sentiment'), 'unclear')}",
        f"Relevance: {_first_text(row.get('action_relevance'), 'portfolio_attention')}",
    ]
    theme = _first_text(row.get("theme"))
    if theme:
        output.append(f"Theme: {theme}")
    for item in _json_string_items(row.get("forward_data_json")):
        output.append(item)
    for item in _json_string_items(row.get("price_targets_json")):
        output.append(f"Price target: {item}")
    return output


def _json_string_items(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _signal_strength(confidence: float) -> str:
    if confidence >= 0.75:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"


def _utc_now_dt() -> datetime:
    return datetime.now(UTC)
