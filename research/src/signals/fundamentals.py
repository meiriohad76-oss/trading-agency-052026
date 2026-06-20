from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol, cast

import pandas as pd
import polars as pl
from pit.exceptions import DataNotAvailableAt

MIN_CROSS_SECTION = 2
LOOKBACK_PRICE_DAYS = 5

CONTRACT_COLUMNS = [
    "ticker",
    "filing_period",
    "filing_year",
    "filing_form",
    "filing_period_end",
    "period_alignment_status",
    "quality_score",
    "growth_score",
    "valuation_score",
    "forward_score",
    "composite_score",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "roe",
    "roa",
    "leverage",
    "inverse_leverage",
    "revenue_growth_qoq",
    "revenue_growth_yoy",
    "net_income_growth_qoq",
    "net_income_growth_yoy",
    "fcf_growth_qoq",
    "fcf_growth_yoy",
    "trailing_pe",
    "inverse_trailing_pe",
    "fcf_yield",
    "forward_pe",
    "forward_eps",
    "eps_beat_rate",
    "analyst_count",
    "forward_data_status",
    "forward_data_as_of",
]


class FundamentalsLoader(Protocol):
    def fundamentals(self, ticker: str, as_of: date) -> object: ...


class FundamentalsHistoryLoader(Protocol):
    def fundamentals_history(
        self,
        ticker: str,
        as_of: date,
        n_periods: int = 8,
    ) -> pd.DataFrame: ...


class FundamentalsPriceLoader(Protocol):
    def prices(self, tickers: list[str], as_of: date, lookback_days: int) -> object: ...


class ForwardFundamentalsLoader(Protocol):
    def forward_fundamentals(self, ticker: str, as_of: date) -> dict[str, object]: ...


def fundamental_score(
    as_of: date,
    universe: set[str],
    loader: FundamentalsLoader,
    *,
    history_loader: FundamentalsHistoryLoader | None = None,
    price_loader: FundamentalsPriceLoader | None = None,
    forward_loader: ForwardFundamentalsLoader | None = None,
) -> dict[str, float]:
    """Return a PIT-safe fundamentals composite score per ticker."""
    frame = fundamental_factor_frame(
        as_of,
        universe,
        loader,
        history_loader=history_loader,
        price_loader=price_loader,
        forward_loader=forward_loader,
    )
    scores: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        score = _float(row.composite_score)
        if score is not None and pd.notna(score):
            scores[str(row.ticker)] = score
    return scores


def fundamental_factor_frame(
    as_of: date,
    universe: Iterable[str],
    loader: FundamentalsLoader,
    *,
    history_loader: FundamentalsHistoryLoader | None = None,
    price_loader: FundamentalsPriceLoader | None = None,
    forward_loader: ForwardFundamentalsLoader | None = None,
) -> pd.DataFrame:
    """Build the fundamentals factor cross-section known at `as_of`."""
    rows = []
    for ticker in sorted({item.upper() for item in universe}):
        try:
            payload = _payload(loader.fundamentals(ticker, as_of))
        except DataNotAvailableAt:
            continue
        row = _factor_row(ticker, payload)
        if row is None:
            continue
        if history_loader is not None:
            row.update(_history_factors(ticker, as_of, history_loader))
        if price_loader is not None:
            row.update(_valuation_factors(ticker, as_of, payload, price_loader))
        if forward_loader is not None:
            row.update(_forward_factors(ticker, as_of, forward_loader))
        rows.append(row)
    frame = pd.DataFrame(rows, columns=CONTRACT_COLUMNS)
    if frame.empty:
        return _empty_frame()
    _add_subscores(frame)
    return frame.sort_values(["composite_score", "ticker"], ascending=[False, True]).reset_index(
        drop=True
    )


