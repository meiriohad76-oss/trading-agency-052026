from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib import import_module
from typing import Protocol, cast
from urllib.parse import urlparse

import httpx

from agency.contracts import validate_contract
from agency.runtime import make_lifecycle_event_id
from agency.services.deterministic_rules import evaluate_deterministic_rules

DEFAULT_OPENAI_LLM_REVIEW_MODEL = "gpt-4.1-mini"
HTTP_BAD_REQUEST = 400
HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404
HTTP_RATE_LIMITED = 429
HTTP_SERVER_ERROR = 500
LLM_REVIEW_ENABLED_ENV = "AGENCY_ENABLE_LLM_REVIEW"
LLM_REVIEW_MODEL_ENV = "OPENAI_LLM_REVIEW_MODEL"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
PROMPT_CLASS = "candidate-review-v1"
AGENT_NAME = "llm-review"
MAX_SIGNAL_ROWS_PER_GROUP = 8
MAX_TEXT_CHARS = 420
MAX_LIST_ITEMS = 6
MIN_OPENAI_API_KEY_LENGTH = 20
ALLOWED_LLM_ACTIONS = {
    "NO_REVIEW",
    "AGREE",
    "DISAGREE",
    "DEFER",
    "NEEDS_MORE_EVIDENCE",
    "NO_TRADE",
    "WATCH",
    "CLOSE_REVIEW",
}
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"]?[^'\"\s,}]+"),
)


@dataclass(frozen=True)
class LlmReviewResult:
    """Context-only or provider-backed LLM review artifact and audit records."""

    review: dict[str, object]
    lifecycle_event: dict[str, object]
    prompt_audit: dict[str, object] | None = None


class LlmReviewProvider(Protocol):
    async def review(
        self,
        evidence_pack: Mapping[str, object],
        deterministic_decision: Mapping[str, object],
    ) -> LlmReviewResult: ...


@dataclass(frozen=True)
class LlmReviewPrompt:
    """Redacted prompt bundle used by provider-backed LLM review."""

    messages: list[dict[str, str]]
    prompt_hash: str
    prompt_payload: dict[str, object]
    redaction_status: str


@dataclass(frozen=True)
class LlmReviewBatchResult:
    """Precomputed LLM reviews ready to inject into a runtime cycle."""

    reviews_by_ticker: dict[str, dict[str, object]]
    lifecycle_events: list[dict[str, object]]
    prompt_audits: list[dict[str, object]]
    reviewed_tickers: list[str]


@dataclass(frozen=True)
class OpenAILlmErrorInfo:
    """Sanitized OpenAI failure details safe for local reports and prompt audits."""

    category: str
    detail: str
    http_status: int | None = None
    retryable: bool = False


