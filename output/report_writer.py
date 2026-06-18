"""Save daily report to reports/YYYY-MM-DD_report.md."""
from pathlib import Path
from datetime import datetime


REPORTS_DIR = Path(__file__).parent.parent / "reports"


def save_report(analysis_text: str, market_summary: dict, candidate_count: int) -> str:
    """
    Save report to disk. Returns the file path.
    """
    REPORTS_DIR.mkdir(exist_ok=True)
    today = datetime.today().strftime("%Y-%m-%d")
    path = REPORTS_DIR / f"{today}_report.md"

    # market_summary holds raw numbers (canonical schema) — format for display here.
    taiex = market_summary.get("加權指數")
    taiex_chg = market_summary.get("加權指數漲跌")
    taiex_pct = market_summary.get("加權指數漲跌_%")
    taiex_str = f"{taiex:,.2f}" if taiex is not None else "—"
    taiex_chg_str = (f"({taiex_chg:+,.2f} / {taiex_pct:+.2f}%)"
                     if taiex_chg is not None else "")
    foreign_total = market_summary.get("外資合計淨買_張")
    foreign_str = f"{foreign_total:+,.0f} 張" if foreign_total is not None else "—"

    header = f"""# 台灣股市選股報告 — {today}

## 大盤概況
- 加權指數：{taiex_str} {taiex_chg_str}
- 成交量：{market_summary.get('成交值_億', '—')} 億
- 上漲/持平/下跌：{market_summary.get('上漲家數', '—')}/{market_summary.get('持平家數', '—')}/{market_summary.get('下跌家數', '—')} 家
- 外資合計：{foreign_str}

> 本報告由 AI 自動產生，僅供參考，不構成投資建議。投資人應自行評估風險。

---

## 今日精選10檔

"""

    content = header + analysis_text

    path.write_text(content, encoding="utf-8")
    return str(path)