def _factor_row(ticker: str, payload: dict[str, object]) -> dict[str, object] | None:
    revenue = _positive_float(payload.get("revenue"))
    net_income = _float(payload.get("net_income"))
    free_cash_flow = _float(payload.get("free_cash_flow"))
    total_assets = _positive_float(payload.get("total_assets"))
    total_liabilities = _float(payload.get("total_liabilities"))
    if revenue is None or net_income is None or free_cash_flow is None:
        return None
    leverage = 0.0
    if total_assets is not None and total_liabilities is not None:
        leverage = max(total_liabilities / total_assets, 0.0)
    total_equity = _positive_float(payload.get("total_equity"))
    row = _contract_defaults(ticker)
    row.update(
        {
            "filing_period": payload.get("filing_period"),
            "filing_year": payload.get("filing_year"),
            "filing_form": payload.get("filing_form"),
            "filing_period_end": payload.get("filing_period_end"),
            "period_alignment_status": str(payload.get("period_alignment_status") or "aligned"),
            "gross_margin": _ratio(payload.get("gross_profit"), revenue),
            "operating_margin": _ratio(payload.get("operating_income"), revenue),
            "net_margin": net_income / revenue,
            "fcf_margin": free_cash_flow / revenue,
            "roe": _ratio(net_income, total_equity),
            "roa": _ratio(net_income, total_assets),
            "leverage": leverage,
            "inverse_leverage": -leverage,
        }
    )
    return row


def _history_factors(
    ticker: str,
    as_of: date,
    history_loader: FundamentalsHistoryLoader,
) -> dict[str, float | None]:
    try:
        history = history_loader.fundamentals_history(ticker, as_of, n_periods=8)
    except DataNotAvailableAt:
        history = pd.DataFrame()
    return _growth_factors(history)


def _growth_factors(history: pd.DataFrame) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for metric, prefix in (
        ("revenue", "revenue_growth"),
        ("net_income", "net_income_growth"),
        ("free_cash_flow", "fcf_growth"),
    ):
        series = _metric_series(history, metric)
        output[f"{prefix}_qoq"] = _growth_qoq(series)
        output[f"{prefix}_yoy"] = _growth_yoy(series)
    return output


def _metric_series(history: pd.DataFrame, metric: str) -> list[float]:
    if history.empty or "metric" not in history.columns:
        return []
    subset = history[history["metric"] == metric].copy()
    if subset.empty:
        return []
    subset = subset.sort_values("period_end")
    return [float(value) for value in subset["value"].tolist() if pd.notna(value)]


def _growth_qoq(values: list[float]) -> float | None:
    if len(values) < 2 or values[-2] == 0.0:
        return None
    return (values[-1] / values[-2]) - 1.0


def _growth_yoy(values: list[float]) -> float | None:
    if len(values) < 5 or values[-5] == 0.0:
        return None
    return (values[-1] / values[-5]) - 1.0


def _valuation_factors(
    ticker: str,
    as_of: date,
    payload: dict[str, object],
    price_loader: FundamentalsPriceLoader,
) -> dict[str, float | None]:
    try:
        prices = price_loader.prices([ticker], as_of, LOOKBACK_PRICE_DAYS)
    except DataNotAvailableAt:
        prices = pd.DataFrame()
    price_frame = _to_pandas(prices)
    close = _latest_close(price_frame, ticker)
    shares = _positive_float(payload.get("shares_outstanding"))
    net_income = _positive_float(payload.get("net_income"))
    free_cash_flow = _float(payload.get("free_cash_flow"))
    market_cap = close * shares if close is not None and shares is not None else None
    return {
        "trailing_pe": market_cap / net_income if market_cap is not None and net_income else None,
        "inverse_trailing_pe": -(market_cap / net_income)
        if market_cap is not None and net_income
        else None,
        "fcf_yield": free_cash_flow / market_cap
        if market_cap is not None and market_cap > 0.0 and free_cash_flow is not None
        else None,
    }


