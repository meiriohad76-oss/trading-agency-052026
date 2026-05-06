from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import polars as pl

from agency.provenance import Provenanced

from .exceptions import DataNotAvailableAt
from .manifest import DatasetName
from .records import provenance_from_row, rows


def fundamentals_from_frame(
    frame: pl.DataFrame,
    *,
    as_of: date,
) -> Provenanced[dict[str, object]]:
    if frame.is_empty():
        raise DataNotAvailableAt(DatasetName.SEC_COMPANY_FACTS.value, as_of, "no rows matched")
    latest_by_metric: dict[str, Mapping[str, object]] = {}
    sorted_rows = rows(
        frame.sort(["metric", "__as_of", "__period_end"], descending=[False, True, True])
    )
    for row in sorted_rows:
        latest_by_metric.setdefault(str(row["metric"]), row)
    payload = {metric: row["value"] for metric, row in latest_by_metric.items()}
    newest_row = rows(frame.sort("__as_of", descending=True).head(1))[0]
    return Provenanced[dict[str, object]](
        value=payload,
        provenance=provenance_from_row(newest_row),
    )


def institutional_holdings_from_frame(
    frame: pl.DataFrame,
    *,
    ticker: str,
    as_of: date,
) -> Provenanced[dict[str, object]]:
    frame = frame.filter(pl.col("__quarter_end") <= as_of)
    if frame.is_empty():
        raise DataNotAvailableAt(
            DatasetName.SEC_13F.value,
            as_of,
            f"no rows matched {ticker.upper()}",
        )
    latest_quarter = frame.get_column("__quarter_end").max()
    quarter = frame.filter(pl.col("__quarter_end") == latest_quarter)
    row = rows(quarter.sort("__as_of", descending=True).head(1))[0]
    payload: dict[str, object] = {
        "ticker": ticker.upper(),
        "quarter_end_date": latest_quarter,
        "holder_count": quarter.get_column("filer_cik").n_unique(),
        "total_shares_held": quarter.get_column("shares_held").sum(),
        "total_change_from_prev_quarter": quarter.get_column("change_from_prev_quarter").sum(),
    }
    return Provenanced[dict[str, object]](value=payload, provenance=provenance_from_row(row))
