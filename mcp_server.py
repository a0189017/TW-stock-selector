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
                "排名採多因子綜合評分（技術面 + 籌碼強度 + 基本面 + 產業族群強度 + RS60），"
                "不再只看技術面單一分數；可用 strategy 切換權重組合。\n\n"
                "支援盤中模式（intraday=true）：個股收盤價與當日線型（跳空/箱型/開高走低/"
                "開低走高/收盤位置）以 TWSE MIS 即時報價計算，技術指標（KD/乖離/量比/RS）"
                "仍以昨日收盤 K 線計算，籌碼面仍為昨日收盤後資料。\n\n"
                "呼叫此工具取得數據後，請以資深台股投資人風格分析，"
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
                            "設為 true 時，個股收盤價與當日線型以 TWSE MIS 即時報價計算，"
                            "適合盤中使用。技術指標與籌碼面資料仍為昨日收盤後資料。"
                        ),
                        "default": False,
                    },
                    "exclude_bad_shape": {
                        "type": "boolean",
                        "description": (
                            "當日線型過濾（預設 false，須搭配 intraday=true 才有作用）。"
                            "設為 true 時，排除「開高走低」或「收在當日低檔」這種當日轉弱的候選股。"
                        ),
                        "default": False,
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["balanced", "trend", "reversal"],
                        "description": (
                            "選股策略權重組合（預設 balanced）。"
                            "balanced：技術面為主，籌碼/基本面/族群為輔，接近原本綜合表現。"
                            "trend：加重均線趨勢、籌碼連買、族群強度、RS60，適合波段趨勢單。"
                            "reversal：降低趨勢/族群權重，適合搭配技術面本身的超賣反彈信號操作。"
                        ),
                        "default": "balanced",
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
                "取得數據後，請以資深台股投資人風格逐一分析每支持股，給出明確操作建議。"
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
                "取得數據後，請以資深台股投資人風格分析這支股票的當前位置與籌碼動態，"
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
        types.Tool(
            name="fetch_backtest_picks",
            description=(
                "回測名單：純粹依『回測驗證過的技術評分（score_stock）』排序，"
                "選出分數最高的 N 檔（預設 10），**完全跳過籌碼面篩選與每交易所配額**。\n\n"
                "用途：主選股（fetch_stock_candidates）會因籌碼篩選 / 配額 / top-N 裁切，"
                "把某些技術面很強的股票在進入推薦前就排除；此工具讓這些高分股不被埋掉，"
                "提供一份獨立的量化技術名單。籌碼欄位僅供參考，不參與排序。\n\n"
                "取得數據後，請以資深台股投資人風格解讀這份純技術名單，並點出哪些是主選股沒選到、"
                "但技術面值得關注的標的；每檔給進場策略、停損點、短期目標價。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "回傳幾檔回測名單（預設 10，上限 30）",
                        "default": 10,
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料（預設 false）",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="fetch_momentum_stocks",
            description=(
                "飆股名單：純動能排序，專挑強勢噴出的股票（漲停/近漲停、爆量、"
                "高相對強度、均線多頭排列、站上布林上軌、連續紅K）。\n\n"
                "與主選股不同：主評分會懲罰超買 / 乖離過大，剛好把飆股排除；"
                "此工具用獨立的純動能評分，**不罰超買**，追的就是強勢動能。\n\n"
                "支援盤中模式（intraday=true）：以 TWSE MIS 即時報價計算當下漲跌幅，"
                "適合盤中抓正在噴的標的。\n\n"
                "取得數據後，請以資深台股投資人風格點出今日最強的飆股、它們的動能來源與風險（追高風險），"
                "每檔給進場策略、停損點、短期目標價。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "回傳幾檔飆股（預設 15，上限 30）",
                        "default": 15,
                    },
                    "intraday": {
                        "type": "boolean",
                        "description": "盤中模式（預設 false）。true 時以 MIS 即時報價計算漲跌幅。",
                        "default": False,
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料（預設 false）",
                        "default": False,
                    },
                },
                "required": [],
            },
        ),
        types.Tool(
            name="fetch_hot_sectors",
            description=(
                "盤中族群推薦：以 TWSE MIS 即時報價，計算全市場各產業的即時強弱"
                "（上漲率、平均漲幅、成交值），回傳最強勢的族群與族群內強勢個股。\n\n"
                "預設盤中模式（intraday=true）；非交易時段或 MIS 取得失敗時，"
                "自動改用收盤資料並標註。籌碼面仍為昨日收盤後資料。\n\n"
                "取得數據後，請以資深台股投資人風格解讀今日資金流向哪些族群、族群輪動與"
                "族群內的領頭羊，給出操作方向。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "intraday": {
                        "type": "boolean",
                        "description": "盤中模式（預設 true）。false 時直接用收盤資料。",
                        "default": True,
                    },
                    "no_cache": {
                        "type": "boolean",
                        "description": "是否強制重新抓取資料（預設 false）",
                        "default": False,
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
        "screener_performance", "fetch_backtest_picks",
        "fetch_momentum_stocks", "fetch_hot_sectors",
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

    if name == "fetch_backtest_picks":
        bp_limit = min(int(arguments.get("limit", 10)), 30)
        result_text = await loop.run_in_executor(
            None, lambda: _run_backtest_picks(bp_limit, no_cache)
        )
        return [types.TextContent(type="text", text=result_text)]

    if name == "fetch_momentum_stocks":
        m_limit = min(int(arguments.get("limit", 15)), 30)
        m_intraday = bool(arguments.get("intraday", False))
        result_text = await loop.run_in_executor(
            None, lambda: _run_momentum_stocks(m_limit, no_cache, m_intraday)
        )
        return [types.TextContent(type="text", text=result_text)]

    if name == "fetch_hot_sectors":
        hs_intraday = bool(arguments.get("intraday", True))
        result_text = await loop.run_in_executor(
            None, lambda: _run_hot_sectors(no_cache, hs_intraday)
        )
        return [types.TextContent(type="text", text=result_text)]

    # fetch_stock_candidates
    limit = min(int(arguments.get("limit", 80)), 150)
    intraday = bool(arguments.get("intraday", False))
    exclude_bad_shape = bool(arguments.get("exclude_bad_shape", False))
    strategy = str(arguments.get("strategy", "balanced"))
    if strategy not in ("balanced", "trend", "reversal"):
        strategy = "balanced"
    result_text = await loop.run_in_executor(
        None, lambda: _run_pipeline(limit, no_cache, intraday, exclude_bad_shape, strategy)
    )
    return [types.TextContent(type="text", text=result_text)]


def _error_json(message: str, traceback_str: str | None = None) -> str:
    """Canonical error envelope shared by all tools (see docs/OUTPUT_SCHEMA.md)."""
    err = {"訊息": message}
    if traceback_str:
        err["traceback"] = traceback_str
    return json.dumps({"error": err}, ensure_ascii=False, indent=2)


def _resolve_data_date() -> tuple[str, bool]:
    """(YYYY-MM-DD, is_today) for the TWSE universe snapshot currently cached."""
    from config import taipei_now
    from data.cache import cache_get, make_key
    today_str = taipei_now().strftime("%Y%m%d")
    actual = cache_get(make_key("twse_universe_date", today_str)) or today_str
    if len(actual) == 8:
        return f"{actual[:4]}-{actual[4:6]}-{actual[6:]}", actual == today_str
    return f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:]}", True


