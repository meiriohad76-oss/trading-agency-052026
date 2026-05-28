from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_run_local_llm_insights_script_writes_disabled_artifact(tmp_path: Path) -> None:
    input_root = tmp_path / "runtime"
    input_root.mkdir()
    (input_root / "evidence-packs.json").write_text("[]", encoding="utf-8")
    (input_root / "selection-reports.json").write_text("[]", encoding="utf-8")
    output_root = tmp_path / "insights"
    env = {**os.environ, "AGENCY_LOCAL_LLM_ENABLED": "false"}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_local_llm_insights.py",
            "--input-root",
            str(input_root),
            "--output-root",
            str(output_root),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads((output_root / "local-llm-insights.json").read_text())
    assert payload["status"] == "disabled"
    assert "Local LLM disabled" in result.stdout


def test_check_local_llm_script_reports_not_configured_without_network() -> None:
    env = {
        **os.environ,
        "AGENCY_LOCAL_LLM_ENABLED": "true",
        "AGENCY_LOCAL_LLM_BASE_URL": "",
        "AGENCY_LOCAL_LLM_API_KEY": "",
        "AGENCY_LOCAL_LLM_MODEL": "",
    }

    result = subprocess.run(
        [sys.executable, "scripts/check_local_llm.py"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["status"] == "not_configured"
