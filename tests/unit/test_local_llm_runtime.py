from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agency.runtime.local_llm import (
    LocalLlmConfig,
    OpenWebUIClient,
    check_local_llm_health,
    generate_local_llm_insights,
)


def test_local_llm_config_normalizes_open_webui_base_url(monkeypatch) -> None:
    monkeypatch.setenv("AGENCY_LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_PROVIDER", "openwebui")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://10.0.0.5:3000")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_API_KEY", "owui-key")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "llama3.1:8b")

    config = LocalLlmConfig.from_env()

    assert config.enabled is True
    assert config.provider == "openwebui"
    assert config.mode == "shadow"
    assert config.chat_completions_url == "http://10.0.0.5:3000/api/chat/completions"
    assert config.models_url == "http://10.0.0.5:3000/api/models"


def test_local_llm_config_supports_direct_ollama(monkeypatch) -> None:
    monkeypatch.setenv("AGENCY_LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://10.100.102.18:11434")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_API_KEY", "")

    config = LocalLlmConfig.from_env()

    assert config.provider == "ollama"
    assert config.configured is True
    assert config.chat_completions_url == "http://10.100.102.18:11434/api/chat"
    assert config.models_url == "http://10.100.102.18:11434/api/tags"


def test_parse_json_object_ignores_trailing_non_json_text() -> None:
    from agency.runtime.local_llm import _parse_json_object

    payload = _parse_json_object(
        '{"summary":"ok","confidence":0.4}\nextra note with } brace'
    )

    assert payload == {"summary": "ok", "confidence": 0.4}


async def test_openwebui_client_posts_openai_compatible_payload() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Evidence is mixed but improving.",
                                    "bullish_case": ["Confirmed positive flow"],
                                    "bearish_case": ["One bearish context signal"],
                                    "what_changed": ["Fresh email evidence arrived"],
                                    "user_checks": ["Check position sizing"],
                                    "contradictions": ["Bullish review with bearish context"],
                                    "confidence": 0.62,
                                }
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 123},
            },
        )

    config = LocalLlmConfig(
        enabled=True,
        base_url="http://pi.local:3000",
        api_key="local-key",
        model="qwen2.5:7b",
    )
    client = OpenWebUIClient(config, transport=httpx.MockTransport(handler))

    result = await client.complete_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Summarize AAPL."},
        ]
    )

    assert result["summary"] == "Evidence is mixed but improving."
    assert requests == [
        {
            "method": "POST",
            "url": "http://pi.local:3000/api/chat/completions",
            "auth": "Bearer local-key",
            "payload": {
                "model": "qwen2.5:7b",
                "messages": [
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Summarize AAPL."},
                ],
                "temperature": 0.1,
                "stream": False,
            },
        }
    ]


async def test_openwebui_client_posts_ollama_native_payload() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            json={
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "summary": "Direct Ollama JSON works.",
                            "bullish_case": ["One constructive point"],
                            "bearish_case": [],
                            "what_changed": [],
                            "user_checks": [],
                            "contradictions": [],
                            "confidence": 0.5,
                        }
                    ),
                },
                "done": True,
            },
        )

    config = LocalLlmConfig(
        enabled=True,
        provider="ollama",
        base_url="http://pi.local:11434",
        api_key="",
        model="qwen2.5:3b-instruct",
    )
    client = OpenWebUIClient(config, transport=httpx.MockTransport(handler))

    result = await client.complete_json(
        [
            {"role": "system", "content": "Return JSON."},
            {"role": "user", "content": "Summarize AAPL."},
        ]
    )

    assert result["summary"] == "Direct Ollama JSON works."
    assert requests == [
        {
            "method": "POST",
            "url": "http://pi.local:11434/api/chat",
            "auth": None,
            "payload": {
                "model": "qwen2.5:3b-instruct",
                "messages": [
                    {"role": "system", "content": "Return JSON."},
                    {"role": "user", "content": "Summarize AAPL."},
                ],
                "stream": False,
                "think": False,
                "format": "json",
                "options": {
                    "temperature": 0,
                    "num_predict": 260,
                    "num_ctx": 2048,
                },
            },
        }
    ]


def test_local_llm_config_uses_longer_default_timeout_for_direct_ollama(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_LOCAL_LLM_ENABLED", "true")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_BASE_URL", "http://pi.local:11434")
    monkeypatch.setenv("AGENCY_LOCAL_LLM_MODEL", "qwen3.5:4b")
    monkeypatch.delenv("AGENCY_LOCAL_LLM_TIMEOUT_SECONDS", raising=False)

    config = LocalLlmConfig.from_env()

    assert config.timeout_seconds == 180.0


async def test_generate_local_llm_insights_writes_shadow_artifact(tmp_path: Path) -> None:
    input_root = _runtime_input_root(tmp_path)
    output_root = tmp_path / "local-llm"
    provider = _FakeProvider(
        {
            "summary": "AAPL has confirmed evidence but needs volume follow-through.",
            "bullish_case": ["Positive deterministic score"],
            "bearish_case": ["Bearish context signal remains"],
            "what_changed": ["Email evidence synced"],
            "user_checks": ["Check data freshness"],
            "contradictions": ["Bullish action with bearish context"],
            "confidence": 0.71,
        }
    )

    result = await generate_local_llm_insights(
        input_root=input_root,
        output_root=output_root,
        config=LocalLlmConfig(
            enabled=True,
            base_url="http://pi.local:3000",
            api_key="local-key",
            model="qwen2.5:7b",
        ),
        provider=provider,
        tickers=["AAPL"],
    )

    assert result["status"] == "completed"
    assert result["mode"] == "shadow"
    assert result["ticker_count"] == 1
    assert provider.call_count == 1
    artifact = json.loads((output_root / "local-llm-insights.json").read_text())
    assert artifact["insights"][0]["ticker"] == "AAPL"
    assert artifact["insights"][0]["summary"] == (
        "AAPL has confirmed evidence but needs volume follow-through."
    )
    assert artifact["insights"][0]["can_affect_trade_gates"] is False