@dataclass(frozen=True)
class OpenAILlmReviewProvider:
    """OpenAI-backed supervised reviewer with safe local fallbacks."""

    api_key: str | None = None
    model: str = DEFAULT_OPENAI_LLM_REVIEW_MODEL
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: float = 45.0

    @classmethod
    def from_env(cls, *, enabled: bool | None = None) -> OpenAILlmReviewProvider:
        env_enabled = _env_flag(LLM_REVIEW_ENABLED_ENV)
        model = os.environ.get(LLM_REVIEW_MODEL_ENV, DEFAULT_OPENAI_LLM_REVIEW_MODEL).strip()
        return cls(
            api_key=_blank_to_none(os.environ.get(OPENAI_API_KEY_ENV)),
            model=model or DEFAULT_OPENAI_LLM_REVIEW_MODEL,
            enabled=env_enabled if enabled is None else enabled,
            base_url=os.environ.get(OPENAI_BASE_URL_ENV, "https://api.openai.com/v1").rstrip("/"),
        )

    async def review(
        self,
        evidence_pack: Mapping[str, object],
        deterministic_decision: Mapping[str, object],
    ) -> LlmReviewResult:
        validate_contract("evidence-pack", evidence_pack)
        event_time = str(evidence_pack["generated_at"])
        if not self.enabled:
            return build_llm_review_stub(
                evidence_pack,
                deterministic_decision,
                generated_at=event_time,
            )

        prompt = build_llm_review_prompt(evidence_pack, deterministic_decision)
        if self.api_key is None:
            review = build_no_review(
                "LLM review was requested, but OPENAI_API_KEY is not configured.",
                concerns=["missing_openai_api_key"],
            )
            return _provider_result(
                evidence_pack,
                deterministic_decision,
                prompt,
                review,
                model=self.model,
                event_time=event_time,
                status="ERROR",
                reason="llm review missing api key",
                response_status="missing_api_key",
            )
        if not looks_like_openai_api_key(self.api_key):
            error_info = OpenAILlmErrorInfo(
                category="invalid_key_shape",
                detail="OPENAI_API_KEY is present but does not look like an OpenAI platform key.",
            )
            review = build_no_review(
                "LLM review was requested, but OPENAI_API_KEY is not a valid OpenAI key shape.",
                concerns=[error_info.detail],
            )
            return _provider_result(
                evidence_pack,
                deterministic_decision,
                prompt,
                review,
                model=self.model,
                event_time=event_time,
                status="ERROR",
                reason="llm review invalid api key shape",
                response_status=error_info.category,
                error=error_info.detail,
                error_info=error_info,
            )

        try:
            response = await self._request_review(prompt.messages)
            raw_review = _response_message_payload(response)
            review = normalize_llm_review(raw_review)
            return _provider_result(
                evidence_pack,
                deterministic_decision,
                prompt,
                review,
                model=self.model,
                event_time=event_time,
                status="RECORDED",
                reason="llm review completed",
                response_status="succeeded",
                usage=_usage_payload(response),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            error_info = classify_openai_error(exc)
            review = build_no_review(
                "LLM review failed safely; deterministic and policy-gated decision is preserved.",
                concerns=[error_info.detail],
            )
            return _provider_result(
                evidence_pack,
                deterministic_decision,
                prompt,
                review,
                model=self.model,
                event_time=event_time,
                status="ERROR",
                reason="llm review failed safely",
                response_status=error_info.category,
                error=error_info.detail,
                error_info=error_info,
            )

    async def _request_review(self, messages: list[dict[str, str]]) -> Mapping[str, object]:
        payload = _chat_completion_payload(self.model, messages, use_completion_tokens=True)
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            verify=_verify_context(),
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if (
                response.status_code == HTTP_BAD_REQUEST
                and "max_completion_tokens" in response.text
            ):
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=_chat_completion_payload(
                        self.model,
                        messages,
                        use_completion_tokens=False,
                    ),
                )
            response.raise_for_status()
            return cast(Mapping[str, object], response.json())


def build_context_only_llm_review() -> dict[str, object]:
    """Return the no-live-LLM review shape used until providers are enabled."""
    return {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": "LLM review is not enabled for this run.",
        "supporting_factors": [],
        "concerns": [],
    }


def build_no_review(rationale: str, *, concerns: list[str] | None = None) -> dict[str, object]:
    """Return a contract-compatible no-review payload with a specific reason."""
    return {
        "action": "NO_REVIEW",
        "confidence": 0.0,
        "rationale": _truncate(rationale, MAX_TEXT_CHARS),
        "supporting_factors": [],
        "concerns": concerns or [],
    }


