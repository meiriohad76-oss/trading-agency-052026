from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from dotenv import load_dotenv

from agency.runtime.live_config_readiness import load_live_config_readiness

PASS = "PASS"
WARN = "WARN"
BLOCK = "BLOCK"
PLANNED = "PLANNED"


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    label: str
    category: str
    purpose: str
    keys: tuple[str, ...]
    mode: str = "all"


PROVIDERS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "alpaca",
        "Alpaca",
        "market_data_broker",
        "Current stock bars plus paper broker account, positions, and order submission.",
        ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    ),
    ProviderSpec(
        "sec_edgar",
        "SEC EDGAR",
        "filings",
        "Company facts, Form 4 insider activity, and 13F institutional filings.",
        ("SEC_USER_AGENT",),
    ),
    ProviderSpec(
        "openai",
        "OpenAI",
        "llm_review",
        "Optional supervised review and explanation calls for bounded paper candidates.",
        ("OPENAI_API_KEY",),
    ),
    ProviderSpec(
        "local_llm_openwebui",
        "Raspberry Pi Local LLM",
        "local_reasoning",
        (
            "Optional Open WebUI model on the Raspberry Pi for shadow-mode summaries, "
            "contradiction checks, and off-hours evidence review."
        ),
        (
            "AGENCY_LOCAL_LLM_BASE_URL",
            "AGENCY_LOCAL_LLM_API_KEY",
            "AGENCY_LOCAL_LLM_MODEL",
        ),
    ),
    ProviderSpec(
        "openfigi",
        "OpenFIGI",
        "reference_data",
        "CUSIP, FIGI, ticker, and security identifier mapping.",
        ("OPENFIGI_API_KEY",),
    ),
    ProviderSpec(
        "benzinga",
        "Benzinga",
        "news_activity",
        "Provider news, calendars, ratings, block trades, and unusual options alerts.",
        ("BENZINGA_API_KEY",),
    ),
    ProviderSpec(
        "unusual_whales",
        "Unusual Whales",
        "activity_options",
        "Dark-pool, off-exchange, options-flow, and unusual-activity alerts.",
        ("UNUSUAL_WHALES_API_KEY",),
    ),
    ProviderSpec(
        "fred",
        "FRED",
        "macro",
        "Macro regime and rate-context time series.",
        ("FRED_API_KEY",),
    ),
    ProviderSpec(
        "polygon_massive",
        "Polygon or Massive",
        "market_flow",
        "Delayed stock trades for market-flow pressure, plus optional options history later.",
        ("POLYGON_API_KEY", "MASSIVE_API_KEY"),
        mode="any",
    ),
    ProviderSpec(
        "subscription_email_agents",
        "Subscription Email Agents",
        "subscription_research",
        "User-authorized Seeking Alpha, TradeVision, and Zacks mailbox exports.",
        (),
    ),
    ProviderSpec(
        "thetadata",
        "ThetaData",
        "options_history",
        "Deep historical options chains, Greeks, and research data.",
        ("THETADATA_USERNAME", "THETADATA_PASSWORD"),
    ),
    ProviderSpec(
        "finra",
        "FINRA OTC Transparency",
        "market_structure",
        "Delayed OTC and ATS market-structure context; no API key expected.",
        (),
    ),
)


def load_provider_readiness(
    live_config: Mapping[str, object] | None = None,
) -> dict[str, object]:
    load_dotenv()
    config = live_config if live_config is not None else load_live_config_readiness()
    rows = [_provider_row(spec, config) for spec in PROVIDERS]
    blocker_count = sum(1 for row in rows if row["status"] == BLOCK)
    warning_count = sum(1 for row in rows if row["status"] == WARN)
    state = _summary_state(blocker_count, warning_count)
    return {
        "schema_version": "0.1.0",
        "ready": blocker_count == 0,
        "state": state,
        "status_label": _summary_label(state),
        "status_class": _status_class(state),
        "provider_count": len(rows),
        "configured_count": sum(1 for row in rows if row["configured"] is True),
        "active_required_count": sum(1 for row in rows if row["required_now"] is True),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "providers": rows,
    }


def _provider_row(spec: ProviderSpec, live_config: Mapping[str, object]) -> dict[str, object]:
    required_now = _required_now(spec, live_config)
    key_rows = [_key_row(name, spec, live_config, required_now) for name in spec.keys]
    configured = _configured(spec, key_rows)
    partial = any(row["present"] for row in key_rows) and not configured
    status = _status(required_now=required_now, configured=configured, partial=partial)
    return {
        "id": spec.provider_id,
        "label": spec.label,
        "category": spec.category,
        "purpose": spec.purpose,
        "required_now": required_now,
        "configured": configured,
        "status": status,
        "status_class": _status_class(status),
        "detail": _detail(spec, status, configured),
        "key_label": _key_label(spec),
        "keys": key_rows,
    }


