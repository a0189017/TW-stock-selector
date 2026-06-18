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
                "支援盤中模式（intraday=true）：個股收盤價會以 yfinance 即時報價覆蓋，"
                "反映當下盤中走勢（約 15 分鐘延遲），籌碼面仍為昨日收盤後資料。\n\n"
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
                    "intraday": {
                        "type": "boolean",
                        "description": (
                            "盤中模式（預設 false）。"
                            "設為 true 時，個股收盤價以 yfinance 即時報價（約 15 分鐘延遲）覆蓋，"
                            "適合盤中使用。籌碼面資料仍為昨日收盤後資料。"
                        ),
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
        types.Tool(
            name="screener_performance",
            description=(
                "評估選股系統過去的實際績效（誠實的命中率報告）。\n"
                "系統每次執行 fetch_stock_candidates 都會把量化候選存檔；此工具回讀"
                "已滿一定天數的歷史推薦，計算其在持有 N 個交易日後的未來報酬，"
                "並依技術評分分組（高/中/低分），給出平均報酬與勝率。\n\n"
                "可用來回答「這套選股到底準不準」、「高分股是否真的表現較好」。\n"
                "取得數據後，請客觀解讀：哪一組勝率/報酬較高、評分是否有鑑別度、"
                "若高分組未明顯優於低分組則提醒使用者評分權重可能需要調整。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "horizon": {
                        "type": "integer",
                        "description": "持有交易日數（預設 10）",
                        "default": 10,
                    },
                    "min_age_days": {
                        "type": "integer",
                        "description": "推薦至少需滿幾天才納入評估（預設 14）",
                        "default": 14,
                    },
                },
                "required": [],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name not in {
        "fetch_stock_candidates", "check_portfolio",
        "add_holding", "remove_holding", "list_holdings", "analyze_stock",
        "screener_performance",
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
            return [types.TextContent(type="text",
                text=_error_json("code、shares、cost 都是必填，且必須大於 0"))]
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
            return [types.TextContent(type="text",
                text=_error_json("請提供股票代號，例如 '2330'"))]
        result_text = await loop.run_in_executor(
            None, lambda: _run_stock_analysis(code, no_cache)
        )
        return [types.TextContent(type="text", text=result_text)]

    if name == "check_portfolio":
        result_text = await loop.run_in_executor(
            None, lambda: _run_health_check(no_cache)
        )
        return [types.TextContent(type="text", text=result_text)]

    if name == "screener_performance":
        horizon = int(arguments.get("horizon", 10))
        min_age = int(arguments.get("min_age_days", 14))
        result_text = await loop.run_in_executor(
            None, lambda: _run_screener_performance(horizon, min_age)
        )
        return [types.TextContent(type="text", text=result_text)]

    # fetch_stock_candidates
    limit = min(int(arguments.get("limit", 80)), 150)
    intraday = bool(arguments.get("intraday", False))
    result_text = await loop.run_in_executor(
        None, lambda: _run_pipeline(limit, no_cache, intraday)
    )
    return [types.TextContent(type="text", text=result_text)]


def _error_json(message: str, traceback_str: str | None = None) -> str:
    """Canonical error envelope shared by all tools (see docs/OUTPUT_SCHEMA.md)."""
    err = {"訊息": message}
    if traceback_str:
        err["traceback"] = traceback_str
    return json.dumps({"error": err}, ensure_ascii=False, indent=2)


def _run_health_check(no_cache: bool = False) -> str:
    """Run portfolio health check and return JSON."""
    from data.cache import set_bypass
    try:
        # Never write to cache during health check — avoids polluting the screener
        # cache with a partial fetch triggered by portfolio-only requests. Bypass
        # reads too when the caller forces a refresh. One global switch now covers
        # every fetcher (no more per-module monkeypatching that missed some).
        set_bypass(read=no_cache, write=True)
        try:
            from portfolio import run_health_check
            result = run_health_check()
            return json.dumps(result, ensure_ascii=False, indent=2)
        finally:
            set_bypass(read=False, write=False)
    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())


def _run_screener_performance(horizon: int = 10, min_age_days: int = 14) -> str:
    """Grade past screenings by forward return. Never writes cache."""
    from data.cache import set_bypass
    try:
        set_bypass(read=False, write=True)
        try:
            from data.recommendations import evaluate_performance
            result = evaluate_performance(horizon=horizon, min_age_days=min_age_days)
            return json.dumps(result, ensure_ascii=False, indent=2)
        finally:
            set_bypass(read=False, write=False)
    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())


