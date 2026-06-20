from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import agency.dashboard as dashboard_module
from agency.app import create_app
from agency.views.cockpit import cockpit_context_from_sources
from tests.unit.test_cockpit_contract import _sample_sources

TEMPLATE = Path("src/agency/templates/cockpit.html")
SCRIPT = Path("src/agency/static/cockpit.js")


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_clearance_gate_starts_closed() -> None:
    html = _template()

    assert 'id="cockpit-submit-ack"' in html
    assert 'data-cockpit-submit-button disabled' in html
    assert "checked" not in html.split('id="cockpit-submit-ack"', 1)[1].split(">", 1)[0]


def test_clearance_phrase_never_persists() -> None:
    script = _script()

    assert "submit paper orders" in script
    assert "localStorage.setItem" in script
    assert "submitPhrase" not in script
    assert "cockpit-submit-phrase" not in script


def test_submit_disabled_until_gate_and_phrase() -> None:
    script = _script()

    assert "SUBMIT_PHRASE = \"submit paper orders\"" in script
    assert "const phraseMatches = phrase.value.trim() === SUBMIT_PHRASE" in script
    assert "const manifestReady = manifestHasOrderIntent()" in script
    assert "acknowledged && phraseMatches" in script
    assert "!manifestReady" in script
    assert "No paper order manifest is attached for this cycle." in script


def test_cockpit_submit_advances_to_cleared_only_after_successful_response() -> None:
    script = _script()
    clearance_block = script.split(
        'const form = document.querySelector("[data-cockpit-clearance-form]");',
        1,
    )[1].split("setupPolicyPanel();", 1)[0]

    assert "if (!response.ok)" in clearance_block
    assert clearance_block.index("if (!response.ok)") < clearance_block.index('showPhase("cleared")')


def test_cockpit_submit_non_json_success_fallback_is_not_failure_copy() -> None:
    script = _script()
    clearance_block = script.split(
        'const form = document.querySelector("[data-cockpit-clearance-form]");',
        1,
    )[1].split("setupPolicyPanel();", 1)[0]

    assert "response.ok" in clearance_block
    assert "Non-JSON submit response received" in clearance_block
    assert 'detail: `Submit failed with HTTP ${response.status}.`' in clearance_block
    assert (
        clearance_block.index("Non-JSON submit response received")
        < clearance_block.index('detail: `Submit failed with HTTP ${response.status}.`')
    )


def test_cockpit_submit_result_uses_dom_text_nodes_for_api_values() -> None:
    script = _script()
    submit_result_block = script.split("function renderSubmitResult(payload)", 1)[1]

    assert "article.innerHTML" not in submit_result_block
    assert ".textContent" in submit_result_block


def test_cockpit_submit_posts_explicit_json_manifest_not_formdata() -> None:
    script = _script()
    clearance_block = script.split(
        'const form = document.querySelector("[data-cockpit-clearance-form]");',
        1,
    )[1].split("setupPolicyPanel();", 1)[0]

    assert "buildSubmitPayload()" in clearance_block
    assert "JSON.stringify(buildSubmitPayload())" in clearance_block
    assert '"Content-Type": "application/json"' in clearance_block
    assert "new FormData(form)" not in clearance_block


def test_clearance_phase_starts_with_bluf_sentence() -> None:
    html = _template()

    assert "Check the manifest, confirm the paper-only gate, then submit approved paper orders." in html


def test_clearance_manifest_displays_order_proof_fields() -> None:
    html = _template()

    assert "Action" in html
    assert "Proof time" in html
    assert "Intent hash" in html
    assert "row.order_intent_hash_label" in html
    assert "Review only; no broker submit field is attached." in html
    assert 'name="order_intent_hash"' in html


def test_cockpit_submit_reuses_execution_freshness_gate(monkeypatch: MonkeyPatch) -> None:
    calls: list[str] = []

    async def fake_submit_execution_order_core(**kwargs: object) -> dict[str, object]:
        calls.append(str(kwargs["ticker"]))
        return {"ticker": str(kwargs["ticker"]), "broker_order_id": "", "order_intent_hash": "a" * 64}

    _patch_submit_context(monkeypatch)
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(),
    )

    assert response.status_code == 200
    assert calls == ["AAA"]
    assert response.json()["state"] == "accepted"


def test_cockpit_submit_passes_request_and_all_order_rows_to_submit_handler(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_submit_execution_order_core(request: Request, **kwargs: object) -> dict[str, object]:
        assert request.url.path == "/cockpit/submit"
        calls.append((str(kwargs["ticker"]), str(kwargs["order_intent_hash"])))
        return {"ticker": str(kwargs["ticker"]), "broker_order_id": "", "order_intent_hash": str(kwargs["order_intent_hash"])}

    _patch_submit_context(monkeypatch, include_second=True)
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(include_second=True),
    )

    assert response.status_code == 200
    assert calls == [("AAA", "a" * 64), ("BBB", "b" * 64)]
    assert response.json()["state"] == "accepted"


