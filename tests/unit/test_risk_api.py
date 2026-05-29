from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from service_fixtures import selection_report

from agency.api import risk as risk_api
from agency.api.risk import (
    PolicyUpdate,
    RuntimeRiskDecisionsUnavailable,
    _updated_policy,
    runtime_risk_decisions,
)
from agency.app import create_app
from agency.services import build_risk_decision
from agency.services.risk import PortfolioPolicy

HTTP_OK = 200
HTTP_UNAVAILABLE = 503
RISK_DECISION_LIMIT = 5


def test_risk_decisions_endpoint_reports_unavailable_when_storage_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "false")
    client = TestClient(create_app())

    response = client.get("/risk/decisions")

    assert response.status_code == HTTP_UNAVAILABLE
    assert response.json()["detail"] == "runtime risk-decision storage is unavailable"


def test_risk_decisions_endpoint_does_not_force_latest_runtime_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_runtime_risk_decisions(**kwargs: object) -> list[dict[str, object]]:
        observed.update(kwargs)
        return [{"ticker": "AAPL"}]

    monkeypatch.setattr(risk_api, "runtime_risk_decisions", fake_runtime_risk_decisions)
    client = TestClient(create_app())

    response = client.get("/risk/decisions")

    assert response.status_code == HTTP_OK
    assert response.json() == [{"ticker": "AAPL"}]
    assert observed["prefer_latest_artifact"] is False


