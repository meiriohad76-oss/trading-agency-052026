from __future__ import annotations

from collections.abc import Iterable

SPDR_SECTOR_ETFS = (
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

BROAD_MARKET_ETFS = (
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
)

SECTOR_ETF_TICKERS = SPDR_SECTOR_ETFS + BROAD_MARKET_ETFS
SECTOR_ETF_SET = frozenset(SECTOR_ETF_TICKERS)


def include_sector_etfs(tickers: Iterable[str]) -> list[str]:
    return sorted({ticker.upper() for ticker in tickers} | SECTOR_ETF_SET)


def covered_sector_etfs(tickers: Iterable[str]) -> list[str]:
    return sorted({ticker.upper() for ticker in tickers} & SECTOR_ETF_SET)
