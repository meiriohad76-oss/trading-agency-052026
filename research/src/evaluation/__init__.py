"""Research evaluation utilities."""

from .combination import SignalWeight, combine_signal_scores, combined_signal_fn, weights_from_ic
from .h1_ic import H1ICConfig, H1ICReport, evaluate_signal_ic
from .llm_ab import ReviewDecision, reviewed_signal_fn, run_llm_ab
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
    "ReviewDecision",
    "SignalWeight",
    "StrategyProfile",
    "SweepPoint",
    "best_by_sharpe",
    "combined_signal_fn",
    "combine_signal_scores",
    "evaluate_signal_ic",
    "profile_strategy",
    "profile_to_frame",
    "reviewed_signal_fn",
    "run_llm_ab",
    "run_parameter_sweep",
    "summarize_signal_verdicts",
    "synthesize_horizon_verdicts",
    "threshold_signal",
    "verdicts_to_markdown",
    "weights_from_ic",
]