def test_cockpit_submit_accepts_explicit_json_manifest(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def fake_submit_execution_order_core(request: Request, **kwargs: object) -> dict[str, object]:
        assert request.headers["content-type"] == "application/json"
        calls.append((str(kwargs["ticker"]), str(kwargs["order_intent_hash"])))
        return {"ticker": str(kwargs["ticker"]), "broker_order_id": "", "order_intent_hash": str(kwargs["order_intent_hash"])}

    _patch_submit_context(monkeypatch, include_second=True)
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        json=_submit_json(include_second=True),
    )

    assert response.status_code == 200
    assert calls == [("AAA", "a" * 64), ("BBB", "b" * 64)]
    assert response.json()["state"] == "accepted"


def test_cockpit_submit_recomputes_order_intent_from_execution_preview(monkeypatch: MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def fake_submit_execution_order(**kwargs: object) -> RedirectResponse:
        captured.update(kwargs)
        return RedirectResponse("/execution-preview", status_code=303)

    _patch_submit_context(monkeypatch)
    monkeypatch.setattr(dashboard_module, "submit_execution_order", fake_submit_execution_order)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data={**_submit_form(), "notional_hint": "999999"},
    )

    assert response.status_code == 409
    assert captured == {}
    assert "changed since the page loaded" in response.json()["detail"]


def test_cockpit_submit_rejects_tampered_hidden_fields(monkeypatch: MonkeyPatch) -> None:
    _patch_submit_context(monkeypatch)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data={**_submit_form(), "order_intent_hash": "b" * 64},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "order details changed; refresh cockpit and approve again"


def test_cockpit_submit_handles_partial_broker_failure(monkeypatch: MonkeyPatch) -> None:
    async def fake_submit_execution_order_core(**kwargs: object) -> dict[str, object]:
        if kwargs["ticker"] == "BBB":
            raise HTTPException(status_code=503, detail="Alpaca rejected BBB")
        return {"ticker": str(kwargs["ticker"]), "broker_order_id": "", "order_intent_hash": str(kwargs["order_intent_hash"])}

    _patch_submit_context(monkeypatch, include_second=True)
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(include_second=True),
    )

    payload = response.json()
    assert response.status_code == 207
    assert payload["state"] == "partial"
    assert payload["accepted"][0]["ticker"] == "AAA"
    assert payload["rejected"][0]["detail"] == "Alpaca rejected BBB"


def test_cockpit_submit_treats_accepted_async_reconcile_as_non_rejected(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_submit_execution_order_core(**_kwargs: object) -> dict[str, object]:
        raise HTTPException(status_code=202, detail="paper submit accepted; reconciliation pending")

    _patch_submit_context(monkeypatch, broker_order_id="paper-pending")
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(),
    )

    payload = response.json()
    assert response.status_code == 202
    assert payload["state"] == "reconcile_pending"
    assert payload["accepted"][0]["ticker"] == "AAA"
    assert payload["rejected"] == []


def test_cockpit_submit_keeps_reconcile_pending_rows_accepted_in_partial_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    async def fake_submit_execution_order_core(**kwargs: object) -> dict[str, object]:
        if kwargs["ticker"] == "BBB":
            raise HTTPException(status_code=503, detail="Alpaca rejected BBB")
        raise HTTPException(status_code=202, detail="paper submit accepted; reconciliation pending")

    _patch_submit_context(monkeypatch, include_second=True, broker_order_id="paper-pending")
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(include_second=True),
    )

    payload = response.json()
    assert response.status_code == 207
    assert payload["state"] == "partial"
    assert payload["accepted"][0]["ticker"] == "AAA"
    assert payload["accepted"][0]["status_code"] == 202
    assert payload["rejected"][0]["ticker"] == "BBB"


def test_cockpit_submit_requires_order_intent_hash_match(monkeypatch: MonkeyPatch) -> None:
    _patch_submit_context(monkeypatch)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data={**_submit_form(), "order_intent_hash": ""},
    )

    assert response.status_code == 409
    assert "order details changed" in response.json()["detail"]


def test_cockpit_submit_rejects_live_trading(monkeypatch: MonkeyPatch) -> None:
    _patch_submit_context(monkeypatch)
    monkeypatch.setenv("LIVE_TRADING", "true")

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(),
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cockpit clearance is paper-only; live trading is locked off."


