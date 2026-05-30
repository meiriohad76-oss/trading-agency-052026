from __future__ import annotations

from collections.abc import Mapping
from datetime import date

import polars as pl

from agency.provenance import Provenanced

from .exceptions import DataNotAvailableAt
from .manifest import DatasetName
from .records import provenance_from_row, rows

_MONETARY_METRICS = frozenset(
    {
        "revenue",
        "net_income",
        "operating_cash_flow",
        "capital_expenditures",
        "free_cash_flow",
        "total_assets",
        "total_liabilities",
        "gross_profit",
        "operating_income",
        "ebitda",
        "depreciation_amortization",
        "research_development",
        "interest_expense",
        "income_tax_expense",
        "current_assets",
        "current_liabilities",
        "long_term_debt",
        "cash_and_equivalents",
        "total_equity",
        "retained_earnings",
    }
)
_BASE_REQUIRED_ANCHOR_METRICS = frozenset({"revenue", "net_income", "free_cash_flow"})
_OPTIONAL_REVENUE_NUMERATORS = frozenset({"gross_profit", "operating_income", "ebitda"})
_QUARTERLY_PERIODS = frozenset({"Q1", "Q2", "Q3", "Q4"})


def fundamentals_from_frame(
    frame: pl.DataFrame,
    *,
    as_of: date,
) -> Provenanced[dict[str, object]]:
    if frame.is_empty():
        raise DataNotAvailableAt(DatasetName.SEC_COMPANY_FACTS.value, as_of, "no rows matched")
    clean = _drop_wrong_units(frame)
    if clean.is_empty():
        raise DataNotAvailableAt(
            DatasetName.SEC_COMPANY_FACTS.value,
            as_of,
            "no rows left after unit validation",
        )
    candidates = _deduplicated_rows(clean)
    required_metrics = _required_anchor_metrics(candidates)
    anchor_rows = _anchor_rows(candidates, required_metrics)
    if not anchor_rows:
        required = ", ".join(sorted(required_metrics))
        raise DataNotAvailableAt(
            DatasetName.SEC_COMPANY_FACTS.value,
            as_of,
            f"no consistent fiscal period with required metrics: {required}",
        )
    payload = {str(row["metric"]): row["value"] for row in anchor_rows}
    newest_row = max(anchor_rows, key=_row_recency_key)
    return Provenanced[dict[str, object]](
        value=payload,
        provenance=provenance_from_row(newest_row),
    )


def fundamentals_history_frame(
    frame: pl.DataFrame,
    *,
    as_of: date,
    n_periods: int = 8,
) -> pl.DataFrame:
    if frame.is_empty() or n_periods <= 0:
        return _empty_fundamentals_history_frame()
    clean = _drop_wrong_units(frame)
    if clean.is_empty():
        return _empty_fundamentals_history_frame()
    candidates = _deduplicated_rows(clean)
    groups = _period_groups(candidates)
    if not groups:
        return _empty_fundamentals_history_frame()
    quarterly_keys = [key for key in groups if key[1] in _QUARTERLY_PERIODS]
    pool = quarterly_keys or list(groups)
    selected_keys = sorted(
        sorted(pool, key=lambda key: (key[0] or date.min, key[2], key[1]), reverse=True)[
            :n_periods
        ],
        key=lambda key: (key[0] or date.min, key[2], key[1]),
    )
    output: list[dict[str, object]] = []
    for key in selected_keys:
        for row in sorted(groups[key], key=lambda item: str(item["metric"])):
            output.append(
                {
                    "metric": str(row["metric"]),
                    "value": row["value"],
                    "period_end": row.get("__period_end"),
                    "fiscal_period": row.get("fiscal_period"),
                    "form": row.get("form"),
                    "filing_date": row.get("filing_date"),
                    "source_id": row.get("source_id"),
                }
            )
    if not output:
        return _empty_fundamentals_history_frame()
    return pl.DataFrame(
        output,
        schema_overrides={
            "period_end": pl.Date,
            "filing_date": pl.Date,
        },
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


def _drop_wrong_units(frame: pl.DataFrame) -> pl.DataFrame:
    if "unit" not in frame.columns:
        return frame
    return frame.filter(
        (~pl.col("metric").is_in(list(_MONETARY_METRICS))) | (pl.col("unit") == "USD")
    )


def _deduplicated_rows(frame: pl.DataFrame) -> list[Mapping[str, object]]:
    best_by_key: dict[tuple[str, object, str, str], Mapping[str, object]] = {}
    for row in rows(frame):
        metric = str(row["metric"])
        key = (
            metric,
            row.get("__period_end"),
            str(row.get("fiscal_period") or ""),
            _form_family(row.get("form")),
        )
        existing = best_by_key.get(key)
        if existing is None or _row_recency_key(row) > _row_recency_key(existing):
            best_by_key[key] = row
    return list(best_by_key.values())


def _required_anchor_metrics(candidates: list[Mapping[str, object]]) -> frozenset[str]:
    available = {str(row["metric"]) for row in candidates}
    required = set(_BASE_REQUIRED_ANCHOR_METRICS & available)
    required.update(_OPTIONAL_REVENUE_NUMERATORS & available)
    return frozenset(required)


def _anchor_rows(
    candidates: list[Mapping[str, object]],
    required_metrics: frozenset[str],
) -> list[Mapping[str, object]]:
    if not required_metrics:
        return []
    by_group = _period_groups(candidates)
    complete: list[tuple[object, str, str]] = []
    for key, group_rows in by_group.items():
        metrics = {str(row["metric"]) for row in group_rows}
        if required_metrics.issubset(metrics):
            complete.append(key)
    if not complete:
        return []
    quarterly = [key for key in complete if key[1] in _QUARTERLY_PERIODS]
    pool = quarterly or complete
    best_key = max(pool, key=lambda key: (key[0] or date.min, key[2], key[1]))
    return sorted(by_group[best_key], key=lambda row: str(row["metric"]))


def _period_groups(
    candidates: list[Mapping[str, object]],
) -> dict[tuple[object, str, str], list[Mapping[str, object]]]:
    by_group: dict[tuple[object, str, str], list[Mapping[str, object]]] = {}
    for row in candidates:
        key = (
            row.get("__period_end"),
            str(row.get("fiscal_period") or ""),
            _form_family(row.get("form")),
        )
        by_group.setdefault(key, []).append(row)
    return by_group


def _form_family(form: object) -> str:
    return str(form or "").upper().replace("/A", "")


def _amendment_rank(form: object) -> int:
    return 1 if str(form or "").upper().endswith("/A") else 0


def _row_recency_key(row: Mapping[str, object]) -> tuple[int, object, object, object]:
    return (
        _amendment_rank(row.get("form")),
        row.get("__as_of") or date.min,
        row.get("filing_date") or date.min,
        row.get("__period_end") or date.min,
    )


def _empty_fundamentals_history_frame() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "metric": pl.Utf8,
            "value": pl.Float64,
            "period_end": pl.Date,
            "fiscal_period": pl.Utf8,
            "form": pl.Utf8,
            "filing_date": pl.Date,
            "source_id": pl.Utf8,
        }
    )
