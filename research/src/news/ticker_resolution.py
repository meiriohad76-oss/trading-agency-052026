from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_AMBIGUOUS_SYMBOLS = frozenset(
    {
        "A",
        "C",
        "F",
        "T",
        "APP",
        "NOW",
        "ON",
        "IT",
        "ALL",
        "ARE",
        "CAN",
        "HAS",
        "KEY",
        "LOW",
        "SEE",
        "TEAM",
    }
)

_CIK_PATTERN = re.compile(r"\bCIK\s*[:#-]?\s*0*(\d{1,10})\b", re.IGNORECASE)
_SEC_ARCHIVE_CIK_PATTERN = re.compile(
    r"sec\.gov/Archives/edgar/data/0*(\d{1,10})/",
    re.IGNORECASE,
)
_DOLLAR_SYMBOL_PATTERN = re.compile(r"(?<![\w$])\$([A-Z][A-Z0-9.]{0,9})(?![A-Z0-9.])")
_EXCHANGE_SYMBOL_PATTERN = re.compile(
    r"\b((?:NASDAQ|NYSE|NYSEARCA|AMEX|ARCA|OTC|CBOE):\s*([A-Z][A-Z0-9.]{0,9}))\b"
)
_PAREN_SYMBOL_PATTERN = re.compile(r"\(([A-Z][A-Z0-9.]{0,9})\)")
_COMMON_STOCK_SUFFIX_PATTERN = re.compile(
    r"\b(class\s+[a-z]|common\s+stock|american\s+depositary\s+shares?|"
    r"depositary\s+shares?|ordinary\s+shares?|ads|adr)\b",
    re.IGNORECASE,
)
_LEGAL_SUFFIX_PATTERN = re.compile(
    r"\b(incorporated|inc|corporation|corp|company|co|plc|ltd|limited|"
    r"holdings?|holding|technologies|technology)\b\.?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TickerAlias:
    ticker: str
    cik: str | None = None
    legal_names: tuple[str, ...] = ()
    brand_aliases: tuple[str, ...] = ()
    allow_plain_brand: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.upper())
        object.__setattr__(self, "cik", _normalize_cik(self.cik))
        object.__setattr__(self, "legal_names", tuple(self.legal_names))
        object.__setattr__(self, "brand_aliases", tuple(self.brand_aliases))


@dataclass(frozen=True)
class TickerResolutionRegistry:
    aliases: tuple[TickerAlias, ...] = ()
    active_tickers: frozenset[str] = field(default_factory=frozenset)
    ambiguous_symbols: frozenset[str] = DEFAULT_AMBIGUOUS_SYMBOLS
    _aliases_by_ticker: Mapping[str, TickerAlias] = field(init=False, repr=False)
    _ticker_by_cik: Mapping[str, str] = field(init=False, repr=False)

    def __init__(
        self,
        *,
        aliases: tuple[TickerAlias, ...] | list[TickerAlias] = (),
        active_tickers: tuple[str, ...] | list[str] | set[str] | frozenset[str] = (),
        ambiguous_symbols: tuple[str, ...] | list[str] | set[str] | frozenset[str] | None = None,
    ) -> None:
        normalized_aliases = tuple(aliases)
        object.__setattr__(self, "aliases", normalized_aliases)
        object.__setattr__(self, "active_tickers", frozenset(t.upper() for t in active_tickers))
        object.__setattr__(
            self,
            "ambiguous_symbols",
            frozenset(
                symbol.upper()
                for symbol in (
                    DEFAULT_AMBIGUOUS_SYMBOLS if ambiguous_symbols is None else ambiguous_symbols
                )
            ),
        )
        object.__setattr__(
            self,
            "_aliases_by_ticker",
            {alias.ticker: alias for alias in normalized_aliases},
        )
        object.__setattr__(
            self,
            "_ticker_by_cik",
            {
                alias.cik: alias.ticker
                for alias in normalized_aliases
                if alias.cik is not None and self.is_active(alias.ticker)
            },
        )

    def is_active(self, ticker: str) -> bool:
        return not self.active_tickers or ticker.upper() in self.active_tickers

    @property
    def aliases_by_ticker(self) -> Mapping[str, TickerAlias]:
        return self._aliases_by_ticker

    @property
    def ticker_by_cik(self) -> Mapping[str, str]:
        return self._ticker_by_cik


