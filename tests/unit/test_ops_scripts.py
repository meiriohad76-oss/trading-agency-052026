from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest
from data_refresh.live_config import RefreshConfigOverrides
from data_refresh.types import RefreshBatchConfig
from live_runtime.summary import build_live_runtime_summary
from news.consumption import load_consumed_news_ids, mark_news_consumed
from news.storage import NEWS_COLUMNS
from pit.manifest import DatasetName
from pit_fixtures import member, write_manifest

import scripts.check_local_runtime as local_runtime
import scripts.run_live_runtime_cycle as live_runtime_cycle_script
from agency.services import RuntimeCycleResult, build_human_review_event
from research.scripts import plan_market_aware_refresh
from research.scripts.run_data_refresh_batch import _market_aware_config
from scripts.backup_postgres import default_backup_path, pg_dump_command
from scripts.check_local_runtime import metric_value
from scripts.check_operational_readiness import check_operational_readiness
from scripts.check_paper_review_status import check_paper_review_status
from scripts.check_provider_readiness import check_provider_readiness
from scripts.restore_postgres import psql_restore_command
from scripts.run_first_version_pipeline import (
    StepResult,
    build_pipeline_steps,
    email_ingest_command,
    runtime_cycle_command,
    subscription_email_requires_console,
    write_pipeline_report,
)
from scripts.run_live_runtime_cycle import (
    _human_review_state_index,
    _max_tickers,
    _runtime_as_of,
    _tickers,
)

EXPECTED_SOURCE_HEALTH = 2.0
EXPECTED_REVIEW_QUEUE_COUNT = 4
EXPECTED_REVIEWED_COUNT = 1
EXPECTED_PENDING_COUNT = 3
EXPECTED_RUNTIME_MAX_TICKERS = 250
MASSIVE_OPERATOR_RUNBOOK_PATHS = (
    Path("research/config/full-universe-pull.example.sh"),
    Path("docs/data-batching-strategy.md"),
    Path("docs/data-extraction-strategy.md"),
    Path("docs/phase-status.md"),
    Path("docs/mvp-gap-analysis.md"),
)


def test_live_runtime_cycle_default_output_root_is_canonical_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["run_live_runtime_cycle.py"])

    args = live_runtime_cycle_script._parse_args()

    assert args.output_root == live_runtime_cycle_script.CANONICAL_RUNTIME_OUTPUT_ROOT


def test_live_runtime_cycle_success_finalization_marks_consumed_news_once(
    tmp_path: Path,
) -> None:
    cycle = RuntimeCycleResult(
        cycle_id="cycle-news",
        as_of="2026-05-06T00:00:00+00:00",
        generated_at="2026-05-06T13:31:00+00:00",
        source_health=[],
        evidence_packs=[],
        selection_reports=[],
        selection_lifecycle_events=[],
        risk_decisions=[],
        risk_lifecycle_events=[],
        execution_previews=[],
        execution_lifecycle_events=[],
        news_consumption_items=[
            {"ticker": "AAPL", "source_ids": ["news:aapl:1", "news:aapl:2"]},
            {"ticker": "MSFT", "source_ids": ["news:msft:1"]},
        ],
    )
    summary = build_live_runtime_summary(cycle, persisted=True)
    ledger_path = tmp_path / "state" / "news_rss_consumed.json"

    live_runtime_cycle_script._finalize_successful_cycle_outputs(
        cycle=cycle,
        summary=summary,
        output_root=tmp_path / "runtime",
        news_consumption_ledger_path=ledger_path,
    )
    live_runtime_cycle_script._finalize_successful_cycle_outputs(
        cycle=cycle,
        summary=summary,
        output_root=tmp_path / "runtime",
        news_consumption_ledger_path=ledger_path,
    )

    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert sorted(ledger["items"]) == ["news:aapl:1", "news:aapl:2", "news:msft:1"]
    assert ledger["items"]["news:aapl:1"]["cycle_id"] == "cycle-news"
    assert ledger["items"]["news:aapl:1"]["ticker"] == "AAPL"


def test_news_consumption_ledger_is_canonical_done_marker(tmp_path: Path) -> None:
    ledger_path = tmp_path / "state" / "news_rss_consumed.json"

    written = mark_news_consumed(
        ledger_path,
        cycle_id="cycle-news",
        as_of="2026-05-22T00:00:00+00:00",
        used_at="2026-05-22T13:30:00+00:00",
        items=[
            {
                "ticker": "AAPL",
                "source_ids": ["news:aapl:1", "news:aapl:1"],
                "raw_source_ids": ["raw:aapl:1", "raw:aapl:1"],
            }
        ],
    )

    assert written == 1
    assert load_consumed_news_ids(ledger_path) == {"news:aapl:1"}
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["items"]["news:aapl:1"]["raw_source_id"] == "raw:aapl:1"
    assert "processed" not in NEWS_COLUMNS
    assert "done" not in NEWS_COLUMNS


