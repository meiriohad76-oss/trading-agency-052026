from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research" / "src"))

from agency.runtime.portfolio_news_agent_bridge import (  # noqa: E402
    export_portfolio_news_agent_events,
)


def main() -> int:
    args = _parse_args()
    result = export_portfolio_news_agent_events(
        root=args.agent_root,
        parquet_path=args.parquet_path,
        manifest_path=args.manifest_path,
        summary_root=args.summary_root,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("status") == "exported" else 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync Portfolio News Agent article summaries into agency evidence.",
    )
    parser.add_argument("--agent-root", type=Path, default=None)
    parser.add_argument(
        "--parquet-path",
        type=Path,
        default=ROOT / "research" / "data" / "parquet" / "subscription_emails.parquet",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=ROOT / "research" / "data" / "manifests" / "subscription_emails.json",
    )
    parser.add_argument(
        "--summary-root",
        type=Path,
        default=ROOT / "research" / "results" / "latest-subscription-emails",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
