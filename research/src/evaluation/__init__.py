"""Research evaluation utilities."""

from .h1_ic import H1ICConfig, H1ICReport, evaluate_signal_ic
from .profile import StrategyProfile, profile_strategy, profile_to_frame
from .sweep import SweepPoint, best_by_sharpe, run_parameter_sweep, threshold_signal
from .verdicts import (
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)

__all__ = [
    "H1ICConfig",
    "H1ICReport",
    "StrategyProfile",
    "SweepPoint",
    "best_by_sharpe",
    "evaluate_signal_ic",
    "profile_strategy",
    "profile_to_frame",
    "run_parameter_sweep",
    "summarize_signal_verdicts",
    "synthesize_horizon_verdicts",
    "threshold_signal",
    "verdicts_to_markdown",
]