def test_default_backup_path_uses_timestamped_postgres_directory() -> None:
    path = default_backup_path(datetime(2026, 5, 8, 10, 30, 5, tzinfo=UTC))

    assert path.as_posix() == "backups/postgres/agency-20260508-103005.sql.gz"


def test_market_aware_plan_args_include_stock_trade_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["plan_market_aware_refresh.py", "--stock-trades-order", "desc"],
    )

    args = plan_market_aware_refresh._parse_args()

    assert args.stock_trades_order == "desc"


def test_market_aware_plan_args_include_news_resolution_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "plan_market_aware_refresh.py",
            "--news-ticker-aliases",
            "research/config/news-ticker-aliases.local.json",
            "--news-resolve-generic-tickers",
            "--news-resolution-min-confidence",
            "0.82",
            "--no-news-keep-unresolved-generic",
        ],
    )

    args = plan_market_aware_refresh._parse_args()

    assert args.news_ticker_aliases == Path(
        "research/config/news-ticker-aliases.local.json"
    )
    assert args.news_resolve_generic_tickers is True
    assert args.news_resolution_min_confidence == 0.82
    assert args.news_keep_unresolved_generic is False


def test_backup_command_targets_local_postgres_container() -> None:
    command = pg_dump_command(
        container="trading-agency-postgres",
        database="agency",
        user="postgres",
    )

    assert command == [
        "docker",
        "exec",
        "trading-agency-postgres",
        "pg_dump",
        "--username",
        "postgres",
        "--dbname",
        "agency",
        "--format",
        "plain",
        "--clean",
        "--if-exists",
    ]


def test_restore_command_reads_sql_from_stdin() -> None:
    command = psql_restore_command(
        container="trading-agency-postgres",
        database="agency",
        user="postgres",
    )

    assert command == [
        "docker",
        "exec",
        "--interactive",
        "trading-agency-postgres",
        "psql",
        "--username",
        "postgres",
        "--dbname",
        "agency",
        "--set",
        "ON_ERROR_STOP=on",
    ]


def test_start_dev_respects_dotenv_database_url_before_sqlite_fallback() -> None:
    script = Path("scripts/start_dev.ps1").read_text(encoding="utf-8")

    assert "Get-DotEnvValue" in script
    assert "$env:DATABASE_URL = $DotEnvDatabaseUrl" in script
    assert "DATABASE_URL is configured from .env" in script


def test_start_dev_restarts_existing_trading_agency_server() -> None:
    script = Path("scripts/start_dev.ps1").read_text(encoding="utf-8")

    assert "Stop-ExistingTradingAgencyServers" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "uvicorn agency\\.app:app" in script
    assert "run_local_app\\.py" in script
    assert "Stop-Process -Id $process.ProcessId" in script
    assert "Existing Trading Agency server process" in script
    assert "Trading Agency is already running" not in script


def test_agency_app_imports_without_external_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, "-c", "import agency.app"],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_legacy_direct_local_app_entrypoint_removed() -> None:
    assert not Path("scripts/run_local_app.py").exists()


def test_start_local_runtime_requires_explicit_demo_seed() -> None:
    script = Path("scripts/start_local_runtime.ps1").read_text(encoding="utf-8")

    assert "[switch]$SeedDemo" in script
    assert "if ($SeedDemo)" in script
    assert "seed_demo_runtime.py" in script
    assert "$SkipSeed" not in script


def test_start_local_runtime_restarts_existing_trading_agency_server() -> None:
    script = Path("scripts/start_local_runtime.ps1").read_text(encoding="utf-8")

    assert "Stop-ExistingTradingAgencyServers" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "uvicorn agency\\.app:app" in script
    assert "run_local_app\\.py" in script
    assert "Stop-Process -Id $process.ProcessId" in script
    assert "Local runtime is already running" not in script


def test_operator_massive_stock_trade_runbooks_use_lane_model() -> None:
    forbidden_lines: list[str] = []
    for path in MASSIVE_OPERATOR_RUNBOOK_PATHS:
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if "--full-universe" in line or "--allow-long-window" in line:
                forbidden_lines.append(f"{path}:{line_number}: {line.strip()}")

    assert forbidden_lines == []

    runbook = Path("research/config/full-universe-pull.example.sh").read_text(
        encoding="utf-8"
    )
    assert "backfill_massive_stock_trades.py" in runbook
    assert "massive_backtest_trade_tape" in runbook
    assert "pull_massive_stock_trades.py" in runbook
    assert "massive_live_trade_slices" in runbook
    assert "massive_premarket_trade_slices" in runbook
    assert "--lane-id" in runbook


def test_live_massive_puller_help_does_not_advertise_disabled_bypass_flags() -> None:
    script = Path("research/scripts/pull_massive_stock_trades.py").read_text(
        encoding="utf-8"
    )

    assert "Disable all safety limits" not in script
    assert "Bypass the direct live-refresh safety guard" not in script
    assert "Only use when the API key has no daily request limits." not in script


