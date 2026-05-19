from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agency.services import (  # noqa: E402
    OpenAILlmReviewProvider,
    build_evidence_pack,
    build_signal_result,
    looks_like_openai_api_key,
)
from agency.services.llm_review import classify_openai_error  # noqa: E402

DEFAULT_OUTPUT_ROOT = ROOT / "research" / "results" / "latest-openai-llm-check"


async def check_openai_llm_review(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    env_path: Path = ROOT / ".env",
    model: str | None = None,
    base_url: str | None = None,
    provider: OpenAILlmReviewProvider | None = None,
) -> dict[str, object]:
    """Run a tiny no-secret live LLM review diagnostic and write a local report."""
    if provider is None:
        load_dotenv(env_path, override=True)
    active_provider = provider or OpenAILlmReviewProvider.from_env(enabled=True)
    if model is not None:
        active_provider = replace(active_provider, model=model)
    if base_url is not None:
        active_provider = replace(active_provider, base_url=base_url.rstrip("/"))

    checked_at = datetime.now(UTC).isoformat()
    key_info = redacted_openai_key_info(active_provider.api_key)
    if active_provider.api_key is None:
        summary = _summary(
            checked_at=checked_at,
            ready=False,
            status="missing_api_key",
            provider=active_provider,
            key_info=key_info,
            error="OPENAI_API_KEY is not configured.",
        )
        write_openai_check_report(summary, output_root)
        return summary

    if key_info["looks_like_openai_key"] is not True:
        summary = _summary(
            checked_at=checked_at,
            ready=False,
            status="invalid_key_shape",
            provider=active_provider,
            key_info=key_info,
            error="OPENAI_API_KEY is present but does not look like an OpenAI platform key.",
        )
        write_openai_check_report(summary, output_root)
        return summary

    try:
        result = await active_provider.review(
            _sample_evidence_pack(checked_at),
            {
                "action": "WATCH",
                "score": 0.65,
                "conviction": 0.55,
                "reason_codes": ["diagnostic_watch_candidate"],
                "blockers": [],
            },
        )
    except Exception as exc:  # pragma: no cover - provider normally fails safely.
        error_info = classify_openai_error(exc)
        summary = _summary(
            checked_at=checked_at,
            ready=False,
            status=error_info.category,
            provider=active_provider,
            key_info=key_info,
            error=error_info.detail,
            http_status=error_info.http_status,
            retryable=error_info.retryable,
        )
        write_openai_check_report(summary, output_root)
        return summary

    if result.prompt_audit is None:
        summary = _summary(
            checked_at=checked_at,
            ready=False,
            status="missing_prompt_audit",
            provider=active_provider,
            key_info=key_info,
            error="Provider returned no prompt audit.",
        )
        write_openai_check_report(summary, output_root)
        return summary

    payload = cast(Mapping[str, object], result.prompt_audit["payload"])
    status = str(payload.get("response_status", "unknown"))
    summary = _summary(
        checked_at=checked_at,
        ready=status == "succeeded",
        status=status,
        provider=active_provider,
        key_info=key_info,
        error=_optional_text(payload.get("error")),
        http_status=_optional_int(payload.get("http_status")),
        llm_action=_optional_text(payload.get("llm_action")),
        llm_confidence=payload.get("llm_confidence"),
        retryable=payload.get("retryable") is True,
    )
    write_openai_check_report(summary, output_root)
    return summary


def redacted_openai_key_info(value: str | None) -> dict[str, object]:
    """Return safe key diagnostics without exposing the secret value."""
    if value is None or not value.strip():
        return {
            "present": False,
            "length": 0,
            "prefix": None,
            "suffix": None,
            "sha256_8": None,
            "looks_like_openai_key": False,
        }
    cleaned = value.strip()
    return {
        "present": True,
        "length": len(cleaned),
        "prefix": cleaned[:7],
        "suffix": cleaned[-4:],
        "sha256_8": hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:8],
        "looks_like_openai_key": looks_like_openai_api_key(cleaned),
    }


