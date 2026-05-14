from __future__ import annotations

import json
from collections.abc import Mapping

import httpx
import pytest

from agency.contracts import ContractValidationError, validate_contract
from agency.services import (
    LlmReviewResult,
    OpenAILlmReviewProvider,
    build_context_only_llm_review,
    build_deterministic_selection,
    build_evidence_pack,
    build_llm_review_prompt,
    build_llm_review_stub,
    build_signal_result,
    classify_openai_error,
    looks_like_openai_api_key,
    normalize_llm_review,
    review_evidence_packs,
)

HTTP_UNAUTHORIZED = 401


def test_llm_review_stub_returns_context_only_review_and_lifecycle_event() -> None:
    selection = build_deterministic_selection(_evidence_pack())

    result = build_llm_review_stub(
        _evidence_pack(),
        selection.selection_report["deterministic"],
    )

    validate_contract("candidate-lifecycle-event", result.lifecycle_event)
    assert result.review == build_context_only_llm_review()
    assert result.lifecycle_event["event_type"] == "LLM_ACTION"
    assert result.lifecycle_event["status"] == "CONTEXT_ONLY"


def test_context_only_review_is_selection_report_compatible() -> None:
    selection = build_deterministic_selection(_evidence_pack())

    assert selection.selection_report["llm_review"] == build_context_only_llm_review()
    validate_contract("selection-report", selection.selection_report)


def test_llm_review_stub_rejects_invalid_evidence_pack() -> None:
    evidence_pack = _evidence_pack()
    evidence_pack["ticker"] = "bad ticker"

    with pytest.raises(ContractValidationError):
        build_llm_review_stub(evidence_pack, {"action": "WATCH"})


def test_llm_prompt_uses_redacted_summary_level_context_only() -> None:
    pack = _evidence_pack(summary="Constructive setup. api_key=super-secret-value")

    prompt = build_llm_review_prompt(pack, {"action": "WATCH", "reason_codes": []})
    content = prompt.messages[-1]["content"]

    assert prompt.redaction_status == "REDACTED"
    assert "super-secret-value" not in content
    assert "[REDACTED]" in content
    assert "Constructive setup" in content
    assert "raw_email_body" not in content


def test_normalize_llm_review_rejects_unsupported_action() -> None:
    review = normalize_llm_review(
        {
            "action": "BUY",
            "confidence": 0.8,
            "rationale": "Promote it.",
            "supporting_factors": ["factor"],
            "concerns": [],
        }
    )

    assert review["action"] == "NO_REVIEW"
    assert review["confidence"] == 0.0
    assert "unsupported_action:BUY" in review["concerns"]


async def test_openai_provider_missing_key_falls_back_with_prompt_audit() -> None:
    provider = OpenAILlmReviewProvider(api_key=None, enabled=True, model="gpt-test")

    result = await provider.review(_evidence_pack(), {"action": "WATCH", "reason_codes": []})

    assert result.review["action"] == "NO_REVIEW"
    assert result.lifecycle_event["status"] == "ERROR"
    assert result.prompt_audit is not None
    validate_contract("prompt-audit", result.prompt_audit)
    assert result.prompt_audit["payload"]["response_status"] == "missing_api_key"


async def test_openai_provider_invalid_key_shape_falls_back_before_network() -> None:
    provider = OpenAILlmReviewProvider(
        api_key="eyJraWQiOiJub3QtYW4tb3BlbmFpLWtleSJ9",
        enabled=True,
        model="gpt-test",
    )

    result = await provider.review(_evidence_pack(), {"action": "WATCH", "reason_codes": []})

    assert result.review["action"] == "NO_REVIEW"
    assert result.prompt_audit is not None
    payload = result.prompt_audit["payload"]
    assert payload["response_status"] == "invalid_key_shape"
    assert payload["http_status"] is None


def test_openai_key_shape_check_requires_platform_key_prefix() -> None:
    assert looks_like_openai_api_key("sk-test-secret-key-value-123456789") is True
    assert looks_like_openai_api_key("eyJraWQiOiJub3QtYW4tb3BlbmFpLWtleSJ9") is False


def test_openai_http_error_classification_redacts_key_material() -> None:
    exc = _openai_status_error(
        401,
        "Incorrect API key provided: sk-test-secret-key-value-123456789.",
    )

    info = classify_openai_error(exc)

    assert info.category == "unauthorized"
    assert info.http_status == HTTP_UNAUTHORIZED
    assert info.retryable is False
    assert "sk-test-secret-key-value-123456789" not in info.detail
    assert "[REDACTED]" in info.detail


async def test_openai_provider_records_sanitized_http_failure_in_prompt_audit() -> None:
    provider = _UnauthorizedProvider(
        api_key="sk-test-secret-key-value-123456789",
        enabled=True,
        model="gpt-test",
    )

    result = await provider.review(_evidence_pack(), {"action": "WATCH", "reason_codes": []})

    assert result.review["action"] == "NO_REVIEW"
    assert result.prompt_audit is not None
    payload = result.prompt_audit["payload"]
    assert payload["response_status"] == "unauthorized"
    assert payload["error_category"] == "unauthorized"
    assert payload["http_status"] == HTTP_UNAUTHORIZED
    assert payload["retryable"] is False
    assert "HTTP 401" in str(payload["error"])
    assert "sk-test-secret-key-value-123456789" not in str(payload["error"])