@dataclass(frozen=True)
class TickerMatch:
    ticker: str | None
    status: str
    method: str | None
    confidence: float
    reason: str
    matched_text: str | None = None


@dataclass(frozen=True)
class ResolvedNewsRow:
    raw: Mapping[str, object]
    match: TickerMatch
    related_tickers: tuple[str, ...] = ()

    @property
    def ticker(self) -> str | None:
        return self.match.ticker

    def to_row(self) -> dict[str, object]:
        row = dict(self.raw)
        row["ticker"] = self.match.ticker
        row["ticker_match_status"] = self.match.status
        row["ticker_match_method"] = self.match.method
        row["ticker_match_confidence"] = self.match.confidence
        row["ticker_match_reason"] = self.match.reason
        row["matched_text"] = self.match.matched_text
        row["related_tickers"] = ",".join(self.related_tickers)
        row["raw_feed_ticker"] = self.raw.get("ticker")
        return row


def aliases_from_reference_details(
    path: Path,
    *,
    active_tickers: set[str] | frozenset[str] | tuple[str, ...] = (),
) -> tuple[TickerAlias, ...]:
    """Build conservative ticker aliases from locally stored Massive reference details."""
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    rows = payload.get("rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        return ()
    active = {str(ticker).upper() for ticker in active_tickers if str(ticker).strip()}
    aliases: list[TickerAlias] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ticker = _clean_text(row.get("ticker"))
        name = _clean_text(row.get("name"))
        if ticker is None or name is None:
            continue
        ticker = ticker.upper()
        if active and ticker not in active:
            continue
        brand = _brand_alias_from_company_name(name)
        aliases.append(
            TickerAlias(
                ticker=ticker,
                legal_names=(name,),
                brand_aliases=(brand,) if brand else (),
                allow_plain_brand=_plain_brand_is_safe(brand),
            )
        )
    return tuple(aliases)


def resolve_news_row(
    row: Mapping[str, object],
    registry: TickerResolutionRegistry,
) -> list[ResolvedNewsRow]:
    raw_feed_ticker = _clean_text(row.get("ticker"))
    if raw_feed_ticker:
        ticker = raw_feed_ticker.upper()
        return [
            ResolvedNewsRow(
                raw=row,
                match=TickerMatch(
                    ticker=ticker,
                    status="feed_ticker",
                    method="feed_ticker",
                    confidence=1.0,
                    reason=f"Feed provided explicit ticker {ticker}.",
                    matched_text=raw_feed_ticker,
                ),
                related_tickers=(ticker,),
            )
        ]

    text = _row_text(row)
    matches: dict[str, TickerMatch] = {}

    for match in _cik_matches(text, registry):
        matches.setdefault(match.ticker or "", match)
    for match in _market_symbol_matches(text, registry):
        matches.setdefault(match.ticker or "", match)
    for match in _alias_matches(text, registry, legal=True):
        matches.setdefault(match.ticker or "", match)
    for match in _alias_matches(text, registry, legal=False):
        matches.setdefault(match.ticker or "", match)

    ticker_matches = [match for ticker, match in matches.items() if ticker]
    if not ticker_matches:
        return [
            ResolvedNewsRow(
                raw=row,
                match=TickerMatch(
                    ticker=None,
                    status="unresolved",
                    method=None,
                    confidence=0.0,
                    reason="No high-confidence ticker match was found in the headline or summary.",
                ),
            )
        ]

    ticker_matches.sort(key=lambda match: match.ticker or "")
    related = tuple(match.ticker for match in ticker_matches if match.ticker is not None)
    return [
        ResolvedNewsRow(raw=row, match=match, related_tickers=related)
        for match in ticker_matches
    ]


def _cik_matches(text: str, registry: TickerResolutionRegistry) -> list[TickerMatch]:
    matches: list[TickerMatch] = []
    for cik in _cik_candidates(text):
        ticker = registry.ticker_by_cik.get(cik or "")
        if ticker is None:
            continue
        matches.append(
            TickerMatch(
                ticker=ticker,
                status="resolved",
                method="sec_cik",
                confidence=0.98,
                reason=f"SEC CIK {cik} matched {ticker} in the alias registry.",
                matched_text=cik,
            )
        )
    return matches


def _cik_candidates(text: str) -> list[str | None]:
    candidates: list[str | None] = []
    candidates.extend(_normalize_cik(raw_match.group(1)) for raw_match in _CIK_PATTERN.finditer(text))
    candidates.extend(
        _normalize_cik(raw_match.group(1)) for raw_match in _SEC_ARCHIVE_CIK_PATTERN.finditer(text)
    )
    return candidates


def _market_symbol_matches(text: str, registry: TickerResolutionRegistry) -> list[TickerMatch]:
    matches: list[TickerMatch] = []
    seen: set[tuple[str, str]] = set()
    for raw_text, symbol in _market_symbol_candidates(text):
        ticker = symbol.upper()
        if not registry.is_active(ticker):
            continue
        key = (ticker, raw_text)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            TickerMatch(
                ticker=ticker,
                status="resolved",
                method="market_symbol",
                confidence=0.93,
                reason=f"Market-formatted symbol {raw_text} matched active ticker {ticker}.",
                matched_text=raw_text,
            )
        )
    return matches


