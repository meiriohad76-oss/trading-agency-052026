from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlsplit, urlunsplit

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_ROOT = REPO_ROOT / "research" / "results" / "latest-live-runtime-cycle"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "research" / "results" / "latest-local-llm-insights"
DEFAULT_LOCAL_LLM_MODEL = "local-default"
LOCAL_LLM_ENABLED_ENV = "AGENCY_LOCAL_LLM_ENABLED"
LOCAL_LLM_BASE_URL_ENV = "AGENCY_LOCAL_LLM_BASE_URL"
LOCAL_LLM_API_KEY_ENV = "AGENCY_LOCAL_LLM_API_KEY"
LOCAL_LLM_MODEL_ENV = "AGENCY_LOCAL_LLM_MODEL"
LOCAL_LLM_MODE_ENV = "AGENCY_LOCAL_LLM_MODE"
LOCAL_LLM_PROVIDER_ENV = "AGENCY_LOCAL_LLM_PROVIDER"
LOCAL_LLM_TIMEOUT_ENV = "AGENCY_LOCAL_LLM_TIMEOUT_SECONDS"
MAX_PROMPT_SIGNAL_ROWS = 8
MAX_TEXT_CHARS = 700


class LocalLlmProvider(Protocol):
    async def complete_json(self, messages: list[dict[str, str]]) -> dict[str, object]: ...


@dataclass(frozen=True)
class LocalLlmConfig:
    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    model: str = DEFAULT_LOCAL_LLM_MODEL
    mode: str = "shadow"
    provider: str = "openwebui"
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> LocalLlmConfig:
        return cls(
            enabled=_env_flag(LOCAL_LLM_ENABLED_ENV),
            base_url=os.environ.get(LOCAL_LLM_BASE_URL_ENV, "").strip(),
            api_key=os.environ.get(LOCAL_LLM_API_KEY_ENV, "").strip(),
            model=os.environ.get(LOCAL_LLM_MODEL_ENV, DEFAULT_LOCAL_LLM_MODEL).strip()
            or DEFAULT_LOCAL_LLM_MODEL,
            mode=os.environ.get(LOCAL_LLM_MODE_ENV, "shadow").strip().lower() or "shadow",
            provider=os.environ.get(LOCAL_LLM_PROVIDER_ENV, "openwebui").strip().lower()
            or "openwebui",
            timeout_seconds=_float_env(LOCAL_LLM_TIMEOUT_ENV, default=60.0),
        )

    @property
    def configured(self) -> bool:
        if self.provider == "ollama":
            return bool(self.base_url and self.model)
        return bool(self.base_url and self.api_key and self.model)

    @property
    def chat_completions_url(self) -> str:
        if self.provider == "ollama":
            return _provider_url(self.base_url, "api/chat")
        return _openwebui_url(self.base_url, "chat/completions")

    @property
    def models_url(self) -> str:
        if self.provider == "ollama":
            return _provider_url(self.base_url, "api/tags")
        return _openwebui_url(self.base_url, "models")


