"""Determine which view module(s) import each patchable runtime dependency."""
import pathlib

VIEWS = pathlib.Path("src/agency/views")
DASH = pathlib.Path("src/agency/dashboard.py")

PATCHABLE = [
    "runtime_selection_reports",
    "runtime_data_source_status",
    "runtime_risk_decisions",
    "runtime_candidate_timeline",
    "human_review_events_for_reports",
    "broker_status_context",
    "build_and_persist_human_review_event",
    "enrich_signal_rows_with_evidence",
    "get_session",
    "load_lane_promotion_status",
    "load_live_config_readiness",
    "load_market_regime_snapshot",
    "load_data_refresh_progress",
    "load_data_load_status",
]

files = {p.stem: p for p in VIEWS.glob("*.py")}
files["dashboard"] = DASH

for name in PATCHABLE:
    holders = []
    for mod, path in files.items():
        txt = path.read_text(encoding="utf-8")
        # imported at top-level (appears in an import line) OR defined as a function
        for line in txt.splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")) and (
                f" {name}," in line or f" {name}\n" in line + "\n"
                or line.rstrip().endswith(f" {name}") or f"({name}" in line
                or f", {name}" in line
            ):
                holders.append(mod)
                break
            if s.startswith((f"def {name}(", f"async def {name}(")):
                holders.append(mod + "(def)")
                break
    print(f"{name}: {holders}")
