from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Protocol, cast

import pandas as pd

MIN_CROSS_SECTION = 2


class FundamentalsLoader(Protocol):
    def fundamentals(self, ticker: str, as_of: date) -> object: ...


def fundamental_score(
    as_of: date,
    universe: set[str],
    loader: FundamentalsLoader,
) -> dict[str, float]:
    """Return a PIT-safe fundamentals composite score per ticker.

    The function reads only through `loader.fundamentals(ticker, as_of)`, so it
    satisfies the walk-forward signal contract. The composite rewards net
    margin and free-cash-flow margin, while penalizing balance-sheet leverage.
    Factor values are cross-sectionally z-scored before averaging.
    """
    frame = fundamental_factor_frame(as_of, universe, loader)
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
) -> pd.DataFrame:
    """Build the fundamentals factor cross-section known at `as_of`."""
    rows = []
    for ticker in sorted({item.upper() for item in universe}):
        try:
            payload = _payload(loader.fundamentals(ticker, as_of))
        except Exception:
            continue
        row = _factor_row(ticker, payload)
        if row is not None:
            rows.append(row)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_frame()
    for column in ("net_margin", "fcf_margin", "inverse_leverage"):
        frame[f"{column}_z"] = _zscore(frame[column])
    z_columns = ["net_margin_z", "fcf_margin_z", "inverse_leverage_z"]
    frame["composite_score"] = frame[z_columns].mean(axis=1)
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
    return {
        "ticker": ticker,
        "net_margin": net_income / revenue,
        "fcf_margin": free_cash_flow / revenue,
        "leverage": leverage,
        "inverse_leverage": -leverage,
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
    if value is None:
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


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "net_margin",
            "fcf_margin",
            "leverage",
            "inverse_leverage",
            "net_margin_z",
            "fcf_margin_z",
            "inverse_leverage_z",
            "composite_score",
        ]
    )
