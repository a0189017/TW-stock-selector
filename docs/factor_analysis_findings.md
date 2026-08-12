# Factor-analysis findings (2026-08-12)

`python backtest.py --factor-analysis --stocks 120` (2y history, 10-day forward
return, ~120 most liquid TWSE/TPEX stocks) — measures each `score_stock`
signal's own predictive lift in isolation: average forward return when the
signal fired vs. when it didn't.

## Raw results (sorted by effect size, pp = percentage points)

| 訊號 | 觸發樣本數 | 觸發平均報酬 | 觸發勝率 | 未觸發平均報酬 | 效果量(pp) |
|---|---|---|---|---|---|
| 乖離過大(>15%) | 974 | 6.54% | 58.4% | 2.89% | **+3.65** |
| RSI超買(>70) | 1048 | 5.54% | 57.4% | 2.98% | **+2.56** |
| 乖離超賣(<-10%) | 557 | 5.51% | 63.7% | 3.11% | +2.40 |
| 均線多頭排列 | 3063 | 4.69% | 57.1% | 2.61% | +2.08 |
| MA5>MA20 | 5814 | 3.91% | 56.6% | 2.32% | +1.59 |
| 布林下軌反彈 | 875 | 4.40% | 60.3% | 3.13% | +1.27 |
| 布林擠壓突破 | 827 | 4.28% | 56.6% | 3.15% | +1.13 |
| 爆量(>=3倍) | 387 | 4.28% | 57.9% | 3.20% | +1.08 |
| RSI超賣(<30) | 253 | 3.73% | 58.1% | 3.23% | +0.50 |
| MACD動能擴大 | 2508 | 3.54% | 55.1% | 3.14% | +0.40 |
| 放量(>=1.5倍) | 1910 | 3.55% | 55.8% | 3.17% | +0.39 |
| KD黃金交叉 | 1044 | 3.31% | 56.7% | 3.23% | **+0.07** |
| MACD柱翻正 | 437 | 2.72% | 57.0% | 3.27% | **-0.55** |
| KD超賣(<30) | 1708 | 2.36% | 55.4% | 3.42% | **-1.06** |
| 乖離健康(-3~5%) | 4652 | 2.24% | 54.5% | 4.10% | **-1.87** |

## What was mis-calibrated

Comparing effect size to the weight each signal held in `score_stock`
(`analysis/indicators.py`) before this pass, four signals were clearly
over-weighted relative to their actual predictive lift, regardless of market
regime — these were adjusted down:

| 訊號 | 舊權重 | 新權重 | 理由 |
|---|---|---|---|
| MACD柱由負轉正 | +20 (全系統最高) | +5 | 效果量 -0.55pp（負向），卻是最高權重 |
| KD黃金交叉 | +15 (第2高) | +3 | 效果量 +0.07pp（幾乎無預測力） |
| KD超賣(<30) | +8 | +2 | 效果量 -1.06pp（負向） |
| 乖離健康(-3~5%) | +10 | +2 | 效果量 -1.87pp（15個訊號中最差） |

## What was deliberately NOT flipped

`乖離過大(>15%)` (-10 → -6) and `RSI超買(>70)` (-8 → -5) tested as the two
*strongest positive* signals in this sample, but the system penalizes them on
purpose as an anti-chase risk-control rule (`ai/prompt_builder.py` — 不追高).
This backtest window is a ~2-year TW equities bull run (TAIEX made repeated
all-time highs through the period) — "already extended" may simply reflect
momentum persistence specific to this regime, not something that would hold
in a down or choppy market. Per user decision (2026-08-12): keep the
penalty's direction, only soften the magnitude. Revisit with a longer or
regime-mixed backtest window before considering a sign flip.

## Not covered by this pass

`analysis/multi_factor.py`'s `STRATEGY_WEIGHTS` (chip/fundamental/sector/RS60
blend weights) were not touched — `backtest.py --factor-analysis` only
isolates the price/volume signals inside `score_stock`, not the chip or
fundamental factors. A similar factor-analysis extension covering those would
be a reasonable follow-up.

## Verification after applying

Re-run `python backtest.py` (default 10-day horizon) before/after to confirm
the high-score vs low-score bucket return spread didn't narrow.
