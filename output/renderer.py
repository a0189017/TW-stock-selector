"""Rich terminal rendering: progress, results."""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text
from rich import box

console = Console()


def make_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def print_header():
    console.print(Panel.fit(
        "[bold yellow]🇹🇼 台灣股市選股系統[/bold yellow]\n"
        "[dim]powered by Claude · 每日10檔精選推薦[/dim]",
        border_style="yellow",
    ))
    console.print()


def print_stage_summary(stage: int, label: str, count: int, total: int):
    console.print(
        f"  [dim]Stage {stage}[/dim] [cyan]{label}[/cyan] "
        f"→ [bold green]{count}[/bold green] / {total} 支"
    )


def print_candidates_table(candidates_df):
    """Show top candidates debug table."""
    if candidates_df.empty:
        console.print("[yellow]無候選股票[/yellow]")
        return

    table = Table(title="候選股票 Top 20", box=box.SIMPLE_HEAVY, header_style="bold magenta")
    table.add_column("排名", justify="right", style="dim")
    table.add_column("代號", style="bold")
    table.add_column("名稱")
    table.add_column("產業", style="dim")
    table.add_column("收盤", justify="right")
    table.add_column("漲跌%", justify="right")
    table.add_column("技術分", justify="right", style="bold cyan")
    table.add_column("信號", style="dim")

    for i, row in candidates_df.head(20).iterrows():
        chg = row.get("change_pct", 0)
        chg_str = f"[green]+{chg:.2f}%[/green]" if chg > 0 else (
            f"[red]{chg:.2f}%[/red]" if chg < 0 else f"{chg:.2f}%"
        )
        signals = ", ".join(row.get("tech_signals", [])[:3])
        table.add_row(
            str(i + 1),
            row.get("code", ""),
            row.get("name", ""),
            row.get("industry", ""),
            f"{row.get('close', 0):.1f}",
            chg_str,
            str(row.get("tech_score", 0)),
            signals,
        )
    console.print(table)


def print_analysis_header():
    console.print()
    console.print(Panel(
        "[bold yellow]📊 Claude 分析中...[/bold yellow]",
        border_style="yellow",
        expand=False,
    ))
    console.print()


def print_analysis_stream(text: str):
    """Print streamed text directly to console."""
    console.print(text, end="", markup=False, highlight=False)


def print_done(report_path: str):
    console.print()
    console.print()
    console.print(Panel(
        f"[bold green]✓ 分析完成[/bold green]\n"
        f"[dim]報告已儲存至：[/dim][cyan]{report_path}[/cyan]",
        border_style="green",
        expand=False,
    ))
