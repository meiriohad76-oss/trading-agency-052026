from __future__ import annotations

from statistics.multiple_comparisons import (
    benjamini_hochberg_adjust,
    bonferroni_adjust,
)

import pytest
from statsmodels.stats.multitest import multipletests

P_VALUES = [0.001, 0.01, 0.02, 0.20]


def test_bonferroni_adjust_matches_statsmodels() -> None:
    expected = multipletests(P_VALUES, method="bonferroni")[1].tolist()

    assert bonferroni_adjust(P_VALUES) == pytest.approx(expected)


def test_benjamini_hochberg_adjust_matches_statsmodels() -> None:
    expected = multipletests(P_VALUES, method="fdr_bh")[1].tolist()

    assert benjamini_hochberg_adjust(P_VALUES) == pytest.approx(expected)


def test_adjusters_reject_invalid_p_values() -> None:
    with pytest.raises(ValueError, match="p-values"):
        bonferroni_adjust([0.1, -0.01])
