"""Research evaluation utilities."""

from .h1_ic import H1ICConfig, H1ICReport, evaluate_signal_ic
from .verdicts import (
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)

__all__ = [
    "H1ICConfig",
    "H1ICReport",
    "evaluate_signal_ic",
    "summarize_signal_verdicts",
    "synthesize_horizon_verdicts",
    "verdicts_to_markdown",
]