def build_llm_review_stub(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    *,
    generated_at: str | None = None,
) -> LlmReviewResult:
    """Build a contract-compatible, context-only LLM review and lifecycle event."""
    validate_contract("evidence-pack", evidence_pack)
    pack = dict(evidence_pack)
    event_time = generated_at or str(pack["generated_at"])
    review = build_context_only_llm_review()
    lifecycle_event = _lifecycle_event(
        pack,
        deterministic_decision,
        review,
        event_time=event_time,
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    return LlmReviewResult(review=review, lifecycle_event=lifecycle_event)


def build_llm_review_prompt(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
) -> LlmReviewPrompt:
    """Build a redacted prompt from summary-level evidence only."""
    validate_contract("evidence-pack", evidence_pack)
    prompt_payload = _prompt_payload(evidence_pack, deterministic_decision)
    user_content = json.dumps(prompt_payload, ensure_ascii=True, sort_keys=True)
    redacted_user_content, redaction_status = _redact_secrets(user_content)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a supervised equity research reviewer. You never execute trades, "
                "never override hard policy gates, and never promote a deterministic "
                "NO_TRADE into a trade. Review only the provided summarized evidence."
            ),
        },
        {"role": "user", "content": redacted_user_content},
    ]
    prompt_hash = hashlib.sha256(
        json.dumps(messages, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return LlmReviewPrompt(
        messages=messages,
        prompt_hash=prompt_hash,
        prompt_payload=prompt_payload,
        redaction_status=redaction_status,
    )


def normalize_llm_review(payload: Mapping[str, object]) -> dict[str, object]:
    """Normalize a provider response into the selection-report LLM review shape."""
    action = str(payload.get("action", "NO_REVIEW")).strip().upper()
    if action not in ALLOWED_LLM_ACTIONS:
        return build_no_review(
            "LLM response used an unsupported action, so the review was ignored.",
            concerns=[f"unsupported_action:{_truncate(action, 80)}"],
        )
    return {
        "action": action,
        "confidence": _clamp_float(payload.get("confidence", 0.0)),
        "rationale": _truncate(
            str(payload.get("rationale") or "LLM review returned no rationale."),
            MAX_TEXT_CHARS,
        ),
        "supporting_factors": _string_items(payload.get("supporting_factors")),
        "concerns": _string_items(payload.get("concerns")),
    }


def looks_like_openai_api_key(value: str | None) -> bool:
    """Return whether a value has the expected local shape for an OpenAI key."""
    if value is None or not value.strip():
        return False
    cleaned = value.strip()
    return cleaned.startswith("sk-") and len(cleaned) >= MIN_OPENAI_API_KEY_LENGTH


def classify_openai_error(exc: Exception) -> OpenAILlmErrorInfo:
    """Map provider exceptions to no-secret categories useful for operations."""
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        category = _http_status_category(status_code, exc.response.text)
        detail = _openai_response_error_detail(exc.response, category)
        return OpenAILlmErrorInfo(
            category=category,
            detail=detail,
            http_status=status_code,
            retryable=_is_retryable_status(status_code),
        )
    if isinstance(exc, httpx.TimeoutException):
        return OpenAILlmErrorInfo(
            category="timeout",
            detail="timeout: OpenAI request timed out",
            retryable=True,
        )
    if isinstance(exc, httpx.RequestError):
        return OpenAILlmErrorInfo(
            category="network_error",
            detail=f"network_error: {_safe_error(exc)}",
            retryable=True,
        )
    if isinstance(exc, (KeyError, TypeError, ValueError, json.JSONDecodeError)):
        return OpenAILlmErrorInfo(
            category="invalid_response",
            detail=f"invalid_response: {_safe_error(exc)}",
            retryable=False,
        )
    return OpenAILlmErrorInfo(
        category="failed",
        detail=f"failed: {_safe_error(exc)}",
        retryable=False,
    )


async def review_evidence_packs(
    evidence_packs: list[Mapping[str, object]],
    *,
    provider: LlmReviewProvider,
    max_reviews: int = 5,
    include_no_trade_with_evidence: bool = False,
) -> LlmReviewBatchResult:
    """Review a bounded set of candidate evidence packs before final selection."""
    reviews_by_ticker: dict[str, dict[str, object]] = {}
    lifecycle_events: list[dict[str, object]] = []
    prompt_audits: list[dict[str, object]] = []
    reviewed_tickers: list[str] = []
    _log_llm_review_event(
        "llm_review_start",
        candidate_count=len(evidence_packs),
        max_reviews=max_reviews,
        model=str(getattr(provider, "model", provider.__class__.__name__)),
    )
    for pack in evidence_packs:
        validate_contract("evidence-pack", pack)
        deterministic = evaluate_deterministic_rules(pack).decision
        if not _should_review_pack(
            pack,
            deterministic,
            include_no_trade_with_evidence=include_no_trade_with_evidence,
        ):
            continue
        if len(reviewed_tickers) >= max_reviews:
            break
        result = await provider.review(pack, deterministic)
        ticker = str(pack["ticker"]).upper()
        reviews_by_ticker[ticker] = result.review
        lifecycle_events.append(result.lifecycle_event)
        reviewed_tickers.append(ticker)
        if result.prompt_audit is not None:
            prompt_audits.append(result.prompt_audit)
    _log_llm_review_event(
        "llm_review_complete",
        candidate_count=len(evidence_packs),
        reviewed=len(reviewed_tickers),
        skipped=max(0, len(evidence_packs) - len(reviewed_tickers)),
        model=str(getattr(provider, "model", provider.__class__.__name__)),
    )
    return LlmReviewBatchResult(
        reviews_by_ticker=reviews_by_ticker,
        lifecycle_events=lifecycle_events,
        prompt_audits=prompt_audits,
        reviewed_tickers=reviewed_tickers,
    )


def _log_llm_review_event(event: str, **payload: object) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "ts": datetime.now(UTC).isoformat(),
                **payload,
            },
            sort_keys=True,
            default=str,
        ),
        flush=True,
    )