def _run_backtest_picks(limit: int = 10, no_cache: bool = False) -> str:
    """
    回測名單: top-N purely by the backtest-validated technical score (score_stock),
    CHIP-BLIND. Scores the most-liquid BACKTEST_POOL_SIZE stocks and ranks by
    tech_score — deliberately bypassing the chip filter / per-exchange quota that
    can drop a high-score stock before it reaches the main recommendation list.
    """
    from data.cache import set_bypass
    try:
        set_bypass(read=no_cache, write=False)

        from data.fetcher_universe import fetch_universe
        from data.fetcher_chip import fetch_chip_data
        from data.fetcher_history import fetch_history
        from data.fetcher_fundamental import fetch_month_revenue
        from analysis.screener import select_liquid_pool, stage2_chip, stage3_technical
        from analysis.common import serialize_tech, serialize_chip, serialize_fundamental, SCHEMA_VERSION
        from config import BACKTEST_POOL_SIZE, get_recent_weekdays

        universe_df = fetch_universe()
        if universe_df.empty:
            return _error_json("無法取得股票清單，請確認網路連線")

        pool = select_liquid_pool(universe_df, BACKTEST_POOL_SIZE)
        if pool.empty:
            return _error_json("流動性池為空，無法產生回測名單")

        # Attach chip columns for DISPLAY only (apply_filter=False → no chip culling).
        chip_df = fetch_chip_data(get_recent_weekdays(7)[:5])
        pool = stage2_chip(pool, chip_df, apply_filter=False)

        history = fetch_history(pool[["code", "exchange"]].to_dict("records"))
        fundamental = fetch_month_revenue(codes=pool["code"].tolist())
        scored = stage3_technical(pool, history, fundamental=fundamental)
        if scored.empty:
            return _error_json("池中無足夠歷史資料的股票可評分")

        picks = scored.head(limit)
        stocks_data = []
        for _, row in picks.iterrows():
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
                "建議價位": d.get("price_levels") or {},
            })

        data_date, is_today = _resolve_data_date()
        return json.dumps({
            "格式版本": SCHEMA_VERSION,
            "資料日期": data_date,
            "資料說明": ("今日收盤資料" if is_today else f"最近交易日資料（{data_date} 收盤）"),
            "名單類型": "回測名單（純技術評分，未經籌碼篩選）",
            "評分池大小": int(len(pool)),
            "回測名單": stocks_data,
        }, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())
    finally:
        set_bypass(read=False, write=False)