async def test_review_evidence_packs_reviews_only_bounded_watch_candidates() -> None:
    provider = _FakeProvider()

    batch = await review_evidence_packs(
        [_evidence_pack(ticker="AAPL", score=0.7), _evidence_pack(ticker="MSFT", score=0.1)],
        provider=provider,
        max_reviews=1,
    )

    assert batch.reviewed_tickers == ["AAPL"]
    assert batch.reviews_by_ticker["AAPL"]["action"] == "AGREE"
    assert len(batch.lifecycle_events) == 1
    assert batch.lifecycle_events[0]["event_type"] == "LLM_ACTION"
    assert provider.reviewed == ["AAPL"]


# ---------------------------------------------------------------------------
# T137 — structured JSON logging for LLM review runs
# ---------------------------------------------------------------------------


async def test_llm_review_start_log_is_emitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """review_evidence_packs prints a JSON llm_review_start event on stdout."""
    provider = _FakeProvider()

    await review_evidence_packs(
        [_evidence_pack(ticker="AAPL", score=0.7)],
        provider=provider,
        max_reviews=5,
    )

    captured = capsys.readouterr()
    start_events = []
    for line in captured.out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("event") == "llm_review_start":
                start_events.append(obj)
        except (json.JSONDecodeError, AttributeError):
            pass

    assert start_events, f"No llm_review_start log line found. Got:\n{captured.out!r}"
    evt = start_events[0]
    assert "candidate_count" in evt
    assert "model" in evt
    assert "ts" in evt


async def test_llm_review_complete_log_is_emitted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """review_evidence_packs prints a JSON llm_review_complete event on stdout."""
    provider = _FakeProvider()

    await review_evidence_packs(
        [_evidence_pack(ticker="AAPL", score=0.7), _evidence_pack(ticker="MSFT", score=0.7)],
        provider=provider,
        max_reviews=5,
    )

    captured = capsys.readouterr()
    complete_events = []
    for line in captured.out.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
            if obj.get("event") == "llm_review_complete":
                complete_events.append(obj)
        except (json.JSONDecodeError, AttributeError):
            pass

    assert complete_events, f"No llm_review_complete log line found. Got:\n{captured.out!r}"
    evt = complete_events[0]
    assert "reviewed" in evt
    assert "skipped" in evt
    assert "ts" in evt


class _FakeProvider:
    def __init__(self) -> None:
        self.reviewed: list[str] = []

    async def review(
        self,
        evidence_pack: Mapping[str, object],
        deterministic_decision: Mapping[str, object],
    ) -> LlmReviewResult:
        self.reviewed.append(str(evidence_pack["ticker"]))
        event = build_llm_review_stub(evidence_pack, deterministic_decision).lifecycle_event
        return LlmReviewResult(
            review={
                "action": "AGREE",
                "confidence": 0.7,
                "rationale": "Evidence supports the deterministic review queue.",
                "supporting_factors": ["confirmed setup"],
                "concerns": [],
            },
            lifecycle_event=event,
            prompt_audit=None,
        )


class _UnauthorizedProvider(OpenAILlmReviewProvider):
    async def _request_review(self, _messages: list[dict[str, str]]) -> Mapping[str, object]:
        raise _openai_status_error(
            401,
            "Incorrect API key provided: sk-test-secret-key-value-123456789.",
        )


def _openai_status_error(status_code: int, message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        status_code,
        request=request,
        json={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "code": "invalid_api_key",
            }
        },
    )
    return httpx.HTTPStatusError("OpenAI request failed", request=request, response=response)


def _evidence_pack_for(
    ticker: str,
    score: float,
    *,
    summary: str = "Confirmed source summary.",
) -> dict[str, object]:
    return build_evidence_pack(
        cycle_id="cycle-1",
        ticker=ticker,
        as_of="2026-05-07T09:30:00Z",
        generated_at="2026-05-07T09:31:00Z",
        signals=[
            build_signal_result(
                cycle_id="cycle-1",
                ticker=ticker,
                as_of="2026-05-07T09:30:00Z",
                lane="fundamentals",
                score=score,
                provenance=_provenance("fundamentals"),
                confidence=0.9,
                summary=summary,
            ),
            build_signal_result(
                cycle_id="cycle-1",
                ticker=ticker,
                as_of="2026-05-07T09:30:00Z",
                lane="insider",
                score=score,
                provenance=_provenance("insider"),
                confidence=0.9,
                summary=summary,
            )
        ],
    )


def _evidence_pack(
    ticker: str = "AAPL",
    score: float = 0.7,
    *,
    summary: str = "Confirmed source summary.",
) -> dict[str, object]:
    return _evidence_pack_for(ticker, score, summary=summary)


def _provenance(source_id: str) -> dict[str, object]:
    return {
        "source": "sec-edgar",
        "source_tier": "OFFICIAL_FILING",
        "source_id": source_id,
        "source_url": None,
        "timestamp_observed": "2026-05-07T09:00:00Z",
        "timestamp_as_of": "2026-05-07T08:59:00Z",
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
