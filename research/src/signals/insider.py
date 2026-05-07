from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any, Protocol, cast

import pandas as pd

DEFAULT_LOOKBACK_DAYS = 90
MIN_CROSS_SECTION = 2
BUY_TRANSACTION_CODES = frozenset({"P"})
SELL_TRANSACTION_CODES = frozenset({"S"})


class InsiderTransactionsLoader(Protocol):
    def insider_transactions(
        self,
        ticker: str,
        as_of: date,
        lookback_days: int,
    ) -> Sequence[object]: ...


def insider_score(
    as_of: date,
    universe: set[str],
    loader: InsiderTransactionsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, float]:
    """Return a PIT-safe insider buying/selling score per ticker."""
    frame = insider_factor_frame(as_of, universe, loader, lookback_days=lookback_days)
    scores: dict[str, float] = {}
    for row in frame.itertuples(index=False):
        score = _float(row.insider_score)
        if score is not None and pd.notna(score):
            scores[str(row.ticker)] = score
    return scores


def insider_factor_frame(
    as_of: date,
    universe: Iterable[str],
    loader: InsiderTransactionsLoader,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Build the Form 4 insider activity cross-section known at `as_of`."""
    if lookback_days < 1:
        raise ValueError("lookback_days must be >= 1")
    rows = []
    for ticker in sorted({item.upper() for item in universe}):
        try:
            transactions = loader.insider_transactions(ticker, as_of, lookback_days)
        except Exception:
            continue
        rows.append(_factor_row(ticker, transactions))
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_frame()
    frame["insider_score"] = _zscore(frame["net_transaction_value"])
    return frame.sort_values(["insider_score", "ticker"], ascending=[False, True]).reset_index(
        drop=True
    )


def _factor_row(ticker: str, transactions: Sequence[object]) -> dict[str, object]:
    buy_value = 0.0
    sell_value = 0.0
    net_shares = 0.0
    directional_count = 0
    filers: set[str] = set()
    for transaction in transactions:
        payload = _payload(transaction)
        direction = _direction(payload.get("transaction_type"))
        shares = _positive_float(payload.get("shares"))
        if direction is None or shares is None:
            continue
        price = _positive_float(payload.get("price"))
        value = shares * price if price is not None else shares
        if direction > 0:
            buy_value += value
        else:
            sell_value += value
        net_shares += direction * shares
        directional_count += 1
        filer = _optional_str(payload.get("filer_cik")) or _optional_str(payload.get("filer_name"))
        if filer is not None:
            filers.add(filer)
    net_value = buy_value - sell_value
    return {
        "ticker": ticker,
        "buy_value": buy_value,
        "sell_value": sell_value,
        "net_transaction_value": net_value,
        "net_shares": net_shares,
        "directional_transactions": directional_count,
        "unique_filers": len(filers),
    }


def _direction(value: object) -> int | None:
    code = _optional_str(value)
    if code is None:
        return None
    code = code.upper()
    if code in BUY_TRANSACTION_CODES:
        return 1
    if code in SELL_TRANSACTION_CODES:
        return -1
    return None


def _payload(value: object) -> dict[str, object]:
    payload = cast(Any, value).value if hasattr(value, "value") else value
    if not isinstance(payload, dict):
        raise TypeError("insider transaction payload must be a dict")
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


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    parsed = str(value).strip()
    return parsed or None


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "ticker",
            "buy_value",
            "sell_value",
            "net_transaction_value",
            "net_shares",
            "directional_transactions",
            "unique_filers",
            "insider_score",
        ]
    )
