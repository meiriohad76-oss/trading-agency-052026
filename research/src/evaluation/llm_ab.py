from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
from backtests.scoped_loader import LoaderLike, SignalFn
from backtests.walk_forward import WalkForwardConfig
from evaluation.profile import profile_strategy, profile_to_frame


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool = True
    score_multiplier: float = 1.0
    reason: str = ""


ReviewFn = Callable[[date, str, float, dict[str, object]], ReviewDecision]
EvidenceFn = Callable[[date, str, LoaderLike], dict[str, object]]


def reviewed_signal_fn(
    signal_fn: SignalFn,
    reviewer: ReviewFn,
    evidence_fn: EvidenceFn | None = None,
) -> SignalFn:
    """Wrap deterministic scores with a mockable qualitative review step."""

    def signal(as_of: date, universe: set[str], loader: LoaderLike) -> dict[str, float]:
        scores = signal_fn(as_of, universe, loader)
        reviewed: dict[str, float] = {}
        for ticker, score in sorted(scores.items()):
            evidence = {} if evidence_fn is None else evidence_fn(as_of, ticker, loader)
            decision = reviewer(as_of, ticker, score, evidence)
            if decision.approved and decision.score_multiplier != 0.0:
                reviewed[ticker] = score * decision.score_multiplier
        return reviewed

    return signal


def run_llm_ab(
    *,
    name: str,
    config: WalkForwardConfig,
    loader: LoaderLike,
    signal_fn: SignalFn,
    reviewer: ReviewFn,
    start: date,
    end: date,
    repeats: int = 1,
) -> pd.DataFrame:
    """Compare deterministic-only and reviewed walk-forward profiles."""
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    rows = [
        _profile_row(
            name=f"{name}:deterministic",
            variant="deterministic",
            repeat=0,
            config=config,
            loader=loader,
            signal_fn=signal_fn,
            start=start,
            end=end,
        )
    ]
    reviewed_fn = reviewed_signal_fn(signal_fn, reviewer)
    for repeat in range(repeats):
        rows.append(
            _profile_row(
                name=f"{name}:reviewed:{repeat}",
                variant="reviewed",
                repeat=repeat,
                config=config,
                loader=loader,
                signal_fn=reviewed_fn,
                start=start,
                end=end,
            )
        )
    return pd.concat(rows, ignore_index=True)


def _profile_row(
    *,
    name: str,
    variant: str,
    repeat: int,
    config: WalkForwardConfig,
    loader: LoaderLike,
    signal_fn: SignalFn,
    start: date,
    end: date,
) -> pd.DataFrame:
    frame = profile_to_frame(
        profile_strategy(
            name=name,
            config=config,
            loader=loader,
            signal_fn=signal_fn,
            start=start,
            end=end,
        )
    )
    frame["variant"] = variant
    frame["repeat"] = repeat
    return frame
