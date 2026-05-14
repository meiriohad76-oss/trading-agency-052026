from __future__ import annotations

import pandas as pd


def cusip_map_coverage_check(
    holdings_df: pd.DataFrame,  # 13F holdings with a "cusip" column
    cusip_map: dict[str, str],  # cusip -> ticker
) -> dict[str, object]:
    """Return coverage stats: total holdings, mapped, unmapped, unmapped_cusips list.

    Args:
        holdings_df: DataFrame with a ``cusip`` column (values compared upper-cased).
        cusip_map: Mapping of CUSIP string to ticker symbol.

    Returns:
        dict with keys:
            - ``total`` (int): number of rows in *holdings_df*
            - ``mapped`` (int): rows whose CUSIP appears in *cusip_map*
            - ``unmapped`` (int): rows whose CUSIP is absent from *cusip_map*
            - ``unmapped_cusips`` (list[str]): deduplicated sorted list of unmapped CUSIPs
    """
    if holdings_df.empty or "cusip" not in holdings_df.columns:
        return {
            "total": 0,
            "mapped": 0,
            "unmapped": 0,
            "unmapped_cusips": [],
        }
    cusips = holdings_df["cusip"].astype(str).str.upper()
    in_map = cusips.isin({k.upper() for k in cusip_map})
    total = len(holdings_df)
    mapped = int(in_map.sum())
    unmapped = total - mapped
    unmapped_cusips = sorted(cusips[~in_map].unique().tolist())
    return {
        "total": total,
        "mapped": mapped,
        "unmapped": unmapped,
        "unmapped_cusips": unmapped_cusips,
    }