def _run_momentum_stocks(limit: int = 15, no_cache: bool = False,
                         intraday: bool = False) -> str:
    """
    飆股名單: pure-momentum ranking (漲停/爆量/高RS/均線多頭突破/連紅), the
    deliberate opposite of the balanced score_stock (no overbought penalty).
    intraday=True patches today's %change with live MIS quotes.
    """
    from data.cache import set_bypass
    try:
        set_bypass(read=no_cache, write=False)

        from data.fetcher_universe import fetch_universe
        from data.fetcher_history import fetch_history
        from analysis.screener import select_liquid_pool
        from analysis.indicators import add_all_indicators, compute_relative_strength
        from analysis.common import extract_indicators, serialize_tech, SCHEMA_VERSION, make_ticker
        from analysis.momentum import score_momentum, consecutive_up_days, is_limit_up
        from analysis.intraday_shape import classify_intraday_shape
        from config import MOMENTUM_POOL_SIZE, MOMENTUM_MIN_SCORE

        universe_df = fetch_universe()
        if universe_df.empty:
            return _error_json("無法取得股票清單，請確認網路連線")

        pool = select_liquid_pool(universe_df, MOMENTUM_POOL_SIZE)
        if pool.empty:
            return _error_json("流動性池為空，無法產生飆股名單")

        snapshot: dict = {}
        snapshot_warn = None
        if intraday:
            from data.fetcher_snapshot import fetch_market_snapshot
            snapshot = fetch_market_snapshot(pool[["code", "exchange"]].to_dict("records"))
            if not snapshot:
                snapshot_warn = "盤中即時報價(MIS)取得失敗，改用收盤漲跌幅"

        history = fetch_history(pool[["code", "exchange"]].to_dict("records"))
        bench = history.get("^TWII")

        rows = []
        for _, stock in pool.iterrows():
            code = stock["code"]
            exchange = stock["exchange"]
            df_hist = history.get(make_ticker(code, exchange))
            if df_hist is None or len(df_hist) < 60:
                continue

            ind = extract_indicators(add_all_indicators(df_hist))
            rs = compute_relative_strength(df_hist, bench)
            up_days = consecutive_up_days(df_hist)

            if code in snapshot:
                change_pct = snapshot[code]["change_pct"]
                close = snapshot[code]["price"]
            else:
                change_pct = float(stock.get("change_pct", 0) or 0)
                close = float(stock.get("close", 0) or 0)

            m_score, m_signals = score_momentum(ind, rs, change_pct, up_days)

            # 當日線型 — only available intraday, since it needs today's O/H/L.
            if code in snapshot:
                q = snapshot[code]
                shape_signals, shape_adj, _ = classify_intraday_shape(
                    q.get("open"), q.get("high"), q.get("low"), q.get("price"), q.get("prev_close"))
                if shape_signals:
                    m_signals = m_signals + shape_signals
                    m_score = max(0, min(100, m_score + shape_adj))

            tech_src = {**ind, "rs20": rs.get("rs20"), "rs_label": rs.get("rs_label")}
            rows.append({
                "代號": code,
                "名稱": stock.get("name", ""),
                "產業": stock.get("industry", ""),
                "交易所": exchange,
                "收盤": round(close, 2),
                "漲跌_%": round(change_pct, 2),
                "動能評分": m_score,
                "漲停": is_limit_up(change_pct),
                "連紅日": up_days,
                "動能信號": m_signals,
                "技術指標": serialize_tech(tech_src),
            })

        rows.sort(key=lambda x: x["動能評分"], reverse=True)
        # Drop near-zero-momentum names rather than padding a thin pool with noise.
        qualified = [r for r in rows if r["動能評分"] >= MOMENTUM_MIN_SCORE]
        picks = qualified[:limit]

        data_date, is_today = _resolve_data_date()
        if intraday and not snapshot_warn:
            note = ("盤中即時模式（漲跌幅與當日線型來自 TWSE MIS 即時報價；"
                    "技術指標——量比/RS/均線結構——仍以昨日收盤 K 線計算，非即時重算）")
        elif is_today:
            note = "今日收盤資料"
        else:
            note = f"最近交易日資料（{data_date} 收盤）"

        output = {
            "格式版本": SCHEMA_VERSION,
            "資料日期": data_date,
            "資料說明": note,
            "名單類型": "飆股名單（純動能排序，不罰超買）",
            "模式": "盤中" if intraday else "收盤",
            "評分池大小": int(len(pool)),
            "飆股名單": picks,
        }
        if snapshot_warn:
            output["資料警示"] = snapshot_warn
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())
    finally:
        set_bypass(read=False, write=False)


