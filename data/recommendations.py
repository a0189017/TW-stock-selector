"""Persist each day's screened candidates so the screener can be graded later.

In MCP mode Claude picks the final 10, so we can't know those server-side — but
persisting the *quantitative* top candidates lets us answer the real question:
"does a high technical score actually lead to better forward returns?"
evaluate_performance() walks past screenings and measures forward returns by
score bucket, giving an honest hit-rate / edge readout.
"""
import sqlite3
from pathlib import Path
from datetime import datetime

from log import get_logger

logger = get_logger()

_DB_PATH = Path(__file__).parent.parent / "recommendations.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screened (
            date       TEXT NOT NULL,
            code       TEXT NOT NULL,
            name       TEXT,
            exchange   TEXT,
            close      REAL,
            tech_score INTEGER,
            rs20       REAL,
            rev_yoy    REAL,
            rank       INTEGER,
            PRIMARY KEY (date, code)
        )
    """)
    return conn


def save_screening(candidates: list[dict], date: str | None = None) -> int:
    """Persist the day's screened candidates. Idempotent per (date, code)."""
    if not candidates:
        return 0
    date = date or datetime.today().strftime("%Y-%m-%d")
    rows = []
    for rank, c in enumerate(candidates, start=1):
        code = str(c.get("code") or c.get("代號") or "").strip()
        if not code:
            continue
        rows.append((
            date, code,
            c.get("name") or c.get("名稱", ""),
            c.get("exchange") or c.get("交易所", ""),
            _num(c.get("close") or c.get("收盤")),
            int(c.get("tech_score") or c.get("技術評分") or 0),
            _num(c.get("rs20")),
            _num(c.get("rev_yoy")),
            rank,
        ))
    try:
        with _conn() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO screened "
                "(date, code, name, exchange, close, tech_score, rs20, rev_yoy, rank) "
                "VALUES (?,?,?,?,?,?,?,?,?)", rows)
        logger.debug("saved %d screened candidates for %s", len(rows), date)
        return len(rows)
    except Exception as e:
        logger.warning("save_screening failed: %s", e)
        return 0


def evaluate_performance(horizon: int = 10, min_age_days: int = 14) -> dict:
    """
    Grade past screenings: for screenings at least `min_age_days` old, measure the
    forward return `horizon` trading days after the screening date, then bucket by
    technical score. Returns a summary dict (safe to JSON-dump).
    """
    try:
        with _conn() as conn:
            cur = conn.execute(
                "SELECT date, code, exchange, close, tech_score FROM screened")
            records = cur.fetchall()
    except Exception as e:
        return {"error": f"讀取推薦歷史失敗: {e}"}

    if not records:
        return {"message": "尚無推薦歷史資料，先執行幾天選股後再評估。"}

    today = datetime.today()
    # Only evaluate screenings old enough for the horizon to have elapsed.
    eligible = []
    for date, code, exchange, close, score in records:
        try:
            age = (today - datetime.strptime(date, "%Y-%m-%d")).days
        except ValueError:
            continue
        if age >= min_age_days and close and close > 0:
            eligible.append((date, code, exchange, float(close), int(score or 0)))

    if not eligible:
        return {"message": f"目前沒有滿 {min_age_days} 天的推薦可評估，請過幾天再看。"}

    from data.fetcher_history import fetch_history
    uniq = {(c, e or "TWSE") for _, c, e, _, _ in eligible}
    history = fetch_history([{"code": c, "exchange": e} for c, e in uniq],
                            bypass_cache=True, include_taiex=False)

    buckets: dict[str, list[float]] = {"高分(≥55)": [], "中分(45-54)": [], "低分(<45)": []}
    detail = []
    for date, code, exchange, close, score in eligible:
        suffix = ".TW" if (exchange or "TWSE") == "TWSE" else ".TWO"
        df = history.get(f"{code}{suffix}")
        if df is None or df.empty:
            continue
        fwd = _forward_return(df, date, close, horizon)
        if fwd is None:
            continue
        bucket = "高分(≥55)" if score >= 55 else "中分(45-54)" if score >= 45 else "低分(<45)"
        buckets[bucket].append(fwd)
        detail.append({"date": date, "code": code, "score": score, f"fwd{horizon}d%": round(fwd, 2)})

    summary = {}
    for name, rets in buckets.items():
        if not rets:
            summary[name] = {"樣本數": 0}
            continue
        wins = sum(1 for r in rets if r > 0)
        summary[name] = {
            "樣本數": len(rets),
            "平均報酬%": round(sum(rets) / len(rets), 2),
            "勝率%": round(wins / len(rets) * 100, 1),
            "最佳%": round(max(rets), 2),
            "最差%": round(min(rets), 2),
        }

    return {
        "評估設定": {"持有交易日": horizon, "最小樣本天數": min_age_days},
        "依技術評分分組": summary,
        "樣本明細": sorted(detail, key=lambda d: d["date"], reverse=True)[:50],
    }


def _forward_return(df, screen_date: str, base_close: float, horizon: int):
    """Return % from the first bar on/after screen_date to `horizon` bars later."""
    import pandas as pd
    try:
        target = pd.to_datetime(screen_date)
    except Exception:
        return None
    after = df[df.index >= target]
    if len(after) < horizon + 1:
        return None
    future_close = float(after["Close"].iloc[horizon])
    if base_close <= 0:
        return None
    return (future_close - base_close) / base_close * 100


def _num(x):
    try:
        if x is None:
            return None
        return float(str(x).replace(",", "").replace("+", "").replace("%", ""))
    except (ValueError, TypeError):
        return None
