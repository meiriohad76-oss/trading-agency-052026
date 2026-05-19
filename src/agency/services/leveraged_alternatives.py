from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

CONFIG_PATH_ENV = "AGENCY_LEVERAGED_ALTERNATIVES_PATH"
PORTFOLIO_POLICY_PATH_ENV = "AGENCY_PORTFOLIO_POLICY_PATH"
DEFAULT_CONFIG_PATH = Path("research/config/leveraged-alternatives.local.json")
DEFAULT_PORTFOLIO_POLICY_PATH = Path("research/config/portfolio-policy.local.json")
LEVERAGED_ACTIONS = {"BUY", "WATCH"}
STALE_FRESHNESS = {"STALE", "UNAVAILABLE"}
CALL_OPTION = "CALL"


@dataclass(frozen=True)
class LeveragedAlternativePolicy:
    enabled: bool = False
    min_conviction: float = 0.85
    min_source_count: int = 2
    min_confirmed_signals: int = 2
    max_leveraged_position_pct: float = 2.0
    etf_review_enabled: bool = True
    min_etf_avg_dollar_volume: float = 0.0
    allow_defined_risk_options: bool = False
    allow_covered_option_writes: bool = False
    min_option_days_to_expiration: int = 14
    max_option_days_to_expiration: int = 60

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
    ) -> LeveragedAlternativePolicy:
        if env is None:
            load_dotenv()
        values = os.environ if env is None else env
        defaults = cls()
        policy = cls(
            enabled=_env_bool(
                values.get("AGENCY_LEVERAGED_ALTERNATIVES_ENABLED"),
                default=defaults.enabled,
            ),
            min_conviction=_env_float(
                values.get("AGENCY_LEVERAGED_MIN_CONVICTION"),
                default=defaults.min_conviction,
            ),
            max_leveraged_position_pct=_env_float(
                values.get("AGENCY_MAX_LEVERAGED_POSITION_PCT"),
                default=defaults.max_leveraged_position_pct,
            ),
            etf_review_enabled=_env_bool(
                values.get("AGENCY_LEVERAGED_ETF_REVIEW_ENABLED"),
                default=defaults.etf_review_enabled,
            ),
            min_etf_avg_dollar_volume=_env_float(
                values.get("AGENCY_MIN_LEVERAGED_ETF_AVG_DOLLAR_VOLUME"),
                default=defaults.min_etf_avg_dollar_volume,
            ),
            allow_defined_risk_options=_env_bool(
                values.get("AGENCY_ALLOW_DEFINED_RISK_OPTIONS"),
                default=defaults.allow_defined_risk_options,
            ),
            allow_covered_option_writes=_env_bool(
                values.get("AGENCY_ALLOW_COVERED_OPTION_WRITES"),
                default=defaults.allow_covered_option_writes,
            ),
            min_option_days_to_expiration=_env_int(
                values.get("AGENCY_MIN_OPTION_DAYS_TO_EXPIRATION"),
                default=defaults.min_option_days_to_expiration,
            ),
            max_option_days_to_expiration=_env_int(
                values.get("AGENCY_MAX_OPTION_DAYS_TO_EXPIRATION"),
                default=defaults.max_option_days_to_expiration,
            ),
        )
        return _policy_with_file_overrides(policy, values)