def test_cockpit_submit_records_broker_order_ids(monkeypatch: MonkeyPatch) -> None:
    async def fake_submit_execution_order_core(**_kwargs: object) -> dict[str, object]:
        return {"ticker": "AAA", "broker_order_id": "paper-123", "order_intent_hash": "a" * 64}

    _patch_submit_context(monkeypatch, broker_order_id="paper-123")
    monkeypatch.setattr(dashboard_module, "_submit_execution_order_core", fake_submit_execution_order_core)

    response = TestClient(create_app()).post(
        "/cockpit/submit",
        data=_submit_form(),
    )

    assert response.status_code == 200
    assert response.json()["accepted"][0]["broker_order_id"] == "paper-123"


def test_clearance_context_manifest_exits_before_buys() -> None:
    sources = _sample_sources()
    sources["portfolio"]["positions"].append(  # type: ignore[index]
        {
            "ticker": "EXIT",
            "qty": 2,
            "current_price": 30.0,
            "entry_price": 35.0,
            "stop_price": 31.0,
            "market_value": 60.0,
            "exit_signal": "STOP_BREACH",
        }
    )

    context = cockpit_context_from_sources(sources)
    manifest = context["clearance"]["manifest"]

    assert manifest[0]["kind"] == "exit"
    assert manifest[-1]["kind"] == "buy"


def test_clearance_context_manifest_carries_visible_order_proof() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Approve",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:30+00:00",
        }
    ]
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "preview_state": "READY",
            "side": "BUY",
            "submit_enabled": True,
            "order_value_label": "$1000.00",
            "notional": 1000.0,
            "order_intent_hash": "a" * 64,
            "order_intent_hash_label": "aaaaaaaaaaaa",
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:30+00:00",
        }
    ]
    sources["execution"]["orderable_rows"] = sources["execution"]["preview_rows"]  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    manifest = context["clearance"]["manifest"]

    assert manifest == [
        {
            "kind": "buy",
            "ticker": "AMZN",
            "side": "BUY",
            "reason": "5 independent source(s); 2 confirmed signal(s).",
            "notional": 1000.0,
            "order_intent_hash": "a" * 64,
            "order_intent_hash_label": "aaaaaaaaaaaa",
            "cycle_id": "cycle-live-20260522-1530",
            "as_of": "2026-05-22T15:28:30+00:00",
        }
    ]


def test_clearance_manifest_uses_execution_preview_proof_when_candidate_is_older() -> None:
    sources = _sample_sources()
    sources["dashboard"]["review_queue"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "action": "WATCH",
            "conviction_pct": 69,
            "gate_status": "PASS",
            "risk_decision": "WARN",
            "review_state": "Ready",
            "human_review_decision": "Approve",
            "source_count": 5,
            "confirmed_signal_count": 2,
            "cycle_id": "old-cycle",
            "as_of": "2026-05-22T14:00:00+00:00",
        }
    ]
    sources["execution"]["preview_rows"] = [  # type: ignore[index]
        {
            "ticker": "AMZN",
            "preview_state": "READY",
            "side": "BUY",
            "submit_enabled": True,
            "notional": 1000.0,
            "order_intent_hash": "b" * 64,
            "order_intent_hash_label": "bbbbbbbbbbbb",
            "cycle_id": "current-execution-cycle",
            "as_of": "2026-05-22T15:28:30+00:00",
        }
    ]
    sources["execution"]["orderable_rows"] = sources["execution"]["preview_rows"]  # type: ignore[index]

    context = cockpit_context_from_sources(sources)
    manifest = context["clearance"]["manifest"]

    assert manifest[0]["order_intent_hash"] == "b" * 64
    assert manifest[0]["cycle_id"] == "current-execution-cycle"
    assert manifest[0]["as_of"] == "2026-05-22T15:28:30+00:00"


def _submit_form(*, include_second: bool = False) -> dict[str, object]:
    form: dict[str, object] = {
        "submit_ack": "on",
        "submit_phrase": "submit paper orders",
        "cycle_id": "cycle-1",
        "ticker": "AAA",
        "as_of": "2026-05-22T15:28:30+00:00",
        "order_intent_hash": "a" * 64,
        "notional_hint": "4200",
        "side_hint": "BUY",
    }
    if include_second:
        form = {
            **form,
            "cycle_id": ["cycle-1", "cycle-1"],
            "ticker": ["AAA", "BBB"],
            "as_of": [
                "2026-05-22T15:28:30+00:00",
                "2026-05-22T15:28:40+00:00",
            ],
            "order_intent_hash": ["a" * 64, "b" * 64],
            "notional_hint": ["4200", "3000"],
            "side_hint": ["BUY", "BUY"],
        }
    return form


