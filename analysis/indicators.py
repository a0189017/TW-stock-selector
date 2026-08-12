"""Compute technical indicators directly with pandas (no external TA library needed)."""
import numpy as np
import pandas as pd


def compute_kd(df: pd.DataFrame, n: int = 9, m: int = 3) -> pd.DataFrame:
    """Taiwan-style KD: RSV with EWM smoothing (alpha=1/3)."""
    low_n = df["Low"].rolling(n).min()
    high_n = df["High"].rolling(n).max()
    denom = (high_n - low_n).replace(0, np.nan)
    rsv = (100 * (df["Close"] - low_n) / denom).clip(0, 100)
    rsv_filled = rsv.ffill().fillna(50)

    k = rsv_filled.ewm(alpha=1 / m, adjust=False).mean()
    d = k.ewm(alpha=1 / m, adjust=False).mean()

    # Mask rows where rolling window wasn't full yet
    k[rsv.isna()] = np.nan
    d[rsv.isna()] = np.nan
    return k.rename("K"), d.rename("D")


def compute_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["Close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["Close"].ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd.rename("MACD"), sig.rename("MACD_sig"), hist.rename("MACD_hist")


def compute_mas(df: pd.DataFrame) -> pd.DataFrame:
    for n in [5, 10, 20, 60, 120, 240]:
        df[f"MA{n}"] = df["Close"].rolling(n).mean()
    return df


def compute_bias(df: pd.DataFrame) -> pd.DataFrame:
    """乖離率 from MA5, MA20, MA60."""
    for n in [5, 20, 60]:
        col = f"MA{n}"
        if col in df.columns:
            df[f"Bias{n}"] = (df["Close"] - df[col]) / df[col] * 100
    return df


def compute_volume_ratio(df: pd.DataFrame) -> pd.DataFrame:
    """Volume ratio: today / 5-day average (excluding today)."""
    vol_ma5 = df["Volume"].rolling(5).mean().shift(1)
    df["VolMA5"] = vol_ma5
    df["VolRatio"] = df["Volume"] / vol_ma5.replace(0, np.nan)
    return df


def compute_rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = df["Close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.rename("RSI")


def compute_atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """
    Wilder's ATR (Average True Range) — volatility measure used to size
    entry/stop-loss/take-profit bands (see analysis/price_levels.py) instead
    of a flat MA or a fixed % of cost.
    """
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return atr.rename("ATR")


def compute_bollinger(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """
    Bollinger Bands (n-day SMA ± k×σ).
    Adds BB_upper, BB_lower, BB_mid, BB_pct (%B), BB_width.
    """
    mid = df["Close"].rolling(n).mean()
    std = df["Close"].rolling(n).std(ddof=0)
    upper = mid + k * std
    lower = mid - k * std
    band_width = (upper - lower).replace(0, np.nan)
    bb_pct = (df["Close"] - lower) / band_width
    bb_width = band_width / mid.replace(0, np.nan) * 100  # width as % of mid
    df["BB_upper"] = upper
    df["BB_lower"] = lower
    df["BB_mid"] = mid
    df["BB_pct"] = bb_pct
    df["BB_width"] = bb_width
    return df


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all indicators to DataFrame in place."""
    df = df.copy()
    k, d = compute_kd(df)
    macd, macd_sig, macd_hist = compute_macd(df)
    df["K"] = k
    df["D"] = d
    df["MACD"] = macd
    df["MACD_sig"] = macd_sig
    df["MACD_hist"] = macd_hist
    df = compute_mas(df)
    df = compute_bias(df)
    df = compute_volume_ratio(df)
    df["RSI"] = compute_rsi(df)
    df = compute_bollinger(df)
    df["ATR"] = compute_atr(df)
    return df


def compute_relative_strength(stock_df: pd.DataFrame,
                              bench_df: pd.DataFrame | None,
                              windows=(20, 60)) -> dict:
    """
    Relative strength = stock return − benchmark (TAIEX) return over each window.
    Positive RS = outperforming the index. Returns {rs20, rs60, rs_label}.
    Empty dict if benchmark unavailable or histories too short.
    """
    if bench_df is None or bench_df.empty or stock_df is None or stock_df.empty:
        return {}

    s_close = stock_df["Close"].dropna()
    b_close = bench_df["Close"].dropna()
    if len(s_close) < max(windows) + 1 or len(b_close) < max(windows) + 1:
        return {}

    out = {}
    for w in windows:
        s_ret = (s_close.iloc[-1] / s_close.iloc[-1 - w] - 1) * 100
        b_ret = (b_close.iloc[-1] / b_close.iloc[-1 - w] - 1) * 100
        out[f"rs{w}"] = round(float(s_ret - b_ret), 2)

    rs20 = out.get("rs20", 0)
    if rs20 >= 8:
        out["rs_label"] = "明顯強於大盤"
    elif rs20 >= 2:
        out["rs_label"] = "略強於大盤"
    elif rs20 <= -8:
        out["rs_label"] = "明顯弱於大盤"
    elif rs20 <= -2:
        out["rs_label"] = "略弱於大盤"
    else:
        out["rs_label"] = "與大盤同步"
    return out


def score_stock(df: pd.DataFrame, rs: dict | None = None,
                fundamental: dict | None = None) -> tuple[int, list[str]]:
    """
    Return (score, signals) for the most recent day.
    Higher score = stronger technical setup.

    rs:          optional relative-strength dict from compute_relative_strength.
    fundamental: optional dict with rev_yoy / rev_mom (月營收成長率, %).
    """
    if df is None or len(df) < 20:
        return 0, []

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last

    score = 0
    signals = []

    def val(row, col):
        v = row.get(col, np.nan)
        return float(v) if pd.notna(v) else np.nan

    # --- KD (max ~15pts) ---
    # Weights re-calibrated 2026-08 against backtest.py --factor-analysis (see
    # docs/factor_analysis_findings.md): "KD超賣(<30)" and "KD黃金交叉" tested
    # with near-zero/negative 10-day forward-return effect size despite being
    # the 2nd-highest weights in the whole formula — cut down accordingly.
    # The k<20&d<20 "深度超賣" branch wasn't isolated in that test, left as-is.
    k, d = val(last, "K"), val(last, "D")
    pk, pd_ = val(prev, "K"), val(prev, "D")
    if not any(np.isnan([k, d, pk, pd_])):
        if k < 20 and d < 20:
            score += 12
            signals.append(f"KD深度超賣({k:.0f}/{d:.0f})")
        elif k < 30 and d < 30:
            score += 2  # was +8 — factor-analysis effect size -1.06pp (negative)
            signals.append(f"KD超賣({k:.0f}/{d:.0f})")
        if pk < pd_ and k >= d:
            score += 3  # was +15 — factor-analysis effect size +0.07pp (no lift)
            signals.append("KD黃金交叉")

    # --- MACD (max ~12pts) ---
    # "MACD柱由負轉正" was the single highest weight in score_stock (+20) but
    # tested with a NEGATIVE forward-return effect (-0.55pp) — cut well below
    # "MACD動能持續擴大" (+0.40pp), which now correctly outweighs it.
    hist = val(last, "MACD_hist")
    phist = val(prev, "MACD_hist")
    if not any(np.isnan([hist, phist])):
        if hist > 0 and phist <= 0:
            score += 5  # was +20 — factor-analysis effect size -0.55pp (negative)
            signals.append("MACD柱由負轉正")
        elif hist > phist > 0:
            score += 12
            signals.append("MACD動能持續擴大")
        elif hist < phist < 0:
            score -= 5   # worsening
        elif hist > 0 and phist > 0:
            score += 5
            signals.append("MACD正值")

    # --- Moving average structure (max 30pts) ---
    close = val(last, "Close")
    ma5 = val(last, "MA5")
    ma10 = val(last, "MA10")
    ma20 = val(last, "MA20")
    ma60 = val(last, "MA60")
    ma120 = val(last, "MA120")
    ma240 = val(last, "MA240")

    if not any(np.isnan([ma5, ma20])) and ma5 > ma20:
        score += 8
        signals.append("MA5>MA20 短線多頭")
    if not any(np.isnan([ma20, ma60])) and ma20 > ma60:
        score += 8
        signals.append("MA20>MA60 中線多頭")
    if not np.isnan(ma240) and close > ma240:
        score += 9
        signals.append("收盤站上年線")
    if not any(np.isnan([ma5, ma10, ma20, ma60])) and ma5 > ma10 > ma20 > ma60:
        score += 5
        signals.append("均線多頭排列")

    # --- 乖離率 (max ~5pts) ---
    # "乖離健康(-3~5%)" tested as the WORST performer of all 15 measured signals
    # (-1.87pp effect size) despite carrying the joint-highest weight — cut hard.
    # "乖離過大(>15%)" tested as the STRONGEST positive signal (+3.65pp) in this
    # 2-year bull-market sample, but that's kept as a risk-control penalty on
    # purpose (追高風控原則, ai/prompt_builder.py) rather than flipped to a
    # reward — the effect may just reflect momentum persistence specific to
    # this backtest window, not something that holds in a down/choppy market.
    # Only the penalty magnitude was softened (-10 → -6). Same reasoning for
    # RSI超買 below. See docs/factor_analysis_findings.md.
    bias20 = val(last, "Bias20")
    if not np.isnan(bias20):
        if -3 <= bias20 <= 5:
            score += 2  # was +10 — factor-analysis effect size -1.87pp (worst signal)
            signals.append(f"20MA乖離健康({bias20:+.1f}%)")
        elif 5 < bias20 <= 10:
            score += 5
            signals.append(f"20MA乖離尚可({bias20:+.1f}%)")
        elif bias20 > 15:
            score -= 6  # was -10 — softened; still a deliberate anti-chase penalty
            signals.append(f"20MA乖離過大({bias20:+.1f}%) 注意追高")
        elif bias20 < -10:
            score += 3  # deeply oversold on MA, potential bounce
            signals.append(f"20MA乖離深度負({bias20:+.1f}%) 超跌反彈機會")

    # --- Volume surge (max 20pts) ---
    vol_ratio = val(last, "VolRatio")
    if not np.isnan(vol_ratio):
        if vol_ratio >= 3.0:
            score += 20
            signals.append(f"爆量 ({vol_ratio:.1f}倍均量)")
        elif vol_ratio >= 2.0:
            score += 15
            signals.append(f"大量 ({vol_ratio:.1f}倍均量)")
        elif vol_ratio >= 1.5:
            score += 10
            signals.append(f"放量 ({vol_ratio:.1f}倍均量)")
        elif vol_ratio < 0.5:
            score -= 3
            signals.append("量能萎縮")

    # --- RSI (max 13pts) ---
    rsi = val(last, "RSI")
    if not np.isnan(rsi):
        if rsi < 20:
            score += 13
            signals.append(f"RSI深度超賣({rsi:.0f})")
        elif rsi < 30:
            score += 8
            signals.append(f"RSI超賣({rsi:.0f})")
        elif rsi > 70:
            # was -8 — softened to -5 for the same reason as 乖離過大 above
            # (factor-analysis measured +2.56pp here; kept as a risk-control
            # penalty, not flipped, per deliberate choice — see
            # docs/factor_analysis_findings.md).
            score -= 5
            signals.append(f"RSI超買({rsi:.0f})")

    # --- Bollinger Bands (max 18pts) ---
    bb_pct = val(last, "BB_pct")
    bb_width = val(last, "BB_width")
    prev_bb_width = val(prev, "BB_width")
    close_change = val(last, "Close") - val(prev, "Close")

    if not np.isnan(bb_pct):
        if bb_pct < 0.1 and close_change > 0:
            score += 10
            signals.append(f"布林下軌反彈(%B={bb_pct:.2f})")
        elif bb_pct > 0.9:
            score -= 5
            signals.append(f"布林上軌警戒(%B={bb_pct:.2f})")

    # Bollinger squeeze breakout: width was shrinking, now expanding
    if not any(np.isnan([bb_width, prev_bb_width])) and prev_bb_width > 0:
        if bb_width > prev_bb_width * 1.1 and bb_pct > 0.5:
            score += 8
            signals.append("布林通道突破收斂")

    # --- 相對強度 RS (max 12pts) ---
    if rs:
        rs20 = rs.get("rs20")
        if rs20 is not None:
            if rs20 >= 8:
                score += 12
                signals.append(f"20日大幅強於大盤({rs20:+.1f}%)")
            elif rs20 >= 2:
                score += 7
                signals.append(f"20日強於大盤({rs20:+.1f}%)")
            elif rs20 <= -8:
                score -= 8
                signals.append(f"20日明顯落後大盤({rs20:+.1f}%)")

    # --- 月營收成長 (max 12pts) ---
    if fundamental:
        yoy = fundamental.get("rev_yoy")
        if yoy is not None:
            if yoy >= 30:
                score += 12
                signals.append(f"月營收YoY大增({yoy:+.0f}%)")
            elif yoy >= 10:
                score += 7
                signals.append(f"月營收YoY成長({yoy:+.0f}%)")
            elif yoy <= -20:
                score -= 8
                signals.append(f"月營收YoY衰退({yoy:+.0f}%)")

    return max(0, score), signals
