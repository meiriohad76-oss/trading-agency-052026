from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import import_module
from typing import cast
from urllib.parse import urlsplit, urlunsplit

import httpx
from subscription_email.article_analysis import analyze_article
from subscription_email.article_types import FetchedArticle
from subscription_email.config import SubscriptionEmailConfig
from subscription_email.types import EmailRecord

from agency.runtime.local_llm import (
    LOCAL_LLM_BASE_URL_ENV,
    LOCAL_LLM_MODEL_ENV,
    LocalLlmConfig,
)
from agency.services.llm_review import looks_like_openai_api_key

OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_BASE_URL_ENV = "OPENAI_BASE_URL"
OPENAI_ARTICLE_MODEL_ENV = "OPENAI_ARTICLE_ANALYSIS_MODEL"
ARTICLE_LLM_ENABLED_ENV = "SUBSCRIPTION_EMAIL_LLM_ANALYSIS_ENABLED"
ARTICLE_LLM_PROVIDER_ENV = "SUBSCRIPTION_EMAIL_ARTICLE_LLM_PROVIDER"
DEFAULT_ARTICLE_MODEL = "gpt-5-nano"
PROMPT_CLASS = "subscription-email-article-analysis-v1"
MAX_BODY_CONTEXT_CHARS = 1600
MAX_ARTICLE_LLM_BODY_CHARS = 5_000
MAX_LOCAL_OLLAMA_ARTICLE_CHARS = 900
MAX_TEXT_ITEM_CHARS = 360
MAX_ITEMS = 6
HTTP_BAD_REQUEST = 400
HIGH_CONFIDENCE_THRESHOLD = 0.75
MEDIUM_CONFIDENCE_THRESHOLD = 0.45

ALLOWED_DIRECTIONS = {"BULLISH", "BEARISH", "NEUTRAL"}
ALLOWED_STRENGTHS = {"low", "medium", "high"}
ALLOWED_CATALYSTS = {
    "analyst_rating",
    "earnings",
    "quant_rating",
    "rank_change",
    "unusual_activity",
}
ALLOWED_RISKS = {
    "execution",
    "legal_or_regulatory",
    "macro",
    "negative_revision",
    "valuation",
}


