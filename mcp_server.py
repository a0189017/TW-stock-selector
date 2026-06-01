"""
MCP Server for 台灣股市選股系統

讓 Claude Desktop 可以直接呼叫選股工具，
由 Claude Desktop 本身做分析，不需要額外的 API 費用。

Claude Desktop 設定方式請見 README 或 claude_desktop_config_snippet.json
"""
import asyncio
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

server = Server("stock-selector")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="fetch_stock_candidates",
            description=(
                "抓取台灣股市今日選股數據。"
                "自動執行三階段篩選（流動性 → 籌碼面 → 技術指標），"
                "回傳最多 80 支候選股票的完整技術面與籌碼面數據，以及今日大盤概況。\n\n"
                "呼叫此工具取得數據後，請以資深台股投資人（股癌）風格分析，"
                "選出今日最值得關注的 10 檔股票，每支給出：推薦理由、技術面、籌碼面、"
                "進場策略、停損點、短期目標價，最後加上大盤觀察。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最多回傳幾支候選股票（預設 80，上限 150）",
                        "default": 80,
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料（預設 false，使用當日 cache）",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="check_portfolio",
            description=(
                "對你的持股進行全面健檢。\n"
                "回傳每支持股的：現價/損益試算、技術指標（KD/MACD/均線/乖離率）、"
                "籌碼面（外資投信動向/融資變化）、預判建議（續抱/減碼/停損觀察）、停損參考價。\n\n"
                "取得數據後，請以股癌風格逐一分析每支持股，給出明確操作建議。"
                "如果持股清單是空的，請提示用戶先用 add_holding 新增持股。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="add_holding",
            description=(
                "新增或更新一筆持股。"
                "code=股票代號（4碼），shares=持有張數，cost=成本均價（每股，元）。\n"
                "例如：持有台積電 2 張，均價 850 元 → code='2330', shares=2, cost=850。\n"
                "如果該代號已存在，會更新張數與成本價。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "股票代號，4位數字，例如 '2330'",
                    },
                    "shares": {
                        "type": "number",
                        "description": "持有張數（1張=1000股），可以是小數如 0.5",
                    },
                    "cost": {
                        "type": "number",
                        "description": "成本均價，每股新台幣（不是每張）",
                    },
                },
                "required": ["code", "shares", "cost"],
            },
        ),
        types.Tool(
            name="remove_holding",
            description="從持股清單中移除一支股票（已賣出）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要移除的股票代號",
                    },
                },
                "required": ["code"],
            },
        ),
        types.Tool(
            name="list_holdings",
            description="列出目前持股清單（代號、名稱、張數、成本價）。不抓取即時行情。",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        types.Tool(
            name="analyze_stock",
            description=(
                "針對單一個股做深度分析，不限定必須在推薦名單內。\n"
                "輸入台股 4 碼代號，回傳：技術面（KD/MACD/均線結構/乖離率/量比）、"
                "籌碼面（外資投信動向/融資變化）、近 10 日 K 線數據，以及技術評分與信號。\n\n"
                "取得數據後，請以股癌風格分析這支股票的當前位置與籌碼動態，"
                "給出：目前技術面判讀、籌碼面觀察、近期支撐壓力、"
                "操作建議（進場/觀望/避開）、合理停損點、短期目標價。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "台股股票代號（4碼數字），例如 '2330'、'6669'",
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料（預設 false）",
                        "default": False,
                    },
                },
                "required": ["code"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name not in {
        "fetch_stock_candidates", "check_portfolio",
        "add_holding", "remove_holding", "list_holdings", "analyze_stock",
    }:
        raise ValueError(f"Unknown tool: {name}")

    loop = asyncio.get_event_loop()

    # ---- Simple portfolio CRUD (no heavy data fetching) ----
    if name == "list_holdings":
        from portfolio import list_holdings
        result = list_holdings()
        text = json.dumps(
            {"持股清單": result, "持股數": len(result)},
            ensure_ascii=False, indent=2,
        )
        return [types.TextContent(type="text", text=text)]

    if name == "add_holding":
        from portfolio import add_holding
        code = str(arguments.get("code", "")).strip()
        shares = float(arguments.get("shares", 0))
        cost = float(arguments.get("cost", 0))
        if not code or shares <= 0 or cost <= 0:
            return [types.TextContent(type="text", text=json.dumps(
                {"error": "code、shares、cost 都是必填，且必須大於 0"},
                ensure_ascii=False))]
        result = add_holding(code, shares, cost)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    if name == "remove_holding":
        from portfolio import remove_holding
        code = str(arguments.get("code", "")).strip()
        result = remove_holding(code)
        return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

    # ---- Heavy data fetching tasks run in executor ----
    no_cache = bool(arguments.get("no_cache", False))

    if name == "analyze_stock":
        code = str(arguments.get("code", "")).strip()
        if not code:
            return [types.TextContent(type="text", text=json.dumps(
                {"error": "請提供股票代號，例如 '2330'"}, ensure_ascii=False))]
        result_text = await loop.run_in_executor(
            None, lambda: _run_stock_analysis(code, no_cache)
        )
        return [types.TextContent(type="text", text=result_text)]

    if name == "check_portfolio":
        result_text = await loop.run_in_executor(
            None, lambda: _run_health_check(no_cache)
        )
        return [types.TextContent(type="text", text=result_text)]

    # fetch_stock_candidates
    limit = min(int(arguments.get("limit", 80)), 150)
    result_text = await loop.run_in_executor(
        None, lambda: _run_pipeline(limit, no_cache)
    )
    return [types.TextContent(type="text", text=result_text)]


def _run_health_check(no_cache: bool = False) -> str:
    """Run portfolio health check and return JSON."""
    try:
        if no_cache:
            import data.cache as dc
            dc.cache_get = lambda key: None

        from portfolio import run_health_check
        result = run_health_check()
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        import traceback
        return json.dumps(
            {"error": str(e), "traceback": traceback.format_exc()},
            ensure_ascii=False,
        )


def _run_pipeline(limit: int = 80, no_cache: bool = False) -> str:
    """Run the full screening pipeline and return JSON result."""
    try:
        if no_cache:
            import data.cache as dc
            dc.cache_get = lambda key: None

        from data.fetcher_universe import fetch_universe, fetch_market_summary
        from data.fetcher_chip import fetch_chip_data, compute_market_foreign_total
        from analysis.screener import stage1_liquidity, stage2_chip, stage3_technical
        from data.fetcher_history import fetch_history
        from config import get_recent_weekdays
        import pandas as pd

        # Phase 1: Universe
        universe_df = fetch_universe()
        if universe_df.empty:
            return json.dumps({"error": "無法取得股票清單，請確認網路連線"}, ensure_ascii=False)

        market_summary = fetch_market_summary(universe_df)

        # Phase 2: Chip data
        dates = get_recent_weekdays(7)[:5]
        chip_df = fetch_chip_data(dates)
        market_summary["foreign_total"] = compute_market_foreign_total(chip_df)

        # Hot sectors and stocks (full universe, before screening)
        from analysis.market_hot import compute_hot_sectors, compute_hot_stocks
        market_summary["hot_sectors"] = compute_hot_sectors(universe_df, chip_df, top_n=5)
        market_summary["hot_stocks"] = compute_hot_stocks(universe_df, chip_df, top_n=10)

        # Stage 1 + 2
        s1 = stage1_liquidity(universe_df)
        s2 = stage2_chip(s1, chip_df)

        if s2.empty:
            s2 = s1  # fallback

        # Phase 3: Historical OHLCV
        candidates_info = s2.head(limit)[["code", "exchange"]].to_dict("records")
        history = fetch_history(candidates_info)

        # Update TAIEX
        taiex_df = history.get("^TWII")
        if taiex_df is not None and not taiex_df.empty:
            closes = taiex_df["Close"].dropna()
            if len(closes) >= 2:
                last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
                chg = last - prev
                pct = chg / prev * 100
                sign = "+" if chg >= 0 else ""
                market_summary["taiex"] = f"{last:,.2f}"
                market_summary["taiex_change"] = f"({sign}{chg:,.2f} / {sign}{pct:.2f}%)"

        # Stage 3: Technical scoring
        final = stage3_technical(s2, history)

        if final.empty:
            final = s2.head(limit)

        # Build output
        stocks_data = []
        for _, row in final.head(limit).iterrows():
            stocks_data.append({
                "代號": row.get("code", ""),
                "名稱": row.get("name", ""),
                "產業": row.get("industry", ""),
                "交易所": row.get("exchange", ""),
                "收盤": row.get("close", 0),
                "漲跌%": row.get("change_pct", 0),
                "技術評分": row.get("tech_score", 0),
                "技術信號": row.get("tech_signals", []),
                "技術指標": {
                    "KD(K/D)": f"{row.get('kd_k', 50):.1f}/{row.get('kd_d', 50):.1f}",
                    "MACD柱": f"{row.get('macd_hist', 0):.4f}",
                    "均線乖離(MA5/MA20/MA60)": (
                        f"{row.get('bias5', 0):+.1f}%/"
                        f"{row.get('bias20', 0):+.1f}%/"
                        f"{row.get('bias60', 0):+.1f}%"
                    ),
                    "量比": f"{row.get('vol_ratio', 1):.1f}x",
                    "均線結構": row.get("ma_structure", "整理"),
                    "MA20": row.get("ma20", 0),
                    "MA60": row.get("ma60", 0),
                },
                "籌碼": {
                    "外資今日淨買(張)": f"{row.get('foreign_net_today', 0):+,.0f}",
                    "外資5日淨買(張)": f"{row.get('foreign_net_5d', 0):+,.0f}",
                    "投信今日淨買(張)": f"{row.get('trust_net_today', 0):+,.0f}",
                    "三大法人今日(張)": f"{row.get('big3_net_today', 0):+,.0f}",
                    "融資餘額變化": f"{row.get('margin_change_pct', 0):+.1f}%",
                    "融資使用率": f"{row.get('margin_util_rate', 0):.1f}%",
                },
            })

        from datetime import datetime
        from data.cache import cache_get, make_key as _make_key

        today_str = datetime.today().strftime("%Y%m%d")
        actual_data_date = cache_get(_make_key("twse_universe_date", today_str))
        if actual_data_date is None:
            # Date key absent (old cache or first run) — assume today's data if we got enough stocks
            actual_data_date = today_str
        # Format for display: YYYYMMDD → YYYY-MM-DD
        data_date = f"{actual_data_date[:4]}-{actual_data_date[4:6]}-{actual_data_date[6:]}" if len(actual_data_date) == 8 else datetime.today().strftime("%Y-%m-%d")
        is_today = (actual_data_date == today_str)
        data_note = "今日收盤資料" if is_today else f"最近交易日資料（使用 {data_date} 收盤價，盤中或資料尚未更新）"

        output = {
            "資料日期": data_date,
            "資料說明": data_note,
            "篩選結果": {
                "全市場股票數": len(universe_df),
                "流動性篩選後": len(s1),
                "籌碼篩選後": len(s2),
                "技術評分通過": len(final),
                "送入分析": len(stocks_data),
            },
            "大盤概況": market_summary,
            "候選股票": stocks_data,
        }

        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return json.dumps({
            "error": str(e),
            "traceback": traceback.format_exc()
        }, ensure_ascii=False)


def _run_stock_analysis(code: str, no_cache: bool = False) -> str:
    """Fetch full technical + chip data for a single stock and return JSON."""
    try:
        import pandas as pd
        from data.fetcher_universe import fetch_universe
        from data.fetcher_chip import fetch_chip_data
        from data.fetcher_history import fetch_history
        from analysis.indicators import add_all_indicators, score_stock
        from config import get_recent_weekdays

        if not (code.isdigit() and len(code) == 4):
            return json.dumps(
                {"error": f"無效的股票代號：{code}，請輸入 4 位數字代號（例如 '2330'）"},
                ensure_ascii=False,
            )

        if no_cache:
            import data.cache as dc
            dc.cache_get = lambda key: None

        # ---- Step 1: Look up basic info from today's universe ----
        universe_df = fetch_universe()
        stock_rows = universe_df[universe_df["code"] == code]

        if not stock_rows.empty:
            info = stock_rows.iloc[0].to_dict()
            exchange = info["exchange"]
            name = info.get("name", code)
        else:
            info = {}
            exchange = None
            name = code

        # ---- Step 2: Fetch history (auto-detect exchange if unknown) ----
        history: dict = {}
        if exchange:
            candidates = [{"code": code, "exchange": exchange}]
            history = fetch_history(candidates, bypass_cache=no_cache, include_taiex=False)
        else:
            # Try TWSE first, then TPEX
            for exch in ("TWSE", "TPEX"):
                candidates = [{"code": code, "exchange": exch}]
                h = fetch_history(candidates, bypass_cache=True, include_taiex=False)
                suffix = ".TW" if exch == "TWSE" else ".TWO"
                if h.get(f"{code}{suffix}") is not None:
                    exchange = exch
                    history = h
                    break

        if not exchange:
            return json.dumps(
                {"error": f"找不到股票 {code}，請確認代號是否正確"},
                ensure_ascii=False,
            )

        suffix = ".TW" if exchange == "TWSE" else ".TWO"
        ticker = f"{code}{suffix}"
        df_hist = history.get(ticker)

        if df_hist is None or df_hist.empty:
            return json.dumps(
                {"error": f"無法取得 {code} 的歷史 K 線，資料可能尚未更新"},
                ensure_ascii=False,
            )

        # ---- Step 3: Technical indicators ----
        df_ind = add_all_indicators(df_hist)
        tech_score, tech_signals = score_stock(df_ind)

        last = df_ind.iloc[-1]

        def v(col, default=0.0):
            val = last.get(col, default)
            return float(val) if pd.notna(val) else default

        close_price = v("Close")
        ma5, ma10, ma20, ma60 = v("MA5"), v("MA10"), v("MA20"), v("MA60")
        if ma5 > ma10 > ma20 > ma60 > 0:
            ma_structure = "多頭排列"
        elif ma5 > ma20 > 0:
            ma_structure = "短多"
        elif ma5 < ma20 and ma20 > 0:
            ma_structure = "空頭偏弱"
        else:
            ma_structure = "整理"

        # ---- Step 4: Chip data ----
        dates = get_recent_weekdays(7)[:5]
        chip_df = fetch_chip_data(dates)
        chip_row: dict = {}
        if not chip_df.empty and "code" in chip_df.columns:
            matched = chip_df[chip_df["code"] == code]
            if not matched.empty:
                chip_row = matched.iloc[0].to_dict()

        # ---- Step 5: Recent candles ----
        recent_candles = []
        for date, row in df_hist.tail(10).iterrows():
            vol_shares = float(row.get("Volume", 0))
            recent_candles.append({
                "日期": str(date)[:10],
                "開": round(float(row.get("Open", 0)), 2),
                "高": round(float(row.get("High", 0)), 2),
                "低": round(float(row.get("Low", 0)), 2),
                "收": round(float(row.get("Close", 0)), 2),
                "量(張)": int(vol_shares / 1000),
            })

        # ---- Build output ----
        current_close = info.get("close", close_price)
        output = {
            "代號": code,
            "名稱": name,
            "交易所": exchange,
            "產業": info.get("industry", "其他"),
            "收盤價": current_close,
            "漲跌%": info.get("change_pct", 0),
            "PE": info.get("pe_ratio", 0),
            "PB": info.get("pb_ratio", 0),
            "殖利率%": info.get("div_yield", 0),
            "技術評分": tech_score,
            "技術信號": tech_signals,
            "技術指標": {
                "KD(K/D)": f"{v('K'):.1f}/{v('D'):.1f}",
                "MACD柱": f"{v('MACD_hist'):.4f}",
                "均線乖離(MA5/MA20/MA60)": (
                    f"{v('Bias5'):+.1f}%/"
                    f"{v('Bias20'):+.1f}%/"
                    f"{v('Bias60'):+.1f}%"
                ),
                "量比": f"{v('VolRatio'):.1f}x",
                "均線結構": ma_structure,
                "MA5": round(ma5, 2),
                "MA10": round(ma10, 2),
                "MA20": round(ma20, 2),
                "MA60": round(ma60, 2),
                "MA120": round(v("MA120"), 2),
                "MA240": round(v("MA240"), 2),
            },
            "籌碼": {
                "外資今日淨買(張)": f"{chip_row.get('foreign_net_today', 0):+,.0f}",
                "外資5日淨買(張)": f"{chip_row.get('foreign_net_5d', 0):+,.0f}",
                "投信今日淨買(張)": f"{chip_row.get('trust_net_today', 0):+,.0f}",
                "三大法人今日(張)": f"{chip_row.get('big3_net_today', 0):+,.0f}",
                "融資餘額變化": f"{chip_row.get('margin_change_pct', 0):+.1f}%",
                "融資使用率": f"{chip_row.get('margin_util_rate', 0):.1f}%",
            },
            "近10日K線": recent_candles,
        }

        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return json.dumps(
            {"error": str(e), "traceback": traceback.format_exc()},
            ensure_ascii=False,
        )


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
