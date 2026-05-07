from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "src"))
sys.path.insert(0, str(ROOT / "src"))

from evaluation.h3_llm_comparison import (  # noqa: E402
    llm_ab_summary_to_markdown,
    summarize_llm_ab,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize H3 LLM A/B results.")
    parser.add_argument("--input", type=Path, required=True, help="CSV or parquet from run_llm_ab.")
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args()

    results = _read_frame(args.input)
    markdown = llm_ab_summary_to_markdown(summarize_llm_ab(results))
    if args.output_md is not None:
        args.output_md.parent.mkdir(parents=True, exist_ok=True)
        args.output_md.write_text(markdown, encoding="utf-8")
    print(markdown)


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


if __name__ == "__main__":
    main()
