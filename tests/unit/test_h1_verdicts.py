from __future__ import annotations

import pandas as pd
from evaluation.verdicts import (
    summarize_signal_verdicts,
    synthesize_horizon_verdicts,
    verdicts_to_markdown,
)

EXPECTED_FLAT_BH_P_VALUE = 0.5


def test_synthesize_horizon_verdicts_applies_corrections_and_row_verdicts() -> None:
    verdicts = synthesize_horizon_verdicts(
        _ic_rows(),
        alpha=0.05,
        min_observations=10,
        min_abs_ic=0.01,
    )

    assert verdicts["p_value_bonferroni"].to_list() == [0.004, 0.004, 1.0, 0.004]
    assert verdicts["verdict"].to_list() == [
        "survive",
        "inverse_candidate",
        "drop",
        "inconclusive",
    ]
    assert verdicts["p_value_bh"].iloc[2] == EXPECTED_FLAT_BH_P_VALUE


def test_summarize_signal_verdicts_chooses_strongest_available_horizon() -> None:
    verdicts = synthesize_horizon_verdicts(
        pd.concat(
            [
                _ic_rows(),
                pd.DataFrame(
                    [
                        _row("weak_edge", 20, 0.005, 0.3, 30, 0.80),
                        _row("weak_edge", 5, 0.0, 0.0, 30, 0.90),
                    ]
                ),
            ],
            ignore_index=True,
        ),
        alpha=0.05,
        min_observations=10,
        min_abs_ic=0.01,
    )

    summary = summarize_signal_verdicts(verdicts)

    assert summary.set_index("signal").loc["positive", "verdict"] == "survive"
    assert summary.set_index("signal").loc["negative", "verdict"] == "inverse_candidate"
    assert summary.set_index("signal").loc["weak_edge", "verdict"] == "drop"


def test_verdicts_to_markdown_renders_compact_table() -> None:
    verdicts = synthesize_horizon_verdicts(_ic_rows(), min_observations=10)
    markdown = verdicts_to_markdown(summarize_signal_verdicts(verdicts))

    assert "| signal | best_horizon |" in markdown
    assert "positive" in markdown


def _ic_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row("positive", 5, 0.04, 3.5, 30, 0.001),
            _row("negative", 5, -0.04, -3.5, 30, 0.001),
            _row("flat", 5, 0.0, 0.0, 30, 0.5),
            _row("underpowered", 5, 0.05, 3.0, 3, 0.001),
        ]
    )


def _row(
    signal: str,
    horizon: int,
    mean_ic: float,
    t_stat: float,
    n_observations: int,
    p_value: float,
) -> dict[str, object]:
    return {
        "signal": signal,
        "horizon": horizon,
        "mean_ic": mean_ic,
        "ic_std": 0.02,
        "t_stat": t_stat,
        "information_ratio": mean_ic / 0.02 if mean_ic else 0.0,
        "n_observations": n_observations,
        "p_value": p_value,
    }