def _lifecycle_event(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    review: Mapping[str, object],
    *,
    event_time: str,
    status: str = "CONTEXT_ONLY",
    reason: str = "llm review disabled",
) -> dict[str, object]:
    cycle_id = str(evidence_pack["cycle_id"])
    ticker = str(evidence_pack["ticker"])
    event_type = "LLM_ACTION"
    return {
        "schema_version": "0.1.0",
        "event_id": make_lifecycle_event_id(
            cycle_id=cycle_id,
            ticker=ticker,
            event_type=event_type,
            event_time=event_time,
        ),
        "cycle_id": cycle_id,
        "ticker": ticker,
        "event_type": event_type,
        "event_time": event_time,
        "status": status,
        "reason": reason,
        "payload": {
            "llm_review": dict(review),
            "deterministic_action": deterministic_decision.get("action", "UNKNOWN"),
        },
    }


def _provider_result(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    prompt: LlmReviewPrompt,
    review: Mapping[str, object],
    *,
    model: str,
    event_time: str,
    status: str,
    reason: str,
    response_status: str,
    usage: Mapping[str, object] | None = None,
    error: str | None = None,
    error_info: OpenAILlmErrorInfo | None = None,
) -> LlmReviewResult:
    lifecycle_event = _lifecycle_event(
        evidence_pack,
        deterministic_decision,
        review,
        event_time=event_time,
        status=status,
        reason=reason,
    )
    validate_contract("candidate-lifecycle-event", lifecycle_event)
    prompt_audit = _prompt_audit(
        evidence_pack,
        prompt,
        review,
        model=model,
        created_at=event_time,
        response_status=response_status,
        usage=usage,
        error=error,
        error_info=error_info,
    )
    return LlmReviewResult(
        review=dict(review),
        lifecycle_event=lifecycle_event,
        prompt_audit=prompt_audit,
    )


def _prompt_payload(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
) -> dict[str, object]:
    return {
        "task": PROMPT_CLASS,
        "guardrails": [
            "Advisory review only; do not recommend execution.",
            "If deterministic action is NO_TRADE, do not promote it.",
            "If hard policy gates block the candidate, agree with the block or defer.",
            "Prefer NEEDS_MORE_EVIDENCE when source breadth or freshness is weak.",
        ],
        "required_response": {
            "action": sorted(ALLOWED_LLM_ACTIONS),
            "confidence": "number from 0 to 1",
            "rationale": "brief decision-focused explanation",
            "supporting_factors": "short list",
            "concerns": "short list",
        },
        "candidate": {
            "cycle_id": str(evidence_pack["cycle_id"]),
            "ticker": str(evidence_pack["ticker"]),
            "as_of": str(evidence_pack["as_of"]),
            "generated_at": str(evidence_pack["generated_at"]),
        },
        "deterministic_decision": _decision_payload(deterministic_decision),
        "data_quality": _mapping_copy(evidence_pack, "data_quality"),
        "signals": {
            "actionable": _signal_rows(evidence_pack, "actionable_signals"),
            "context": _signal_rows(evidence_pack, "context_signals"),
            "suppressed": _signal_rows(evidence_pack, "suppressed_signals"),
        },
    }