def _run_hot_sectors(no_cache: bool = False, intraday: bool = True,
                     top_sectors: int = 5, top_stocks: int = 10) -> str:
    """
    盤中族群推薦: rank industries + individual stocks by intraday strength.
    Reuses compute_hot_sectors/compute_hot_stocks over a universe whose
    price/change columns are overwritten with live MIS quotes. Chip stays EOD.
    """
    from data.cache import set_bypass
    try:
        set_bypass(read=no_cache, write=False)

        from data.fetcher_universe import fetch_universe
        from data.fetcher_chip import fetch_chip_data
        from analysis.market_hot import compute_hot_sectors, compute_hot_stocks
        from analysis.common import SCHEMA_VERSION
        from config import get_recent_weekdays

        universe_df = fetch_universe()
        if universe_df.empty:
            return _error_json("無法取得股票清單，請確認網路連線")

        warn = None
        patched = 0
        if intraday:
            from data.fetcher_snapshot import fetch_market_snapshot
            cands = universe_df[["code", "exchange"]].to_dict("records")
            snapshot = fetch_market_snapshot(cands)
            if snapshot:
                universe_df = universe_df.copy()
                # Vectorised patch: build a per-field {code: value} map and .map()
                # once per column (was 4× row-wise .apply over ~2000 rows).
                codes = universe_df["code"]
                tv_est = {c: q["price"] * q["volume_lots"] * 1000 for c, q in snapshot.items()}
                universe_df["close"] = codes.map({c: q["price"] for c, q in snapshot.items()}).fillna(universe_df["close"])
                universe_df["change"] = codes.map({c: q["change"] for c, q in snapshot.items()}).fillna(universe_df["change"])
                universe_df["change_pct"] = codes.map({c: q["change_pct"] for c, q in snapshot.items()}).fillna(universe_df["change_pct"])
                universe_df["trade_value"] = codes.map(tv_est).fillna(universe_df["trade_value"])
                patched = len(snapshot)
            else:
                warn = "盤中即時報價(MIS)取得失敗，以下為收盤資料"
                intraday = False

        chip_df = fetch_chip_data(get_recent_weekdays(7)[:5])
        sectors = compute_hot_sectors(universe_df, chip_df, top_n=top_sectors)
        stocks = compute_hot_stocks(universe_df, chip_df, top_n=top_stocks)

        data_date, is_today = _resolve_data_date()
        if intraday:
            note = f"盤中即時模式（TWSE MIS 即時報價，已更新 {patched} 檔；籌碼面為 {data_date} 收盤）"
        else:
            note = "今日收盤資料" if is_today else f"最近交易日資料（{data_date} 收盤）"

        output = {
            "格式版本": SCHEMA_VERSION,
            "資料日期": data_date,
            "資料說明": note,
            "模式": "盤中" if intraday else "收盤",
            "強勢族群": sectors,
            "強勢個股": stocks,
        }
        if warn:
            output["資料警示"] = warn
        return json.dumps(output, ensure_ascii=False, indent=2)

    except Exception as e:
        import traceback
        return _error_json(str(e), traceback.format_exc())
    finally:
        set_bypass(read=False, write=False)


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


