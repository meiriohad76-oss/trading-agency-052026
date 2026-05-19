from __future__ import annotations

import json
from pathlib import Path

import pytest

from agency.services import LlmReviewResult, OpenAILlmReviewProvider
from scripts.check_openai_llm_review import (
    check_openai_llm_review,
    redacted_openai_key_info,
    write_openai_check_report,
)


def test_redacted_openai_key_info_never_returns_full_key() -> None:
    key = "sk-proj-test-secret-key-value-1234567890"

    info = redacted_openai_key_info(key)
    serialized = json.dumps(info)

    assert info["present"] is True
    assert info["prefix"] == "sk-proj"
    assert info["suffix"] == "7890"
    assert info["looks_like_openai_key"] is True
    assert key not in serialized


async def test_openai_llm_check_missing_key_writes_report(tmp_path: Path) -> None:
    provider = OpenAILlmReviewProvider(api_key=None, enabled=True, model="gpt-test")

    summary = await check_openai_llm_review(output_root=tmp_path, provider=provider)

    assert summary["ready"] is False
    assert summary["status"] == "missing_api_key"
    assert (tmp_path / "openai-llm-check.json").exists()
    assert (tmp_path / "openai-llm-check.md").exists()


async def test_openai_llm_check_rejects_non_openai_key_shape(tmp_path: Path) -> None:
    provider = OpenAILlmReviewProvider(
        api_key="eyJraWQiOiJub3QtYW4tb3BlbmFpLWtleSJ9",
        enabled=True,
        model="gpt-test",
    )

    summary = await check_openai_llm_review(output_root=tmp_path, provider=provider)

    assert summary["ready"] is False
    assert summary["status"] == "invalid_key_shape"
    assert "OPENAI_API_KEY" in str(summary["error"])


async def test_openai_llm_check_prefers_env_file_over_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_key = "sk-proj-file-key-value-1234567890"
    monkeypatch.setenv("OPENAI_API_KEY", "eyJraWQiOiJub3QtYW4tb3BlbmFpLWtleSJ9")
    env_path = tmp_path / ".env"
    env_path.write_text(f"OPENAI_API_KEY={env_key}\n", encoding="utf-8")

    async def fake_review(
        self: OpenAILlmReviewProvider,
        _evidence_pack: object,
        _deterministic_decision: object,
    ) -> LlmReviewResult:
        assert self.api_key == env_key
        return LlmReviewResult(
            review={},
            lifecycle_event={},
            prompt_audit={
                "payload": {
                    "response_status": "succeeded",
                    "error": None,
                    "http_status": None,
                    "llm_action": "AGREE",
                    "llm_confidence": 0.8,
                    "retryable": False,
                }
            },
        )

    monkeypatch.setattr(OpenAILlmReviewProvider, "review", fake_review)

    summary = await check_openai_llm_review(output_root=tmp_path, env_path=env_path)

    assert summary["ready"] is True
    assert summary["status"] == "succeeded"
    assert summary["api_key"]["prefix"] == "sk-proj"


def test_openai_llm_check_report_contains_only_redacted_key_data(tmp_path: Path) -> None:
    summary = {
        "schema_version": "0.1.0",
        "checked_at": "2026-05-11T09:00:00+00:00",
        "ready": False,
        "status": "unauthorized",
        "status_label": "Unauthorized API key",
        "model": "gpt-test",
        "base_url": "https://api.openai.com/v1",
        "api_key": redacted_openai_key_info("sk-proj-test-secret-key-value-1234567890"),
        "http_status": 401,
        "retryable": False,
        "llm_action": "NO_REVIEW",
        "llm_confidence": 0.0,
        "error": "unauthorized: HTTP 401; message=[REDACTED]",
        "next_action": "Replace OPENAI_API_KEY with a valid OpenAI platform API key.",
    }

    write_openai_check_report(summary, tmp_path)

    contents = (tmp_path / "openai-llm-check.md").read_text(encoding="utf-8")
    assert "sk-proj-test-secret-key-value-1234567890" not in contents
    assert "Unauthorized API key" not in contents
    assert "unauthorized" in contents