@dataclass(frozen=True)
class ArticleLlmAnalyzer:
    """OpenAI-backed article thesis analyzer with deterministic fallback."""

    api_key: str | None
    model: str
    enabled: bool
    base_url: str = "https://api.openai.com/v1"
    provider: str = "openai"
    timeout_seconds: int = 45

    @classmethod
    def from_config(cls, config: SubscriptionEmailConfig) -> ArticleLlmAnalyzer:
        provider = (
            os.environ.get(ARTICLE_LLM_PROVIDER_ENV)
            or config.article_llm_provider
            or "openai"
        ).strip().lower()
        if provider == "local_ollama":
            local_config = LocalLlmConfig.from_env()
            model = os.environ.get(LOCAL_LLM_MODEL_ENV, "").strip() or config.article_llm_model
            timeout_seconds = max(
                config.article_llm_timeout_seconds,
                int(local_config.timeout_seconds),
            )
            return cls(
                api_key=None,
                model=model.strip() or local_config.model,
                enabled=(
                    config.article_llm_analysis_enabled
                    or _env_flag(ARTICLE_LLM_ENABLED_ENV)
                ),
                base_url=local_config.base_url,
                provider=provider,
                timeout_seconds=max(1, timeout_seconds),
            )
        model = (
            os.environ.get(OPENAI_ARTICLE_MODEL_ENV)
            or config.article_llm_model
            or DEFAULT_ARTICLE_MODEL
        )
        return cls(
            api_key=_blank_to_none(os.environ.get(OPENAI_API_KEY_ENV)),
            model=model.strip() or DEFAULT_ARTICLE_MODEL,
            enabled=config.article_llm_analysis_enabled or _env_flag(ARTICLE_LLM_ENABLED_ENV),
            base_url=os.environ.get(OPENAI_BASE_URL_ENV, "https://api.openai.com/v1").rstrip("/"),
            provider=provider,
            timeout_seconds=config.article_llm_timeout_seconds,
        )

    def analyze(
        self,
        page: FetchedArticle,
        *,
        config: SubscriptionEmailConfig,
        record: EmailRecord,
    ) -> dict[str, object]:
        fallback = analyze_article(page, config=config)
        if not self.enabled:
            return fallback
        if self.provider == "local_ollama":
            return self._analyze_with_local_ollama_shadow(
                page,
                config=config,
                record=record,
                fallback=fallback,
            )
        if not looks_like_openai_api_key(self.api_key):
            return _fallback_with_reason(
                fallback,
                "deterministic_keyword_fallback: openai_key_missing_or_invalid",
            )
        try:
            response = self._request(_messages(page, config=config, record=record))
            payload = _response_message_payload(response)
            return normalize_article_llm_analysis(
                payload,
                page=page,
                config=config,
                fallback=fallback,
                model=self.model,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _fallback_with_reason(
                fallback,
                f"deterministic_keyword_fallback: {_safe_error(exc)}",
            )

    def _analyze_with_local_ollama_shadow(
        self,
        page: FetchedArticle,
        *,
        config: SubscriptionEmailConfig,
        record: EmailRecord,
        fallback: Mapping[str, object],
    ) -> dict[str, object]:
        if not self.base_url.strip() or not self.model.strip():
            return _fallback_with_local_shadow_status(
                fallback,
                provider="local_ollama",
                model=self.model,
                status="not_configured",
                error=(
                    f"Set {LOCAL_LLM_BASE_URL_ENV} and {LOCAL_LLM_MODEL_ENV} "
                    "before running local article analysis."
                ),
            )
        try:
            payload = self._request_local_ollama(
                _local_ollama_messages(page, config=config, record=record)
            )
            shadow = normalize_article_llm_analysis(
                payload,
                page=page,
                config=config,
                fallback=fallback,
                model=self.model,
                provider="local_ollama",
            )
            return _fallback_with_local_shadow_analysis(fallback, shadow)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return _fallback_with_local_shadow_status(
                fallback,
                provider="local_ollama",
                model=self.model,
                status="failed",
                error=_safe_error(exc),
            )

    def _request(self, messages: list[dict[str, str]]) -> Mapping[str, object]:
        payload = _chat_payload(self.model, messages, use_completion_tokens=True)
        with httpx.Client(timeout=self.timeout_seconds, verify=_verify_context()) as client:
            response = client.post(
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
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=_chat_payload(self.model, messages, use_completion_tokens=False),
                )
            response.raise_for_status()
            return cast(Mapping[str, object], response.json())

    def _request_local_ollama(self, messages: list[dict[str, str]]) -> Mapping[str, object]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {
                "temperature": 0,
                "num_predict": 260,
                "num_ctx": 3072,
            },
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                _ollama_chat_url(self.base_url),
                headers={"Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            return _local_ollama_response_payload(response.json())


def analyze_article_with_optional_llm(
    page: FetchedArticle,
    *,
    config: SubscriptionEmailConfig,
    record: EmailRecord,
) -> dict[str, object]:
    return ArticleLlmAnalyzer.from_config(config).analyze(page, config=config, record=record)


def normalize_article_llm_analysis(
    payload: Mapping[str, object],
    *,
    page: FetchedArticle,
    config: SubscriptionEmailConfig,
    fallback: Mapping[str, object],
    model: str,
    provider: str = "openai",
) -> dict[str, object]:
    direction = _choice(str(payload.get("direction", "")), ALLOWED_DIRECTIONS)
    tickers = _configured_tickers(payload.get("tickers"), config)
    catalysts = _allowed_items(payload.get("catalysts"), ALLOWED_CATALYSTS)
    risks = _allowed_items(payload.get("risk_flags"), ALLOWED_RISKS)
    key_points = _string_items(payload.get("key_points"))
    thesis = _sentence_fragment(_text(payload.get("thesis"), MAX_TEXT_ITEM_CHARS))
    decision_use = _sentence_fragment(_text(payload.get("decision_use"), MAX_TEXT_ITEM_CHARS))
    strength = _choice(str(payload.get("signal_strength", "")), ALLOWED_STRENGTHS)
    confidence = _confidence(payload.get("confidence"), strength=strength)
    output = {
        **dict(fallback),
        "status": "article_analyzed",
        "url": _normalize_url(page.url),
        "direction": direction or fallback.get("direction", "NEUTRAL"),
        "tickers": tickers or _string_items(fallback.get("tickers")),
        "catalysts": catalysts or _string_items(fallback.get("catalysts")),
        "risk_flags": risks or _string_items(fallback.get("risk_flags")),
        "key_points": key_points or _string_items(fallback.get("key_points")),
        "thesis": thesis or str(fallback.get("thesis", "")),
        "decision_use": decision_use or str(fallback.get("decision_use", "")),
        "signal_strength": strength or _strength_from_confidence(confidence),
        "confidence": confidence,
        "context_source": _analysis_identity(model, provider=provider),
        "context_chars": len(" ".join(page.text[: config.article_max_chars].split())),
        "status_code": int(page.status_code),
        "title_hash": _hash(page.title or ""),
        "text_hash": _hash(" ".join(page.text[: config.article_max_chars].split())),
    }
    if output["signal_strength"] not in ALLOWED_STRENGTHS:
        fallback_strength = fallback.get("signal_strength")
        output["signal_strength"] = (
            fallback_strength if fallback_strength in ALLOWED_STRENGTHS else "low"
        )
    return output


def _messages(
    page: FetchedArticle,
    *,
    config: SubscriptionEmailConfig,
    record: EmailRecord,
) -> list[dict[str, str]]:
    prompt = _article_prompt(page, config=config, record=record)
    return [
        {
            "role": "system",
            "content": (
                "You are a supervised equity-research article analyst. "
                "You produce concise ticker-specific evidence summaries for a "
                "paper-trading research workflow."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=True, sort_keys=True)},
    ]


def _local_ollama_messages(
    page: FetchedArticle,
    *,
    config: SubscriptionEmailConfig,
    record: EmailRecord,
) -> list[dict[str, str]]:
    prompt = _local_ollama_article_prompt(page, config=config, record=record)
    return [
        {
            "role": "system",
            "content": (
                "You are a shadow-only local article analyst for a supervised "
                "paper-trading workflow. Return one compact valid JSON object only. "
                "Keys: direction, confidence, tickers, thesis, key_points, catalysts, "
                "risk_flags, decision_use, signal_strength. You cannot approve trades, "
                "block trades, change gates, or feed subscription_thesis."
            ),
        },
        {"role": "user", "content": json.dumps(prompt, ensure_ascii=True, sort_keys=True)},
    ]


def _local_ollama_article_prompt(
    page: FetchedArticle,
    *,
    config: SubscriptionEmailConfig,
    record: EmailRecord,
) -> dict[str, object]:
    article_text = _clip(page.text, MAX_LOCAL_OLLAMA_ARTICLE_CHARS)
    return {
        "task": PROMPT_CLASS,
        "shadow_only": True,
        "configured_tickers": list(config.tickers),
        "email_subject": _clip(record.subject, 180),
        "article_title": _clip(page.title or "", 180),
        "article_text": article_text,
        "body_characters_original": len(page.text),
        "body_truncated": len(article_text) < len(page.text),
        "allowed": {
            "direction": sorted(ALLOWED_DIRECTIONS),
            "catalysts": sorted(ALLOWED_CATALYSTS),
            "risk_flags": sorted(ALLOWED_RISKS),
            "signal_strength": sorted(ALLOWED_STRENGTHS),
        },
        "rules": [
            "Use only configured_tickers.",
            "Use concise ticker-specific wording.",
            "No trading instruction.",
            "JSON only.",
        ],
    }


def _article_prompt(
    page: FetchedArticle,
    *,
    config: SubscriptionEmailConfig,
    record: EmailRecord,
    body_limit: int | None = None,
) -> dict[str, object]:
    article_text = _clip(page.text, body_limit or _article_body_limit(config))
    return {
        "task": PROMPT_CLASS,
        "guardrails": [
            "Summarize and reason over only the provided email/article text.",
            "Do not give trading instructions or execution advice.",
            "Tie every conclusion to the tickers detected in the configured universe.",
            "Do not copy long excerpts; summarize in your own words.",
        ],
        "configured_tickers": list(config.tickers),
        "email": {
            "sender_domain": record.sender_domain,
            "subject": _clip(record.subject, 240),
            "body_context": _clip(_redact_urls(record.body_text), MAX_BODY_CONTEXT_CHARS),
        },
        "article": {
            "url_domain": urlsplit(page.url).netloc.lower(),
            "title": _clip(page.title or "", 240),
            "status_code": page.status_code,
            "text": article_text,
            "body_characters_original": len(page.text),
            "body_truncated": len(article_text) < len(page.text),
        },
        "required_response": {
            "direction": "BULLISH, BEARISH, or NEUTRAL for the focused ticker context",
            "confidence": "number from 0 to 1",
            "tickers": "configured tickers that the article materially discusses",
            "thesis": "specific ticker-focused thesis, not a generic category",
            "key_points": "specific facts/arguments that matter to the ticker",
            "catalysts": sorted(ALLOWED_CATALYSTS),
            "risk_flags": sorted(ALLOWED_RISKS),
            "decision_use": "how the agency should use this evidence",
            "signal_strength": "low, medium, or high",
        },
    }


def _article_body_limit(config: SubscriptionEmailConfig) -> int:
    return min(config.article_max_chars, MAX_ARTICLE_LLM_BODY_CHARS)


def _chat_payload(
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
                "name": "subscription_article_analysis",
                "strict": True,
                "schema": _response_schema(),
            },
        },
    }
    payload["max_completion_tokens" if use_completion_tokens else "max_tokens"] = 900
    return payload


