"""Statistical primitives for hypothesis tests."""

from .forward_returns import compute_forward_returns
from .ic import ICResult, compute_ic, compute_ic_panel
from .multiple_comparisons import (
    benjamini_hochberg_adjust,
    bonferroni_adjust,
)
from .turnover_costs import apply_costs

__all__ = [
    "ICResult",
    "apply_costs",
    "benjamini_hochberg_adjust",
    "bonferroni_adjust",
    "compute_forward_returns",
    "compute_ic",
    "compute_ic_panel",
]
