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


def _extract_signal_flags(df_ind: pd.DataFrame) -> dict[str, bool]:
    """
    Named boolean flags mirroring score_stock's conditions (analysis/indicators.py),
    read at the most recent bar of df_ind. Used to isolate each signal's own
    predictive power — score_stock's weights are hand-tuned; this measures
    whether the weight roughly matches the signal's actual forward-return lift.
    """
    if df_ind is None or len(df_ind) < 2:
        return {}
    last, prev = df_ind.iloc[-1], df_ind.iloc[-2]

    def v(row, col):
        val = row.get(col, np.nan)
        return float(val) if pd.notna(val) else np.nan

    k, d, pk, pd_ = v(last, "K"), v(last, "D"), v(prev, "K"), v(prev, "D")
    hist, phist = v(last, "MACD_hist"), v(prev, "MACD_hist")
    ma5, ma10, ma20, ma60 = v(last, "MA5"), v(last, "MA10"), v(last, "MA20"), v(last, "MA60")
    bias20 = v(last, "Bias20")
    vol_ratio = v(last, "VolRatio")
    rsi = v(last, "RSI")
    bb_pct, bb_width, prev_bb_width = v(last, "BB_pct"), v(last, "BB_width"), v(prev, "BB_width")

    return {
        "KD超賣(<30)": not any(np.isnan([k, d])) and k < 30 and d < 30,
        "KD黃金交叉": not any(np.isnan([pk, pd_, k, d])) and pk < pd_ and k >= d,
        "MACD柱翻正": not any(np.isnan([hist, phist])) and hist > 0 and phist <= 0,
        "MACD動能擴大": not any(np.isnan([hist, phist])) and hist > phist > 0,
        "均線多頭排列": not any(np.isnan([ma5, ma10, ma20, ma60])) and ma5 > ma10 > ma20 > ma60,
        "MA5>MA20": not any(np.isnan([ma5, ma20])) and ma5 > ma20,
        "乖離健康(-3~5%)": not np.isnan(bias20) and -3 <= bias20 <= 5,
        "乖離超賣(<-10%)": not np.isnan(bias20) and bias20 < -10,
        "乖離過大(>15%)": not np.isnan(bias20) and bias20 > 15,
        "爆量(>=3倍)": not np.isnan(vol_ratio) and vol_ratio >= 3.0,
        "放量(>=1.5倍)": not np.isnan(vol_ratio) and vol_ratio >= 1.5,
        "RSI超賣(<30)": not np.isnan(rsi) and rsi < 30,
        "RSI超買(>70)": not np.isnan(rsi) and rsi > 70,
        "布林下軌反彈": not np.isnan(bb_pct) and bb_pct < 0.1,
        "布林擠壓突破": (not any(np.isnan([bb_width, prev_bb_width])) and prev_bb_width > 0
                    and bb_width > prev_bb_width * 1.1 and not np.isnan(bb_pct) and bb_pct > 0.5),
    }


def factor_analysis(code_exchanges: list[tuple[str, str]], horizon: int, step: int,
                    period: str) -> dict:
    """
    Isolate each named signal's own forward-return lift: for every sampled
    (stock, day), record which signals fired, then split ALL forward returns
    into "fired" vs "not fired" per signal. A signal whose fired-group average
    clearly beats its not-fired-group average is pulling its weight; one that
    doesn't is a candidate to reweight down in score_stock.
    """
    tickers = [f"{c}{'.TW' if e == 'TWSE' else '.TWO'}" for c, e in code_exchanges]
    logger.info("factor-analysis: downloading %d tickers (%s)", len(tickers), period)
    history = _download(tickers, period)

    # {signal_name: {"fired": [returns], "not_fired": [returns]}}
    buckets: dict[str, dict[str, list]] = {}

    for ticker, df in history.items():
        df_ind = add_all_indicators(df)
        closes = df_ind["Close"].values
        n = len(df_ind)
        for i in range(60, n - horizon, step):
            flags = _extract_signal_flags(df_ind.iloc[:i + 1])
            if not flags:
                continue
            base = closes[i]
            future = closes[i + horizon]
            if base <= 0 or np.isnan(base) or np.isnan(future):
                continue
            ret = (future - base) / base * 100
            for name, fired in flags.items():
                b = buckets.setdefault(name, {"fired": [], "not_fired": []})
                b["fired" if fired else "not_fired"].append(ret)

    results = {}
    for name, groups in buckets.items():
        fired, not_fired = np.array(groups["fired"]), np.array(groups["not_fired"])
        if len(fired) == 0 or len(not_fired) == 0:
            continue
        fired_avg, not_fired_avg = float(fired.mean()), float(not_fired.mean())
        results[name] = {
            "觸發樣本數": len(fired),
            "觸發_平均報酬%": round(fired_avg, 2),
            "觸發_勝率%": round(float((fired > 0).mean() * 100), 1),
            "未觸發_平均報酬%": round(not_fired_avg, 2),
            "效果量(觸發-未觸發)pp": round(fired_avg - not_fired_avg, 2),
        }
    return dict(sorted(results.items(), key=lambda kv: kv[1]["效果量(觸發-未觸發)pp"], reverse=True))