def test_metric_value_parses_prometheus_gauge() -> None:
    metrics = "# HELP demo Demo\nagency_source_health_total 2\n"

    assert metric_value(metrics, "agency_source_health_total") == EXPECTED_SOURCE_HEALTH


def test_check_local_runtime_records_route_budget_timings() -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        payload: object
        if path == "/health":
            payload = {"status": "ok"}
        elif path in {"/reports/selection", "/risk/decisions"}:
            payload = [{"ticker": "AAPL"}]
        elif path == "/api/cockpit":
            payload = {"candidates": [{"ticker": "AAPL"}]}
        else:
            raise AssertionError(path)
        return _timed_payload(path=path, payload=payload)

    def fake_fetch_text(_base_url: str, path: str) -> dict[str, object]:
        if path == "/metrics":
            return _timed_payload(
                path=path,
                payload="# HELP demo Demo\nagency_source_health_total 2\n",
            )
        if path == "/":
            return _timed_payload(path=path, payload="<html>Command</html>")
        if path == "/cockpit":
            return _timed_payload(path=path, payload="<html>Cockpit</html>")
        raise AssertionError(path)

    summary = local_runtime.check_runtime(
        min_selection_reports=1,
        min_risk_decisions=1,
        timed_fetch_json=fake_fetch_json,
        timed_fetch_text=fake_fetch_text,
    )

    timings = summary["route_timings"]
    assert timings["/reports/selection"]["budget_seconds"] == 5.0
    assert timings["/reports/selection"]["budget_metric"] == "total_seconds"
    assert timings["/"]["budget_seconds"] == 12.0
    assert timings["/"]["budget_metric"] == "first_byte_seconds"
    assert timings["/cockpit"]["budget_seconds"] == 12.0
    assert timings["/cockpit"]["budget_metric"] == "first_byte_seconds"
    assert timings["/api/cockpit"]["budget_seconds"] == 12.0
    assert timings["/api/cockpit"]["budget_metric"] == "total_seconds"


def test_check_local_runtime_fails_slow_selection_reports_route() -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/reports/selection":
            return _timed_payload(
                path=path,
                payload=[{"ticker": "AAPL"}],
                total_seconds=5.25,
            )
        if path == "/health":
            return _timed_payload(path=path, payload={"status": "ok"})
        if path == "/risk/decisions":
            return _timed_payload(path=path, payload=[{"ticker": "AAPL"}])
        if path == "/api/cockpit":
            return _timed_payload(path=path, payload={"candidates": []})
        raise AssertionError(path)

    def fake_fetch_text(_base_url: str, path: str) -> dict[str, object]:
        if path == "/metrics":
            return _timed_payload(
                path=path,
                payload="# HELP demo Demo\nagency_source_health_total 2\n",
            )
        if path == "/":
            return _timed_payload(path=path, payload="<html>Command</html>")
        if path == "/cockpit":
            return _timed_payload(path=path, payload="<html>Cockpit</html>")
        raise AssertionError(path)

    with pytest.raises(RuntimeError, match="Selection reports route exceeded 5.0s"):
        local_runtime.check_runtime(
            min_selection_reports=1,
            min_risk_decisions=1,
            timed_fetch_json=fake_fetch_json,
            timed_fetch_text=fake_fetch_text,
        )


def test_check_local_runtime_fails_slow_cockpit_root_first_byte() -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/health":
            return _timed_payload(path=path, payload={"status": "ok"})
        if path == "/reports/selection":
            return _timed_payload(path=path, payload=[{"ticker": "AAPL"}])
        if path == "/risk/decisions":
            return _timed_payload(path=path, payload=[{"ticker": "AAPL"}])
        if path == "/api/cockpit":
            return _timed_payload(path=path, payload={"candidates": []})
        raise AssertionError(path)

    def fake_fetch_text(_base_url: str, path: str) -> dict[str, object]:
        if path == "/metrics":
            return _timed_payload(
                path=path,
                payload="# HELP demo Demo\nagency_source_health_total 2\n",
            )
        if path == "/":
            return _timed_payload(
                path=path,
                payload="<html>Command</html>",
                first_byte_seconds=12.2,
            )
        if path == "/cockpit":
            return _timed_payload(path=path, payload="<html>Cockpit</html>")
        raise AssertionError(path)

    with pytest.raises(RuntimeError, match="V3 cockpit root route exceeded 12.0s"):
        local_runtime.check_runtime(
            min_selection_reports=1,
            min_risk_decisions=1,
            timed_fetch_json=fake_fetch_json,
            timed_fetch_text=fake_fetch_text,
        )