def _response_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "direction",
            "confidence",
            "tickers",
            "thesis",
            "key_points",
            "catalysts",
            "risk_flags",
            "decision_use",
            "signal_strength",
        ],
        "properties": {
            "direction": {"type": "string", "enum": sorted(ALLOWED_DIRECTIONS)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "tickers": {"type": "array", "items": {"type": "string"}},
            "thesis": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "catalysts": {"type": "array", "items": {"type": "string"}},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
            "decision_use": {"type": "string"},
            "signal_strength": {"type": "string", "enum": sorted(ALLOWED_STRENGTHS)},
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
        raise TypeError("article analysis JSON must be an object")
    return cast(Mapping[str, object], payload)


def _fallback_with_reason(
    fallback: Mapping[str, object],
    reason: str,
) -> dict[str, object]:
    output = dict(fallback)
    output["status"] = "article_analyzed_deterministic_fallback"
    output["context_source"] = reason
    key_points = _string_items(output.get("key_points"))
    output["key_points"] = [*key_points, "LLM article analysis was unavailable"][:MAX_ITEMS]
    return output


def _fallback_with_local_shadow_analysis(
    fallback: Mapping[str, object],
    shadow: Mapping[str, object],
) -> dict[str, object]:
    output = dict(fallback)
    output.update(
        {
            "local_llm_article_status": "completed",
            "local_llm_article_provider": "local_ollama",
            "local_llm_article_model": _local_shadow_model(shadow.get("context_source")),
            "local_llm_article_context_source": _string(shadow.get("context_source")),
            "local_llm_article_direction": _string(shadow.get("direction")),
            "local_llm_article_confidence": _float(shadow.get("confidence")),
            "local_llm_article_tickers": _string_items(shadow.get("tickers")),
            "local_llm_article_thesis": _string(shadow.get("thesis")),
            "local_llm_article_key_points": _string_items(shadow.get("key_points")),
            "local_llm_article_catalysts": _string_items(shadow.get("catalysts")),
            "local_llm_article_risk_flags": _string_items(shadow.get("risk_flags")),
            "local_llm_article_decision_use": _string(shadow.get("decision_use")),
            "local_llm_article_signal_strength": _string(shadow.get("signal_strength")),
            "local_llm_article_comparison": _local_shadow_comparison(fallback, shadow),
            "local_llm_article_can_affect_trade_gates": False,
        }
    )
    return output


def _fallback_with_local_shadow_status(
    fallback: Mapping[str, object],
    *,
    provider: str,
    model: str,
    status: str,
    error: str,
) -> dict[str, object]:
    output = dict(fallback)
    output.update(
        {
            "local_llm_article_status": status,
            "local_llm_article_provider": provider,
            "local_llm_article_model": model,
            "local_llm_article_context_source": _analysis_identity(
                model,
                provider="local_ollama",
            )
            if model
            else "",
            "local_llm_article_error": _clip(error, MAX_TEXT_ITEM_CHARS),
            "local_llm_article_comparison": (
                "Local LLM article read was unavailable; deterministic article "
                "analysis remains the only scored evidence."
            ),
            "local_llm_article_can_affect_trade_gates": False,
        }
    )
    return output


def _local_shadow_comparison(
    fallback: Mapping[str, object],
    shadow: Mapping[str, object],
) -> str:
    deterministic = _direction_text(fallback.get("direction"))
    local = _direction_text(shadow.get("direction"))
    confidence = _float(shadow.get("confidence"))
    confidence_text = f" at {round(confidence * 100)}% confidence" if confidence else ""
    if deterministic == local:
        return f"Local LLM agrees with deterministic direction {deterministic}{confidence_text}."
    if local == "NEUTRAL" and deterministic != "NEUTRAL":
        return (
            f"Local LLM is neutral while deterministic direction is {deterministic}"
            f"{confidence_text}."
        )
    if deterministic == "NEUTRAL" and local != "NEUTRAL":
        return (
            f"Local LLM sees {local} context while deterministic direction is NEUTRAL"
            f"{confidence_text}."
        )
    return (
        f"Local LLM disagrees: deterministic direction {deterministic}, "
        f"local direction {local}{confidence_text}."
    )


def _local_shadow_model(context_source: object) -> str:
    context = _string(context_source)
    prefix = "local_ollama_article_analysis:"
    suffix = f":{PROMPT_CLASS}"
    if not context.startswith(prefix) or not context.endswith(suffix):
        return ""
    return context[len(prefix) : -len(suffix)]


def _direction_text(value: object) -> str:
    text = _string(value).upper()
    return text if text in ALLOWED_DIRECTIONS else "NEUTRAL"


def _configured_tickers(value: object, config: SubscriptionEmailConfig) -> list[str]:
    configured = {ticker.upper() for ticker in config.tickers}
    output: list[str] = []
    for item in _string_items(value):
        ticker = item.upper().lstrip("$")
        if ticker in configured:
            output.append(ticker)
    return output


def _allowed_items(value: object, allowed: set[str]) -> list[str]:
    return [item for item in _string_items(value) if item in allowed][:MAX_ITEMS]


def _string_items(value: object) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list | tuple):
        values = [item for item in value if isinstance(item, str)]
    else:
        values = []
    return [_clip(item, MAX_TEXT_ITEM_CHARS).rstrip(" .") for item in values if item.strip()][
        :MAX_ITEMS
    ]


def _choice(value: str, allowed: set[str]) -> str | None:
    normalized = value.strip()
    if normalized.upper() in allowed:
        return normalized.upper()
    if normalized.lower() in allowed:
        return normalized.lower()
    return None


def _text(value: object, max_chars: int) -> str | None:
    if not isinstance(value, str):
        return None
    clipped = _clip(value, max_chars)
    return clipped or None


def _sentence_fragment(value: str | None) -> str | None:
    if value is None:
        return None
    return value.rstrip(" .")


def _clip(value: str, max_chars: int) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _float(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int | float):
        parsed = float(value)
    elif isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return 0.0
    else:
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return max(0.0, min(1.0, parsed))


def _confidence(value: object, *, strength: str | None) -> float:
    parsed = _float(value)
    if parsed > 0.0 or _looks_like_numeric_zero(value):
        return parsed
    return {
        "high": 0.8,
        "medium": 0.55,
        "low": 0.3,
    }.get(str(strength or "").lower(), 0.0)


def _looks_like_numeric_zero(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return float(value) == 0.0
    if isinstance(value, str):
        try:
            return float(value.strip()) == 0.0
        except ValueError:
            return False
    return False


def _strength_from_confidence(confidence: float) -> str:
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "high"
    if confidence >= MEDIUM_CONFIDENCE_THRESHOLD:
        return "medium"
    return "low"


def _normalize_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ""))


