from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from agency.db import get_session
from agency.runtime import structured_log
from agency.services import build_runtime_cycle_from_payload, persist_runtime_cycle
from agency.services.runtime_audit import now_utc_text


async def main() -> None:
    args = _parse_args()
    started_at = now_utc_text()
    cycle = build_runtime_cycle_from_payload(_load_payload(args.input))
    async with get_session() as session:
        await persist_runtime_cycle(
            session,
            cycle,
            audit_trigger="MANUAL",
            audit_started_at=started_at,
            audit_finished_at=now_utc_text(),
        )
        await session.commit()
    print(
        structured_log(
            "agency_cycle_completed",
            cycle_id=cycle.cycle_id,
            evidence_pack_count=len(cycle.evidence_packs),
            selection_report_count=len(cycle.selection_reports),
            risk_decision_count=len(cycle.risk_decisions),
            execution_preview_count=len(cycle.execution_previews),
        )
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one local paper agency cycle.")
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="JSON payload with cycle_id, as_of, generated_at, source_health, signals.",
    )
    return parser.parse_args()


def _load_payload(path: Path) -> Mapping[str, object]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError("cycle input JSON must be an object")
    return cast(Mapping[str, object], payload)


if __name__ == "__main__":
    asyncio.run(main())
