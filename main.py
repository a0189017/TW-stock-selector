"""
台灣股市選股系統 — 每日10檔精選推薦
Usage:
    python main.py           # 正常執行（使用 cache）
    python main.py --no-cache  # 強制重新抓取所有資料
    python main.py --debug   # 顯示中間篩選結果
"""
import argparse
import sys
import time
from datetime import datetime

from output.renderer import (console, make_progress, print_header,
                              print_stage_summary, print_candidates_table,
                              print_analysis_header, print_analysis_stream, print_done)
from output.report_writer import save_report


def patch_cache_if_no_cache(no_cache: bool):
    """If --no-cache, make every cache read miss (fetch fresh)."""
    from data.cache import set_bypass
    set_bypass(read=no_cache)


def get_taiex_info(history: dict) -> tuple[str, str]:
    """Extract TAIEX last price and change from fetched history."""
    taiex_df = history.get("^TWII")
    if taiex_df is None or taiex_df.empty:
        return "—", "—"
    closes = taiex_df["Close"].dropna()
    if len(closes) < 2:
        return f"{closes.iloc[-1]:,.2f}", "—"
    last = closes.iloc[-1]
    prev = closes.iloc[-2]
    change = last - prev
    pct = change / prev * 100
    sign = "+" if change >= 0 else ""
    change_str = f"({sign}{change:,.2f} / {sign}{pct:.2f}%)"
    return f"{last:,.2f}", change_str


def main():
    parser = argparse.ArgumentParser(description="台灣股市選股系統")
    parser.add_argument("--no-cache", action="store_true", help="強制重新抓取所有資料")
    parser.add_argument("--debug", action="store_true", help="顯示中間篩選結果")
    args = parser.parse_args()

    patch_cache_if_no_cache(args.no_cache)
    if args.debug:
        from log import enable_debug
        enable_debug()

    print_header()
    start_time = time.time()

    with make_progress() as progress:

        # ----------------------------------------------------------------
        # Phase 1: Universe
        # ----------------------------------------------------------------
        task = progress.add_task("Phase 1/5  抓取股票清單（TWSE + TPEX）...", total=None)
        from data.fetcher_universe import fetch_universe, fetch_market_summary
        universe_df = fetch_universe()
        progress.update(task, description=f"Phase 1/5  股票清單 ✓  共 {len(universe_df)} 支")

        if universe_df.empty:
            console.print("[bold red]錯誤：無法取得股票清單。請確認網路連線後再試。[/bold red]")
            sys.exit(1)

        market_summary = fetch_market_summary(universe_df)

        # ----------------------------------------------------------------
        # Phase 2: Chip data
        # ----------------------------------------------------------------
        progress.update(task, description="Phase 2/5  抓取籌碼資料（三大法人 + 融資融券）...")
        from data.fetcher_chip import fetch_chip_data, compute_market_foreign_total
        from config import get_recent_weekdays
        dates = get_recent_weekdays(7)[:5]
        chip_df = fetch_chip_data(dates)
        foreign_total = compute_market_foreign_total(chip_df)
        market_summary["foreign_total"] = foreign_total
        progress.update(task, description=f"Phase 2/5  籌碼資料 ✓  {len(chip_df)} 支有籌碼數據")

        # ----------------------------------------------------------------
        # Compute hot sectors and hot stocks from full universe
        # ----------------------------------------------------------------
        from analysis.market_hot import compute_hot_sectors, compute_hot_stocks
        hot_sectors = compute_hot_sectors(universe_df, chip_df, top_n=5)
        hot_stocks = compute_hot_stocks(universe_df, chip_df, top_n=10)
        market_summary["hot_sectors"] = hot_sectors
        market_summary["hot_stocks"] = hot_stocks

        # ----------------------------------------------------------------
        # Stage 1 + 2 Screening (instant)
        # ----------------------------------------------------------------
        from analysis.screener import stage1_liquidity, stage2_chip
        s1_df = stage1_liquidity(universe_df)
        s2_df = stage2_chip(s1_df, chip_df)

        if args.debug:
            print_stage_summary(1, "流動性篩選", len(s1_df), len(universe_df))
            print_stage_summary(2, "籌碼信號篩選", len(s2_df), len(s1_df))

        if s2_df.empty:
            console.print("[yellow]警告：Stage 2 無候選股票，放寬條件直接使用 Stage 1 結果[/yellow]")
            s2_df = s1_df

        # ----------------------------------------------------------------
        # Phase 3: Historical OHLCV
        # ----------------------------------------------------------------
        progress.update(task, description=f"Phase 3/5  下載 {len(s2_df)} 支股票歷史資料...")
        candidates_info = s2_df[["code", "exchange"]].to_dict("records")
        from data.fetcher_history import fetch_history
        history = fetch_history(candidates_info)
        progress.update(task, description=f"Phase 3/5  歷史資料 ✓  {len(history)} 支成功下載")

        # Update TAIEX in market summary
        taiex_price, taiex_change = get_taiex_info(history)
        market_summary["taiex"] = taiex_price
        market_summary["taiex_change"] = taiex_change

        # ----------------------------------------------------------------
        # Stage 3: Technical scoring
        # ----------------------------------------------------------------
        progress.update(task, description="Phase 4/5  技術指標評分（含相對強度 + 月營收）...")
        from analysis.screener import stage3_technical
        from data.fetcher_fundamental import fetch_month_revenue
        fundamental = fetch_month_revenue()
        final_candidates = stage3_technical(s2_df, history, fundamental=fundamental)

        if args.debug:
            print_stage_summary(3, "技術指標篩選", len(final_candidates), len(s2_df))

        if final_candidates.empty:
            console.print("[yellow]警告：技術篩選後無候選股票，使用 Stage 2 結果（無指標分數）[/yellow]")
            final_candidates = s2_df.head(80)

        # Persist the quantitative screening so it can be graded later
        try:
            from data.recommendations import save_screening
            save_screening(final_candidates.to_dict("records"))
        except Exception:
            pass

        progress.update(task, description=f"Phase 4/5  技術評分 ✓  {len(final_candidates)} 支進入 Claude 分析")

    if args.debug:
        print_candidates_table(final_candidates)

    # ----------------------------------------------------------------
    # Phase 4: Claude analysis
    # ----------------------------------------------------------------
    print_analysis_header()

    from ai.prompt_builder import SYSTEM_PROMPT, build_user_prompt
    from ai.claude_client import analyze_stocks

    user_prompt = build_user_prompt(final_candidates.to_dict("records"), market_summary)

    tokens_buffer = []

    def on_token(text: str):
        print_analysis_stream(text)
        tokens_buffer.append(text)

    analysis_text = analyze_stocks(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=user_prompt,
        on_token=on_token,
    )

    # ----------------------------------------------------------------
    # Phase 5: Save report
    # ----------------------------------------------------------------
    report_path = save_report(analysis_text, market_summary, len(final_candidates))
    elapsed = time.time() - start_time
    print_done(report_path)
    console.print(f"  [dim]總耗時：{elapsed:.1f} 秒[/dim]")


if __name__ == "__main__":
    main()