async def test_runtime_risk_decisions_uses_repository_payloads() -> None:
    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        assert session == "fake-session"
        assert ticker == "AAPL"
        assert limit == RISK_DECISION_LIMIT
        return [_risk_decision()]

    payloads = await runtime_risk_decisions(
        ticker="AAPL",
        limit=RISK_DECISION_LIMIT,
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert payloads[0]["ticker"] == "AAPL"
    assert payloads[0]["decision"] == "ALLOW"


async def test_runtime_risk_decisions_can_skip_internal_validation() -> None:
    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        return [{"ticker": "AAPL"}]

    payloads = await runtime_risk_decisions(
        session_provider=_fake_session_provider,
        reader=reader,
        validate_payloads=False,
    )

    assert payloads == [{"ticker": "AAPL"}]


async def test_runtime_risk_decisions_filters_demo_seed_payloads() -> None:
    demo = {**_risk_decision(), "cycle_id": "demo-cycle-1"}

    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        del session, ticker, limit
        return [demo, _risk_decision()]

    payloads = await runtime_risk_decisions(
        session_provider=_fake_session_provider,
        reader=reader,
    )

    assert [payload["cycle_id"] for payload in payloads] == ["cycle-1"]


async def test_runtime_risk_decisions_uses_latest_artifact_when_db_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", "true")
    artifact = tmp_path / "risk-decisions.json"
    artifact.write_text(
        json.dumps([_risk_decision(), {**_risk_decision(), "ticker": "MSFT"}]),
        encoding="utf-8",
    )

    payloads = await runtime_risk_decisions(
        ticker="AAPL",
        session_provider=_raising_session_provider,
        artifact_root=tmp_path,
    )

    assert [payload["ticker"] for payload in payloads] == ["AAPL"]
    assert payloads[0]["runtime_origin"] == "runtime_artifact_fallback"


async def test_runtime_risk_decisions_can_prefer_newer_runtime_artifact(
    tmp_path: Path,
) -> None:
    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        del session, ticker, limit
        return [
            {
                **_risk_decision(),
                "cycle_id": "live-pit-2026-05-19-20260519T124015Z",
                "generated_at": "2026-05-19T12:40:15Z",
            }
        ]

    artifact = tmp_path / "risk-decisions.json"
    artifact.write_text(
        json.dumps(
            [
                {
                    **_risk_decision(),
                    "cycle_id": "full-active-refresh-20260524T0625Z",
                    "generated_at": "2026-05-24T06:26:28Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    payloads = await runtime_risk_decisions(
        session_provider=_fake_session_provider,
        reader=reader,
        artifact_root=tmp_path,
        prefer_latest_artifact=True,
    )

    assert payloads[0]["cycle_id"] == "full-active-refresh-20260524T0625Z"
    assert payloads[0]["runtime_origin"] == "runtime_artifact_selected"
    assert payloads[0]["runtime_storage_superseded"] is True
    assert str(payloads[0]["runtime_artifact_path"]).endswith("risk-decisions.json")
    assert payloads[0]["runtime_artifact_timestamp"] == "2026-05-24T06:26:28Z"


async def test_runtime_risk_decisions_do_not_supersede_unknown_db_timestamp(
    tmp_path: Path,
) -> None:
    async def reader(
        session: object,
        ticker: str | None,
        limit: int,
    ) -> list[dict[str, object]]:
        del session, ticker, limit
        return [
            {
                **_risk_decision(),
                "cycle_id": "db-unknown-timestamp",
                "generated_at": "not-a-timestamp",
                "as_of": "also-not-a-timestamp",
            }
        ]

    artifact = tmp_path / "risk-decisions.json"
    artifact.write_text(
        json.dumps(
            [
                {
                    **_risk_decision(),
                    "cycle_id": "artifact-valid-timestamp",
                    "generated_at": "2026-05-24T06:26:28Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    payloads = await runtime_risk_decisions(
        session_provider=_fake_session_provider,
        reader=reader,
        artifact_root=tmp_path,
        prefer_latest_artifact=True,
        validate_payloads=False,
    )

    assert payloads[0]["cycle_id"] == "db-unknown-timestamp"
    assert "runtime_storage_superseded" not in payloads[0]


async def test_runtime_risk_decisions_does_not_use_artifact_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AGENCY_RUNTIME_ARTIFACT_FALLBACK", raising=False)
    artifact = tmp_path / "risk-decisions.json"
    artifact.write_text(json.dumps([_risk_decision()]), encoding="utf-8")

    with pytest.raises(RuntimeRiskDecisionsUnavailable):
        await runtime_risk_decisions(
            session_provider=_raising_session_provider,
            artifact_root=tmp_path,
        )


async def test_runtime_risk_decisions_raises_for_unavailable_db() -> None:
    with pytest.raises(RuntimeRiskDecisionsUnavailable):
        await runtime_risk_decisions(
            session_provider=_raising_session_provider,
            artifact_root=Path("missing-runtime-artifacts"),
        )


def test_policy_update_preserves_omitted_fields_and_runtime_controls() -> None:
    current = PortfolioPolicy(
        min_final_conviction=0.7,
        max_new_positions_per_cycle=4,
        default_position_pct=7.5,
        take_profit_pct=12.0,
        stop_loss_pct=5.0,
        broker_submit_enabled=True,
        allow_short_trades=True,
    )

    updated = _updated_policy(
        current,
        PolicyUpdate(take_profit_pct=15.0),
        broker_submit_enabled=False,
        allow_short_trades=False,
    )

    assert updated.take_profit_pct == 15.0
    assert updated.stop_loss_pct == 5.0
    assert updated.min_final_conviction == 0.7
    assert updated.max_new_positions_per_cycle == 4
    assert updated.default_position_pct == 7.5
    assert updated.broker_submit_enabled is False
    assert updated.allow_short_trades is False


def test_policy_update_rejects_invalid_values() -> None:
    with pytest.raises(Exception) as exc_info:
        _updated_policy(
            PortfolioPolicy(),
            PolicyUpdate(default_position_pct=-1.0),
            broker_submit_enabled=False,
            allow_short_trades=False,
        )

    assert "default_position_pct" in str(exc_info.value)


@asynccontextmanager
async def _fake_session_provider() -> AsyncIterator[object]:
    yield "fake-session"


@asynccontextmanager
async def _raising_session_provider() -> AsyncIterator[object]:
    raise OSError("database unavailable")
    yield


def _risk_decision() -> dict[str, object]:
    return build_risk_decision(
        selection_report(action="BUY"),
        {"source_count": 1, "degraded_source_count": 0},
        generated_at="2026-05-07T09:32:00Z",
    ).risk_decision
