from __future__ import annotations

from prices.sector_etfs import BROAD_MARKET_ETFS, SECTOR_ETF_TICKERS, SPDR_SECTOR_ETFS


def test_sector_etf_list_covers_required_spdr_and_broad_market_tickers() -> None:
    assert SPDR_SECTOR_ETFS == (
        "XLK",
        "XLE",
        "XLF",
        "XLV",
        "XLI",
        "XLB",
        "XLY",
        "XLP",
        "XLU",
        "XLC",
        "XLRE",
    )
    assert BROAD_MARKET_ETFS == ("SPY", "QQQ", "IWM", "DIA")
    assert len(SECTOR_ETF_TICKERS) == len(set(SECTOR_ETF_TICKERS))
