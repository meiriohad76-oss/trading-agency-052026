from __future__ import annotations

import asyncio

from agency.db import get_session
from agency.services import persist_demo_runtime_seed


async def main() -> None:
    async with get_session() as session:
        seed = await persist_demo_runtime_seed(session)
        await session.commit()
    print(
        "Seeded demo runtime cycle: "
        f"{len(seed.source_health)} sources, "
        f"{len(seed.selection_reports)} selection reports, "
        f"{len(seed.risk_decisions)} risk decisions, "
        f"{len(seed.execution_previews)} execution previews."
    )


if __name__ == "__main__":
    asyncio.run(main())