def _required_now(spec: ProviderSpec, live_config: Mapping[str, object]) -> bool:
    if spec.provider_id == "openai":
        return os.environ.get("AGENCY_ENABLE_LLM_REVIEW", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if spec.provider_id == "local_llm_openwebui":
        return _env_enabled("AGENCY_LOCAL_LLM_ENABLED")
    if spec.provider_id == "alpaca":
        return str(live_config.get("provider", "")).lower() == "alpaca" or _env_enabled(
            "AGENCY_ALPACA_BROKER_ENABLED",
            "AGENCY_BROKER_SUBMIT_ENABLED",
        )
    if spec.provider_id == "sec_edgar":
        return any(check.get("label") == "SEC User-Agent" for check in _checks(live_config))
    if spec.provider_id == "polygon_massive":
        return any(check.get("label") == "Massive market-flow" for check in _checks(live_config))
    if spec.provider_id == "subscription_email_agents":
        return any(check.get("label") == "Subscription emails" for check in _checks(live_config))
    return False


def _env_enabled(*names: str) -> bool:
    return any(
        os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
        for name in names
    )


def _key_row(
    name: str,
    spec: ProviderSpec,
    live_config: Mapping[str, object],
    required_now: bool,
) -> dict[str, object]:
    return {
        "name": name,
        "present": _key_present(name, spec, live_config),
        "required_now": required_now,
        "file": ".env" if name != "SEC_USER_AGENT" else ".env or live-refresh.local.json",
    }


def _key_present(
    name: str,
    spec: ProviderSpec,
    live_config: Mapping[str, object],
) -> bool:
    if os.environ.get(name, "").strip() != "":
        return True
    if spec.provider_id == "sec_edgar":
        return any(
            check.get("label") == "SEC User-Agent" and check.get("status") == PASS
            for check in _checks(live_config)
        )
    return False


def _configured(spec: ProviderSpec, key_rows: Sequence[Mapping[str, object]]) -> bool:
    if not key_rows:
        return True
    if spec.provider_id == "local_llm_openwebui" and _local_llm_provider() == "ollama":
        present_by_name = {str(row["name"]): row["present"] is True for row in key_rows}
        return bool(
            present_by_name.get("AGENCY_LOCAL_LLM_BASE_URL")
            and present_by_name.get("AGENCY_LOCAL_LLM_MODEL")
        )
    present = [row["present"] is True for row in key_rows]
    if spec.mode == "any":
        return any(present)
    return all(present)


def _status(*, required_now: bool, configured: bool, partial: bool) -> str:
    if configured:
        return PASS
    if required_now:
        return BLOCK
    if partial:
        return WARN
    return PLANNED


def _detail(spec: ProviderSpec, status: str, configured: bool) -> str:
    if not spec.keys:
        return "No local API key is expected for this provider."
    if configured:
        if spec.provider_id == "local_llm_openwebui":
            return (
                "Configured locally for shadow-mode advisory insights; "
                "it cannot change trade gates."
            )
        return "Configured locally; secret values are not exposed."
    if status == BLOCK:
        return f"Required now; add {_key_label(spec)} to local config."
    if status == WARN:
        return f"Partially configured; complete {_key_label(spec)} before enabling."
    return f"Planned provider; add {_key_label(spec)} when an account is available."


def _key_label(spec: ProviderSpec) -> str:
    if spec.provider_id == "local_llm_openwebui" and _local_llm_provider() == "ollama":
        return "AGENCY_LOCAL_LLM_BASE_URL, AGENCY_LOCAL_LLM_MODEL"
    separator = " or " if spec.mode == "any" else ", "
    return separator.join(spec.keys) if spec.keys else "No key required"


def _status_class(status: str) -> str:
    if status in {PASS, "ready"}:
        return "pass"
    if status in {WARN, "attention"}:
        return "warn"
    if status in {BLOCK, "blocked"}:
        return "block"
    return "neutral"


def _summary_state(blocker_count: int, warning_count: int) -> str:
    if blocker_count > 0:
        return "blocked"
    if warning_count > 0:
        return "attention"
    return "ready"


def _summary_label(state: str) -> str:
    return {
        "ready": "Provider Keys Ready",
        "attention": "Provider Keys Need Attention",
        "blocked": "Missing Provider Keys",
    }.get(state, state.title())


def _checks(live_config: Mapping[str, object]) -> Sequence[Mapping[str, object]]:
    value = live_config.get("checks")
    if not isinstance(value, list):
        return ()
    return [item for item in value if isinstance(item, Mapping)]


def _local_llm_provider() -> str:
    return os.environ.get("AGENCY_LOCAL_LLM_PROVIDER", "openwebui").strip().lower()
