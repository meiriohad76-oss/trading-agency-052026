from __future__ import annotations

from statistics.turnover_costs import apply_costs

import pandas as pd
import pytest

PER_SIDE_BPS = 5.0
ROUND_TRIP_COST = 0.001


def test_apply_costs_uses_one_sided_turnover_and_per_side_bps() -> None:
    returns = pd.Series([0.010, -0.020], index=pd.Index(["p1", "p2"]), name="returns")
    turnover = pd.Series([1.0, 0.5], index=returns.index)

    adjusted = apply_costs(returns, turnover, PER_SIDE_BPS)

    assert adjusted.to_list() == pytest.approx([0.010 - ROUND_TRIP_COST, -0.020 - 0.0005])
    assert adjusted.name == "returns"


def test_apply_costs_aligns_inputs_by_index() -> None:
    returns = pd.Series([0.01, 0.02], index=pd.Index(["keep", "drop"]))
    turnover = pd.Series([1.0], index=pd.Index(["keep"]))

    adjusted = apply_costs(returns, turnover, PER_SIDE_BPS)

    assert adjusted.index.to_list() == ["keep"]


def test_apply_costs_rejects_negative_costs() -> None:
    with pytest.raises(ValueError, match="bps"):
        apply_costs(pd.Series([0.01]), pd.Series([1.0]), -1.0)
