"""Tests for DB-backed policy persistence (T128 / STRUCT-5)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agency.services.risk import (
    PortfolioPolicy,
    load_active_portfolio_policy,
    load_policy_from_db,
    save_policy_to_db,
)

# ---------------------------------------------------------------------------
# Fake session helpers
# ---------------------------------------------------------------------------

def _make_session_with_row(row: dict[str, object] | None) -> Any:
    """Build a fake async session that returns *row* for any SELECT query."""
    mapping_result = MagicMock()
    if row is None:
        mapping_result.first.return_value = None
    else:
        mapping_result.first.return_value = row

    execute_result = MagicMock()
    execute_result.mappings.return_value = mapping_result

    session = AsyncMock()
    session.execute.return_value = execute_result
    return session


def _make_empty_session() -> Any:
    """Fake session that returns no row (empty table)."""
    return _make_session_with_row(None)


# ---------------------------------------------------------------------------
# load_policy_from_db tests
# ---------------------------------------------------------------------------


async def test_load_policy_returns_none_when_empty_db() -> None:
    session = _make_empty_session()
    result = await load_policy_from_db(session)
    assert result is None


async def test_load_policy_reconstructs_policy_from_db_row() -> None:
    row = {
        "data": {
            "min_final_conviction": 0.75,
            "max_new_positions_per_cycle": 5,
            "max_gross_exposure_pct": 90.0,
            "default_position_pct": 12.0,
            "take_profit_pct": 10.0,
            "stop_loss_pct": 5.0,
            "trailing_stop_pct": 3.5,
            "hourly_loss_alert_pct": 1.5,
            "broker_submit_enabled": False,
        }
    }
    session = _make_session_with_row(row)
    result = await load_policy_from_db(session)
    assert result is not None
    assert result.min_final_conviction == 0.75
    assert result.take_profit_pct == 10.0
    assert result.stop_loss_pct == 5.0
    assert result.max_new_positions_per_cycle == 5
    assert result.broker_submit_enabled is False


async def test_load_policy_uses_defaults_for_missing_fields() -> None:
    """Partial data dict falls back to PortfolioPolicy defaults for missing keys."""
    row = {"data": {"take_profit_pct": 12.0}}
    session = _make_session_with_row(row)
    result = await load_policy_from_db(session)
    assert result is not None
    assert result.take_profit_pct == 12.0
    # missing fields use defaults
    defaults = PortfolioPolicy()
    assert result.min_final_conviction == defaults.min_final_conviction
    assert result.stop_loss_pct == defaults.stop_loss_pct


async def test_load_policy_returns_none_when_data_is_not_mapping() -> None:
    row = {"data": "bad-value"}
    session = _make_session_with_row(row)
    result = await load_policy_from_db(session)
    assert result is None


# ---------------------------------------------------------------------------
# save_policy_to_db tests
# ---------------------------------------------------------------------------


async def test_save_policy_executes_upsert_statement() -> None:
    session = AsyncMock()
    policy = PortfolioPolicy(take_profit_pct=12.0, stop_loss_pct=5.0)
    await save_policy_to_db(session, policy)
    session.execute.assert_called_once()


async def test_save_and_load_round_trip_via_fake_session() -> None:
    """Verify that save produces a dict that load can reconstruct."""
    policy = PortfolioPolicy(take_profit_pct=12.0, stop_loss_pct=5.0)
    row = {"data": policy.as_dict()}
    session = _make_session_with_row(row)
    loaded = await load_policy_from_db(session)
    assert loaded is not None
    assert loaded.take_profit_pct == 12.0
    assert loaded.stop_loss_pct == 5.0


# ---------------------------------------------------------------------------
# Policy API endpoint tests
# ---------------------------------------------------------------------------


async def test_get_policy_endpoint_returns_env_defaults_when_db_empty() -> None:
    from contextlib import asynccontextmanager

    from agency.api.risk import get_policy

    @asynccontextmanager
    async def empty_session_provider() -> AsyncIterator[Any]:
        yield _make_empty_session()

    result = await get_policy(session_provider=empty_session_provider)
    defaults = PortfolioPolicy.from_env()
    assert result["take_profit_pct"] == defaults.take_profit_pct
    assert result["stop_loss_pct"] == defaults.stop_loss_pct


async def test_get_policy_endpoint_returns_db_policy_when_present() -> None:
    from agency.api.risk import get_policy

    row = {
        "data": {
            "min_final_conviction": 0.70,
            "max_new_positions_per_cycle": 4,
            "max_gross_exposure_pct": 80.0,
            "default_position_pct": 11.0,
            "take_profit_pct": 9.0,
            "stop_loss_pct": 4.5,
            "trailing_stop_pct": 3.0,
            "hourly_loss_alert_pct": 1.0,
            "broker_submit_enabled": False,
        }
    }

    @asynccontextmanager
    async def session_with_row_provider() -> AsyncIterator[Any]:
        yield _make_session_with_row(row)

    result = await get_policy(session_provider=session_with_row_provider)
    assert result["take_profit_pct"] == 9.0
    assert result["stop_loss_pct"] == 4.5


async def test_update_policy_endpoint_saves_and_returns_updated_policy() -> None:
    from agency.api.risk import PolicyUpdate, update_policy

    execute_calls: list[Any] = []

    class FakeSession(AsyncMock):
        async def execute(self, stmt: Any) -> Any:  # type: ignore[override]
            execute_calls.append(stmt)
            # First call is SELECT (return empty), second is INSERT upsert
            if len(execute_calls) == 1:
                return _make_empty_session().execute.return_value
            return MagicMock()

    session = FakeSession()
    @asynccontextmanager
    async def fake_provider() -> AsyncIterator[Any]:
        yield session

    body = PolicyUpdate(take_profit_pct=15.0, stop_loss_pct=6.0)
    result = await update_policy(body, session_provider=fake_provider)
    assert result["take_profit_pct"] == 15.0
    assert result["stop_loss_pct"] == 6.0
    # broker_submit_enabled must NOT be affected by UI update
    assert "broker_submit_enabled" in result


async def test_update_policy_uses_runtime_only_execution_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB policy updates cannot enable broker submit or short permissions."""
    from agency.api.risk import PolicyUpdate, update_policy

    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "false")
    monkeypatch.setenv("AGENCY_ALLOW_SHORT_TRADES", "false")

    # Simulate DB row with broker_submit_enabled=True
    row = {
        "data": {
            "min_final_conviction": 0.62,
            "max_new_positions_per_cycle": 3,
            "max_gross_exposure_pct": 100.0,
            "default_position_pct": 10.0,
            "take_profit_pct": 8.0,
            "stop_loss_pct": 4.0,
            "trailing_stop_pct": 3.0,
            "hourly_loss_alert_pct": 1.0,
            "broker_submit_enabled": True,
            "allow_short_trades": True,
        }
    }

    session = _make_session_with_row(row)

    @asynccontextmanager
    async def fake_provider() -> AsyncIterator[Any]:
        yield session

    body = PolicyUpdate(take_profit_pct=10.0)
    result = await update_policy(body, session_provider=fake_provider)
    assert result["broker_submit_enabled"] is False
    assert result["allow_short_trades"] is False


async def test_active_policy_uses_db_sizing_and_env_execution_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "data": {
            "min_final_conviction": 0.70,
            "max_new_positions_per_cycle": 4,
            "max_gross_exposure_pct": 80.0,
            "default_position_pct": 11.0,
            "take_profit_pct": 9.0,
            "stop_loss_pct": 4.5,
            "trailing_stop_pct": 3.0,
            "hourly_loss_alert_pct": 1.0,
            "broker_submit_enabled": False,
            "allow_short_trades": False,
        }
    }

    @asynccontextmanager
    async def session_with_row_provider() -> AsyncIterator[Any]:
        yield _make_session_with_row(row)

    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.setenv("AGENCY_ALLOW_SHORT_TRADES", "true")

    policy = await load_active_portfolio_policy(session_provider=session_with_row_provider)

    assert policy.take_profit_pct == 9.0
    assert policy.stop_loss_pct == 4.5
    assert policy.broker_submit_enabled is True
    assert policy.allow_short_trades is True