def _analysis_identity(model: str, *, provider: str = "openai") -> str:
    prefix = "local_ollama_article_analysis" if provider == "local_ollama" else "openai_llm_article_analysis"
    return f"{prefix}:{model}:{PROMPT_CLASS}"


def _local_ollama_response_payload(response: Mapping[str, object]) -> Mapping[str, object]:
    message = response["message"]
    if not isinstance(message, Mapping):
        raise TypeError("Ollama message must be an object")
    content = message["content"]
    if not isinstance(content, str):
        raise TypeError("Ollama message content must be text")
    return _json_object_from_text(content)


def _json_object_from_text(content: str) -> Mapping[str, object]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        if start < 0:
            raise
        payload, _end = json.JSONDecoder().raw_decode(content[start:])
    if not isinstance(payload, Mapping):
        raise TypeError("article analysis JSON must be an object")
    return cast(Mapping[str, object], payload)


def _ollama_chat_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    if not base:
        return ""
    parsed = urlsplit(base)
    path = parsed.path.rstrip("/")
    if path.endswith("/api/chat") or path == "/api/chat":
        return base
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/api/chat", "", ""))


def _string(value: object) -> str:
    return value if isinstance(value, str) and value else ""


def _redact_urls(value: str) -> str:
    return re.sub(r"https?://[^\s<>)\"]+", "[url redacted]", value)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _blank_to_none(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    api_key = os.environ.get(OPENAI_API_KEY_ENV, "").strip()
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    return _clip(text, 160)


def _verify_context() -> ssl.SSLContext | bool:
    if sys.platform != "win32":
        return True
    try:
        truststore = import_module("truststore")
    except ModuleNotFoundError:
        return True
    context_factory = cast(type[ssl.SSLContext], truststore.SSLContext)
    return context_factory(ssl.PROTOCOL_TLS_CLIENT)