def _submit_json(*, include_second: bool = False) -> dict[str, object]:
    form = _submit_form(include_second=include_second)
    tickers = form["ticker"] if isinstance(form["ticker"], list) else [form["ticker"]]
    cycles = form["cycle_id"] if isinstance(form["cycle_id"], list) else [form["cycle_id"]]
    as_of_values = form["as_of"] if isinstance(form["as_of"], list) else [form["as_of"]]
    hashes = (
        form["order_intent_hash"]
        if isinstance(form["order_intent_hash"], list)
        else [form["order_intent_hash"]]
    )
    notionals = (
        form["notional_hint"]
        if isinstance(form["notional_hint"], list)
        else [form["notional_hint"]]
    )
    sides = form["side_hint"] if isinstance(form["side_hint"], list) else [form["side_hint"]]
    return {
        "submit_ack": True,
        "submit_phrase": "submit paper orders",
        "orders": [
            {
                "cycle_id": str(cycles[index]),
                "ticker": str(ticker),
                "as_of": str(as_of_values[index]),
                "order_intent_hash": str(hashes[index]),
                "notional_hint": str(notionals[index]),
                "side_hint": str(sides[index]),
            }
            for index, ticker in enumerate(tickers)
        ],
    }


def _execution_context(*, include_second: bool = False, broker_order_id: str = "") -> dict[str, object]:
    rows = [
        {
            "cycle_id": "cycle-1",
            "ticker": "AAA",
            "as_of": "2026-05-22T15:28:30+00:00",
            "side": "BUY",
            "quantity": None,
            "notional": 4200.0,
            "time_in_force": "DAY",
            "order_intent_hash": "a" * 64,
            "order_approved": True,
            "submit_enabled": True,
            "submit_blocker": "ready",
            "broker_order_id": broker_order_id,
            "preview": {
                "cycle_id": "cycle-1",
                "ticker": "AAA",
                "as_of": "2026-05-22T15:28:30+00:00",
                "order_intent_hash": "a" * 64,
                "order_intent_version": "0.1.0",
            },
        }
    ]
    if include_second:
        rows.append(
            {
                **rows[0],
                "ticker": "BBB",
                "as_of": "2026-05-22T15:28:40+00:00",
                "notional": 3000.0,
                "order_intent_hash": "b" * 64,
                "preview": {
                    "cycle_id": "cycle-1",
                    "ticker": "BBB",
                    "as_of": "2026-05-22T15:28:40+00:00",
                    "order_intent_hash": "b" * 64,
                    "order_intent_version": "0.1.0",
                },
            }
        )
    return {
        "execution_freshness_gate": {"ready": True, "detail": "fresh"},
        "preview_rows": rows,
    }


def _patch_submit_context(
    monkeypatch: MonkeyPatch,
    *,
    include_second: bool = False,
    broker_order_id: str = "",
) -> None:
    async def fake_broker() -> dict[str, object]:
        return {
            "connected": True,
            "mode": "paper",
            "checked_at": datetime.now(UTC).isoformat(),
            "account": {"status": "ACTIVE", "equity": 100000.0, "buying_power": 100000.0},
            "positions": [],
            "orders": [],
        }

    async def fake_sources() -> list[dict[str, object]]:
        checked_at = datetime.now(UTC).isoformat()
        return [
            {
                "schema_version": "0.1.0",
                "source": source,
                "source_tier": "MARKET_DATA",
                "status": "HEALTHY",
                "checked_at": checked_at,
                "freshness": "FRESH",
                "last_success_at": checked_at,
                "observed_lag_seconds": 1,
                "error_count": 0,
                "reliability_score": 1.0,
                "rate_limit_reset_at": None,
                "notes": [],
            }
            for source in ("daily-market-bars", "massive-stock-trades")
        ]

    async def fake_context(**_kwargs: object) -> dict[str, object]:
        return _execution_context(include_second=include_second, broker_order_id=broker_order_id)

    def fake_freshness_gate(_broker: object, _sources: object) -> dict[str, object]:
        return {"ready": True, "detail": "fresh"}

    monkeypatch.setenv("AGENCY_ALPACA_BROKER_ENABLED", "true")
    monkeypatch.setenv("AGENCY_BROKER_SUBMIT_ENABLED", "true")
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.setattr(dashboard_module, "_fresh_broker_status_context", fake_broker)
    monkeypatch.setattr(dashboard_module, "runtime_data_source_status", fake_sources)
    monkeypatch.setattr(dashboard_module, "execution_preview_context", fake_context)
    monkeypatch.setattr(dashboard_module, "_require_immediate_execution_freshness", fake_freshness_gate)