def _run_pipeline(limit: int = 80, no_cache: bool = False, intraday: bool = False,
                  exclude_bad_shape: bool = False, strategy: str = "balanced") -> str:
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
            # Degraded fallback: no stock cleared the chip filter. Re-attach chip
            # columns without filtering so candidates still carry chip data
            # instead of emitting all-null 籌碼.
            s2 = stage2_chip(s1, chip_df, apply_filter=False)

        # True Stage-2 survivor count, captured before the quota sampling below
        # narrows s2 to `limit` rows (so 篩選結果 reports the filter, not the sample).
        chip_pass_count = len(s2)

        # Phase 3: Historical OHLCV
        # Rank by chip strength, then sample the top `limit` with per-exchange
        # quotas proportional to each board's post-chip presence. Two problems
        # this avoids: (1) head() on stage1 order lists TWSE before TPEX; and
        # (2) a plain chip_signals sort still starves the OTC board, because the
        # TPEX API exposes fewer chip-signal sources (no 5-day net, consecutive
        # buys, or margin-change) so its stocks structurally score lower.
        if "chip_signals" in s2.columns and len(s2) > limit:
            s2 = s2.sort_values("chip_signals", ascending=False).reset_index(drop=True)
            total = len(s2)
            picked_idx: list = []
            for _exch, grp in s2.groupby("exchange", sort=False):
                quota = max(1, round(limit * len(grp) / total))
                picked_idx.extend(grp.head(quota).index.tolist())
            picked = s2.loc[picked_idx].sort_values("chip_signals", ascending=False)
            if len(picked) < limit:  # top up rounding shortfall by chip strength
                rest = s2.drop(index=picked_idx).head(limit - len(picked))
                picked = pd.concat([picked, rest])
            s2 = picked.head(limit).reset_index(drop=True)
        candidates_info = s2.head(limit)[["code", "exchange"]].to_dict("records")
        history = fetch_history(candidates_info)

        # Update TAIEX — prefer live TWSE MIS (data/fetcher_snapshot.py) over
        # yfinance's ^TWII history, which has been observed to stop updating
        # for multiple days at a time and would silently show a stale index
        # (and poison the futures basis calc below, which depends on it).
        from data.fetcher_snapshot import fetch_taiex_live
        taiex_live = fetch_taiex_live()
        taiex_close = None
        if taiex_live:
            market_summary["加權指數"] = taiex_live["price"]
            market_summary["加權指數漲跌"] = taiex_live["change"]
            market_summary["加權指數漲跌_%"] = taiex_live["change_pct"]
            taiex_close = taiex_live["price"]
        else:
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
                    taiex_close = last

        if taiex_close:
            # Futures overlay: basis + institutional positions
            from data.fetcher_futures import fetch_futures_summary
            futures = fetch_futures_summary(taiex_close=taiex_close)
            if futures:
                market_summary["期貨概況"] = futures

        # Stage 3: Technical scoring (with relative strength + monthly revenue)
        # + multi-factor chip/fundamental/sector/RS60 blend, ranked by total_score
        # (fetch_backtest_picks calls stage3_technical with none of this and keeps
        # ranking by tech_score alone — see stage3_technical's docstring).
        from data.fetcher_fundamental import fetch_month_revenue
        from analysis.market_hot import compute_sector_score_map
        fundamental = fetch_month_revenue(codes=s2["code"].tolist())
        sector_score_map = compute_sector_score_map(universe_df, chip_df)
        final = stage3_technical(s2, history, fundamental=fundamental,
                                 sector_score_map=sector_score_map,
                                 strategy=strategy, rank_by="total_score")

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
                "綜合評分": d.get("total_score", d.get("tech_score", 0)),
                "評分分項": d.get("score_breakdown", {}),
                "技術信號": d.get("combined_signals", d.get("tech_signals", [])),
                "技術指標": serialize_tech(d),
                "籌碼": serialize_chip(d),
                "基本面": serialize_fundamental(d),
                "建議價位": d.get("price_levels") or {},
            })

        # ---- Intraday: patch close price + change% with TWSE MIS live quotes ----
        # (Unified on MIS — same source as fetch_hot_sectors/fetch_momentum_stocks
        # intraday mode. Replaces the old yfinance realtime path: MIS is faster,
        # covers both TWSE+TPEX in one batched call, and has no ~15-min delay.)
        snapshot_warn = None
        excluded_bad_shape_count = 0
        if intraday and stocks_data:
            from data.fetcher_snapshot import fetch_market_snapshot
            from analysis.intraday_shape import classify_intraday_shape, is_bad_shape
            rt_candidates = [{"code": s["代號"], "exchange": s["交易所"]} for s in stocks_data]
            snapshot = fetch_market_snapshot(rt_candidates)
            if snapshot:
                for s in stocks_data:
                    q = snapshot.get(s["代號"])
                    if not q:
                        continue
                    s["收盤"] = q["price"]
                    s["漲跌_%"] = q["change_pct"]
                    # 當日線型: pure O/H/L/current arithmetic, only knowable
                    # intraday — appended as extra signals, doesn't touch 技術評分
                    # (that stays the EOD score the candidate was selected on).
                    shape_signals, _shape_adj, shape_metrics = classify_intraday_shape(
                        q.get("open"), q.get("high"), q.get("low"), q.get("price"), q.get("prev_close"))
                    if shape_signals:
                        s["技術信號"] = s["技術信號"] + shape_signals
                        s["當日線型"] = shape_metrics

                if exclude_bad_shape:
                    before = len(stocks_data)
                    stocks_data = [s for s in stocks_data
                                  if not is_bad_shape(s.get("技術信號", []))]
                    excluded_bad_shape_count = before - len(stocks_data)
            else:
                snapshot_warn = "盤中即時報價(MIS)取得失敗，以下為收盤資料"
                intraday = False

        data_date, is_today = _resolve_data_date()
        if intraday:
            data_note = (f"盤中即時模式（個股報價與當日線型來自 TWSE MIS 即時報價；"
                        f"技術指標——KD/乖離/量比/RS——仍以 {data_date} 收盤 K 線計算，"
                        f"與即時報價可能不同步；籌碼面為 {data_date} 收盤後資料）")
            if exclude_bad_shape and excluded_bad_shape_count:
                data_note += f"；已依當日線型排除 {excluded_bad_shape_count} 檔轉弱標的"
        elif is_today:
            data_note = "今日收盤資料"
        else:
            data_note = f"最近交易日資料（使用 {data_date} 收盤價，盤中或資料尚未更新）"

        # Degraded-source flags: fetch failures are logged to stderr (invisible to
        # an MCP client), so surface any missing data source in the output itself.
        degraded = []
        if chip_df is None or chip_df.empty:
            degraded.append("籌碼面資料缺失(外資/投信/融資)")
        if "期貨概況" not in market_summary:
            degraded.append("期貨資料缺失(台指期/正逆價差)")
        if not fundamental:
            degraded.append("基本面資料缺失(月營收；未設定 FINMIND_TOKEN 時僅候選股逐檔抓取)")
        if universe_df.attrs.get("missing_exchanges"):
            degraded.append("交易所資料缺失:" + "、".join(universe_df.attrs["missing_exchanges"]))
        if snapshot_warn:
            degraded.append(snapshot_warn)

        from analysis.common import SCHEMA_VERSION
        output = {
            "格式版本": SCHEMA_VERSION,
            "資料日期": data_date,
            "資料說明": data_note,
            "選股策略": strategy,
            "篩選結果": {
                "全市場股票數": len(universe_df),
                "流動性篩選後": len(s1),
                "籌碼篩選後": chip_pass_count,
                "技術評分通過": len(final),
                "送入分析": len(stocks_data),
            },
            "大盤概況": market_summary,
            "候選股票": stocks_data,
        }
        if degraded:
            output["資料來源警示"] = degraded

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
        from analysis.common import extract_indicators, serialize_tech, serialize_chip, serialize_fundamental, make_ticker
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
                if h.get(make_ticker(code, exch)) is not None:
                    exchange = exch
                    history = h
                    break

        if not exchange:
            return _error_json(f"找不到股票 {code}，請確認代號是否正確")

        ticker = make_ticker(code, exchange)
        df_hist = history.get(ticker)

        if df_hist is None or df_hist.empty:
            return _error_json(f"無法取得 {code} 的歷史 K 線，資料可能尚未更新")

        # ---- Step 3: Technical indicators ----
        df_ind = add_all_indicators(df_hist)
        rs = compute_relative_strength(df_hist, history.get("^TWII"))

        # ---- Step 4: Fundamentals (monthly revenue) ----
        from data.fetcher_fundamental import fetch_month_revenue
        fund = fetch_month_revenue(codes=[code]).get(code, {})

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
        from analysis.common import SCHEMA_VERSION, price_divergence_signal, divergence_confidence_discount
        current_close = info.get("close", close_price)
        # Same reconciliation stage3_technical does for the screener: 收盤 is the
        # official exchange close, but yf_close drives the indicators — flag it
        # when they diverge so the analyst knows KD/乖離/RS may be off a different
        # print, and discount tech_score's confidence by the same tiers.
        divergence = price_divergence_signal(current_close, close_price)
        if divergence:
            tech_signals = list(tech_signals) + [divergence]
            discount = divergence_confidence_discount(current_close, close_price)
            if discount < 1.0:
                tech_score = round(tech_score * discount)

        from analysis.price_levels import compute_price_levels
        price_levels = compute_price_levels(
            close=current_close, ma5=ind.get("ma5"), ma20=ind.get("ma20"),
            ma60=ind.get("ma60"), atr=ind.get("atr"), bias20=ind.get("bias20"),
            rsi=ind.get("rsi"), bb_pct=ind.get("bb_pct"),
        )
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
            "建議價位": price_levels or {},
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