def write_openai_check_report(summary: Mapping[str, object], output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "openai-llm-check.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "openai-llm-check.md").write_text(_markdown(summary), encoding="utf-8")


def _summary(
    *,
    checked_at: str,
    ready: bool,
    status: str,
    provider: OpenAILlmReviewProvider,
    key_info: Mapping[str, object],
    error: str | None,
    http_status: int | None = None,
    retryable: bool = False,
    llm_action: str | None = None,
    llm_confidence: object = None,
) -> dict[str, object]:
    return {
        "schema_version": "0.1.0",
        "checked_at": checked_at,
        "ready": ready,
        "status": status,
        "status_label": _status_label(status),
        "model": provider.model,
        "base_url": provider.base_url,
        "api_key": dict(key_info),
        "http_status": http_status,
        "retryable": retryable,
        "llm_action": llm_action,
        "llm_confidence": llm_confidence,
        "error": error,
        "next_action": _next_action(status),
    }


def _sample_evidence_pack(generated_at: str) -> dict[str, object]:
    provenance = {
        "source": "diagnostic",
        "source_tier": "OFFICIAL_FILING",
        "source_id": "openai-llm-check",
        "source_url": None,
        "timestamp_observed": generated_at,
        "timestamp_as_of": generated_at,
        "freshness": "FRESH",
        "confidence": 1.0,
        "verification_level": "CONFIRMED",
    }
    return build_evidence_pack(
        cycle_id="openai-llm-check",
        ticker="AAPL",
        as_of=generated_at,
        generated_at=generated_at,
        signals=[
            build_signal_result(
                cycle_id="openai-llm-check",
                ticker="AAPL",
                as_of=generated_at,
                lane="fundamentals",
                score=0.62,
                provenance=provenance,
                confidence=0.8,
                summary="Diagnostic evidence pack for validating supervised LLM review.",
            )
        ],
    )


def _markdown(summary: Mapping[str, object]) -> str:
    key_info = cast(Mapping[str, object], summary["api_key"])
    rows = [
        ("Verdict", "ready" if summary["ready"] is True else "attention"),
        ("Status", str(summary["status"])),
        ("Model", str(summary["model"])),
        ("Base URL", str(summary["base_url"])),
        ("Key present", str(key_info["present"])),
        ("Key length", str(key_info["length"])),
        ("Key prefix", str(key_info["prefix"])),
        ("Key suffix", str(key_info["suffix"])),
        ("Key hash", str(key_info["sha256_8"])),
        ("HTTP status", str(summary["http_status"])),
        ("Retryable", str(summary["retryable"])),
        ("Next action", str(summary["next_action"])),
    ]
    table = "\n".join(f"| {label} | {value} |" for label, value in rows)
    error = str(summary.get("error") or "None")
    return (
        "# OpenAI LLM Review Check\n\n"
        f"Checked at: `{summary['checked_at']}`\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        f"{table}\n\n"
        f"Error: `{error}`\n"
    )


def _status_label(status: str) -> str:
    return {
        "succeeded": "Ready",
        "missing_api_key": "Missing API key",
        "invalid_key_shape": "Invalid API key shape",
        "unauthorized": "Unauthorized API key",
        "forbidden": "Forbidden",
        "model_not_found": "Model not available",
        "rate_limited": "Rate limited",
    }.get(status, status.replace("_", " ").title())


def _next_action(status: str) -> str:
    return {
        "succeeded": "LLM review can be enabled for bounded paper cycles.",
        "missing_api_key": "Add OPENAI_API_KEY to .env.",
        "unauthorized": "Replace OPENAI_API_KEY with a valid OpenAI platform API key.",
        "invalid_key_shape": "Replace OPENAI_API_KEY with an OpenAI platform key.",
        "forbidden": "Check project, organization, model, and billing access.",
        "model_not_found": "Set OPENAI_LLM_REVIEW_MODEL to a model available to the key.",
        "rate_limited": "Wait for quota reset or lower the review candidate limit.",
    }.get(status, "Inspect openai-llm-check.json and retry after fixing configuration.")


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a no-secret OpenAI LLM review check.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--env-path", type=Path, default=ROOT / ".env")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    summary = asyncio.run(
        check_openai_llm_review(
            output_root=args.output_root,
            env_path=args.env_path,
            model=args.model,
            base_url=args.base_url,
        )
    )
    print(json.dumps(summary, sort_keys=True))
    return 1 if args.fail_on_error and summary["ready"] is not True else 0


if __name__ == "__main__":
    raise SystemExit(main())
