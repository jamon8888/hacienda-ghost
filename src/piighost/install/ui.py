from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

console = Console()


def step(message: str) -> None:
    console.print(f"\n[bold cyan]→[/bold cyan] {message}")


def success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow] {message}", style="yellow")


def error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}", style="red")


def info(message: str) -> None:
    console.print(f"  {message}", style="dim")


@contextmanager
def spinner(label: str) -> Generator[None, None, None]:
    with console.status(f"[cyan]{label}[/cyan]"):
        yield


def download_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )
