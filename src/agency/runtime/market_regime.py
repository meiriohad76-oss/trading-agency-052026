from __future__ import annotations

import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_SRC = REPO_ROOT / "research" / "src"
DEFAULT_PARQUET_ROOT = REPO_ROOT / "research" / "data" / "parquet"
DEFAULT_MANIFEST_ROOT = REPO_ROOT / "research" / "data" / "manifests"
PRICES_MANIFEST = DEFAULT_MANIFEST_ROOT / "prices_daily.json"

BROAD_MARKET_ETFS = ("SPY", "QQQ", "IWM", "DIA")
SECTOR_ETFS = ("XLK", "XLE", "XLF", "XLV", "XLI", "XLB", "XLY", "XLP", "XLU", "XLC", "XLRE")
ALL_CONTEXT_ETFS = frozenset((*BROAD_MARKET_ETFS, *SECTOR_ETFS))
LOOKBACK_DAYS = 100
SHORT_SESSIONS = 5
PRIMARY_SESSIONS = 20
LONG_SESSIONS = 60
MIN_BREADTH_COVERAGE = 0.55
FULL_BREADTH_COVERAGE = 0.9
BREADTH_PASS_THRESHOLD = 0.55
BREADTH_BLOCK_THRESHOLD = 0.42
DATA_LIMITED_CONFIDENCE = 0.5
RETURN_TONE_THRESHOLD = 0.02
RISK_OFF_SPY_RETURN = -0.025
RISK_OFF_QQQ_RETURN = -0.03
RISK_ON_SPY_RETURN = 0.02
HIGH_DISPERSION_SPREAD = 1.5
SECTOR_TAILWIND_SCORE = 0.65
SECTOR_HEADWIND_SCORE = -0.65
MIN_PRICE_OBSERVATIONS = 2
PRICE_DATA_PASS_LAG_DAYS = 5
PRICE_DATA_WARN_LAG_DAYS = 10
SCORE_GAUGE_CAP = 3.0
RETURN_GAUGE_CAP = 0.25
EXCESS_GAUGE_CAP = 0.15

ETF_LABELS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "IWM": "Russell 2000",
    "DIA": "Dow Industrials",
    "XLK": "Technology",
    "XLE": "Energy",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLI": "Industrials",
    "XLB": "Materials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLC": "Communication Services",
    "XLRE": "Real Estate",
}


class MarketRegimeLoader(Protocol):
    def sector_etfs(self, as_of: date, lookback_days: int) -> pl.DataFrame: ...

    def universe_members(self, as_of: date) -> set[str]: ...

    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> pl.DataFrame: ...


@dataclass(frozen=True)
class PriceMetric:
    ticker: str
    observations: int
    latest_date: date | None
    latest_price: float | None
    return_5d: float | None
    return_20d: float | None
    return_60d: float | None
    above_sma20: bool | None
    above_sma50: bool | None


@dataclass(frozen=True)
class RegimeInputs:
    spy_return_20d: float | None
    qqq_return_20d: float | None
    breadth_score: float | None
    sector_spread: float | None
    tailwind_count: int
    headwind_count: int
    confidence: float


def load_market_regime_snapshot(
    *,
    as_of: date | None = None,
    loader: MarketRegimeLoader | None = None,
) -> dict[str, object]:
    """Build a local, PIT-safe market and sector regime snapshot for the dashboard."""
    manifest_as_of = _latest_price_as_of(PRICES_MANIFEST)
    source_backed_as_of = as_of is not None or manifest_as_of is not None
    snapshot_as_of = as_of or manifest_as_of or date.today()
    active_loader = loader or _default_loader()
    quality_rows: list[dict[str, object]] = []
    if not source_backed_as_of:
        quality_rows.append(
            _quality_row(
                "Price manifest date",
                "BLOCK",
                "Price manifest has no source-backed max_timestamp_as_of; this dashboard is unavailable for live decisions.",
            )
        )

    sector_metrics = _load_sector_metrics(active_loader, snapshot_as_of, quality_rows)
    universe_members = _load_universe_members(active_loader, snapshot_as_of, quality_rows)
    breadth = _load_breadth(active_loader, snapshot_as_of, universe_members, quality_rows)

    benchmark_rows = _benchmark_rows(sector_metrics)
    sector_rows = _sector_rows(sector_metrics)
    confidence = _confidence(
        benchmark_rows=benchmark_rows,
        sector_rows=sector_rows,
        universe=breadth,
    )
    regime = _classify_regime(
        RegimeInputs(
            spy_return_20d=_metric_return(sector_metrics.get("SPY"), "return_20d"),
            qqq_return_20d=_metric_return(sector_metrics.get("QQQ"), "return_20d"),
            breadth_score=_float_or_none(breadth.get("breadth_score")),
            sector_spread=_sector_spread(sector_rows),
            tailwind_count=sum(1 for row in sector_rows if row["stance"] == "Tailwind"),
            headwind_count=sum(1 for row in sector_rows if row["stance"] == "Headwind"),
            confidence=confidence,
        )
    )
    _append_data_age_check(
        snapshot_as_of,
        quality_rows,
        source_backed=source_backed_as_of,
    )
    summary = _summary(
        regime,
        snapshot_as_of,
        confidence,
        breadth,
        benchmark_rows,
        sector_rows,
        source_backed=source_backed_as_of,
    )
    return {
        "active_nav": "market",
        "summary": summary,
        "kpis": _kpi_rows(summary, breadth, benchmark_rows, sector_rows),
        "benchmark_rows": benchmark_rows,
        "sector_rows": sector_rows,
        "breadth": breadth,
        "quality_rows": quality_rows,
        "universe": _universe_summary(universe_members, breadth),
        "data_source": _price_manifest_summary(PRICES_MANIFEST),
    }


def _default_loader() -> MarketRegimeLoader:
    if str(RESEARCH_SRC) not in sys.path:
        sys.path.insert(0, str(RESEARCH_SRC))
    loader_module = import_module("pit.loader")
    loader_class = cast(Any, loader_module).PITLoader
    return cast(
        MarketRegimeLoader,
        loader_class(parquet_root=DEFAULT_PARQUET_ROOT, manifest_root=DEFAULT_MANIFEST_ROOT),
    )


def _latest_price_as_of(path: Path) -> date | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("max_timestamp_as_of")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _price_manifest_summary(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "provider_label": "cached provider data",
            "row_count_label": "rows unavailable",
            "detail": "Price manifest was unavailable; data quality checks show the cache state.",
        }
    if not isinstance(payload, Mapping):
        return {
            "provider_label": "cached provider data",
            "row_count_label": "rows unavailable",
            "detail": "Price manifest was not readable; data quality checks show the cache state.",
        }
    sources = payload.get("sources")
    if isinstance(sources, list) and sources:
        provider_label = ", ".join(sorted(str(source) for source in sources))
    else:
        provider_label = str(payload.get("source") or "cached provider data")
    row_count = _int_or_zero(payload.get("row_count"))
    ticker_count = _int_or_zero(payload.get("ticker_count"))
    return {
        "provider_label": provider_label,
        "row_count_label": f"{row_count:,} rows" if row_count else "rows unavailable",
        "detail": (
            f"{row_count:,} cached daily price rows across {ticker_count} tickers"
            if row_count and ticker_count
            else "Cached daily prices are used for this read-only dashboard"
        ),
    }


def _load_sector_metrics(
    loader: MarketRegimeLoader,
    as_of: date,
    quality_rows: list[dict[str, object]],
) -> dict[str, PriceMetric]:
    try:
        frame = loader.sector_etfs(as_of, LOOKBACK_DAYS)
    except Exception as exc:
        quality_rows.append(
            _quality_row("Sector ETF prices", "BLOCK", f"Could not load sector ETFs: {exc}")
        )
        return {}
    metrics = _metrics_by_ticker(frame)
    present = len(set(metrics) & ALL_CONTEXT_ETFS)
    expected = len(ALL_CONTEXT_ETFS)
    status = "PASS" if present == expected else "WARN" if present else "BLOCK"
    quality_rows.append(
        _quality_row("Sector ETF prices", status, f"{present}/{expected} context ETFs available")
    )
    return metrics