class OpenWebUIClient:
    def __init__(
        self,
        config: LocalLlmConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport

    async def complete_json(self, messages: list[dict[str, str]]) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                self.config.chat_completions_url,
                headers=self._headers(),
                json=self._chat_payload(messages),
            )
            response.raise_for_status()
            return _completion_json_payload(response.json(), provider=self.config.provider)

    async def health(self) -> dict[str, object]:
        async with httpx.AsyncClient(
            timeout=self.config.timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.get(
                self.config.models_url,
                headers=self._headers(include_content_type=False),
            )
            response.raise_for_status()
            payload = response.json()
        return {
            "provider": self.config.provider,
            "configured": self.config.configured,
            "reachable": True,
            "status": "ready",
            "status_label": "Local LLM reachable",
            "model": self.config.model,
            "models_url": self.config.models_url,
            "model_count": len(payload) if isinstance(payload, list) else len(payload.get("data", []))
            if isinstance(payload, Mapping)
            else 0,
        }

    def _headers(self, *, include_content_type: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.config.provider != "ollama" and self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        if include_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _chat_payload(self, messages: list[dict[str, str]]) -> dict[str, object]:
        if self.config.provider == "ollama":
            return {
                "model": self.config.model,
                "messages": messages,
                "stream": False,
                "format": "json",
            }
        return {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.1,
            "stream": False,
        }


async def check_local_llm_health(
    *,
    config: LocalLlmConfig | None = None,
    client: OpenWebUIClient | None = None,
) -> dict[str, object]:
    config = config or LocalLlmConfig.from_env()
    if not config.enabled:
        return {
            "schema_version": "0.1.0",
            "status": "disabled",
            "status_label": "Local LLM disabled",
            "status_class": "warn",
            "provider": config.provider,
            "configured": config.configured,
            "reachable": False,
            "model": config.model,
            "detail": "Set AGENCY_LOCAL_LLM_ENABLED=true to use the Raspberry Pi LLM.",
            "generated_at": _utc_now(),
        }
    if not config.configured:
        return {
            "schema_version": "0.1.0",
            "status": "not_configured",
            "status_label": "Local LLM not configured",
            "status_class": "warn",
            "provider": config.provider,
            "configured": False,
            "reachable": False,
            "model": config.model,
            "detail": (
                "Set AGENCY_LOCAL_LLM_BASE_URL, AGENCY_LOCAL_LLM_API_KEY, "
                "and AGENCY_LOCAL_LLM_MODEL."
            ),
            "generated_at": _utc_now(),
        }
    try:
        result = await (client or OpenWebUIClient(config)).health()
    except Exception as exc:  # noqa: BLE001 - no-secret health surface.
        return {
            "schema_version": "0.1.0",
            "status": "unreachable",
            "status_label": "Local LLM unreachable",
            "status_class": "block",
            "provider": config.provider,
            "configured": config.configured,
            "reachable": False,
            "model": config.model,
            "detail": f"{type(exc).__name__}: {_text(str(exc))}",
            "generated_at": _utc_now(),
        }
    return {
        "schema_version": "0.1.0",
        "status": "ready",
        "status_class": "pass",
        "detail": "Open WebUI responded to the local model health check.",
        "generated_at": _utc_now(),
        **result,
    }


async def generate_local_llm_insights(
    *,
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    config: LocalLlmConfig | None = None,
    provider: LocalLlmProvider | None = None,
    tickers: Sequence[str] | None = None,
    max_tickers: int | None = None,
) -> dict[str, object]:
    config = config or LocalLlmConfig.from_env()
    output_root.mkdir(parents=True, exist_ok=True)
    if not config.enabled:
        payload = _base_payload(
            status="disabled",
            config=config,
            input_root=input_root,
            insights=[],
            detail="Local LLM insight worker is disabled.",
        )
        _write_payload(output_root, payload)
        return payload
    if not config.configured:
        payload = _base_payload(
            status="not_configured",
            config=config,
            input_root=input_root,
            insights=[],
            detail=(
                "Set AGENCY_LOCAL_LLM_BASE_URL, AGENCY_LOCAL_LLM_API_KEY, "
                "and AGENCY_LOCAL_LLM_MODEL before running local insights."
            ),
        )
        _write_payload(output_root, payload)
        return payload

    runtime_rows = _runtime_rows(input_root, tickers=tickers, max_tickers=max_tickers)
    llm = provider or OpenWebUIClient(config)
    insights: list[dict[str, object]] = []
    for row in runtime_rows:
        ticker = str(row["ticker"])
        try:
            insight = await llm.complete_json(_messages_for_ticker(row))
            insights.append(_normalize_insight(ticker, insight, row=row, config=config))
        except Exception as exc:  # noqa: BLE001 - persisted as no-secret worker status.
            insights.append(_failed_insight(ticker, exc, row=row, config=config))

    payload = _base_payload(
        status="completed",
        config=config,
        input_root=input_root,
        insights=insights,
        detail=f"Generated {len(insights)} local LLM ticker insight(s) in shadow mode.",
    )
    _write_payload(output_root, payload)
    return payload


def generate_local_llm_insights_sync(**kwargs: object) -> dict[str, object]:
    return asyncio.run(generate_local_llm_insights(**kwargs))


def _runtime_rows(
    input_root: Path,
    *,
    tickers: Sequence[str] | None,
    max_tickers: int | None,
) -> list[dict[str, object]]:
    evidence_packs = _read_json_list(input_root / "evidence-packs.json")
    reports = _read_json_list(input_root / "selection-reports.json")
    reports_by_ticker = {
        str(report.get("ticker") or "").strip().upper(): report
        for report in reports
        if isinstance(report, Mapping)
    }
    allowed = {ticker.upper() for ticker in tickers} if tickers else None
    rows: list[dict[str, object]] = []
    for pack in evidence_packs:
        if not isinstance(pack, Mapping):
            continue
        ticker = str(pack.get("ticker") or "").strip().upper()
        if not ticker or (allowed is not None and ticker not in allowed):
            continue
        report = reports_by_ticker.get(ticker, {})
        rows.append(
            {
                "ticker": ticker,
                "evidence_pack": dict(pack),
                "selection_report": dict(report) if isinstance(report, Mapping) else {},
                "sort_key": _sort_key(pack, report if isinstance(report, Mapping) else {}),
            }
        )
    rows.sort(key=lambda row: cast(tuple[float, str], row["sort_key"]))
    if max_tickers is not None:
        rows = rows[: max(0, max_tickers)]
    return rows


def _sort_key(pack: Mapping[str, object], report: Mapping[str, object]) -> tuple[float, str]:
    conviction = _float(
        report.get("final_conviction")
        or _mapping(report.get("deterministic")).get("conviction")
        or 0.0
    )
    actionable = len(_list(pack.get("actionable_signals")))
    return (-conviction - actionable, str(pack.get("ticker") or ""))


def _messages_for_ticker(row: Mapping[str, object]) -> list[dict[str, str]]:
    payload = _prompt_payload(row)
    return [
        {
            "role": "system",
            "content": (
                "You are an advisory local LLM worker for a supervised paper-trading "
                "agency. Return strict JSON only. You cannot approve trades, change "
                "risk gates, or override deterministic policy. Your job is to explain "
                "evidence, contradictions, and user checks in plain English."
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=True, sort_keys=True)},
    ]


def _prompt_payload(row: Mapping[str, object]) -> dict[str, object]:
    pack = _mapping(row.get("evidence_pack"))
    report = _mapping(row.get("selection_report"))
    return {
        "ticker": row.get("ticker"),
        "final_action": report.get("final_action"),
        "final_conviction": report.get("final_conviction"),
        "deterministic": _mapping(report.get("deterministic")),
        "actionable_signals": _signal_summaries(pack.get("actionable_signals")),
        "context_signals": _signal_summaries(pack.get("context_signals")),
        "suppressed_signals": _signal_summaries(pack.get("suppressed_signals")),
        "required_json_schema": {
            "summary": "string",
            "bullish_case": ["string"],
            "bearish_case": ["string"],
            "what_changed": ["string"],
            "user_checks": ["string"],
            "contradictions": ["string"],
            "confidence": "number from 0 to 1",
        },
    }


def _signal_summaries(value: object) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for row in _list(value)[:MAX_PROMPT_SIGNAL_ROWS]:
        item = _mapping(row)
        output.append(
            {
                "lane": item.get("lane"),
                "direction": item.get("direction"),
                "score": item.get("score"),
                "confidence": item.get("confidence"),
                "freshness": item.get("freshness"),
                "reason_codes": _list(item.get("reason_codes"))[:5],
            }
        )
    return output


def _normalize_insight(
    ticker: str,
    payload: Mapping[str, object],
    *,
    row: Mapping[str, object],
    config: LocalLlmConfig,
) -> dict[str, object]:
    report = _mapping(row.get("selection_report"))
    return {
        "ticker": ticker,
        "status": "completed",
        "provider": config.provider,
        "model": config.model,
        "mode": config.mode,
        "can_affect_trade_gates": False,
        "cycle_id": str(report.get("cycle_id") or ""),
        "final_action": str(report.get("final_action") or ""),
        "final_conviction": _float(report.get("final_conviction")),
        "summary": _text(payload.get("summary")),
        "bullish_case": _string_list(payload.get("bullish_case")),
        "bearish_case": _string_list(payload.get("bearish_case")),
        "what_changed": _string_list(payload.get("what_changed")),
        "user_checks": _string_list(payload.get("user_checks")),
        "contradictions": _string_list(payload.get("contradictions")),
        "confidence": max(0.0, min(1.0, _float(payload.get("confidence")))),
        "generated_at": _utc_now(),
    }


def _failed_insight(
    ticker: str,
    exc: Exception,
    *,
    row: Mapping[str, object],
    config: LocalLlmConfig,
) -> dict[str, object]:
    report = _mapping(row.get("selection_report"))
    return {
        "ticker": ticker,
        "status": "failed",
        "provider": config.provider,
        "model": config.model,
        "mode": config.mode,
        "can_affect_trade_gates": False,
        "cycle_id": str(report.get("cycle_id") or ""),
        "final_action": str(report.get("final_action") or ""),
        "summary": "Local LLM insight failed; use deterministic evidence only.",
        "error": f"{type(exc).__name__}: {_text(str(exc))}",
        "generated_at": _utc_now(),
    }


def _base_payload(
    *,
    status: str,
    config: LocalLlmConfig,
    input_root: Path,
    insights: Sequence[Mapping[str, object]],
    detail: str,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "status": status,
        "status_label": _status_label(status),
        "status_class": "pass" if status == "completed" else "warn",
        "provider": config.provider,
        "mode": config.mode,
        "model": config.model,
        "base_url": config.base_url,
        "input_root": str(input_root),
        "ticker_count": len(insights),
        "insights": [dict(row) for row in insights],
        "detail": detail,
        "generated_at": _utc_now(),
        "can_affect_trade_gates": False,
    }


def _write_payload(output_root: Path, payload: Mapping[str, object]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "local-llm-insights.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _completion_json_payload(payload: object, *, provider: str) -> dict[str, object]:
    data = _mapping(payload)
    if provider == "ollama":
        message = _mapping(data.get("message"))
        content = str(message.get("content") or "").strip()
        return _parse_json_object(content)
    choices = _list(data.get("choices"))
    if not choices:
        raise ValueError("OpenWebUI response did not contain choices")
    message = _mapping(_mapping(choices[0]).get("message"))
    content = str(message.get("content") or "").strip()
    return _parse_json_object(content)


def _parse_json_object(content: str) -> dict[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(content[start : end + 1])
    if not isinstance(payload, Mapping):
        raise TypeError("local LLM response JSON must be an object")
    return dict(payload)


def _openwebui_url(base_url: str, endpoint: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    if path.endswith(("/chat/completions", "/models")):
        return base
    path = f"{path}/{endpoint}" if path.endswith(("/api", "/v1")) else f"{path}/api/{endpoint}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _provider_url(base_url: str, endpoint: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    parts = urlsplit(base)
    path = parts.path.rstrip("/")
    if path.endswith(endpoint):
        return base
    path = f"{path}/{endpoint}"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _read_json_list(path: Path) -> list[object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _status_label(status: str) -> str:
    return {
        "completed": "Local LLM insights ready",
        "disabled": "Local LLM disabled",
        "not_configured": "Local LLM not configured",
    }.get(status, status.replace("_", " ").title())


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, *, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _string_list(value: object) -> list[str]:
    return [_text(item) for item in _list(value) if _text(item)]


def _text(value: object) -> str:
    text = str(value or "").strip()
    if len(text) > MAX_TEXT_CHARS:
        return text[: MAX_TEXT_CHARS - 1].rstrip() + "..."
    return text


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
