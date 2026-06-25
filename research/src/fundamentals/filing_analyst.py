from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-4o-mini"

_SYSTEM_PROMPT = """You are a financial analyst reviewing SEC filings.
Respond ONLY with a single valid JSON object — no markdown, no commentary.
The JSON must have exactly these keys:
  sentiment: "BULLISH" | "BEARISH" | "NEUTRAL"
  confidence: float 0.0–1.0
  eps_vs_estimate: "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN"
  revenue_vs_estimate: "BEAT" | "MISS" | "IN_LINE" | "UNKNOWN"
  guidance_change: "RAISED" | "LOWERED" | "MAINTAINED" | "NONE" | "UNKNOWN"
  key_positives: list of at most 3 short strings
  key_risks: list of at most 3 short strings
  headline_sentence: one sentence summary for an operator reviewing a trade candidate
"""


@dataclass
class FilingAnalysis:
    ticker: str
    form: str
    filing_date: str
    report_date: str | None
    sentiment: str = "NEUTRAL"
    confidence: float = 0.0
    eps_vs_estimate: str = "UNKNOWN"
    revenue_vs_estimate: str = "UNKNOWN"
    guidance_change: str = "UNKNOWN"
    key_positives: list[str] = field(default_factory=list)
    key_risks: list[str] = field(default_factory=list)
    headline_sentence: str = ""
    llm_available: bool = False
    analyzed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def signal_score(self) -> float:
        """Map sentiment + confidence to a numeric score in [−1, +1]."""
        base = {"BULLISH": 1.0, "BEARISH": -1.0, "NEUTRAL": 0.0}.get(self.sentiment, 0.0)
        return base * max(0.1, self.confidence)


class FilingAnalyst:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = MODEL,
        max_text_chars: int = 8_000,
    ) -> None:
        self._api_key = api_key or ""
        self._model = model
        self._max_text_chars = max_text_chars

    def analyze(self, filing: Any, extract: Any) -> FilingAnalysis:
        """Analyze a filing extract. Never raises."""
        stub = FilingAnalysis(
            ticker=str(getattr(filing, "ticker", "")),
            form=str(getattr(filing, "form", "")),
            filing_date=str(getattr(filing, "filing_date", "")),
            report_date=getattr(filing, "report_date", None),
        )

        if not self._api_key or not self._api_key.startswith("sk-"):
            return stub

        stub.llm_available = True
        text = extract.primary_text[: self._max_text_chars]
        user_prompt = (
            f"Analyze this {filing.form} SEC filing for {filing.ticker} "
            f"(report date: {filing.report_date or filing.filing_date}):\n\n{text}"
        )

        try:
            raw = self._call_openai(user_prompt)
            return self._parse_response(raw, stub)
        except Exception:
            return stub

    def _call_openai(self, user_prompt: str) -> str:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                OPENAI_CHAT_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
        choices = resp.json().get("choices", [])
        if not choices:
            return ""
        return str(choices[0].get("message", {}).get("content", ""))

    def _parse_response(self, raw: str, stub: FilingAnalysis) -> FilingAnalysis:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = clean.rsplit("```", 1)[0]
            parsed = json.loads(clean)
        except (json.JSONDecodeError, ValueError):
            return stub

        stub.sentiment = str(parsed.get("sentiment", "NEUTRAL"))
        stub.confidence = float(parsed.get("confidence", 0.0))
        stub.eps_vs_estimate = str(parsed.get("eps_vs_estimate", "UNKNOWN"))
        stub.revenue_vs_estimate = str(parsed.get("revenue_vs_estimate", "UNKNOWN"))
        stub.guidance_change = str(parsed.get("guidance_change", "UNKNOWN"))
        stub.key_positives = [str(s) for s in (parsed.get("key_positives") or [])[:3]]
        stub.key_risks = [str(s) for s in (parsed.get("key_risks") or [])[:3]]
        stub.headline_sentence = str(parsed.get("headline_sentence", ""))
        return stub