def _print_factor_analysis(results: dict):
    print(f"\n{'信號':<16} | {'樣本':>6} | {'觸發報酬/勝率':>16} | {'未觸發報酬':>10} | {'效果量pp':>8}")
    print("-" * 70)
    for name, r in results.items():
        print(f"{name:<16} | {r['觸發樣本數']:>6} | "
              f"{r['觸發_平均報酬%']:>6.2f}% /{r['觸發_勝率%']:>5.1f}% | "
              f"{r['未觸發_平均報酬%']:>9.2f}% | {r['效果量(觸發-未觸發)pp']:>+7.2f}")
    print("\n效果量(pp) 越大代表該信號的實證預測力越強——若目前 score_stock 給的權重與這裡")
    print("的排序明顯不成比例（例如效果量很小卻給很高分），代表權重值得依此重新調整。")


def _bucket(score: int) -> str:
    if score >= 55:
        return "高分(≥55)"
    if score >= 45:
        return "中分(45-54)"
    if score >= 35:
        return "低分(<45)"
    return "未達門檻(<35)"


_BUCKET_NAMES = ["高分(≥55)", "中分(45-54)", "低分(<45)", "未達門檻(<35)"]


def backtest(code_exchanges: list[tuple[str, str]], horizons: list[int], step: int,
             period: str) -> dict:
    """
    Returns {horizon: result_dict}. History is downloaded once and each (stock, day)
    is scored once; every horizon reuses that score, so comparing horizons is cheap.
    """
    tickers = [f"{c}{'.TW' if e == 'TWSE' else '.TWO'}" for c, e in code_exchanges]
    logger.info("backtest: downloading %d tickers (%s)", len(tickers), period)
    history = _download(tickers, period)
    max_h = max(horizons)

    # buckets[horizon][bucket_name] -> list of forward returns
    buckets = {h: {name: [] for name in _BUCKET_NAMES} for h in horizons}
    samples = {h: 0 for h in horizons}

    for ticker, df in history.items():
        df_ind = add_all_indicators(df)
        closes = df_ind["Close"].values
        n = len(df_ind)
        # need >=60 bars of history before scoring, and max_h bars after
        for i in range(60, n - max_h, step):
            score, _ = score_stock(df_ind.iloc[:i + 1])  # pure technical, scored once
            name = _bucket(score)
            base = closes[i]
            if base <= 0 or np.isnan(base):
                continue
            for h in horizons:
                future = closes[i + h]
                if np.isnan(future):
                    continue
                buckets[h][name].append((future - base) / base * 100)
                samples[h] += 1

    results = {}
    for h in horizons:
        groups = {}
        for name in _BUCKET_NAMES:
            rets = buckets[h][name]
            if not rets:
                groups[name] = {"樣本數": 0}
                continue
            arr = np.array(rets)
            groups[name] = {
                "樣本數": len(arr),
                "平均報酬%": round(float(arr.mean()), 2),
                "中位數%": round(float(np.median(arr)), 2),
                "勝率%": round(float((arr > 0).mean() * 100), 1),
            }
        results[h] = {
            "設定": {"股票數": len(history), "持有交易日": h,
                    "取樣間隔": step, "歷史長度": period, "總樣本": samples[h]},
            "分組結果": groups,
        }
    return results