def build_leveraged_alternative_review(
    selection_report: Mapping[str, object] | None,
    *,
    risk_decision: Mapping[str, object] | None = None,
    policy: LeveragedAlternativePolicy | None = None,
    etf_catalog: Sequence[Mapping[str, object]] | None = None,
    option_chain: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    normalized_policy = policy or LeveragedAlternativePolicy.from_env()
    if selection_report is None:
        return _empty_review(normalized_policy, reason="No selection report is available.")

    ticker = _ticker(selection_report)
    conviction = _conviction(selection_report)
    checks = _trigger_checks(selection_report, risk_decision, normalized_policy)
    eligible = all(check["status"] == "PASS" for check in checks)
    alternatives = (
        _build_alternatives(
            selection_report,
            policy=normalized_policy,
            etf_catalog=etf_catalog,
            option_chain=option_chain,
        )
        if eligible
        else []
    )
    available_count = sum(1 for item in alternatives if item["eligible"] is True)
    status_label, status_class = _review_status(
        policy=normalized_policy,
        eligible=eligible,
        available_count=available_count,
    )
    return {
        "schema_version": "0.1.0",
        "ticker": ticker,
        "enabled": normalized_policy.enabled,
        "eligible": eligible,
        "triggered": conviction >= normalized_policy.min_conviction,
        "status_label": status_label,
        "status_class": status_class,
        "summary": _review_summary(
            ticker=ticker,
            policy=normalized_policy,
            eligible=eligible,
            available_count=available_count,
            checks=checks,
        ),
        "advisory_only": True,
        "baseline": {
            "action": _action(selection_report),
            "conviction_pct": round(conviction * 100),
            "source_count": _source_count(selection_report),
            "confirmed_signal_count": _confirmed_signal_count(selection_report),
            "risk_decision": _risk_state(risk_decision),
            "max_leveraged_position_pct": normalized_policy.max_leveraged_position_pct,
        },
        "trigger_checks": checks,
        "alternatives": alternatives,
        "alternative_count": len(alternatives),
        "available_alternative_count": available_count,
        "warnings": [
            "Advisory only: leveraged alternatives are never auto-submitted.",
            "Leveraged ETFs reset daily and can diverge from the stock over multi-day holds.",
            "Options alternatives are defined-risk only; naked option writing is blocked.",
        ],
    }


def evaluate_option_write_request(
    *,
    write_type: str,
    contracts: int,
    policy: LeveragedAlternativePolicy | None = None,
    covered_position_qty: float = 0.0,
    cash_available: float = 0.0,
    strike: float = 0.0,
) -> dict[str, object]:
    normalized_policy = policy or LeveragedAlternativePolicy.from_env()
    normalized_type = write_type.strip().lower()
    required_shares = max(contracts, 0) * 100
    if not normalized_policy.allow_covered_option_writes:
        return _write_decision("BLOCK", "covered option writes are disabled by policy")
    if normalized_type == "covered_call":
        if covered_position_qty >= required_shares:
            return _write_decision("PASS", "covered call is backed by existing shares")
        return _write_decision("BLOCK", "covered call would be naked")
    if normalized_type == "cash_secured_put":
        required_cash = required_shares * max(strike, 0.0)
        if cash_available >= required_cash:
            return _write_decision("PASS", "put write is cash secured")
        return _write_decision("BLOCK", "put write is not cash secured")
    return _write_decision("BLOCK", "naked option writing is not allowed")


def load_leveraged_etf_catalog(
    path: Path | str | None = None,
) -> list[dict[str, object]]:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    payload = _read_json_object(config_path)
    rows = payload.get("leveraged_etfs", []) if payload is not None else []
    if isinstance(rows, list):
        loaded = [dict(row) for row in rows if isinstance(row, Mapping)]
        if loaded:
            return loaded
    return [dict(row) for row in _default_etf_catalog()]


def _build_alternatives(
    selection_report: Mapping[str, object],
    *,
    policy: LeveragedAlternativePolicy,
    etf_catalog: Sequence[Mapping[str, object]] | None,
    option_chain: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    ticker = _ticker(selection_report)
    catalog = list(etf_catalog) if etf_catalog is not None else load_leveraged_etf_catalog()
    alternatives = _etf_alternatives(ticker, catalog, policy)
    if not alternatives:
        alternatives.append(_unavailable_alternative("leveraged_etf", "No curated ETF mapping."))
    if policy.allow_defined_risk_options:
        alternatives.extend(_option_alternatives(selection_report, option_chain, policy))
    return alternatives


def _etf_alternatives(
    ticker: str,
    catalog: Sequence[Mapping[str, object]],
    policy: LeveragedAlternativePolicy,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in catalog:
        if str(item.get("underlying", "")).upper() != ticker:
            continue
        direction = str(item.get("direction", "LONG")).upper()
        if direction != "LONG":
            continue
        enabled = _bool_value(item.get("enabled", True))
        avg_dollar_volume = _optional_float(item.get("avg_dollar_volume"))
        liquid_enough = (
            avg_dollar_volume is None
            or avg_dollar_volume >= policy.min_etf_avg_dollar_volume
        )
        eligible = policy.etf_review_enabled and enabled and liquid_enough
        blocker = None
        if not policy.etf_review_enabled:
            blocker = "ETF review is disabled by policy."
        elif not enabled:
            blocker = "This ETF row is disabled in the local catalog."
        elif not liquid_enough:
            blocker = "Average dollar volume is below the local liquidity floor."
        rows.append(
            {
                "type": "leveraged_etf",
                "label": f"{item.get('ticker', 'ETF')} leveraged ETF",
                "ticker": str(item.get("ticker", "")).upper(),
                "underlying": ticker,
                "eligible": eligible,
                "orderable": False,
                "status_label": "Review Only" if eligible else "Unavailable",
                "status_class": "warn" if eligible else "block",
                "leverage_factor": _optional_float(item.get("leverage_factor")),
                "issuer": str(item.get("issuer", "Unknown issuer")),
                "expense_ratio_pct": _optional_float(item.get("expense_ratio_pct")),
                "estimated_position_pct": (
                    policy.max_leveraged_position_pct if eligible else 0.0
                ),
                "max_loss": None,
                "breakeven": None,
                "rationale": _etf_rationale(item, policy),
                "blocker": blocker,
                "warnings": [
                    "Daily reset product; use only as supervised paper-review context.",
                    "Broker availability and current liquidity must be verified before use.",
                ],
            }
        )
    return rows


def _option_alternatives(
    selection_report: Mapping[str, object],
    option_chain: Sequence[Mapping[str, object]],
    policy: LeveragedAlternativePolicy,
) -> list[dict[str, object]]:
    if not option_chain:
        return [_unavailable_alternative("defined_risk_option", "No option chain is available.")]
    as_of = _as_of_date(selection_report)
    calls: list[Mapping[str, object]] = []
    for row in option_chain:
        days_to_expiration = _days_to_expiration(row, as_of)
        if (
            _option_type(row) == CALL_OPTION
            and days_to_expiration is not None
            and policy.min_option_days_to_expiration
            <= days_to_expiration
            <= policy.max_option_days_to_expiration
        ):
            calls.append(row)
    long_call = _best_long_call(calls)
    if long_call is None:
        return [_unavailable_alternative("defined_risk_option", "No suitable long call found.")]
    short_call = _best_short_call(calls, long_call)
    if short_call is None:
        return [_long_call_alternative(long_call)]
    debit = _option_ask(long_call) - _option_bid(short_call)
    width = _option_strike(short_call) - _option_strike(long_call)
    if debit <= 0.0 or width <= 0.0:
        return [_long_call_alternative(long_call)]
    return [
        {
            "type": "defined_risk_call_spread",
            "label": "Defined-risk call debit spread",
            "ticker": _option_symbol(long_call),
            "underlying": _ticker(selection_report),
            "eligible": True,
            "orderable": False,
            "status_label": "Review Only",
            "status_class": "warn",
            "leverage_factor": None,
            "issuer": "option chain",
            "expense_ratio_pct": None,
            "estimated_position_pct": 0.0,
            "max_loss": round(debit * 100.0, 2),
            "breakeven": round(_option_strike(long_call) + debit, 2),
            "rationale": (
                f"Long {_option_strike(long_call):.2f} call and short "
                f"{_option_strike(short_call):.2f} call cap max loss at the debit paid."
            ),
            "blocker": None,
            "warnings": [
                "Defined-risk option review only; no options order is generated.",
                "Requires live chain liquidity, spread, and broker support checks.",
            ],
        }
    ]


def _long_call_alternative(row: Mapping[str, object]) -> dict[str, object]:
    premium = _option_ask(row)
    return {
        "type": "defined_risk_long_call",
        "label": "Defined-risk long call",
        "ticker": _option_symbol(row),
        "underlying": str(row.get("underlying", "")),
        "eligible": True,
        "orderable": False,
        "status_label": "Review Only",
        "status_class": "warn",
        "leverage_factor": None,
        "issuer": "option chain",
        "expense_ratio_pct": None,
        "estimated_position_pct": 0.0,
        "max_loss": round(premium * 100.0, 2),
        "breakeven": round(_option_strike(row) + premium, 2),
        "rationale": "Long call has bounded max loss equal to premium paid.",
        "blocker": None,
        "warnings": [
            "Defined-risk option review only; no options order is generated.",
            "Requires live chain liquidity, spread, and broker support checks.",
        ],
    }


def _trigger_checks(
    selection_report: Mapping[str, object],
    risk_decision: Mapping[str, object] | None,
    policy: LeveragedAlternativePolicy,
) -> list[dict[str, str]]:
    return [
        _check(
            "feature_enabled",
            "PASS" if policy.enabled else "BLOCK",
            "leveraged alternative review is enabled"
            if policy.enabled
            else "leveraged alternative review is disabled by policy",
        ),
        _action_check(selection_report),
        _conviction_check(selection_report, policy),
        _source_count_check(selection_report, policy),
        _confirmed_signal_check(selection_report, policy),
        _freshness_check(selection_report),
        _hard_blocker_check(selection_report, risk_decision),
    ]


def _action_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    action = _action(selection_report)
    if action in LEVERAGED_ACTIONS:
        return _check("final_action", "PASS", f"{action} can be reviewed for leverage.")
    return _check("final_action", "BLOCK", f"{action} is not a long leverage candidate.")


def _conviction_check(
    selection_report: Mapping[str, object],
    policy: LeveragedAlternativePolicy,
) -> dict[str, str]:
    conviction = _conviction(selection_report)
    if conviction >= policy.min_conviction:
        return _check("conviction", "PASS", "conviction meets leveraged review threshold.")
    return _check("conviction", "BLOCK", "conviction is below leveraged review threshold.")


def _source_count_check(
    selection_report: Mapping[str, object],
    policy: LeveragedAlternativePolicy,
) -> dict[str, str]:
    count = _source_count(selection_report)
    if count >= policy.min_source_count:
        return _check("source_breadth", "PASS", "independent source breadth is sufficient.")
    return _check("source_breadth", "BLOCK", "not enough independent source breadth.")


def _confirmed_signal_check(
    selection_report: Mapping[str, object],
    policy: LeveragedAlternativePolicy,
) -> dict[str, str]:
    count = _confirmed_signal_count(selection_report)
    if count >= policy.min_confirmed_signals:
        return _check("confirmed_signals", "PASS", "confirmed signal count is sufficient.")
    return _check("confirmed_signals", "BLOCK", "not enough confirmed signals.")


def _freshness_check(selection_report: Mapping[str, object]) -> dict[str, str]:
    freshness = _freshness(selection_report)
    if freshness in STALE_FRESHNESS:
        return _check("freshness", "BLOCK", f"critical evidence freshness is {freshness}.")
    return _check("freshness", "PASS", f"critical evidence freshness is {freshness}.")


def _hard_blocker_check(
    selection_report: Mapping[str, object],
    risk_decision: Mapping[str, object] | None,
) -> dict[str, str]:
    if _risk_state(risk_decision) == "BLOCK":
        return _check("hard_blockers", "BLOCK", "risk decision blocks this candidate.")
    statuses = [
        str(item.get("status", ""))
        for item in _mapping_list(selection_report.get("policy_gates", []))
    ]
    if "BLOCK" in statuses:
        return _check("hard_blockers", "BLOCK", "selection policy gate blocks this candidate.")
    return _check("hard_blockers", "PASS", "no hard blocker is present.")


def _review_status(
    *,
    policy: LeveragedAlternativePolicy,
    eligible: bool,
    available_count: int,
) -> tuple[str, str]:
    if not policy.enabled:
        return ("Disabled", "neutral")
    if not eligible:
        return ("Unavailable", "block")
    if available_count == 0:
        return ("No Match", "warn")
    return ("Advisory Available", "warn")


def _review_summary(
    *,
    ticker: str,
    policy: LeveragedAlternativePolicy,
    eligible: bool,
    available_count: int,
    checks: Sequence[Mapping[str, str]],
) -> str:
    if not policy.enabled:
        return "Leveraged alternative review is disabled until local policy enables it."
    if not eligible:
        blocker = next(
            (check["reason"] for check in checks if check["status"] == "BLOCK"),
            "trigger conditions were not met",
        )
        return f"{ticker} is not eligible for leveraged alternatives: {blocker}"
    if available_count == 0:
        return f"{ticker} meets the trigger, but no eligible alternative is available."
    return (
        f"{ticker} meets the high-conviction trigger. {available_count} advisory "
        "alternative(s) are available for supervised paper review only."
    )


def _empty_review(policy: LeveragedAlternativePolicy, *, reason: str) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "ticker": "UNKNOWN",
        "enabled": policy.enabled,
        "eligible": False,
        "triggered": False,
        "status_label": "Unavailable",
        "status_class": "neutral",
        "summary": reason,
        "advisory_only": True,
        "baseline": {
            "action": "NONE",
            "conviction_pct": 0,
            "source_count": 0,
            "confirmed_signal_count": 0,
            "risk_decision": "UNKNOWN",
            "max_leveraged_position_pct": policy.max_leveraged_position_pct,
        },
        "trigger_checks": [],
        "alternatives": [],
        "alternative_count": 0,
        "available_alternative_count": 0,
        "warnings": [],
    }


def _unavailable_alternative(kind: str, reason: str) -> dict[str, object]:
    return {
        "type": kind,
        "label": "Unavailable",
        "ticker": "n/a",
        "underlying": "n/a",
        "eligible": False,
        "orderable": False,
        "status_label": "Unavailable",
        "status_class": "block",
        "leverage_factor": None,
        "issuer": "n/a",
        "expense_ratio_pct": None,
        "estimated_position_pct": 0.0,
        "max_loss": None,
        "breakeven": None,
        "rationale": reason,
        "blocker": reason,
        "warnings": [],
    }


def _default_etf_catalog() -> list[dict[str, object]]:
    return [
        _etf("AAPL", "AAPU", 2.0, "Direxion"),
        _etf("AMZN", "AMZU", 2.0, "Direxion"),
        _etf("GOOGL", "GGLL", 2.0, "Direxion"),
        _etf("META", "METU", 2.0, "Direxion"),
        _etf("MSFT", "MSFU", 2.0, "Direxion"),
        _etf("NVDA", "NVDU", 2.0, "Direxion"),
        _etf("NVDA", "NVDL", 2.0, "GraniteShares"),
        _etf("TSLA", "TSLL", 2.0, "Direxion"),
    ]


def _etf(underlying: str, ticker: str, leverage: float, issuer: str) -> dict[str, object]:
    return {
        "underlying": underlying,
        "ticker": ticker,
        "direction": "LONG",
        "leverage_factor": leverage,
        "issuer": issuer,
        "expense_ratio_pct": None,
        "enabled": True,
        "avg_dollar_volume": None,
    }


def _etf_rationale(
    item: Mapping[str, object],
    policy: LeveragedAlternativePolicy,
) -> str:
    leverage = _optional_float(item.get("leverage_factor"))
    leverage_label = "leveraged" if leverage is None else f"{leverage:.1f}x"
    return (
        f"{item.get('ticker', 'ETF')} is a {leverage_label} daily-reset long ETF "
        f"mapped to {item.get('underlying', 'the stock')}. Advisory cap is "
        f"{policy.max_leveraged_position_pct:.1f}% of portfolio."
    )


def _best_long_call(calls: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    liquid = [row for row in calls if _option_ask(row) > 0.0 and _option_delta(row) > 0.0]
    if not liquid:
        return None
    return min(liquid, key=lambda row: abs(_option_delta(row) - 0.55))


def _best_short_call(
    calls: Sequence[Mapping[str, object]],
    long_call: Mapping[str, object],
) -> Mapping[str, object] | None:
    long_expiration = str(long_call.get("expiration", ""))
    long_strike = _option_strike(long_call)
    candidates = [
        row
        for row in calls
        if str(row.get("expiration", "")) == long_expiration
        and _option_strike(row) > long_strike
        and _option_bid(row) > 0.0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda row: abs(_option_delta(row) - 0.30))


def _write_decision(status: str, reason: str) -> dict[str, object]:
    return {
        "status": status,
        "allowed": status == "PASS",
        "reason": reason,
    }


def _check(name: str, status: str, reason: str) -> dict[str, str]:
    return {"name": name, "status": status, "reason": reason}


def _policy_with_file_overrides(
    policy: LeveragedAlternativePolicy,
    env: Mapping[str, str],
) -> LeveragedAlternativePolicy:
    output = policy
    for path in _policy_paths(env):
        payload = _read_json_object(path)
        if payload is not None:
            output = _policy_from_payload(output, payload)
    return output


def _policy_paths(env: Mapping[str, str]) -> list[Path]:
    paths = [
        Path(env.get(PORTFOLIO_POLICY_PATH_ENV, DEFAULT_PORTFOLIO_POLICY_PATH.as_posix())),
        Path(env.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH.as_posix())),
    ]
    deduped: list[Path] = []
    for path in paths:
        if path not in deduped:
            deduped.append(path)
    return deduped


def _policy_from_payload(
    policy: LeveragedAlternativePolicy,
    payload: Mapping[str, object],
) -> LeveragedAlternativePolicy:
    return LeveragedAlternativePolicy(
        enabled=_payload_bool(payload, "leveraged_alternatives_enabled", default=policy.enabled),
        min_conviction=_payload_float(
            payload,
            "leveraged_min_conviction",
            default=policy.min_conviction,
        ),
        min_source_count=_payload_int(
            payload,
            "leveraged_min_source_count",
            default=policy.min_source_count,
        ),
        min_confirmed_signals=_payload_int(
            payload,
            "leveraged_min_confirmed_signals",
            default=policy.min_confirmed_signals,
        ),
        max_leveraged_position_pct=_payload_float(
            payload,
            "max_leveraged_position_pct",
            default=policy.max_leveraged_position_pct,
        ),
        etf_review_enabled=_payload_bool(
            payload,
            "leveraged_etf_review_enabled",
            default=policy.etf_review_enabled,
        ),
        min_etf_avg_dollar_volume=_payload_float(
            payload,
            "min_leveraged_etf_avg_dollar_volume",
            default=policy.min_etf_avg_dollar_volume,
        ),
        allow_defined_risk_options=_payload_bool(
            payload,
            "allow_defined_risk_options",
            default=policy.allow_defined_risk_options,
        ),
        allow_covered_option_writes=_payload_bool(
            payload,
            "allow_covered_option_writes",
            default=policy.allow_covered_option_writes,
        ),
        min_option_days_to_expiration=_payload_int(
            payload,
            "min_option_days_to_expiration",
            default=policy.min_option_days_to_expiration,
        ),
        max_option_days_to_expiration=_payload_int(
            payload,
            "max_option_days_to_expiration",
            default=policy.max_option_days_to_expiration,
        ),
    )


def _read_json_object(path: Path) -> Mapping[str, object] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _ticker(report: Mapping[str, object]) -> str:
    return str(report.get("ticker", "UNKNOWN")).upper()


def _action(report: Mapping[str, object]) -> str:
    return str(report.get("final_action", report.get("action", "NO_TRADE"))).upper()


def _conviction(report: Mapping[str, object]) -> float:
    value = report.get("final_conviction")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    value = report.get("conviction_pct")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value) / 100.0))
    return 0.0