def test_check_local_runtime_fails_slow_cockpit_api_total_time() -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/health":
            return _timed_payload(path=path, payload={"status": "ok"})
        if path == "/reports/selection":
            return _timed_payload(path=path, payload=[{"ticker": "AAPL"}])
        if path == "/risk/decisions":
            return _timed_payload(path=path, payload=[{"ticker": "AAPL"}])
        if path == "/api/cockpit":
            return _timed_payload(
                path=path,
                payload={"candidates": [{"ticker": "AAPL"}]},
                total_seconds=12.5,
            )
        raise AssertionError(path)

    def fake_fetch_text(_base_url: str, path: str) -> dict[str, object]:
        if path == "/metrics":
            return _timed_payload(
                path=path,
                payload="# HELP demo Demo\nagency_source_health_total 2\n",
            )
        if path == "/":
            return _timed_payload(path=path, payload="<html>Command</html>")
        if path == "/cockpit":
            return _timed_payload(path=path, payload="<html>Cockpit</html>")
        raise AssertionError(path)

    with pytest.raises(RuntimeError, match="V3 cockpit API route exceeded 12.0s"):
        local_runtime.check_runtime(
            min_selection_reports=1,
            min_risk_decisions=1,
            timed_fetch_json=fake_fetch_json,
            timed_fetch_text=fake_fetch_text,
        )


def _timed_payload(
    *,
    path: str,
    payload: object,
    first_byte_seconds: float = 0.01,
    total_seconds: float = 0.02,
) -> dict[str, object]:
    return {
        "path": path,
        "payload": payload,
        "first_byte_seconds": first_byte_seconds,
        "total_seconds": total_seconds,
    }


def test_runtime_as_of_prefers_configured_end_for_replay(tmp_path: Path) -> None:
    args = argparse.Namespace(
        as_of=None,
        replay_freshness=True,
        manifest_root=tmp_path / "manifests",
        parquet_root=tmp_path / "parquet",
    )
    config = RefreshConfigOverrides(end=date(2025, 12, 31))

    assert _runtime_as_of(args=args, config=config, lanes=("abnormal_volume",)) == date(
        2025,
        12,
        31,
    )


def test_runtime_as_of_live_mode_does_not_pin_to_stale_config_end(tmp_path: Path) -> None:
    args = argparse.Namespace(
        as_of=None,
        replay_freshness=False,
        manifest_root=tmp_path / "manifests",
        parquet_root=tmp_path / "parquet",
    )
    config = RefreshConfigOverrides(end=date(2025, 12, 31))

    assert _runtime_as_of(args=args, config=config, lanes=("abnormal_volume",)) != date(
        2025,
        12,
        31,
    )


def test_runtime_as_of_uses_utc_clock_for_live_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 5, 13, 21, 30, tzinfo=UTC)

    monkeypatch.setattr(live_runtime_cycle_script, "datetime", FakeDateTime)
    args = argparse.Namespace(
        as_of=None,
        replay_freshness=False,
        manifest_root=tmp_path / "manifests",
        parquet_root=tmp_path / "parquet",
    )

    assert live_runtime_cycle_script._runtime_as_of(
        args=args,
        config=None,
        lanes=("abnormal_volume",),
    ) == date(2026, 5, 13)


def test_runtime_as_of_live_mode_uses_latest_source_backed_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime(2026, 5, 16, 8, 0, tzinfo=UTC)

    monkeypatch.setattr(live_runtime_cycle_script, "datetime", FakeDateTime)
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    parquet_path = parquet_root / "prices_daily.parquet"
    pl.DataFrame({"ticker": ["AAPL"], "close": [100.0]}).write_parquet(parquet_path)
    (manifest_root / "prices_daily.json").write_text(
        json.dumps(
            {
                "dataset": "prices_daily",
                "path": parquet_path.name,
                "schema_version": 1,
                "row_count": 1,
                "checksum": "fixture",
                "fetched_at": "2026-05-11T21:00:00+00:00",
                "max_timestamp_as_of": "2026-05-11T00:00:00+00:00",
                "stale_after": "2099-01-01T00:00:00+00:00",
                "source_url": "fixture://pit",
            }
        ),
        encoding="utf-8",
    )
    args = argparse.Namespace(
        as_of=None,
        replay_freshness=False,
        manifest_root=manifest_root,
        parquet_root=parquet_root,
    )

    assert _runtime_as_of(args=args, config=None, lanes=("abnormal_volume",)) == date(
        2026,
        5,
        11,
    )


def test_canonical_runtime_output_keeps_last_persisted_summary_on_persist_failure() -> None:
    assert (
        live_runtime_cycle_script._should_write_persistence_failure_artifacts(
            live_runtime_cycle_script.CANONICAL_RUNTIME_OUTPUT_ROOT
        )
        is False
    )
    assert (
        live_runtime_cycle_script._should_write_persistence_failure_artifacts(
            Path("research/results/diagnostic-live-runtime")
        )
        is True
    )


@pytest.mark.asyncio
async def test_runtime_cycle_broker_snapshot_cli_disable_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_broker_snapshot() -> dict[str, object]:
        raise AssertionError("broker snapshot should not run")

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setattr(
        live_runtime_cycle_script,
        "broker_snapshot",
        fail_broker_snapshot,
    )

    assert await live_runtime_cycle_script._broker_snapshot_if_enabled(enabled=False) is None