def _print_comparison(results: dict):
    """Print a high-score-vs-threshold comparison table across horizons."""
    horizons = sorted(results)
    print(f"\n{'持有日':>5} | {'高分 報酬/勝率':>16} | {'中分':>14} | "
          f"{'低分':>14} | {'未達門檻':>14} | {'高分每日%':>8}")
    print("-" * 88)
    for h in horizons:
        g = results[h]["分組結果"]

        def cell(name):
            d = g.get(name, {})
            if not d.get("樣本數"):
                return f"{'—':>14}"
            return f"{d['平均報酬%']:>6.2f}% /{d['勝率%']:>5.1f}%"

        hi = g.get("高分(≥55)", {})
        per_day = f"{hi['平均報酬%'] / h:.2f}" if hi.get("樣本數") else "—"
        print(f"{h:>5} | {cell('高分(≥55)'):>16} | {cell('中分(45-54)')} | "
              f"{cell('低分(<45)')} | {cell('未達門檻(<35)')} | {per_day:>8}")

    # Which horizon gives the cleanest monotonic ordering by avg return?
    best_h, best_spread = None, -1e9
    for h in horizons:
        g = results[h]["分組結果"]
        vals = [g.get(n, {}).get("平均報酬%") for n in _BUCKET_NAMES]
        if any(v is None for v in vals):
            continue
        monotonic = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
        spread = vals[0] - vals[-1]
        if monotonic and spread > best_spread:
            best_h, best_spread = h, spread
    if best_h is not None:
        print(f"\n結論：持有 {best_h} 日的評分鑑別度最乾淨（四組報酬單調遞增，"
              f"高分−未達門檻 = {best_spread:.2f}pp）")
    else:
        print("\n結論：各 horizon 的分組排序皆非完全單調，評分鑑別度有限")


def main():
    p = argparse.ArgumentParser(description="技術評分回測")
    p.add_argument("--stocks", type=int, default=120, help="取樣股票數（最流動）")
    p.add_argument("--codes", type=str, default="", help="指定代號，逗號分隔（覆蓋 --stocks）")
    p.add_argument("--horizon", type=int, default=10, help="持有交易日")
    p.add_argument("--compare-horizons", type=str, default="",
                   help="一次比較多個 horizon，逗號分隔，例如 5,10,20")
    p.add_argument("--step", type=int, default=5, help="取樣間隔（交易日）")
    p.add_argument("--period", type=str, default="2y", help="yfinance 歷史長度")
    p.add_argument("--factor-analysis", action="store_true",
                   help="逐一測量每個技術信號自己的未來報酬/勝率效果量，"
                        "用實證數據檢查 score_stock 的手調權重是否合理")
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()

    if args.debug:
        enable_debug()

    if args.codes:
        # default everything to TWSE; .TWO fallback is rarely needed for a manual list
        code_exchanges = [(c.strip(), "TWSE") for c in args.codes.split(",") if c.strip()]
    else:
        code_exchanges = _pick_codes(args.stocks)

    import json

    if args.factor_analysis:
        results = factor_analysis(code_exchanges, args.horizon, args.step, args.period)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        _print_factor_analysis(results)
        return

    if args.compare_horizons:
        horizons = sorted({int(h) for h in args.compare_horizons.split(",") if h.strip()})
        results = backtest(code_exchanges, horizons, args.step, args.period)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        _print_comparison(results)
        return

    result = backtest(code_exchanges, [args.horizon], args.step, args.period)[args.horizon]
    print(json.dumps(result, ensure_ascii=False, indent=2))

    groups = result["分組結果"]
    hi = groups.get("高分(≥55)", {}).get("平均報酬%")
    lo = groups.get("低分(<45)", {}).get("平均報酬%")
    if hi is not None and lo is not None:
        verdict = "✓ 高分組優於低分組，評分有效" if hi > lo else "✗ 高分組未優於低分組，建議調整權重"
        print(f"\n結論：{verdict}（高分 {hi}% vs 低分 {lo}%）")


if __name__ == "__main__":
    main()