def _source_count(report: Mapping[str, object]) -> int:
    value = report.get("source_count")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    quality = _data_quality(report)
    value = quality.get("source_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _confirmed_signal_count(report: Mapping[str, object]) -> int:
    value = report.get("confirmed_signal_count")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    quality = _data_quality(report)
    value = quality.get("confirmed_signal_count")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _freshness(report: Mapping[str, object]) -> str:
    value = report.get("freshness")
    if isinstance(value, str):
        return value.upper()
    quality = _data_quality(report)
    value = quality.get("freshness")
    return str(value).upper() if isinstance(value, str) else "UNKNOWN"


def _data_quality(report: Mapping[str, object]) -> Mapping[str, object]:
    evidence = report.get("evidence_pack")
    if not isinstance(evidence, Mapping):
        return {}
    quality = evidence.get("data_quality")
    return quality if isinstance(quality, Mapping) else {}


def _risk_state(risk_decision: Mapping[str, object] | None) -> str:
    if risk_decision is None:
        return "UNKNOWN"
    return str(risk_decision.get("decision", "UNKNOWN")).upper()


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _as_of_date(report: Mapping[str, object]) -> date:
    value = str(report.get("as_of", date.today().isoformat()))[:10]
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.today()


def _days_to_expiration(row: Mapping[str, object], as_of: date) -> int | None:
    expiration = row.get("expiration")
    if not isinstance(expiration, str):
        return None
    try:
        return (date.fromisoformat(expiration[:10]) - as_of).days
    except ValueError:
        return None


def _option_type(row: Mapping[str, object]) -> str:
    return str(row.get("option_type", row.get("type", ""))).upper()


def _option_symbol(row: Mapping[str, object]) -> str:
    return str(row.get("symbol", row.get("ticker", "OPTION"))).upper()


def _option_strike(row: Mapping[str, object]) -> float:
    return _float_value(row.get("strike"))


def _option_delta(row: Mapping[str, object]) -> float:
    return _float_value(row.get("delta"))


def _option_bid(row: Mapping[str, object]) -> float:
    return _float_value(row.get("bid", row.get("mid", 0.0)))


def _option_ask(row: Mapping[str, object]) -> float:
    return _float_value(row.get("ask", row.get("mid", 0.0)))


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    parsed = _float_value(value)
    return parsed if parsed > 0.0 else None


def _float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return float(value)


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _env_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _payload_bool(payload: Mapping[str, object], key: str, *, default: bool) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else default


def _payload_float(payload: Mapping[str, object], key: str, *, default: float) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    return float(value)


def _payload_int(payload: Mapping[str, object], key: str, *, default: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