def _prompt_audit(
    evidence_pack: Mapping[str, object],
    prompt: LlmReviewPrompt,
    review: Mapping[str, object],
    *,
    model: str,
    created_at: str,
    response_status: str,
    usage: Mapping[str, object] | None,
    error: str | None,
    error_info: OpenAILlmErrorInfo | None,
) -> dict[str, object]:
    identity = "|".join(
        [
            str(evidence_pack["cycle_id"]),
            str(evidence_pack["ticker"]).upper(),
            prompt.prompt_hash,
            model,
        ]
    )
    audit: dict[str, object] = {
        "schema_version": "0.1.0",
        "prompt_id": f"llm-review-{hashlib.sha256(identity.encode('utf-8')).hexdigest()}",
        "run_id": None,
        "cycle_id": str(evidence_pack["cycle_id"]),
        "agent_name": AGENT_NAME,
        "model": model,
        "prompt_class": PROMPT_CLASS,
        "prompt_hash": prompt.prompt_hash,
        "created_at": created_at,
        "redaction_status": prompt.redaction_status,
        "payload": {
            "ticker": str(evidence_pack["ticker"]).upper(),
            "response_status": response_status,
            "llm_action": str(review["action"]),
            "llm_confidence": review["confidence"],
            "llm_rationale": str(review["rationale"]),
            "supporting_factor_count": len(_string_items(review.get("supporting_factors"))),
            "concern_count": len(_string_items(review.get("concerns"))),
            "usage": dict(usage or {}),
            "error": error,
            "error_category": error_info.category if error_info is not None else None,
            "http_status": error_info.http_status if error_info is not None else None,
            "retryable": error_info.retryable if error_info is not None else False,
        },
    }
    validate_contract("prompt-audit", audit)
    return audit


def _chat_completion_payload(
    model: str,
    messages: list[dict[str, str]],
    *,
    use_completion_tokens: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "candidate_llm_review",
                "strict": True,
                "schema": _review_response_schema(),
            },
        },
    }
    if use_completion_tokens:
        payload["max_completion_tokens"] = 700
    else:
        payload["max_tokens"] = 700
    return payload


def _review_response_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["action", "confidence", "rationale", "supporting_factors", "concerns"],
        "properties": {
            "action": {"type": "string", "enum": sorted(ALLOWED_LLM_ACTIONS)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string"},
            "supporting_factors": {"type": "array", "items": {"type": "string"}},
            "concerns": {"type": "array", "items": {"type": "string"}},
        },
    }


def _response_message_payload(response: Mapping[str, object]) -> Mapping[str, object]:
    choices = response["choices"]
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI response did not contain choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise TypeError("OpenAI choice must be an object")
    message = choice["message"]
    if not isinstance(message, Mapping):
        raise TypeError("OpenAI message must be an object")
    content = message["content"]
    if not isinstance(content, str):
        raise TypeError("OpenAI message content must be text")
    payload = json.loads(content)
    if not isinstance(payload, Mapping):
        raise TypeError("LLM review JSON must be an object")
    return cast(Mapping[str, object], payload)


def _usage_payload(response: Mapping[str, object]) -> dict[str, object]:
    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return {}
    return {str(key): value for key, value in usage.items() if isinstance(value, int | float | str)}


def _decision_payload(deterministic_decision: Mapping[str, object]) -> dict[str, object]:
    return {
        "action": str(deterministic_decision.get("action", "UNKNOWN")),
        "score": deterministic_decision.get("score", 0.0),
        "conviction": deterministic_decision.get("conviction", 0.0),
        "reason_codes": _string_items(deterministic_decision.get("reason_codes")),
        "blockers": _string_items(deterministic_decision.get("blockers")),
    }


def _mapping_copy(payload: Mapping[str, object], key: str) -> dict[str, object]:
    value = payload[key]
    if not isinstance(value, Mapping):
        raise TypeError(f"{key} must be a mapping")
    return {str(item_key): item_value for item_key, item_value in value.items()}


