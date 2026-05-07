from __future__ import annotations

import pandas as pd
import pytest
from evaluation.h3_llm_comparison import llm_ab_summary_to_markdown, summarize_llm_ab

EXPECTED_REPEATS = 2


def test_summarize_llm_ab_reports_mean_deltas_and_survival_verdict() -> None:
    summary = summarize_llm_ab(
        _ab_frame(
            deterministic={"sharpe": 1.0, "cagr": 0.12, "max_drawdown": -0.10, "turnover": 2.0},
            reviewed=[
                {"sharpe": 1.12, "cagr": 0.14, "max_drawdown": -0.09, "turnover": 1.8},
                {"sharpe": 1.08, "cagr": 0.13, "max_drawdown": -0.10, "turnover": 1.6},
            ],
        )
    )
    row = summary.iloc[0]

    assert row["reviewed_repeats"] == EXPECTED_REPEATS
    assert row["sharpe_delta"] == pytest.approx(0.10)
    assert row["cagr_delta"] == pytest.approx(0.015)
    assert row["verdict"] == "llm_survives"


def test_summarize_llm_ab_marks_negative_delta_as_deterministic_only() -> None:
    summary = summarize_llm_ab(
        _ab_frame(
            deterministic={"sharpe": 1.0, "cagr": 0.12, "max_drawdown": -0.10, "turnover": 2.0},
            reviewed=[
                {"sharpe": 0.95, "cagr": 0.11, "max_drawdown": -0.12, "turnover": 2.1},
            ],
        )
    )

    assert summary.iloc[0]["verdict"] == "deterministic_only"


def test_llm_ab_summary_to_markdown_renders_compact_report() -> None:
    summary = summarize_llm_ab(
        _ab_frame(
            deterministic={"sharpe": 1.0, "cagr": 0.12, "max_drawdown": -0.10, "turnover": 2.0},
            reviewed=[
                {"sharpe": 1.08, "cagr": 0.13, "max_drawdown": -0.09, "turnover": 1.8},
            ],
        )
    )

    markdown = llm_ab_summary_to_markdown(summary)

    assert "| Sharpe | 1.0000 | 1.0800 | 0.0800 |" in markdown
    assert "Verdict: `llm_survives` across 1 reviewed repeat(s)." in markdown


def test_summarize_llm_ab_requires_one_deterministic_row() -> None:
    with pytest.raises(ValueError, match="exactly one deterministic"):
        summarize_llm_ab(
            pd.DataFrame(
                [
                    {
                        "variant": "deterministic",
                        "repeat": 0,
                        "sharpe": 1.0,
                        "cagr": 0.10,
                        "max_drawdown": -0.10,
                        "turnover": 1.0,
                    },
                    {
                        "variant": "deterministic",
                        "repeat": 1,
                        "sharpe": 1.1,
                        "cagr": 0.11,
                        "max_drawdown": -0.09,
                        "turnover": 1.2,
                    },
                ]
            )
        )


def _ab_frame(
    *,
    deterministic: dict[str, float],
    reviewed: list[dict[str, float]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = [{"variant": "deterministic", "repeat": 0, **deterministic}]
    rows.extend(
        {"variant": "reviewed", "repeat": index, **row} for index, row in enumerate(reviewed)
    )
    return pd.DataFrame(rows)