def _load_universe_members(
    loader: MarketRegimeLoader,
    as_of: date,
    quality_rows: list[dict[str, object]],
) -> set[str]:
    try:
        members = {ticker.upper() for ticker in loader.universe_members(as_of)}
    except Exception as exc:
        quality_rows.append(
            _quality_row("Active universe", "BLOCK", f"Could not load universe membership: {exc}")
        )
        return set()
    stock_members = members - ALL_CONTEXT_ETFS
    status = "PASS" if stock_members else "BLOCK"
    quality_rows.append(
        _quality_row("Active universe", status, f"{len(stock_members)} active stock tickers")
    )
    return stock_members


def _load_breadth(
    loader: MarketRegimeLoader,
    as_of: date,
    universe_members: set[str],
    quality_rows: list[dict[str, object]],
) -> dict[str, object]:
    if not universe_members:
        return _empty_breadth("No active universe members were available.")
    try:
        frame = loader.prices(sorted(universe_members), as_of, LOOKBACK_DAYS)
    except Exception as exc:
        quality_rows.append(
            _quality_row("Universe breadth", "BLOCK", f"Could not load stock prices: {exc}")
        )
        return _empty_breadth("Universe price history was unavailable.")
    metrics = _metrics_by_ticker(frame)
    priced_count = len(metrics)
    member_count = len(universe_members)
    coverage = priced_count / member_count if member_count else 0.0
    status = (
        "PASS"
        if coverage >= FULL_BREADTH_COVERAGE
        else "WARN"
        if coverage >= MIN_BREADTH_COVERAGE
        else "BLOCK"
    )
    quality_rows.append(
        _quality_row(
            "Universe breadth",
            status,
            f"{priced_count}/{member_count} active tickers have usable price history",
        )
    )
    above20 = _boolean_ratio(metric.above_sma20 for metric in metrics.values())
    above50 = _boolean_ratio(metric.above_sma50 for metric in metrics.values())
    advancers = _positive_return_ratio(metric.return_5d for metric in metrics.values())
    breadth_score = _average_present([above20, above50, advancers])
    return {
        "member_count": member_count,
        "priced_count": priced_count,
        "coverage": coverage,
        "coverage_label": _whole_pct(coverage),
        "above_sma20": above20,
        "above_sma20_label": _whole_pct(above20),
        "above_sma50": above50,
        "above_sma50_label": _whole_pct(above50),
        "advancers_5d": advancers,
        "advancers_5d_label": _whole_pct(advancers),
        "breadth_score": breadth_score,
        "breadth_score_label": _whole_pct(breadth_score),
        "state_class": _breadth_class(breadth_score, coverage),
        "detail": _breadth_detail(breadth_score, coverage, priced_count, member_count),
    }


def _metrics_by_ticker(frame: pl.DataFrame) -> dict[str, PriceMetric]:
    if frame.is_empty() or "ticker" not in frame.columns:
        return {}
    price_column = _price_column(frame)
    groups: dict[str, list[tuple[date, float]]] = {}
    for row in frame.select(["ticker", "date", price_column]).sort(["ticker", "date"]).to_dicts():
        ticker = str(row["ticker"]).upper()
        record_date = _date_or_none(row.get("date"))
        close = _float_or_none(row.get(price_column))
        if record_date is None or close is None or close <= 0.0:
            continue
        groups.setdefault(ticker, []).append((record_date, close))
    return {ticker: _price_metric(ticker, values) for ticker, values in groups.items()}