def _signal_rows(evidence_pack: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = evidence_pack[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    rows: list[dict[str, object]] = []
    for item in value[:MAX_SIGNAL_ROWS_PER_GROUP]:
        if not isinstance(item, Mapping):
            raise TypeError(f"{key} entries must be mappings")
        rows.append(_signal_row(cast(Mapping[str, object], item)))
    return rows


def _signal_row(signal: Mapping[str, object]) -> dict[str, object]:
    provenance = _mapping_copy(signal, "provenance")
    source_url = provenance.get("source_url")
    return {
        "lane": str(signal["lane"]),
        "score": signal["score"],
        "direction": str(signal["direction"]),
        "actionability": str(signal["actionability"]),
        "source_tier": str(signal["source_tier"]),
        "verification_level": str(signal["verification_level"]),
        "freshness": str(signal["freshness"]),
        "confidence": signal["confidence"],
        "reason_codes": _string_items(signal.get("reason_codes")),
        "summary": _truncate(str(signal.get("summary") or ""), MAX_TEXT_CHARS),
        "source": str(provenance.get("source", "")),
        "source_id": _truncate(str(provenance.get("source_id", "")), 160),
        "source_domain": _domain(source_url),
    }


def _should_review_pack(
    evidence_pack: Mapping[str, object],
    deterministic_decision: Mapping[str, object],
    *,
    include_no_trade_with_evidence: bool,
) -> bool:
    action = str(deterministic_decision.get("action", "")).upper()
    if action == "WATCH":
        return True
    if not include_no_trade_with_evidence:
        return False
    actionable = evidence_pack.get("actionable_signals")
    context = evidence_pack.get("context_signals")
    has_actionable = isinstance(actionable, list) and bool(actionable)
    has_context = isinstance(context, list) and bool(context)
    return has_actionable or has_context


def _redact_secrets(value: str) -> tuple[str, str]:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    status = "REDACTED" if redacted != value else "NO_SECRETS"
    return redacted, status


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        text = _truncate(str(item).strip(), 180)
        if text:
            items.append(text)
        if len(items) >= MAX_LIST_ITEMS:
            break
    return items


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: max(0, limit - 3)]}..."


def _clamp_float(value: object) -> float:
    if not isinstance(value, int | float):
        return 0.0
    return min(1.0, max(0.0, float(value)))


def _domain(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlparse(value)
    return parsed.netloc or None


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _safe_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    redacted, _status = _redact_secrets(text)
    return _truncate(redacted, 180)


def _http_status_category(status_code: int, response_text: str) -> str:
    if status_code == HTTP_UNAUTHORIZED:
        return "unauthorized"
    if status_code == HTTP_FORBIDDEN:
        return "forbidden"
    if status_code == HTTP_NOT_FOUND:
        return "model_not_found" if "model" in response_text.lower() else "not_found"
    if status_code == HTTP_RATE_LIMITED:
        return "rate_limited"
    if status_code >= HTTP_SERVER_ERROR:
        return "server_error"
    return f"http_{status_code}"


def _openai_response_error_detail(response: httpx.Response, category: str) -> str:
    body = _openai_error_body(response)
    if body:
        return _truncate(f"{category}: HTTP {response.status_code}; {body}", 240)
    return _truncate(f"{category}: HTTP {response.status_code}", 240)


def _openai_error_body(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        redacted, _status = _redact_secrets(response.text)
        return _truncate(redacted, 160)
    if not isinstance(payload, Mapping):
        return ""
    error = payload.get("error")
    if not isinstance(error, Mapping):
        return ""
    parts = []
    for key in ("message", "type", "code", "param"):
        value = error.get(key)
        if isinstance(value, str) and value.strip():
            redacted, _status = _redact_secrets(value)
            parts.append(f"{key}={_truncate(redacted, 120)}")
    return "; ".join(parts)


def _is_retryable_status(status_code: int) -> bool:
    return status_code == HTTP_RATE_LIMITED or status_code >= HTTP_SERVER_ERROR


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
