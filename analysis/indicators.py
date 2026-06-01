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
    return df


def score_stock(df: pd.DataFrame) -> tuple[int, list[str]]:
    """
    Return (score, signals) for the most recent day.
    Higher score = stronger technical setup.
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

    # --- KD (max 25pts) ---
    k, d = val(last, "K"), val(last, "D")
    pk, pd_ = val(prev, "K"), val(prev, "D")
    if not any(np.isnan([k, d, pk, pd_])):
        if k < 20 and d < 20:
            score += 12
            signals.append(f"KD深度超賣({k:.0f}/{d:.0f})")
        elif k < 30 and d < 30:
            score += 8
            signals.append(f"KD超賣({k:.0f}/{d:.0f})")
        if pk < pd_ and k >= d:
            score += 15
            signals.append("KD黃金交叉")

    # --- MACD (max 20pts) ---
    hist = val(last, "MACD_hist")
    phist = val(prev, "MACD_hist")
    if not any(np.isnan([hist, phist])):
        if hist > 0 and phist <= 0:
            score += 20
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

    # --- 乖離率 (max 10pts) ---
    bias20 = val(last, "Bias20")
    if not np.isnan(bias20):
        if -3 <= bias20 <= 5:
            score += 10
            signals.append(f"20MA乖離健康({bias20:+.1f}%)")
        elif 5 < bias20 <= 10:
            score += 5
            signals.append(f"20MA乖離尚可({bias20:+.1f}%)")
        elif bias20 > 15:
            score -= 10
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

    return max(0, score), signals
