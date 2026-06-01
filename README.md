# TW Stock Selector — 台股 AI 選股系統

每日從全市場 2,000+ 支股票，透過三階段量化篩選縮減至約 80 支候選，再由 Claude AI 以資深台股投資人視角挑出 10 檔精選推薦，附帶技術面、籌碼面分析與明確進出場策略。

支援兩種使用方式：
- **CLI 模式** — 執行 `main.py`，結果以 Rich 終端介面呈現並存成 Markdown 報告
- **MCP Server 模式** — 整合進 Claude Desktop，直接在對話框中呼叫選股工具

---

## 篩選流程

```
全市場 2,000+ 支
     │
     ▼ Stage 1：流動性篩選
     │  成交值 ≥ 1,000 萬、股價 10–5,000 元、排除 ETF / 警示股
     │
     ▼ Stage 2：籌碼信號篩選
     │  外資 / 投信淨買、融資變化，至少 2 個正向籌碼信號
     │
     ▼ Stage 3：技術指標評分
     │  KD、MACD、均線結構、乖離率、量比，取前 80 名
     │
     ▼ Claude AI 分析
        選出 10 檔，給出推薦理由、進場策略、停損點、目標價
```

---

## 安裝

**需求：** Python 3.11+

```bash
git clone https://github.com/a0189017/TW-stock-selector.git
cd TW-stock-selector

python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

建立 `.env` 檔案並填入 Anthropic API 金鑰（CLI 模式必要，MCP 模式不需要）：

```
ANTHROPIC_API_KEY=sk-ant-...
```

---

## 使用方式

### CLI 模式

```bash
# 正常執行（使用 6 小時 cache）
python main.py

# 強制重新抓取所有資料
python main.py --no-cache

# 顯示中間篩選結果
python main.py --debug
```

報告會存到 `reports/` 目錄（`.gitignore` 已排除）。

### MCP Server 模式（Claude Desktop）

啟動 MCP Server，讓 Claude Desktop 直接使用選股工具，無需額外 API 費用（分析由 Claude Desktop 本身執行）。

**1. 設定 Claude Desktop**

編輯 `~/Library/Application Support/Claude/claude_desktop_config.json`，加入：

```json
{
  "mcpServers": {
    "stock-selector": {
      "command": "/path/to/TW-stock-selector/venv/bin/python3",
      "args": ["/path/to/TW-stock-selector/mcp_server.py"]
    }
  }
}
```

將 `/path/to/TW-stock-selector` 替換為你的實際路徑。

**2. 重啟 Claude Desktop**

重啟後即可在對話中使用以下工具：

| 工具 | 說明 |
|------|------|
| `fetch_stock_candidates` | 執行三階段篩選，回傳最多 80 支候選，請 Claude 選出今日 10 檔 |
| `check_portfolio` | 對持股進行健檢，分析技術面與籌碼面，給出續抱 / 停損建議 |
| `analyze_stock` | 深度分析單一個股（輸入 4 碼代號） |
| `add_holding` | 新增持股（代號、張數、成本價） |
| `remove_holding` | 移除持股 |
| `list_holdings` | 列出目前持股清單 |

**範例對話：**
> 「幫我跑今天的選股，選出最值得進場的 10 檔」
> 「幫我健檢持股，看看有沒有需要停損的」
> 「分析 2330 台積電目前的技術面和籌碼」

---

## 資料來源

| 資料 | 來源 |
|------|------|
| 股票清單、今日行情 | TWSE OpenAPI、TPEX OpenAPI |
| 三大法人、融資融券 | TWSE RWD API |
| 歷史 K 線（OHLCV） | Yahoo Finance（yfinance） |

資料有 6 小時 cache（SQLite），避免頻繁打 API。

---

## 專案結構

```
├── main.py              # CLI 入口
├── mcp_server.py        # MCP Server 入口
├── config.py            # 參數設定（篩選門檻、Cache TTL 等）
├── portfolio.py         # 持股管理（CRUD）
├── data/
│   ├── fetcher_universe.py   # 抓取全市場股票清單
│   ├── fetcher_chip.py       # 抓取籌碼資料
│   ├── fetcher_history.py    # 抓取歷史 K 線
│   └── cache.py              # SQLite cache 封裝
├── analysis/
│   ├── screener.py           # 三階段篩選邏輯
│   ├── indicators.py         # 技術指標計算（KD / MACD / 均線 / 量比）
│   └── market_hot.py         # 強勢族群 / 強勢個股計算
├── ai/
│   ├── claude_client.py      # Anthropic API 呼叫（streaming）
│   └── prompt_builder.py     # 系統提示詞 + 用戶提示詞建構
└── output/
    ├── renderer.py           # Rich 終端輸出
    └── report_writer.py      # Markdown 報告存檔
```

---

## 免責聲明

本工具僅供研究與學習用途，選股結果不構成任何投資建議。股市有風險，投資前請自行判斷。