def _run_pipeline(limit: int = 80, no_cache: bool = False, intraday: bool = False) -> str:
    """Run the full screening pipeline and return JSON result."""
    from data.cache import set_bypass
    try:
        set_bypass(read=no_cache, write=False)

        from data.fetcher_universe import fetch_universe, fetch_market_summary
        from data.fetcher_chip import fetch_chip_data, compute_market_foreign_total
        from analysis.screener import stage1_liquidity, stage2_chip, stage3_technical
        from data.fetcher_history import fetch_history
        from config import get_recent_weekdays
        import pandas as pd

        # Phase 1: Universe
        universe_df = fetch_universe()
        if universe_df.empty:
            return _error_json("無法取得股票清單，請確認網路連線")

        market_summary = fetch_market_summary(universe_df)

        # Phase 2: Chip data
        dates = get_recent_weekdays(7)[:5]
        chip_df = fetch_chip_data(dates)
        market_summary["外資合計淨買_張"] = compute_market_foreign_total(chip_df)

        # Hot sectors and stocks (full universe, before screening)
        from analysis.market_hot import compute_hot_sectors, compute_hot_stocks
        market_summary["強勢族群"] = compute_hot_sectors(universe_df, chip_df, top_n=5)
        market_summary["強勢個股"] = compute_hot_stocks(universe_df, chip_df, top_n=10)

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
                market_summary["加權指數"] = round(last, 2)
                market_summary["加權指數漲跌"] = round(chg, 2)
                market_summary["加權指數漲跌_%"] = round(pct, 2)

                # Futures overlay: basis + institutional positions
                from data.fetcher_futures import fetch_futures_summary
                futures = fetch_futures_summary(taiex_close=last)
                if futures:
                    market_summary["期貨概況"] = futures

        # Stage 3: Technical scoring (with relative strength + monthly revenue)
        from data.fetcher_fundamental import fetch_month_revenue
        fundamental = fetch_month_revenue()
        final = stage3_technical(s2, history, fundamental=fundamental)

        if final.empty:
            final = s2.head(limit)

        # Persist the quantitative screening so screener_performance can grade it
        try:
            from data.recommendations import save_screening
            save_screening(final.to_dict("records"))
        except Exception:
            pass

        # Build output
        from analysis.common import serialize_tech, serialize_chip, serialize_fundamental
        stocks_data = []
        for _, row in final.head(limit).iterrows():
            d = row.to_dict()
            stocks_data.append({
                "代號": d.get("code", ""),
                "名稱": d.get("name", ""),
                "產業": d.get("industry", ""),
                "交易所": d.get("exchange", ""),
                "收盤": d.get("close", 0),
                "漲跌_%": d.get("change_pct", 0),
                "技術評分": d.get("tech_score", 0),
                "技術信號": d.get("tech_signals", []),
                "技術指標": serialize_tech(d),
                "籌碼": serialize_chip(d),
                "基本面": serialize_fundamental(d),
            })

        # ---- Intraday: patch close price + change% with yfinance realtime quotes ----
        if intraday and stocks_data:
            from data.fetcher_realtime import fetch_realtime_quotes
            rt_candidates = [{"code": s["代號"], "exchange": s["交易所"]} for s in stocks_data]
            rt_quotes = fetch_realtime_quotes(rt_candidates)
            rt_count = 0
            for s in stocks_data:
                qt = rt_quotes.get(s["代號"])
                if qt:
                    s["收盤"] = qt["close"]
                    s["漲跌_%"] = qt["change_pct"]
                    rt_count += 1

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
        if intraday:
            data_note = f"盤中即時模式（個股報價來自 yfinance，約 15 分鐘延遲；籌碼面為 {data_date} 收盤後資料）"
        elif is_today:
            data_note = "今日收盤資料"
        else:
            data_note = f"最近交易日資料（使用 {data_date} 收盤價，盤中或資料尚未更新）"

        from analysis.common import SCHEMA_VERSION
        output = {
            "格式版本": SCHEMA_VERSION,
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
        return _error_json(str(e), traceback.format_exc())
    finally:
        set_bypass(read=False, write=False)


def _run_stock_analysis(code: str, no_cache: bool = False) -> str:
    """Fetch full technical + chip data for a single stock and return JSON."""
    from data.cache import set_bypass
    try:
        import pandas as pd
        from data.fetcher_universe import fetch_universe
        from data.fetcher_chip import fetch_chip_data
        from data.fetcher_history import fetch_history
        from analysis.indicators import add_all_indicators, score_stock, compute_relative_strength
        from analysis.common import extract_indicators, serialize_tech, serialize_chip, serialize_fundamental
        from config import get_recent_weekdays

        if not (code.isdigit() and len(code) == 4):
            return _error_json(f"無效的股票代號：{code}，請輸入 4 位數字代號（例如 '2330'）")

        set_bypass(read=no_cache, write=False)

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
            history = fetch_history(candidates, bypass_cache=no_cache, include_taiex=True)
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
            return _error_json(f"找不到股票 {code}，請確認代號是否正確")

        suffix = ".TW" if exchange == "TWSE" else ".TWO"
        ticker = f"{code}{suffix}"
        df_hist = history.get(ticker)

        if df_hist is None or df_hist.empty:
            return _error_json(f"無法取得 {code} 的歷史 K 線，資料可能尚未更新")

        # ---- Step 3: Technical indicators ----
        df_ind = add_all_indicators(df_hist)
        rs = compute_relative_strength(df_hist, history.get("^TWII"))

        # ---- Step 4: Fundamentals (monthly revenue) ----
        from data.fetcher_fundamental import fetch_month_revenue
        fund = fetch_month_revenue().get(code, {})

        tech_score, tech_signals = score_stock(df_ind, rs=rs, fundamental=fund)

        ind = extract_indicators(df_ind)
        ind["rs_label"] = rs.get("rs_label")
        ind["rs20"] = rs.get("rs20")
        close_price = ind.get("yf_close", 0)

        # ---- Step 5: Chip data ----
        dates = get_recent_weekdays(7)[:5]
        chip_df = fetch_chip_data(dates)
        chip_row: dict = {}
        if not chip_df.empty and "code" in chip_df.columns:
            matched = chip_df[chip_df["code"] == code]
            if not matched.empty:
                chip_row = matched.iloc[0].to_dict()

        # ---- Step 6: Recent candles ----
        recent_candles = []
        for date, row in df_hist.tail(10).iterrows():
            vol_shares = float(row.get("Volume", 0))
            recent_candles.append({
                "日期": str(date)[:10],
                "開": round(float(row.get("Open", 0)), 2),
                "高": round(float(row.get("High", 0)), 2),
                "低": round(float(row.get("Low", 0)), 2),
                "收": round(float(row.get("Close", 0)), 2),
                "量_張": int(vol_shares / 1000),
            })

        # ---- Build output ----
        from analysis.common import SCHEMA_VERSION
        current_close = info.get("close", close_price)
        output = {
            "格式版本": SCHEMA_VERSION,
            "代號": code,
            "名稱": name,
            "交易所": exchange,
            "產業": info.get("industry", "其他"),
            "收盤": current_close,
            "漲跌_%": info.get("change_pct", 0),
            "PE": info.get("pe_ratio", 0),
            "PB": info.get("pb_ratio", 0),
            "殖利率_%": info.get("div_yield", 0),
            "技術評分": tech_score,
            "技術信號": tech_signals,
            "技術指標": serialize_tech(ind, full=True),
            "籌碼": serialize_chip(chip_row),
            "基本面": serialize_fundamental(fund),
            "近10日K線": recent_candles,
        }

        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())
    finally:
        set_bypass(read=False, write=False)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