def _price_metric(ticker: str, values: Sequence[tuple[date, float]]) -> PriceMetric:
    ordered = sorted(values, key=lambda item: item[0])
    prices = [item[1] for item in ordered]
    latest_date = ordered[-1][0] if ordered else None
    latest_price = prices[-1] if prices else None
    return PriceMetric(
        ticker=ticker,
        observations=len(prices),
        latest_date=latest_date,
        latest_price=latest_price,
        return_5d=_session_return(prices, SHORT_SESSIONS),
        return_20d=_session_return(prices, PRIMARY_SESSIONS),
        return_60d=_session_return(prices, LONG_SESSIONS),
        above_sma20=_above_sma(prices, PRIMARY_SESSIONS),
        above_sma50=_above_sma(prices, 50),
    )


def _benchmark_rows(metrics: Mapping[str, PriceMetric]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for ticker in BROAD_MARKET_ETFS:
        metric = metrics.get(ticker)
        rows.append(_market_row(ticker, metric))
    return rows


def _market_row(ticker: str, metric: PriceMetric | None) -> dict[str, object]:
    return_20d = _metric_return(metric, "return_20d")
    return {
        "ticker": ticker,
        "label": ETF_LABELS[ticker],
        "latest_price": _price_label(metric.latest_price if metric else None),
        "return_5d": _signed_pct(_metric_return(metric, "return_5d")),
        "return_20d": _signed_pct(return_20d),
        "return_60d": _signed_pct(_metric_return(metric, "return_60d")),
        "observations": metric.observations if metric else 0,
        "tone_class": _return_class(return_20d),
        "latest_date": metric.latest_date.isoformat() if metric and metric.latest_date else "n/a",
    }


def _sector_rows(metrics: Mapping[str, PriceMetric]) -> list[dict[str, object]]:
    if not set(metrics).intersection(SECTOR_ETFS):
        return []
    raw_rows = [
        _raw_sector_row(ticker, metrics.get(ticker), metrics.get("SPY"))
        for ticker in SECTOR_ETFS
    ]
    z5 = _zscore([_float_or_zero(row["excess_5d_value"]) for row in raw_rows])
    z20 = _zscore([_float_or_zero(row["excess_20d_value"]) for row in raw_rows])
    z60 = _zscore([_float_or_zero(row["excess_60d_value"]) for row in raw_rows])
    scored: list[dict[str, object]] = []
    for index, row in enumerate(raw_rows):
        score = 0.2 * z5[index] + 0.5 * z20[index] + 0.3 * z60[index]
        stance = _sector_stance(score, _float_or_none(row["excess_20d_value"]))
        scored.append(
            {
                **row,
                "score": score,
                "score_label": f"{score:+.2f}",
                "score_gauge_style": _gauge_style(score, SCORE_GAUGE_CAP),
                "stance": stance,
                "stance_class": _sector_stance_class(stance),
                "guidance": _sector_guidance(str(row["label"]), stance),
            }
        )
    sorted_rows = sorted(
        scored,
        key=lambda row: (-_float_or_zero(row["score"]), str(row["ticker"])),
    )
    for rank, row in enumerate(sorted_rows, start=1):
        row["rank"] = rank
    return sorted_rows


def _raw_sector_row(
    ticker: str,
    metric: PriceMetric | None,
    benchmark: PriceMetric | None,
) -> dict[str, object]:
    return_5d = _metric_return(metric, "return_5d")
    return_20d = _metric_return(metric, "return_20d")
    return_60d = _metric_return(metric, "return_60d")
    excess_5d = _excess(return_5d, _metric_return(benchmark, "return_5d"))
    excess_20d = _excess(return_20d, _metric_return(benchmark, "return_20d"))
    excess_60d = _excess(return_60d, _metric_return(benchmark, "return_60d"))
    return {
        "ticker": ticker,
        "label": ETF_LABELS[ticker],
        "latest_price": _price_label(metric.latest_price if metric else None),
        "return_5d": _signed_pct(return_5d),
        "return_20d": _signed_pct(return_20d),
        "return_60d": _signed_pct(return_60d),
        "excess_5d": _signed_pct(excess_5d),
        "excess_20d": _signed_pct(excess_20d),
        "excess_60d": _signed_pct(excess_60d),
        "return_20d_class": _return_class(return_20d),
        "return_60d_class": _return_class(return_60d),
        "excess_20d_class": _return_class(excess_20d),
        "return_20d_gauge_style": _gauge_style(return_20d, RETURN_GAUGE_CAP),
        "return_60d_gauge_style": _gauge_style(return_60d, RETURN_GAUGE_CAP),
        "excess_20d_gauge_style": _gauge_style(excess_20d, EXCESS_GAUGE_CAP),
        "excess_5d_value": excess_5d,
        "excess_20d_value": excess_20d,
        "excess_60d_value": excess_60d,
        "observations": metric.observations if metric else 0,
        "latest_date": metric.latest_date.isoformat() if metric and metric.latest_date else "n/a",
    }


def _classify_regime(inputs: RegimeInputs) -> dict[str, str]:
    if inputs.confidence < DATA_LIMITED_CONFIDENCE:
        return {
            "key": "data_limited",
            "label": "Data Limited",
            "status_class": "warn",
            "headline": "Top-down context needs fresher or broader data.",
            "interpretation": (
                "The agency can still review single-name evidence, but market and sector "
                "context should not influence approvals until coverage recovers."
            ),
            "decision_guidance": "Keep decisions context-only for the regime lane.",
        }
    spy = inputs.spy_return_20d
    qqq = inputs.qqq_return_20d
    breadth = inputs.breadth_score
    if (
        _is_at_most(spy, RISK_OFF_SPY_RETURN)
        or _is_at_most(qqq, RISK_OFF_QQQ_RETURN)
        or _is_at_most(breadth, BREADTH_BLOCK_THRESHOLD)
    ):
        return {
            "key": "risk_off",
            "label": "Risk Off",
            "status_class": "block",
            "headline": "Broad tape is defensive; raise the bar for new BUY actions.",
            "interpretation": (
                "Weak benchmark returns or poor breadth mean single-stock signals need "
                "stronger corroboration before paper orders are approved."
            ),
            "decision_guidance": (
                "Prefer DEFER/WATCH unless the candidate has unusually strong evidence."
            ),
        }
    if (
        _is_at_least(spy, RISK_ON_SPY_RETURN)
        and _is_at_least(qqq, 0.0)
        and _is_at_least(breadth, BREADTH_PASS_THRESHOLD)
    ):
        return {
            "key": "risk_on",
            "label": "Risk On",
            "status_class": "pass",
            "headline": "Market backdrop is constructive enough for normal paper review.",
            "interpretation": (
                "Benchmarks and breadth are supportive, so strong single-name signals can "
                "move through the normal approval path."
            ),
            "decision_guidance": (
                "Use sector tailwinds as corroboration, not as a standalone buy trigger."
            ),
        }
    if (
        _is_at_least(inputs.sector_spread, HIGH_DISPERSION_SPREAD)
        and inputs.tailwind_count
        and inputs.headwind_count
    ):
        return {
            "key": "high_dispersion",
            "label": "High Dispersion",
            "status_class": "warn",
            "headline": (
                "Sector leadership is split; stock selection matters more than index direction."
            ),
            "interpretation": (
                "The agency should reward candidates in leading sectors and demand extra "
                "evidence for names sitting in weak groups."
            ),
            "decision_guidance": "Lean on sector alignment during human review and risk sizing.",
        }
    return {
        "key": "balanced",
        "label": "Balanced",
        "status_class": "neutral",
        "headline": "Top-down backdrop is mixed but usable.",
        "interpretation": (
            "The market does not provide a strong push either way. Candidate-specific "
            "fundamentals, technicals, flow, and news should dominate the judgment."
        ),
        "decision_guidance": "Keep regime as context unless a sector tailwind/headwind is extreme.",
    }


def _summary(
    regime: Mapping[str, str],
    as_of: date,
    confidence: float,
    breadth: Mapping[str, object],
    benchmark_rows: Sequence[Mapping[str, object]],
    sector_rows: Sequence[Mapping[str, object]],
    *,
    source_backed: bool = True,
) -> dict[str, object]:
    if not source_backed:
        return {
            "as_of": "not source-backed",
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "regime_key": "unavailable",
            "regime_label": "Unavailable",
            "status_class": "block",
            "headline": "Market regime is unavailable until price data date is source-backed.",
            "interpretation": (
                "The price manifest does not expose a reliable latest bar date, so this "
                "dashboard must not be used as live market context."
            ),
            "decision_guidance": "Refresh daily market bars and verify the price manifest before relying on sector or breadth context.",
            "confidence": 0.0,
            "confidence_pct": 0,
            "topbar_label": "Market regime unavailable / no source-backed price date",
            "detail": "Price manifest max_timestamp_as_of is missing or invalid.",
        }
    return {
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "regime_key": regime["key"],
        "regime_label": regime["label"],
        "status_class": regime["status_class"],
        "headline": regime["headline"],
        "interpretation": regime["interpretation"],
        "decision_guidance": regime["decision_guidance"],
        "confidence": confidence,
        "confidence_pct": round(confidence * 100),
        "topbar_label": f"{regime['label']} / data through {as_of.isoformat()}",
        "detail": _summary_detail(breadth, benchmark_rows, sector_rows),
    }


def _kpi_rows(
    summary: Mapping[str, object],
    breadth: Mapping[str, object],
    benchmark_rows: Sequence[Mapping[str, object]],
    sector_rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    spy = _find_row(benchmark_rows, "SPY")
    qqq = _find_row(benchmark_rows, "QQQ")
    top_sector = sector_rows[0] if sector_rows else None
    weak_sector = sector_rows[-1] if sector_rows else None
    return [
        {
            "label": "Regime",
            "value": str(summary["regime_label"]),
            "detail": f"{summary['confidence_pct']}% confidence",
            "class": str(summary["status_class"]),
        },
        {
            "label": "Breadth",
            "value": str(breadth["breadth_score_label"]),
            "detail": str(breadth["detail"]),
            "class": str(breadth["state_class"]),
        },
        {
            "label": "SPY 20D",
            "value": str(spy.get("return_20d", "n/a")) if spy else "n/a",
            "detail": "broad risk benchmark",
            "class": str(spy.get("tone_class", "neutral")) if spy else "neutral",
        },
        {
            "label": "QQQ 20D",
            "value": str(qqq.get("return_20d", "n/a")) if qqq else "n/a",
            "detail": "growth benchmark",
            "class": str(qqq.get("tone_class", "neutral")) if qqq else "neutral",
        },
        {
            "label": "Leading Sector",
            "value": str(top_sector.get("label", "n/a")) if top_sector else "n/a",
            "detail": str(top_sector.get("score_label", "")) if top_sector else "no sector rows",
            "class": str(top_sector.get("stance_class", "neutral")) if top_sector else "neutral",
        },
        {
            "label": "Weakest Sector",
            "value": str(weak_sector.get("label", "n/a")) if weak_sector else "n/a",
            "detail": str(weak_sector.get("score_label", "")) if weak_sector else "no sector rows",
            "class": str(weak_sector.get("stance_class", "neutral")) if weak_sector else "neutral",
        },
    ]


def _universe_summary(
    universe_members: set[str],
    breadth: Mapping[str, object],
) -> dict[str, object]:
    return {
        "member_count": len(universe_members),
        "priced_count": breadth.get("priced_count", 0),
        "coverage_label": breadth.get("coverage_label", "n/a"),
        "above_sma20_label": breadth.get("above_sma20_label", "n/a"),
        "above_sma50_label": breadth.get("above_sma50_label", "n/a"),
        "advancers_5d_label": breadth.get("advancers_5d_label", "n/a"),
        "state_class": breadth.get("state_class", "neutral"),
    }


def _summary_detail(
    breadth: Mapping[str, object],
    benchmark_rows: Sequence[Mapping[str, object]],
    sector_rows: Sequence[Mapping[str, object]],
) -> str:
    spy = _find_row(benchmark_rows, "SPY")
    top = sector_rows[0] if sector_rows else None
    weak = sector_rows[-1] if sector_rows else None
    spy_text = f"SPY 20D {spy['return_20d']}" if spy else "SPY unavailable"
    sector_text = (
        f"leader {top['label']} ({top['score_label']}), "
        f"laggard {weak['label']} ({weak['score_label']})"
        if top and weak
        else "sector leadership unavailable"
    )
    return f"{spy_text}; breadth score {breadth['breadth_score_label']}; {sector_text}."


def _confidence(
    *,
    benchmark_rows: Sequence[Mapping[str, object]],
    sector_rows: Sequence[Mapping[str, object]],
    universe: Mapping[str, object],
) -> float:
    benchmark_coverage = _ratio(
        sum(
            1
            for row in benchmark_rows
            if _int_or_zero(row.get("observations")) >= PRIMARY_SESSIONS
        ),
        len(BROAD_MARKET_ETFS),
    )
    sector_coverage = _ratio(
        sum(
            1
            for row in sector_rows
            if _int_or_zero(row.get("observations")) >= PRIMARY_SESSIONS
        ),
        len(SECTOR_ETFS),
    )
    breadth_coverage = _float_or_zero(universe.get("coverage"))
    confidence = 0.35 * benchmark_coverage + 0.3 * sector_coverage + 0.35 * breadth_coverage
    return max(0.0, min(1.0, confidence))


def _empty_breadth(detail: str) -> dict[str, object]:
    return {
        "member_count": 0,
        "priced_count": 0,
        "coverage": 0.0,
        "coverage_label": "n/a",
        "above_sma20": None,
        "above_sma20_label": "n/a",
        "above_sma50": None,
        "above_sma50_label": "n/a",
        "advancers_5d": None,
        "advancers_5d_label": "n/a",
        "breadth_score": None,
        "breadth_score_label": "n/a",
        "state_class": "block",
        "detail": detail,
    }


def _price_column(frame: pl.DataFrame) -> str:
    for column in ("adj_close", "close"):
        if column in frame.columns:
            return column
    return "close"


def _session_return(prices: Sequence[float], sessions: int) -> float | None:
    if len(prices) < MIN_PRICE_OBSERVATIONS:
        return None
    start_index = max(0, len(prices) - sessions - 1)
    start = prices[start_index]
    end = prices[-1]
    if start <= 0.0:
        return None
    return end / start - 1.0


def _above_sma(prices: Sequence[float], sessions: int) -> bool | None:
    if len(prices) < sessions:
        return None
    window = prices[-sessions:]
    average = sum(window) / len(window)
    return prices[-1] > average


def _boolean_ratio(values: Iterable[bool | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(1 for value in usable if value) / len(usable)


def _positive_return_ratio(values: Iterable[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(1 for value in usable if value > 0.0) / len(usable)


def _average_present(values: Sequence[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _zscore(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    stddev = math.sqrt(variance)
    if stddev <= 0.0:
        return [0.0 for _ in values]
    return [(value - mean) / stddev for value in values]


def _excess(value: float | None, benchmark: float | None) -> float | None:
    if value is None or benchmark is None:
        return None
    return value - benchmark


def _sector_stance(score: float, excess_20d: float | None) -> str:
    if score >= SECTOR_TAILWIND_SCORE and _is_at_least(excess_20d, 0.0):
        return "Tailwind"
    if score <= SECTOR_HEADWIND_SCORE and _is_at_most(excess_20d, 0.0):
        return "Headwind"
    return "Neutral"


def _sector_stance_class(stance: str) -> str:
    return {"Tailwind": "pass", "Headwind": "block"}.get(stance, "neutral")


def _sector_guidance(label: str, stance: str) -> str:
    if stance == "Tailwind":
        return (
            f"{label} is adding top-down support; same-sector candidates may need "
            "less extra corroboration."
        )
    if stance == "Headwind":
        return (
            f"{label} is a drag; same-sector candidates should show stronger "
            "stock-specific evidence."
        )
    return f"{label} is not giving a clear top-down push; keep focus on ticker-specific evidence."


def _sector_spread(rows: Sequence[Mapping[str, object]]) -> float | None:
    scores = [_float_or_none(row.get("score")) for row in rows]
    usable = [score for score in scores if score is not None]
    if len(usable) < MIN_PRICE_OBSERVATIONS:
        return None
    return max(usable) - min(usable)


def _metric_return(metric: PriceMetric | None, field: str) -> float | None:
    if metric is None:
        return None
    return {
        "return_5d": metric.return_5d,
        "return_20d": metric.return_20d,
        "return_60d": metric.return_60d,
    }[field]


def _return_class(value: float | None) -> str:
    if value is None:
        return "neutral"
    if value >= RETURN_TONE_THRESHOLD:
        return "pass"
    if value <= -RETURN_TONE_THRESHOLD:
        return "block"
    return "neutral"


def _breadth_class(breadth_score: float | None, coverage: float) -> str:
    if breadth_score is None or coverage < MIN_BREADTH_COVERAGE:
        return "block"
    if breadth_score >= BREADTH_PASS_THRESHOLD:
        return "pass"
    if breadth_score <= BREADTH_BLOCK_THRESHOLD:
        return "block"
    return "warn"


def _breadth_detail(
    breadth_score: float | None,
    coverage: float,
    priced_count: int,
    member_count: int,
) -> str:
    if breadth_score is None:
        return "Breadth unavailable"
    return (
        f"{priced_count}/{member_count} tickers priced; "
        f"{_whole_pct(coverage)} coverage across the active universe"
    )


def _append_data_age_check(
    as_of: date,
    quality_rows: list[dict[str, object]],
    *,
    source_backed: bool = True,
) -> None:
    if not source_backed:
        quality_rows.append(
            _quality_row(
                "Price data age",
                "BLOCK",
                "Latest daily bar age cannot be verified without a source-backed manifest date",
            )
        )
        return
    lag_days = max(0, (date.today() - as_of).days)
    status = (
        "PASS"
        if lag_days <= PRICE_DATA_PASS_LAG_DAYS
        else "WARN"
        if lag_days <= PRICE_DATA_WARN_LAG_DAYS
        else "BLOCK"
    )
    quality_rows.append(
        _quality_row(
            "Price data age",
            status,
            f"Latest daily bar is {lag_days} calendar day(s) old",
        )
    )


def _quality_row(label: str, status: str, detail: str) -> dict[str, object]:
    return {
        "label": label,
        "status": status,
        "status_class": {"PASS": "pass", "WARN": "warn", "BLOCK": "block"}.get(status, "neutral"),
        "detail": detail,
    }


def _find_row(
    rows: Sequence[Mapping[str, object]],
    ticker: str,
) -> Mapping[str, object] | None:
    for row in rows:
        if row.get("ticker") == ticker:
            return row
    return None


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.1%}"


def _whole_pct(value: object) -> str:
    number = _float_or_none(value)
    if number is None:
        return "n/a"
    return f"{round(number * 100)}%"


def _price_label(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.2f}"


def _gauge_style(value: float | None, cap: float) -> str:
    if value is None or cap <= 0.0:
        return "width: 0%"
    width = max(0.0, min(1.0, abs(value) / cap))
    return f"width: {round(width * 100)}%"


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    else:
        try:
            number = float(str(value))
        except ValueError:
            return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _float_or_zero(value: object) -> float:
    return _float_or_none(value) or 0.0


def _int_or_zero(value: object) -> int:
    number = _float_or_none(value)
    if number is None:
        return 0
    return int(number)


def _date_or_none(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_at_least(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _is_at_most(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold
