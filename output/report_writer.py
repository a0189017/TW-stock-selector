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

    header = f"""# 台灣股市選股報告 — {today}

## 大盤概況
- 加權指數：{market_summary.get('taiex', '—')} {market_summary.get('taiex_change', '')}
- 成交量：{market_summary.get('volume_b', '—')} 億
- 上漲/持平/下跌：{market_summary.get('up', '—')}/{market_summary.get('flat', '—')}/{market_summary.get('down', '—')} 家
- 外資合計：{market_summary.get('foreign_total', '—')}

> 本報告由 AI 自動產生，僅供參考，不構成投資建議。投資人應自行評估風險。

---

## 今日精選10檔

"""

    content = header + analysis_text

    path.write_text(content, encoding="utf-8")
    return str(path)
