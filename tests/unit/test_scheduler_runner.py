from __future__ import annotations

from agency.runtime.scheduler_runner import jobs_for_phase


def test_pre_market_jobs_include_stock_trades_and_email() -> None:
    jobs = jobs_for_phase("pre_market")
    names = {j["name"] for j in jobs}
    assert "stock_trades" in names
    assert "subscription_emails" in names
    assert "sec_company_facts" not in names


def test_regular_market_jobs_include_news_only() -> None:
    jobs = jobs_for_phase("regular_market")
    names = {j["name"] for j in jobs}
    assert "news_rss" in names
    assert "prices_daily" not in names
    assert "sec_form4" not in names


def test_after_hours_jobs_include_prices_and_trades() -> None:
    jobs = jobs_for_phase("after_hours")
    names = {j["name"] for j in jobs}
    assert "prices_daily" in names
    assert "stock_trades" in names


def test_overnight_jobs_include_sec_baselines() -> None:
    jobs = jobs_for_phase("overnight")
    names = {j["name"] for j in jobs}
    assert "sec_company_facts" in names
    assert "sec_form4" in names
    assert "sec_13f" in names
