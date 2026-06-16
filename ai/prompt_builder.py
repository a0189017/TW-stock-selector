"""Build Claude prompts for the 股癌-style analyst."""
import json
from datetime import datetime

from analysis.common import serialize_tech, serialize_chip, serialize_fundamental


SYSTEM_PROMPT = """你是一位擁有超過15年台股實戰經驗的選股達人。你的分析風格精準、直白，每句話都有料，不說廢話。

你的分析原則：
- 籌碼為王：外資和投信的動向比技術線型更重要，主力進場才是真信號
- 技術確認：籌碼面強的股票，再用KD、MACD、均線確認時機
- 不追高：乖離率過大（超過+15%）的票要特別提醒，要等回測均線再進
- 停損紀律：每一檔推薦都要給明確的停損點（跌破哪條均線或哪個價位就出場）
- 產業題材：會點出每檔股票的當前市場題材或產業趨勢背景
- 大盤為鏡：先判斷市場情緒，再決定倉位輕重

你的語言風格：
- 用繁體中文，台灣投資人習慣的說法
- 適時使用投資術語：洗盤、蹲馬步、外資回頭、籌碼乾淨、主力拉抬、強勢整理
- 數字精確：價格精確到小數點後一位，量用「張」為單位
- 結論先行：先說推薦理由，再補充細節

輸出格式規定：

**第一部分：今日市場總覽**
先給出「今日強勢族群」與「今日強勢個股」兩個小節，各用條列式呈現，說明為何這些族群/個股今日特別強勢。

**第二部分：10檔精選推薦**
每支股票依序給出：
1. **推薦理由**（1~2句，直接點出最強的理由）
2. **技術面**（KD、MACD、均線現況，重點是趨勢方向）
3. **籌碼面**（外資、投信動向，融資是否健康）
4. **進場策略**（建議的進場價格區間，支撐/壓力位）
5. **停損點**（跌破哪裡就走人，一定要寫）
6. **短期目標**（1~3週的目標價）

**第三部分：今日大盤觀察**（3~5句，根據上漲下跌家數、外資方向、成交量來判斷市場情緒）

注意：10檔推薦要適度分散產業，不要全押同一個族群。推薦個股時可優先考量與強勢族群相關的標的。"""


def build_user_prompt(candidates: list[dict], market_summary: dict) -> str:
    today = datetime.today().strftime("%Y-%m-%d")

    stocks_data = []
    for s in candidates:
        entry = {
            "代號": s.get("code", ""),
            "名稱": s.get("name", ""),
            "產業": s.get("industry", "其他"),
            "交易所": s.get("exchange", ""),
            "收盤": s.get("close", 0),
            "漲跌%": s.get("change_pct", 0),
            "技術評分": s.get("tech_score", 0),
            "技術信號": s.get("tech_signals", []),
            "技術指標": serialize_tech(s),
            "籌碼": serialize_chip(s),
            "基本面": serialize_fundamental(s),
        }
        stocks_data.append(entry)

    # Build hot sectors section
    hot_sectors = market_summary.get("hot_sectors", [])
    if hot_sectors:
        sectors_lines = []
        for s in hot_sectors:
            sign = "+" if s["avg_change_pct"] >= 0 else ""
            sectors_lines.append(
                f"  - {s['industry']}：平均漲幅 {sign}{s['avg_change_pct']}%，"
                f"上漲率 {s['up_ratio_pct']}%（{s['up_count']}/{s['stock_count']}支），"
                f"三大法人 {s['big3_net']:+,.0f} 張，成交值 {s['trade_value_b']} 億"
            )
        hot_sectors_text = "\n".join(sectors_lines)
    else:
        hot_sectors_text = "  （資料不足）"

    # Build hot stocks section
    hot_stocks = market_summary.get("hot_stocks", [])
    if hot_stocks:
        stocks_lines = []
        for s in hot_stocks:
            sign = "+" if s["change_pct"] >= 0 else ""
            stocks_lines.append(
                f"  - {s['code']} {s['name']}（{s['industry']}）：{sign}{s['change_pct']}%，"
                f"收盤 {s['close']}，外資 {s['foreign_net_today']:+,.0f} 張，"
                f"投信 {s['trust_net_today']:+,.0f} 張，外資5日 {s['foreign_net_5d']:+,.0f} 張"
            )
        hot_stocks_text = "\n".join(stocks_lines)
    else:
        hot_stocks_text = "  （資料不足）"

    prompt = f"""今天是 {today}，以下是經過三階段篩選後的 {len(candidates)} 檔候選股票。

【今日大盤數據】
- 上市成交量：{market_summary.get('volume_b', '—')} 億
- 上漲/持平/下跌家數：{market_summary.get('up', '—')}/{market_summary.get('flat', '—')}/{market_summary.get('down', '—')}
- 加權指數：{market_summary.get('taiex', '—')} （{market_summary.get('taiex_change', '—')}）
- 外資合計：{market_summary.get('foreign_total', '—')}

【今日強勢、熱門族群（Top 5）】
{hot_sectors_text}

【今日強勢、熱門個股（Top 10，全市場）】
{hot_stocks_text}

【候選股票資料（經三階段篩選）】
{json.dumps(stocks_data, ensure_ascii=False, indent=2)}

請依照格式輸出以下三個部分：

**第一部分：今日市場總覽**
根據上方「強勢族群」與「強勢個股」資料，用你的專業視角解讀今日市場的主軸題材。說明哪些族群領漲、資金動向集中在哪裡，以及這對選股方向的意義。

**第二部分：10檔精選推薦**
從 {len(candidates)} 檔候選股中選出今日最值得關注的 **10 檔**，按推薦強度由高到低排列（第1名最強）。
每檔必須包含：推薦理由、技術面、籌碼面、進場策略、停損點、短期目標。

**第三部分：今日大盤觀察**（3~5句，根據上漲下跌家數、外資方向、成交量來判斷市場情緒）

提醒：
- 技術評分只是初步量化參考，最終判斷請用你的綜合判斷力
- 不要全選同一個產業
- 如果某檔票很好但乖離太大，可以列為「等待回測後再進」
- 強勢族群中的標的若也符合技術/籌碼條件，可優先考量
"""
    return prompt