async def test_generate_local_llm_insights_disabled_writes_status_without_calls(
    tmp_path: Path,
) -> None:
    input_root = _runtime_input_root(tmp_path)
    output_root = tmp_path / "local-llm"
    provider = _FakeProvider({})

    result = await generate_local_llm_insights(
        input_root=input_root,
        output_root=output_root,
        config=LocalLlmConfig(enabled=False),
        provider=provider,
    )

    assert result["status"] == "disabled"
    assert provider.call_count == 0
    artifact = json.loads((output_root / "local-llm-insights.json").read_text())
    assert artifact["status"] == "disabled"
    assert artifact["insights"] == []


async def test_generate_local_llm_insights_marks_artifact_failed_when_all_tickers_fail(
    tmp_path: Path,
) -> None:
    input_root = _runtime_input_root(tmp_path)
    output_root = tmp_path / "local-llm"
    provider = _FailingProvider(RuntimeError("model timed out"))

    result = await generate_local_llm_insights(
        input_root=input_root,
        output_root=output_root,
        config=LocalLlmConfig(
            enabled=True,
            base_url="http://pi.local:3000",
            api_key="local-key",
            model="qwen3.5:4b",
        ),
        provider=provider,
        tickers=["AAPL"],
    )

    assert result["status"] == "failed"
    assert result["status_class"] == "block"
    assert result["status_label"] == "Local LLM insights failed"
    assert result["detail"] == (
        "Generated 0/1 local LLM ticker insight(s); all requested insights failed."
    )
    artifact = json.loads((output_root / "local-llm-insights.json").read_text())
    assert artifact["status"] == "failed"
    assert artifact["insights"][0]["status"] == "failed"


async def test_check_local_llm_health_reports_not_configured_without_network() -> None:
    result = await check_local_llm_health(
        config=LocalLlmConfig(enabled=True, base_url="", api_key="", model="")
    )

    assert result["status"] == "not_configured"
    assert result["reachable"] is False


async def test_check_local_llm_health_uses_openwebui_models_endpoint() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={"data": [{"id": "qwen2.5:7b"}]})

    config = LocalLlmConfig(
        enabled=True,
        base_url="http://pi.local:3000/api",
        api_key="local-key",
        model="qwen2.5:7b",
    )
    client = OpenWebUIClient(config, transport=httpx.MockTransport(handler))

    result = await check_local_llm_health(config=config, client=client)

    assert result["status"] == "ready"
    assert result["reachable"] is True
    assert result["model_count"] == 1
    assert requests == ["http://pi.local:3000/api/models"]


async def test_check_local_llm_health_reports_direct_ollama_detail() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b-instruct"}]})

    config = LocalLlmConfig(
        enabled=True,
        provider="ollama",
        base_url="http://pi.local:11434",
        api_key="",
        model="qwen2.5:3b-instruct",
    )
    client = OpenWebUIClient(config, transport=httpx.MockTransport(handler))

    result = await check_local_llm_health(config=config, client=client)

    assert result["status"] == "ready"
    assert result["status_label"] == "Direct Ollama reachable"
    assert result["detail"] == "Direct Ollama responded to the local model health check."
    assert result["model_count"] == 1
    assert requests == ["http://pi.local:11434/api/tags"]


def _runtime_input_root(tmp_path: Path) -> Path:
    input_root = tmp_path / "runtime"
    input_root.mkdir()
    evidence_pack = {
        "ticker": "AAPL",
        "generated_at": "2026-05-28T08:00:00+00:00",
        "actionable_signals": [
            {
                "lane": "technical_analysis",
                "direction": "BULLISH",
                "score": 0.72,
                "confidence": 0.8,
                "reason_codes": ["trend_confirmed"],
            }
        ],
        "context_signals": [
            {
                "lane": "subscription_thesis",
                "direction": "BEARISH",
                "score": -0.2,
                "confidence": 0.55,
                "reason_codes": ["article_risk"],
            }
        ],
    }
    selection_report = {
        "ticker": "AAPL",
        "cycle_id": "cycle-1",
        "final_action": "WATCH",
        "final_conviction": 0.68,
        "deterministic": {"action": "WATCH", "reason_codes": ["trend_confirmed"]},
    }
    (input_root / "evidence-packs.json").write_text(
        json.dumps([evidence_pack]),
        encoding="utf-8",
    )
    (input_root / "selection-reports.json").write_text(
        json.dumps([selection_report]),
        encoding="utf-8",
    )
    return input_root


class _FakeProvider:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.call_count = 0

    async def complete_json(self, messages: list[dict[str, str]]) -> dict[str, object]:
        self.call_count += 1
        assert messages[0]["role"] == "system"
        assert "advisory" in messages[0]["content"].lower()
        assert "AAPL" in messages[1]["content"]
        return dict(self.payload)


class _FailingProvider:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    async def complete_json(self, _messages: list[dict[str, str]]) -> dict[str, object]:
        raise self.exc
