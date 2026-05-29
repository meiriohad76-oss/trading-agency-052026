# Tooltip Registry

Operator-facing tooltips should explain what a field means, why it matters, and what the operator can do next.

| Label | Tooltip Intent |
| --- | --- |
| Trade Eligibility | Explains whether the current row can become a paper order after research and order approval. |
| Coverage | Explains how much of the required universe or dataset is currently represented. |
| Reviewed/Pending | Explains how much of today's review queue is already handled. |
| Open Risk | Explains whether a row is blocked, cautionary, or open for review by the risk layer. |
| Confirmed signals | Explains that confirmed evidence comes from directly inspected source data. |
| Conviction | Explains that conviction combines signal direction, confidence, source quality, freshness, and policy gates. |
| Candidate impact | Explains whether running or due refresh work may change the visible candidate queue. |

## Market Regime

| Label | Tooltip Intent |
| --- | --- |
| Regime: Risk On | SPY 5D >= +1%, breadth >= 55%, vol < 20%. Standard approval path for candidates. |
| Regime: Risk Off | Broad market is defensive. SPY 5D <= -1.5% or breadth <= 35% or bond flight detected. Raise the conviction bar. |
| Regime: Volatile | High realized volatility with a large price swing. Reduce position sizes and tighten stops. |
| Regime: Rotating | Sector leadership is split. Market index direction is less useful. Focus on sector alignment per candidate. |
| Regime: Neutral | No strong directional signal. Candidate-specific evidence dominates the decision. |
| Vol Regime: CALM | VIX below 20. Normal fear levels. Standard position sizing applies. |
| Vol Regime: ELEVATED | VIX 20-35. Elevated uncertainty. Reduce new position sizes to 75% of normal. |
| Vol Regime: HIGH | VIX above 35. High fear. Reduce position sizes to 50%. Prefer cash over new entries. |
| Breadth | Percent of active US equities that advanced over the past 5 sessions. Above 55% means broad participation. |
| Sector: ADVANCING | RS-Ratio positive and RS-Momentum positive. Sector is leading. |
| Sector: TOPPING | RS-Ratio positive but RS-Momentum turning negative. Sector is still ahead but losing steam. |
| Sector: BASING | RS-Ratio negative but RS-Momentum improving. Sector is lagging but showing early recovery. |
| Sector: DECLINING | RS-Ratio negative and RS-Momentum negative. Sector is underperforming and weakening. |
| Flow confirmed | CMF(14) positive and OBV trend rising. Institutional flow is accumulating in this sector ETF. |
| Flow not confirmed | Price momentum is present but CMF/OBV does not yet confirm the move. |
| Momentum score | Composite z-score: 20% of 5D, 50% of 20D, 30% of 60D excess return vs SPY. Positive means leadership. |
| Flow score | Chaikin Money Flow (14-day). Positive means accumulation; negative means distribution. |
| RS-Ratio | Sector 20D return minus SPY 20D return. Positive means the sector is outperforming the broad market. |
| RS-Momentum | Change in RS-Ratio over 5 sessions. Positive means relative strength is improving. |
| Conviction boost | Added to or subtracted from a candidate's final conviction score based on sector tailwind or headwind. |
| 2S10S (T10Y2Y) | 10-year minus 2-year Treasury yield spread. Below 0 is an inverted yield curve. |
| HY OAS | ICE BofA High Yield Option-Adjusted Spread. Widening spreads signal institutional risk-off. |
| CORP OAS | Investment-grade corporate option-adjusted spread. Wider means tighter credit conditions. |
| STRESS INDEX | St. Louis Fed Financial Stress Index. Negative means below-average stress; rising means tension. |
| CLAIMS (ICSA) | Weekly initial jobless claims. Rising claims can signal a weakening labor market. |
| 10Y YIELD | 10-year Treasury constant maturity rate. A fast rise pressures equity valuations. |
| Tailwind portfolio | Position sector is advancing with flow confirmation. The backdrop supports holding. |
| Topping portfolio | Position sector is positive but losing relative strength. Monitor for deterioration. |
| Headwind portfolio | Position sector is underperforming and weakening. Consider tightening the stop. |
| Intraday drift | Current session return for each sector ETF vs SPY. Advisory only; does not change regime modifiers. |
| Data as of | Latest price bar date used for regime calculations. Market data is sourced from Massive state files. |
| FRED as of | Date of latest FRED values. FRED updates daily series and is cached for 24 hours. |