def _market_symbol_candidates(text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    candidates.extend(
        (match.group(0), match.group(1))
        for match in _DOLLAR_SYMBOL_PATTERN.finditer(text)
    )
    candidates.extend(
        (match.group(1).replace(" ", ""), match.group(2))
        for match in _EXCHANGE_SYMBOL_PATTERN.finditer(text)
    )
    candidates.extend(
        (match.group(0), match.group(1))
        for match in _PAREN_SYMBOL_PATTERN.finditer(text)
    )
    return candidates


def _alias_matches(
    text: str,
    registry: TickerResolutionRegistry,
    *,
    legal: bool,
) -> list[TickerMatch]:
    matches: list[TickerMatch] = []
    for alias in registry.aliases:
        if not registry.is_active(alias.ticker):
            continue
        names = alias.legal_names if legal else alias.brand_aliases
        if not legal and not alias.allow_plain_brand:
            continue
        for name in names:
            matched = _find_alias(text, name)
            if matched is None:
                continue
            method = "legal_name" if legal else "brand_alias"
            confidence = 0.88 if legal else 0.78
            reason = (
                f"Legal-name alias {matched!r} matched {alias.ticker}."
                if legal
                else f"Configured brand alias {matched!r} matched {alias.ticker}."
            )
            matches.append(
                TickerMatch(
                    ticker=alias.ticker,
                    status="resolved",
                    method=method,
                    confidence=confidence,
                    reason=reason,
                    matched_text=matched,
                )
            )
            break
    return matches


def _find_alias(text: str, alias: str) -> str | None:
    cleaned = alias.strip()
    if not cleaned:
        return None
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(cleaned)}(?![A-Za-z0-9])", re.IGNORECASE)
    match = pattern.search(text)
    return match.group(0) if match else None


def _row_text(row: Mapping[str, object]) -> str:
    return " ".join(
        value
        for value in (
            _clean_text(row.get("title")),
            _clean_text(row.get("summary")),
            _clean_text(row.get("url")),
        )
        if value
    )


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _brand_alias_from_company_name(name: str) -> str | None:
    cleaned = _COMMON_STOCK_SUFFIX_PATTERN.sub(" ", name)
    cleaned = _LEGAL_SUFFIX_PATTERN.sub(" ", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9&'. -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    if not cleaned:
        return None
    words = cleaned.split()
    if len(words) > 3:
        cleaned = " ".join(words[:3])
    return cleaned or None


def _plain_brand_is_safe(brand: str | None) -> bool:
    if brand is None:
        return False
    normalized = brand.upper().replace(".", "")
    if len(normalized) < 4:
        return False
    return normalized not in DEFAULT_AMBIGUOUS_SYMBOLS


def _normalize_cik(value: str | None) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"\D", "", value)
    if not digits:
        return None
    return digits.zfill(10)
