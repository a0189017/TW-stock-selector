"""Persistent portfolio management — add, remove, list holdings."""
import json
from pathlib import Path
from datetime import datetime

PORTFOLIO_FILE = Path(__file__).parent / "portfolio.json"


def load_portfolio() -> list[dict]:
    if PORTFOLIO_FILE.exists():
        try:
            return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def save_portfolio(holdings: list[dict]) -> None:
    PORTFOLIO_FILE.write_text(
        json.dumps(holdings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_holding(code: str, shares: float, cost: float, name: str = "") -> dict:
    """Add or update a holding. shares = 張數, cost = 成本均價 (TWD)."""
    code = code.strip()
    holdings = load_portfolio()
    today = datetime.today().strftime("%Y-%m-%d")

    for h in holdings:
        if h["code"] == code:
            h["shares"] = float(shares)
            h["cost"] = float(cost)
            h["updated"] = today
            if name:
                h["name"] = name
            save_portfolio(holdings)
            return {"action": "updated", "holding": h}

    new_h = {
        "code": code,
        "name": name,
        "shares": float(shares),
        "cost": float(cost),
        "added": today,
    }
    holdings.append(new_h)
    save_portfolio(holdings)
    return {"action": "added", "holding": new_h}


def remove_holding(code: str) -> dict:
    """Remove a holding by stock code."""
    code = code.strip()
    holdings = load_portfolio()
    before = len(holdings)
    holdings = [h for h in holdings if h["code"] != code]
    if len(holdings) < before:
        save_portfolio(holdings)
        return {"action": "removed", "code": code}
    return {"action": "not_found", "code": code}


def list_holdings() -> list[dict]:
    return load_portfolio()


def _pre_recommendation(tech_score: int, macd_hist: float, bias20: float,
                         foreign_net_5d: float, margin_change_pct: float,
                         return_pct: float) -> tuple[str, list[str]]:
    """
    Rule-based pre-assessment. Returns (label, risk_signals).
    Label: 續抱 / 減碼 / 停損觀察
    """
    signals = []
    score = 0

    # Technical
    if macd_hist > 0:
        score += 2
    elif macd_hist < 0:
        score -= 2
        signals.append("MACD柱翻負")

    if bias20 > 15:
        score -= 1
        signals.append(f"20MA乖離過大({bias20:+.1f}%)，注意追高風險")
    elif bias20 < -10:
        score -= 2
        signals.append(f"跌破20MA乖離深({bias20:+.1f}%)，注意支撐")

    if tech_score >= 45:
        score += 2
    elif tech_score <= 25:
        score -= 2
        signals.append("技術指標轉弱")

    # Chip
    if foreign_net_5d > 1000:
        score += 2
        signals.append(f"外資5日買超{foreign_net_5d:,.0f}張")
    elif foreign_net_5d < -1000:
        score -= 2
        signals.append(f"外資5日賣超{abs(foreign_net_5d):,.0f}張，主力出場警示")

    if margin_change_pct > 5:
        score -= 1
        signals.append(f"融資餘額增加{margin_change_pct:+.1f}%，散戶追多")

    # P&L context
    if return_pct > 20 and score < 2:
        signals.append(f"已獲利{return_pct:.1f}%，技術轉弱可考慮分批獲利了結")
    if return_pct < -8:
        score -= 1
        signals.append(f"已虧損{abs(return_pct):.1f}%，需注意停損紀律")

    if score >= 3:
        label = "續抱"
    elif score >= 0:
        label = "減碼觀察"
    else:
        label = "停損觀察"

    return label, signals


def run_health_check() -> dict:
    """
    Run full portfolio health check.
    Returns structured data for all holdings — Claude Desktop does the narrative.
    """
    holdings = load_portfolio()
    if not holdings:
        return {"error": "portfolio_empty",
                "message": "持股清單是空的。請先用 add_holding 新增你的持股。"}

    codes = [h["code"] for h in holdings]

    # ---- Fetch current prices ----
    from data.fetcher_universe import fetch_twse_universe, fetch_tpex_universe
    twse_df = fetch_twse_universe()
    tpex_df = fetch_tpex_universe()
    import pandas as pd
    price_df = pd.concat([twse_df, tpex_df], ignore_index=True) if not (twse_df.empty and tpex_df.empty) else pd.DataFrame()
    price_map = {}
    exchange_map = {}
    if not price_df.empty:
        for _, row in price_df[price_df["code"].isin(codes)].iterrows():
            price_map[row["code"]] = {
                "close": row["close"],
                "change_pct": row["change_pct"],
                "name": row["name"],
            }
            exchange_map[row["code"]] = row["exchange"]

    # ---- Fetch chip data ----
    from data.fetcher_chip import fetch_chip_data
    from config import get_recent_weekdays
    chip_df = fetch_chip_data(get_recent_weekdays(7)[:5])
    chip_map = {}
    if not chip_df.empty:
        chip_idx = chip_df.set_index("code")
        for code in codes:
            if code in chip_idx.index:
                row = chip_idx.loc[code]
                chip_map[code] = {
                    "foreign_net_today": float(row.get("foreign_net_today", 0)),
                    "foreign_net_5d": float(row.get("foreign_net_5d", 0)),
                    "trust_net_today": float(row.get("trust_net_today", 0)),
                    "trust_net_5d": float(row.get("trust_net_5d", 0)),
                    "big3_net_today": float(row.get("big3_net_today", 0)),
                    "margin_change_pct": float(row.get("margin_change_pct", 0)),
                    "margin_util_rate": float(row.get("margin_util_rate", 0)),
                }

    # ---- Fetch historical data + indicators ----
    candidates = [
        {"code": c, "exchange": exchange_map.get(c, "TWSE")}
        for c in codes
    ]
    from data.fetcher_history import fetch_history
    from analysis.indicators import add_all_indicators, score_stock
    # Always bypass cache for health checks: holdings may not be in screener cache,
    # and we want the most current price data for risk assessment.
    history = fetch_history(candidates, bypass_cache=True, include_taiex=False)

    tech_map = {}
    for code in codes:
        exchange = exchange_map.get(code, "TWSE")
        suffix = ".TW" if exchange == "TWSE" else ".TWO"
        ticker = f"{code}{suffix}"
        df_h = history.get(ticker)
        if df_h is None or len(df_h) < 20:
            continue
        df_ind = add_all_indicators(df_h)
        t_score, t_signals = score_stock(df_ind)
        last = df_ind.iloc[-1]

        def v(col, default=0.0):
            import numpy as np
            val = last.get(col, default)
            return float(val) if pd.notna(val) else default

        tech_map[code] = {
            "tech_score": t_score,
            "tech_signals": t_signals,
            "kd_k": round(v("K"), 1),
            "kd_d": round(v("D"), 1),
            "macd_hist": round(v("MACD_hist"), 4),
            "bias20": round(v("Bias20"), 2),
            "bias60": round(v("Bias60"), 2),
            "vol_ratio": round(v("VolRatio"), 2),
            "ma5": round(v("MA5"), 2),
            "ma20": round(v("MA20"), 2),
            "ma60": round(v("MA60"), 2),
            "ma240": round(v("MA240"), 2),
            "ma_structure": (
                "多頭排列" if v("MA5") > v("MA10") > v("MA20") > v("MA60") > 0
                else "短多" if v("MA5") > v("MA20") > 0
                else "空頭排列" if v("MA5") < v("MA20") < v("MA60")
                else "整理"
            ),
        }

    # ---- Assemble results ----
    from datetime import datetime
    total_cost_twd = 0.0
    total_value_twd = 0.0
    results = []

    for h in holdings:
        code = h["code"]
        shares = h.get("shares", 0)          # 張
        cost_price = h.get("cost", 0)        # 每股成本
        price_info = price_map.get(code, {})
        current_price = price_info.get("close", 0)
        name = price_info.get("name") or h.get("name", code)
        today_chg = price_info.get("change_pct", 0)

        # P&L  (1張 = 1000股)
        cost_twd = shares * 1000 * cost_price
        value_twd = shares * 1000 * current_price if current_price else 0
        pnl_twd = value_twd - cost_twd
        return_pct = (pnl_twd / cost_twd * 100) if cost_twd > 0 else 0.0
        total_cost_twd += cost_twd
        total_value_twd += value_twd

        chip = chip_map.get(code, {})
        tech = tech_map.get(code, {})

        pre_rec, risk_signals = _pre_recommendation(
            tech_score=tech.get("tech_score", 0),
            macd_hist=tech.get("macd_hist", 0),
            bias20=tech.get("bias20", 0),
            foreign_net_5d=chip.get("foreign_net_5d", 0),
            margin_change_pct=chip.get("margin_change_pct", 0),
            return_pct=return_pct,
        )

        # Key support / reference stop-loss
        ma20 = tech.get("ma20", 0)
        ma60 = tech.get("ma60", 0)
        stop_ref = ma60 if ma60 > 0 else (cost_price * 0.92)

        results.append({
            "代號": code,
            "名稱": name,
            "交易所": exchange_map.get(code, "TWSE"),
            "持有張數": shares,
            "成本均價": cost_price,
            "現價": current_price,
            "今日漲跌%": today_chg,
            "損益": {
                "未實現損益(元)": round(pnl_twd),
                "報酬率%": round(return_pct, 2),
                "持有市值(元)": round(value_twd),
                "持有成本(元)": round(cost_twd),
            },
            "技術面": {
                "技術評分": tech.get("tech_score", "—"),
                "技術信號": tech.get("tech_signals", []),
                "KD(K/D)": f"{tech.get('kd_k', 0):.1f}/{tech.get('kd_d', 0):.1f}",
                "MACD柱": tech.get("macd_hist", 0),
                "均線結構": tech.get("ma_structure", "—"),
                "20MA乖離": f"{tech.get('bias20', 0):+.1f}%",
                "60MA乖離": f"{tech.get('bias60', 0):+.1f}%",
                "量比": f"{tech.get('vol_ratio', 0):.1f}x",
                "MA20": tech.get("ma20", 0),
                "MA60": ma60,
                "MA240": tech.get("ma240", 0),
            },
            "籌碼面": {
                "外資今日淨買(張)": f"{chip.get('foreign_net_today', 0):+,.0f}",
                "外資5日淨買(張)": f"{chip.get('foreign_net_5d', 0):+,.0f}",
                "投信今日淨買(張)": f"{chip.get('trust_net_today', 0):+,.0f}",
                "三大法人今日(張)": f"{chip.get('big3_net_today', 0):+,.0f}",
                "融資餘額變化": f"{chip.get('margin_change_pct', 0):+.1f}%",
                "融資使用率": f"{chip.get('margin_util_rate', 0):.1f}%",
            },
            "預判建議": pre_rec,
            "風險提示": risk_signals,
            "停損參考價": round(stop_ref, 1),
        })

    total_return = ((total_value_twd - total_cost_twd) / total_cost_twd * 100
                    if total_cost_twd > 0 else 0.0)

    return {
        "資料日期": datetime.today().strftime("%Y-%m-%d"),
        "持股概況": {
            "持股檔數": len(results),
            "總持有成本(元)": round(total_cost_twd),
            "總市值(元)": round(total_value_twd),
            "總未實現損益(元)": round(total_value_twd - total_cost_twd),
            "整體報酬率%": round(total_return, 2),
        },
        "持股明細": results,
    }
