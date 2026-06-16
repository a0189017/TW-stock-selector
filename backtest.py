"""Validate the technical scoring weights against history.

The scores in analysis/indicators.score_stock are hand-tuned magic numbers. This
script checks whether they actually separate winners from losers: it computes the
technical score on every Nth historical bar for a sample of liquid stocks, then
measures the forward return `horizon` trading days later, bucketed by score.

If the high-score bucket doesn't beat the low-score bucket, the weights need work.

Usage:
    python backtest.py                       # default: ~120 liquid stocks, 2y, 10-day horizon
    python backtest.py --stocks 200 --horizon 20 --step 3
    python backtest.py --codes 2330,2454,3008
"""
import argparse

import numpy as np
import pandas as pd
import yfinance as yf

from analysis.indicators import add_all_indicators, score_stock
from log import get_logger, enable_debug

logger = get_logger()


def _download(tickers: list[str], period: str) -> dict[str, pd.DataFrame]:
    raw = yf.download(tickers=tickers, period=period, interval="1d",
                      auto_adjust=True, progress=False, threads=True, group_by="ticker")
    out = {}
    if raw.empty:
        return out
    multi = isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            df = raw[t].copy() if multi else raw.copy()
            df = df.dropna(subset=["Close"])
            if len(df) > 80:
                out[t] = df
        except Exception:
            continue
    return out


def _pick_codes(n: int) -> list[tuple[str, str]]:
    """Pick the n most liquid ordinary stocks from today's universe."""
    from data.fetcher_universe import fetch_universe
    from analysis.screener import stage1_liquidity
    df = stage1_liquidity(fetch_universe())
    df = df.sort_values("trade_value", ascending=False).head(n)
    return list(zip(df["code"], df["exchange"]))


def backtest(code_exchanges: list[tuple[str, str]], horizon: int, step: int,
             period: str) -> dict:
    tickers = [f"{c}{'.TW' if e == 'TWSE' else '.TWO'}" for c, e in code_exchanges]
    logger.info("backtest: downloading %d tickers (%s)", len(tickers), period)
    history = _download(tickers, period)

    buckets = {"高分(≥55)": [], "中分(45-54)": [], "低分(<45)": [], "未達門檻(<35)": []}
    samples = 0

    for ticker, df in history.items():
        df_ind = add_all_indicators(df)
        closes = df_ind["Close"].values
        n = len(df_ind)
        # need >=60 bars of history before scoring, and horizon bars after
        for i in range(60, n - horizon, step):
            window = df_ind.iloc[:i + 1]
            score, _ = score_stock(window)          # pure technical, no RS/fundamental
            base, future = closes[i], closes[i + horizon]
            if base <= 0 or np.isnan(base) or np.isnan(future):
                continue
            fwd = (future - base) / base * 100
            if score >= 55:
                buckets["高分(≥55)"].append(fwd)
            elif score >= 45:
                buckets["中分(45-54)"].append(fwd)
            elif score >= 35:
                buckets["低分(<45)"].append(fwd)
            else:
                buckets["未達門檻(<35)"].append(fwd)
            samples += 1

    result = {
        "設定": {"股票數": len(history), "持有交易日": horizon,
                "取樣間隔": step, "歷史長度": period, "總樣本": samples},
        "分組結果": {},
    }
    for name, rets in buckets.items():
        if not rets:
            result["分組結果"][name] = {"樣本數": 0}
            continue
        arr = np.array(rets)
        result["分組結果"][name] = {
            "樣本數": len(arr),
            "平均報酬%": round(float(arr.mean()), 2),
            "中位數%": round(float(np.median(arr)), 2),
            "勝率%": round(float((arr > 0).mean() * 100), 1),
        }
    return result


def main():
    p = argparse.ArgumentParser(description="技術評分回測")
    p.add_argument("--stocks", type=int, default=120, help="取樣股票數（最流動）")
    p.add_argument("--codes", type=str, default="", help="指定代號，逗號分隔（覆蓋 --stocks）")
    p.add_argument("--horizon", type=int, default=10, help="持有交易日")
    p.add_argument("--step", type=int, default=5, help="取樣間隔（交易日）")
    p.add_argument("--period", type=str, default="2y", help="yfinance 歷史長度")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    if args.debug:
        enable_debug()

    if args.codes:
        # default everything to TWSE; .TWO fallback is rarely needed for a manual list
        code_exchanges = [(c.strip(), "TWSE") for c in args.codes.split(",") if c.strip()]
    else:
        code_exchanges = _pick_codes(args.stocks)

    result = backtest(code_exchanges, args.horizon, args.step, args.period)

    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))

    groups = result["分組結果"]
    hi = groups.get("高分(≥55)", {}).get("平均報酬%")
    lo = groups.get("低分(<45)", {}).get("平均報酬%")
    if hi is not None and lo is not None:
        verdict = "✓ 高分組優於低分組，評分有效" if hi > lo else "✗ 高分組未優於低分組，建議調整權重"
        print(f"\n結論：{verdict}（高分 {hi}% vs 低分 {lo}%）")


if __name__ == "__main__":
    main()
