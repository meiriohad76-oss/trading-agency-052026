from __future__ import annotations

from backtests.scoped_loader import SignalFn
from signals.abnormal_volume import abnormal_volume_score
from signals.fundamentals import fundamental_score
from signals.insider import insider_score
from signals.institutional import institutional_score
from signals.news import news_score
from signals.options_flow import options_flow_score
from signals.sector_momentum import sector_momentum_score

SIGNALS: dict[str, SignalFn] = {
    "abnormal_volume": abnormal_volume_score,
    "fundamentals": fundamental_score,
    "insider": insider_score,
    "institutional": institutional_score,
    "news": news_score,
    "options_flow": options_flow_score,
    "sector_momentum": sector_momentum_score,
}
