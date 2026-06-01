from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime

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
    period_end = _period_end(newest_row)
    payload.update(
        {
            "filing_period": newest_row.get("fiscal_period"),
            "filing_year": newest_row.get("fiscal_year") or _year_from_dateish(period_end),
            "filing_form": newest_row.get("form"),
            "filing_period_end": period_end,
            "period_alignment_status": "aligned",
            "quality_score_basis": "period_aligned_only",
        }
    )
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
                    "period_end": _period_end(row),
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
    total_shares = _column_sum(quarter, "shares_held") or 0.0
    total_change = _column_sum(quarter, "change_from_prev_quarter") or 0.0
    previous_shares = total_shares - total_change
    total_value = _column_sum(quarter, "value_usd_thousands")
    payload: dict[str, object] = {
        "ticker": ticker.upper(),
        "quarter_end_date": latest_quarter,
        "holder_count": quarter.get_column("filer_cik").n_unique(),
        "total_shares_held": total_shares,
        "previous_shares_held": previous_shares,
        "total_change_from_prev_quarter": total_change,
        "net_change_current_share_ratio": _safe_ratio(total_change, total_shares),
        "net_change_prior_share_ratio": _safe_ratio(total_change, previous_shares),
        "holder_changes": _holder_changes(quarter),
    }
    if total_value is not None:
        payload["total_value_usd_thousands"] = total_value
        payload["implied_value_per_share"] = _implied_value_per_share(total_value, total_shares)
    return Provenanced[dict[str, object]](value=payload, provenance=provenance_from_row(row))


def _holder_changes(frame: pl.DataFrame) -> list[dict[str, object]]:
    holders: dict[str, dict[str, object]] = {}
    frame_rows = rows(frame)
    use_filer_names = _has_reliable_filer_names(frame_rows)
    for row in frame_rows:
        holder_cik = _clean_text(row.get("filer_cik")) or "unknown"
        holder = holders.setdefault(
            holder_cik,
            {
                "holder_cik": holder_cik,
                "holder_name": _holder_name(row, use_filer_name=use_filer_names),
                "current_shares": 0.0,
                "previous_shares": 0.0,
                "change_from_prev_quarter": 0.0,
                "value_usd_thousands": 0.0,
                "source_id": _clean_text(row.get("source_id")),
            },
        )
        current_shares = _float(row.get("shares_held")) or 0.0
        change = _float(row.get("change_from_prev_quarter")) or 0.0
        value = _float(row.get("value_usd_thousands")) or 0.0
        holder["current_shares"] = float(holder["current_shares"]) + current_shares
        holder["previous_shares"] = float(holder["previous_shares"]) + current_shares - change
        holder["change_from_prev_quarter"] = float(holder["change_from_prev_quarter"]) + change
        holder["value_usd_thousands"] = float(holder["value_usd_thousands"]) + value
        if row.get("__as_of") is not None:
            holder["source_id"] = _clean_text(row.get("source_id"))

    output = list(holders.values())
    for holder in output:
        holder["implied_value_per_share"] = _implied_value_per_share(
            float(holder["value_usd_thousands"]),
            float(holder["current_shares"]),
        )
    return sorted(
        output,
        key=lambda item: abs(float(item.get("change_from_prev_quarter") or 0.0)),
        reverse=True,
    )[:5]


def _has_reliable_filer_names(frame_rows: list[Mapping[str, object]]) -> bool:
    if any(_clean_text(row.get("issuer_name")) for row in frame_rows):
        return True
    names = {_clean_text(row.get("filer_name")) for row in frame_rows}
    names.discard(None)
    ciks = {_clean_text(row.get("filer_cik")) for row in frame_rows}
    ciks.discard(None)
    return len(names) > 1 or len(ciks) <= 1


def _holder_name(row: Mapping[str, object], *, use_filer_name: bool) -> str:
    name = (
        _clean_text(row.get("filer_name")) or _clean_text(row.get("holder_name"))
        if use_filer_name
        else None
    )
    issuer_name = _clean_text(row.get("issuer_name"))
    if name and name != issuer_name:
        return name
    return _clean_text(row.get("filer_cik")) or "Unknown holder"


def _column_sum(frame: pl.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    value = frame.get_column(column).sum()
    return _float(value)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator > 0.0 else None


def _implied_value_per_share(value_usd_thousands: float, shares: float) -> float | None:
    return (value_usd_thousands * 1000.0 / shares) if shares > 0.0 else None


def _float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text if text and text.lower() not in {"nan", "none", "nat"} else None


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
            _period_end(row),
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
    best_key = max(pool, key=lambda key: (_date_sort_value(key[0]), key[2], key[1]))
    return sorted(by_group[best_key], key=lambda row: str(row["metric"]))


def _period_groups(
    candidates: list[Mapping[str, object]],
) -> dict[tuple[object, str, str], list[Mapping[str, object]]]:
    by_group: dict[tuple[object, str, str], list[Mapping[str, object]]] = {}
    for row in candidates:
        key = (
            _period_end(row),
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
        _date_sort_value(row.get("__as_of") or row.get("timestamp_as_of")),
        _date_sort_value(row.get("filing_date")),
        _date_sort_value(_period_end(row)),
    )


def _period_end(row: Mapping[str, object]) -> object:
    return row.get("__period_end") or row.get("period_end")


def _date_sort_value(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return date.min
    return date.min


def _year_from_dateish(value: object) -> int | None:
    parsed = _date_sort_value(value)
    return parsed.year if parsed != date.min else None


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