def test_check_paper_review_status_summarizes_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        assert path == "/status/paper-review"
        return {
            "cycle_id": "cycle-1",
            "verdict": "ready_for_paper_validation",
            "progress": {
                "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                "reviewed_count": EXPECTED_REVIEWED_COUNT,
                "pending_count": EXPECTED_PENDING_COUNT,
                "approve_count": 0,
                "defer_count": 1,
                "reject_count": 0,
            },
            "queue": [{}, {}, {}, {}],
        }

    monkeypatch.setattr(
        "scripts.check_paper_review_status._fetch_json",
        fake_fetch_json,
    )

    summary = check_paper_review_status(min_queue=4, min_reviewed=1, max_pending=3)

    assert summary == {
        "cycle_id": "cycle-1",
        "verdict": "ready_for_paper_validation",
        "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
        "reviewed_count": EXPECTED_REVIEWED_COUNT,
        "pending_count": EXPECTED_PENDING_COUNT,
        "approve_count": 0,
        "defer_count": 1,
        "reject_count": 0,
    }


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.check_operational_readiness",
        "scripts.check_paper_review_status",
        "scripts.check_paper_trade_path",
    ],
)
def test_status_check_fetch_json_retries_connection_reset(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module = importlib.import_module(module_name)
    attempts = 0

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ready": true}'

    def fake_urlopen(*_args: object, **_kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("reset")
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    assert module._fetch_json("http://example.test", "/status") == {"ready": True}
    assert attempts == 2


@pytest.mark.parametrize(
    "module_name",
    [
        "scripts.check_operational_readiness",
        "scripts.check_paper_review_status",
        "scripts.check_paper_trade_path",
    ],
)
def test_status_check_fetch_json_survives_two_connection_resets(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
) -> None:
    module = importlib.import_module(module_name)
    attempts = 0

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"ready": true}'

    def fake_urlopen(*_args: object, **_kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionResetError("reset")
        return Response()

    monkeypatch.setattr(module, "urlopen", fake_urlopen)

    assert module._fetch_json("http://example.test", "/status") == {"ready": True}
    assert attempts == 3


def test_check_local_runtime_fetch_text_survives_two_connection_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"ok"

    def fake_urlopen(*_args: object, **_kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ConnectionResetError("reset")
        return Response()

    monkeypatch.setattr(local_runtime, "urlopen", fake_urlopen)

    result = local_runtime._fetch_text_with_timing("http://example.test", "/status")

    assert result["payload"] == "ok"
    assert result["attempt"] == 3


def test_check_paper_trade_path_summarizes_orderability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("scripts.check_paper_trade_path")

    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/status/paper-review":
            return {
                "cycle_id": "cycle-1",
                "verdict": "ready_for_paper_validation",
                "progress": {
                    "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "reviewed_count": 2,
                    "pending_count": 2,
                    "approve_count": 1,
                    "defer_count": 1,
                    "reject_count": 0,
                },
                "queue": [{}, {}, {}, {}],
            }
        assert path == "/status/execution-preview"
        return {
            "cycle_id": "cycle-1",
            "ready": True,
            "ready_count": 1,
            "submit_ready_count": 1,
            "order_approval_available_count": 0,
            "review_only_count": 3,
            "blocked_count": 0,
            "disabled_count": 3,
            "submit_gate_open": True,
            "freshness_gate": {"ready": True, "detail": "fresh"},
            "blockers": [],
        }

    monkeypatch.setattr(module, "_fetch_json", fake_fetch_json)

    summary = module.check_paper_trade_path(min_orderable=1, min_submit_ready=1)

    assert summary == {
        "cycle_id": "cycle-1",
        "paper_review_verdict": "ready_for_paper_validation",
        "review_total_count": EXPECTED_REVIEW_QUEUE_COUNT,
        "reviewed_count": 2,
        "pending_count": 2,
        "approve_count": 1,
        "ready": True,
        "orderable_count": 1,
        "submit_ready_count": 1,
        "order_approval_available_count": 0,
        "review_only_count": 3,
        "blocked_count": 0,
        "disabled_count": 3,
        "submit_gate_open": True,
        "freshness_ready": True,
    }


def test_check_paper_trade_path_fails_when_no_submit_ready_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = importlib.import_module("scripts.check_paper_trade_path")

    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/status/paper-review":
            return {
                "cycle_id": "cycle-1",
                "verdict": "context_only_source_health",
                "progress": {
                    "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "reviewed_count": 0,
                    "pending_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "approve_count": 0,
                    "defer_count": 0,
                    "reject_count": 0,
                },
                "queue": [{}, {}, {}, {}],
            }
        assert path == "/status/execution-preview"
        return {
            "cycle_id": "cycle-1",
            "ready": False,
            "ready_count": 0,
            "submit_ready_count": 0,
            "order_approval_available_count": 0,
            "review_only_count": 4,
            "blocked_count": 0,
            "disabled_count": 4,
            "submit_gate_open": False,
            "freshness_gate": {
                "ready": False,
                "detail": "Broker snapshot is stale.",
            },
            "blockers": [
                {
                    "ticker": "NVDA",
                    "state": "DISABLED",
                    "side": "NONE",
                    "risk_decision": "WARN",
                    "reason": "confirmed signal count 1 is below required 2.",
                }
            ],
        }

    monkeypatch.setattr(module, "_fetch_json", fake_fetch_json)

    with pytest.raises(RuntimeError, match="submit-ready paper order count is below"):
        module.check_paper_trade_path(min_orderable=0, min_submit_ready=1)


def test_check_operational_readiness_summarizes_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/status/full-live-readiness":
            return {
                "verdict": "ready_with_partial_lanes",
                "state": "attention",
                "status_label": "Review Operational",
                "review_operational_ready": True,
                "tradable_ready": False,
            }
        assert path == "/status/operational-readiness"
        return {
            "ready": True,
            "state": "attention",
            "status_label": "Operational With Attention",
            "blocker_count": 0,
            "warning_count": 1,
            "live_readiness": {"cycle_id": "cycle-1"},
            "data_refresh": {
                "state": "complete",
                "status_label": "Complete",
                "eta_label": "complete",
            },
            "data_load_status": {
                "state": "ready",
                "status_label": "Ready",
                "as_of": "2026-05-11T00:00:00+00:00",
                "status_checked_at": "2026-05-16T08:00:00+00:00",
            },
            "paper_review": {
                "progress": {
                    "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "reviewed_count": EXPECTED_REVIEWED_COUNT,
                    "pending_count": EXPECTED_PENDING_COUNT,
                }
            },
        }

    monkeypatch.setattr(
        "scripts.check_operational_readiness._fetch_json",
        fake_fetch_json,
    )

    summary = check_operational_readiness(min_queue=4, min_reviewed=1)

    assert summary == {
        "ready": True,
        "state": "attention",
        "status_label": "Operational With Attention",
        "blocker_count": 0,
        "warning_count": 1,
        "cycle_id": "cycle-1",
        "full_live_verdict": "ready_with_partial_lanes",
        "full_live_state": "attention",
        "full_live_status_label": "Review Operational",
        "review_operational_ready": True,
        "tradable_ready": False,
        "data_refresh_state": "complete",
        "data_refresh_status_label": "Complete",
        "data_refresh_eta": "complete",
        "data_load_state": "ready",
        "data_load_status_label": "Ready",
        "data_load_as_of": "2026-05-11T00:00:00+00:00",
        "data_load_checked_at": "2026-05-16T08:00:00+00:00",
        "queue_count": EXPECTED_REVIEW_QUEUE_COUNT,
        "reviewed_count": EXPECTED_REVIEWED_COUNT,
        "pending_count": EXPECTED_PENDING_COUNT,
    }


def test_check_operational_readiness_fails_when_full_live_is_not_review_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/status/full-live-readiness":
            return {
                "verdict": "loading",
                "review_operational_ready": False,
                "next_actions": [
                    "Wait for stock_trades to finish; ETA 2m.",
                    "Do not start paper review yet.",
                ],
            }
        assert path == "/status/operational-readiness"
        return {
            "ready": True,
            "state": "ready",
            "status_label": "Operational",
            "blocker_count": 0,
            "warning_count": 0,
            "live_readiness": {"cycle_id": "cycle-1"},
            "paper_review": {
                "progress": {
                    "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "reviewed_count": EXPECTED_REVIEWED_COUNT,
                    "pending_count": EXPECTED_PENDING_COUNT,
                }
            },
        }

    monkeypatch.setattr(
        "scripts.check_operational_readiness._fetch_json",
        fake_fetch_json,
    )

    with pytest.raises(RuntimeError) as exc:
        check_operational_readiness(min_queue=4, min_reviewed=1)

    message = str(exc.value)
    assert "full-live readiness is not review-operational (loading)" in message
    assert "Wait for stock_trades to finish" in message
    assert "Do not start paper review yet" in message


def test_check_operational_readiness_fails_on_cycle_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        if path == "/status/full-live-readiness":
            return {
                "verdict": "ready_with_partial_lanes",
                "state": "attention",
                "status_label": "Review Operational",
                "review_operational_ready": True,
                "tradable_ready": False,
            }
        assert path == "/status/operational-readiness"
        return {
            "ready": True,
            "state": "attention",
            "status_label": "Operational With Attention",
            "blocker_count": 0,
            "warning_count": 1,
            "live_readiness": {"cycle_id": "live-pit-old"},
            "data_load_status": {
                "cycle_id": "live-pit-current",
                "state": "ready",
                "status_label": "Ready",
            },
            "paper_review": {
                "progress": {
                    "total_count": EXPECTED_REVIEW_QUEUE_COUNT,
                    "reviewed_count": EXPECTED_REVIEWED_COUNT,
                    "pending_count": EXPECTED_PENDING_COUNT,
                }
            },
        }

    monkeypatch.setattr(
        "scripts.check_operational_readiness._fetch_json",
        fake_fetch_json,
    )

    with pytest.raises(RuntimeError) as exc:
        check_operational_readiness(min_queue=4, min_reviewed=1)

    assert "cycle mismatch" in str(exc.value)
    assert "live-pit-old" in str(exc.value)
    assert "live-pit-current" in str(exc.value)


def test_check_provider_readiness_summarizes_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch_json(_base_url: str, path: str) -> dict[str, object]:
        assert path == "/status/provider-readiness"
        return {
            "ready": True,
            "state": "ready",
            "provider_count": 10,
            "configured_count": 3,
            "active_required_count": 2,
            "blocker_count": 0,
            "warning_count": 0,
            "providers": [
                {"label": "Alpaca", "configured": True},
                {"label": "Unusual Whales", "configured": False},
            ],
        }

    monkeypatch.setattr(
        "scripts.check_provider_readiness._fetch_json",
        fake_fetch_json,
    )

    summary = check_provider_readiness(require_configured="Alpaca")

    assert summary == {
        "ready": True,
        "state": "ready",
        "provider_count": 10,
        "configured_count": 3,
        "active_required_count": 2,
        "blocker_count": 0,
        "warning_count": 0,
    }


def test_first_version_pipeline_defaults_are_bounded(tmp_path: Path) -> None:
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        '{"article_login_preflight_required": false}',
        encoding="utf-8",
    )
    args = _pipeline_args(subscription_email_config=config_path)

    steps = build_pipeline_steps(args)
    email_command = email_ingest_command(args)
    cycle_command = runtime_cycle_command(args)

    assert [step.name for step in steps] == [
        "subscription_email_ingest",
        "live_runtime_cycle",
    ]
    assert "--max-emails" in email_command
    assert "1" in email_command
    assert "--max-article-links" in email_command
    assert "--no-persist" not in cycle_command
    assert steps[0].requires_console is False


def test_first_version_pipeline_marks_email_login_preflight_interactive(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "subscription-email.json"
    config_path.write_text(
        '{"article_login_preflight_required": true}',
        encoding="utf-8",
    )
    args = _pipeline_args(subscription_email_config=config_path)

    steps = build_pipeline_steps(args)

    assert subscription_email_requires_console(args) is True
    assert steps[0].name == "subscription_email_ingest"
    assert steps[0].requires_console is True


def test_first_version_pipeline_can_skip_email_and_check_dashboard() -> None:
    args = _pipeline_args(
        skip_email=True,
        check_dashboard=True,
        persist=False,
        replay_freshness=True,
    )

    steps = build_pipeline_steps(args)
    cycle_command = runtime_cycle_command(args)

    assert [step.name for step in steps] == ["live_runtime_cycle", "dashboard_readiness"]
    assert "--no-persist" in cycle_command
    assert "--replay-freshness" in cycle_command


def test_first_version_pipeline_writes_auditable_report(tmp_path: Path) -> None:
    result = StepResult(
        name="live_runtime_cycle",
        returncode=0,
        stdout="ok",
        stderr="",
        started_at="2026-05-11T09:00:00Z",
        finished_at="2026-05-11T09:00:01Z",
        duration_seconds=1.0,
    )
    summary = {
        "ok": True,
        "verdict": "agency_pipeline_passed",
        "failed_step": None,
        "completed_steps": ["live_runtime_cycle"],
        "step_count": 1,
        "successful_step_count": 1,
        "dashboard": "http://127.0.0.1:8000/",
    }

    write_pipeline_report(summary, [result], tmp_path)

    assert (tmp_path / "first-version-pipeline.json").exists()
    report = (tmp_path / "first-version-pipeline.md").read_text(encoding="utf-8")
    assert "agency_pipeline_passed" in report
    assert "| live_runtime_cycle | passed | 1.0s |" in report


def test_runtime_cycle_can_use_active_pit_universe(tmp_path: Path) -> None:
    parquet_root = tmp_path / "parquet"
    manifest_root = tmp_path / "manifests"
    parquet_root.mkdir()
    manifest_root.mkdir()
    universe_path = parquet_root / "universe_membership.parquet"
    frame = pl.DataFrame(
        [
            member("MSFT", date(2019, 1, 1), None),
            member("AAPL", date(2019, 1, 1), None),
            member("OLD", date(2019, 1, 1), date(2020, 1, 1)),
        ]
    )
    frame.write_parquet(universe_path)
    write_manifest(manifest_root, DatasetName.UNIVERSE_MEMBERSHIP, universe_path.name, frame.height)
    args = argparse.Namespace(ticker=[], runtime_universe=None, max_tickers=None)

    tickers = _tickers(
        args,
        RefreshConfigOverrides(runtime_universe="active", runtime_max_tickers=250),
        as_of=date(2026, 5, 8),
        manifest_root=manifest_root,
        parquet_root=parquet_root,
    )

    assert tickers == ["AAPL", "MSFT"]
    assert (
        _max_tickers(
            args,
            RefreshConfigOverrides(runtime_max_tickers=EXPECTED_RUNTIME_MAX_TICKERS),
        )
        == EXPECTED_RUNTIME_MAX_TICKERS
    )


def test_live_runtime_human_review_state_index_keeps_latest_review() -> None:
    older_approval = build_human_review_event(
        cycle_id="live-pit-current",
        ticker="aapl",
        as_of="2026-05-07T09:31:00Z",
        decision="APPROVE",
        event_time="2026-05-07T09:32:00Z",
        selection_report_hash="a" * 64,
    )
    latest_defer = build_human_review_event(
        cycle_id="live-pit-current",
        ticker="AAPL",
        as_of="2026-05-07T09:31:00Z",
        decision="DEFER",
        event_time="2026-05-07T09:35:00Z",
        selection_report_hash="b" * 64,
    )
    unrelated_order_approval = {
        **latest_defer,
        "event_type": "ORDER_APPROVAL",
    }

    indexed = _human_review_state_index(
        [older_approval, latest_defer, unrelated_order_approval]
    )

    assert list(indexed) == [
        ("live-pit-current", "AAPL", "2026-05-07T09:31:00Z")
    ]
    assert indexed[("live-pit-current", "AAPL", "2026-05-07T09:31:00Z")] is latest_defer


def test_market_aware_refresh_config_defers_daily_history_during_regular_market(
    tmp_path: Path,
) -> None:
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 11),
        datasets=("stock_trades", "prices_daily", "sec_company_facts", "sec_form4"),
        tickers=("AAPL",),
        massive_credentials_present=True,
        market_data_provider="massive",
    )

    adjusted = _market_aware_config(
        config,
        config_path=None,
        now_text="2026-05-11T10:00:00-04:00",
    )

    assert adjusted.datasets == ()


def test_market_aware_refresh_config_accepts_naive_new_york_now(
    tmp_path: Path,
) -> None:
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 11),
        datasets=("stock_trades",),
        tickers=("AAPL",),
        massive_credentials_present=True,
        market_data_provider="massive",
    )

    adjusted = _market_aware_config(
        config,
        config_path=None,
        now_text="2026-05-11T10:00:00",
    )

    assert adjusted.datasets == ()