def _forward_factors(
    ticker: str,
    as_of: date,
    forward_loader: ForwardFundamentalsLoader,
) -> dict[str, object]:
    try:
        state = forward_loader.forward_fundamentals(ticker, as_of)
    except DataNotAvailableAt:
        return {"forward_data_status": "missing"}
    return {
        "forward_pe": _positive_float(state.get("forward_pe")),
        "forward_eps": _float(state.get("forward_eps")),
        "eps_beat_rate": _float(state.get("eps_beat_rate")),
        "analyst_count": _float(state.get("analyst_count")),
        "forward_data_status": str(state.get("forward_data_status") or "missing"),
        "forward_data_as_of": state.get("forward_data_as_of"),
    }


def _to_pandas(value: object) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, pl.DataFrame):
        return value.to_pandas()
    return pd.DataFrame()


def _latest_close(frame: pd.DataFrame, ticker: str) -> float | None:
    if frame.empty or "close" not in frame.columns:
        return None
    subset = frame
    if "ticker" in subset.columns:
        subset = subset[subset["ticker"].astype(str).str.upper() == ticker.upper()]
    if subset.empty:
        return None
    if "date" in subset.columns:
        subset = subset.sort_values("date")
    return _positive_float(subset.iloc[-1]["close"])


def _add_subscores(frame: pd.DataFrame) -> None:
    _add_subscore(
        frame,
        "quality_score",
        [
            "gross_margin",
            "operating_margin",
            "net_margin",
            "fcf_margin",
            "roe",
            "roa",
            "inverse_leverage",
        ],
    )
    _add_subscore(
        frame,
        "growth_score",
        [
            "revenue_growth_qoq",
            "revenue_growth_yoy",
            "net_income_growth_qoq",
            "net_income_growth_yoy",
            "fcf_growth_qoq",
            "fcf_growth_yoy",
        ],
    )
    _add_subscore(frame, "valuation_score", ["fcf_yield", "inverse_trailing_pe"])
    frame["inverse_forward_pe"] = -pd.to_numeric(frame["forward_pe"], errors="coerce")
    _add_subscore(frame, "forward_score", ["inverse_forward_pe", "eps_beat_rate"])
    score_columns = ["quality_score", "growth_score", "valuation_score", "forward_score"]
    frame["composite_score"] = frame[score_columns].mean(axis=1, skipna=True).fillna(0.0)


def _add_subscore(frame: pd.DataFrame, score_column: str, columns: list[str]) -> None:
    z_columns: list[str] = []
    for column in columns:
        if column not in frame.columns:
            continue
        if not frame[column].notna().any():
            continue
        z_column = f"{column}_z"
        frame[z_column] = _zscore(frame[column])
        z_columns.append(z_column)
    if z_columns:
        frame[score_column] = frame[z_columns].mean(axis=1, skipna=True)
    else:
        frame[score_column] = pd.NA


def _contract_defaults(ticker: str) -> dict[str, object]:
    return dict.fromkeys(CONTRACT_COLUMNS) | {
        "ticker": ticker,
        "period_alignment_status": "aligned",
        "forward_data_status": "not_configured",
    }


def _payload(value: object) -> dict[str, object]:
    payload = cast(Any, value).value if hasattr(value, "value") else value
    if not isinstance(payload, dict):
        raise TypeError("fundamentals payload must be a dict")
    return payload


def _zscore(series: pd.Series) -> pd.Series:
    if len(series.dropna()) < MIN_CROSS_SECTION:
        return pd.Series([0.0 for _ in series], index=series.index)
    std = series.std(ddof=0)
    if std == 0.0 or pd.isna(std):
        return pd.Series([0.0 for _ in series], index=series.index)
    return (series - series.mean()) / std


def _float(value: object) -> float | None:
    if value is None or value is pd.NA:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _positive_float(value: object) -> float | None:
    parsed = _float(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def _ratio(numerator: object, denominator: object) -> float | None:
    parsed_numerator = _float(numerator)
    parsed_denominator = _positive_float(denominator)
    if parsed_numerator is None or parsed_denominator is None:
        return None
    return parsed_numerator / parsed_denominator


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=CONTRACT_COLUMNS)
