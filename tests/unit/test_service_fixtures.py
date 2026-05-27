from __future__ import annotations

import tests.unit.service_fixtures as fixtures


def test_selection_report_fixture_validates_before_return(
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_validate_contract(name: str, payload: object) -> None:
        calls.append(name)
        assert isinstance(payload, dict)

    monkeypatch.setattr(fixtures, "validate_contract", fake_validate_contract)

    report = fixtures.selection_report()

    assert report["ticker"] == "AAPL"
    assert calls == ["selection-report"]