def test_market_aware_refresh_config_applies_planned_tickers_and_batch_cap(
    tmp_path: Path,
) -> None:
    tickers = tuple(f"T{i:02d}" for i in range(25))
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
        datasets=("stock_trades",),
        tickers=tickers,
        massive_credentials_present=True,
        market_data_provider="massive",
    )

    adjusted = _market_aware_config(
        config,
        config_path=None,
        now_text="2026-05-11T10:00:00-04:00",
    )

    assert adjusted.datasets == ()
    assert adjusted.tickers == tickers


def test_market_aware_refresh_config_caps_stock_trades_even_with_context_rows(
    tmp_path: Path,
) -> None:
    tickers = tuple(f"T{i:02d}" for i in range(25))
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2026, 5, 11),
        end=date(2026, 5, 11),
        datasets=("stock_trades", "news_rss"),
        tickers=tickers,
        rss_feeds=("Example,https://example.test/rss",),
        massive_credentials_present=True,
        market_data_provider="massive",
    )

    adjusted = _market_aware_config(
        config,
        config_path=None,
        now_text="2026-05-11T10:00:00-04:00",
    )

    assert adjusted.datasets == ("news_rss",)
    assert adjusted.tickers == tickers


def test_market_aware_refresh_config_preserves_skipped_support_dataset(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "research" / "data" / "manifests" / "sec_form4.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "sec_form4",
                "row_count": 1,
                "fetched_at": "2026-05-17T10:00:00+00:00",
                "max_timestamp_as_of": "2026-05-15T00:00:00+00:00",
                "issues": [],
            }
        ),
        encoding="utf-8",
    )
    config = RefreshBatchConfig(
        repo_root=tmp_path,
        output_root=tmp_path / "results",
        start=date(2021, 1, 1),
        end=date(2026, 5, 15),
        datasets=("sec_form4",),
        tickers=("HON",),
        sec_user_agent="Trading Agency admin@example.com",
    )

    adjusted = _market_aware_config(
        config,
        config_path=None,
        now_text="2026-05-17T10:00:00-04:00",
    )

    assert adjusted.datasets == ("sec_form4",)
    assert adjusted.tickers == ("HON",)


def _pipeline_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "config": "research/config/live-refresh.local.json",
        "subscription_email_config": "research/config/subscription-email.local.json",
        "refresh_data": False,
        "refresh_dataset": None,
        "skip_email": False,
        "email_max_emails": 1,
        "email_max_article_links": 1,
        "email_include_seen": False,
        "email_unseen_only": False,
        "as_of": None,
        "replay_freshness": False,
        "max_tickers": 10,
        "persist": True,
        "output_root": "research/results/latest-live-runtime-cycle",
        "check_dashboard": False,
        "base_url": "http://127.0.0.1:8000",
        "min_queue": 1,
        "min_reviewed": 0,
        "fail_on_warning": False,
        "report_root": "research/results/latest-first-version-pipeline",
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)
