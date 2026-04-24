from __future__ import annotations

import sys
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

console = Console(highlight=False)

_utf8 = (sys.stdout.encoding or "").lower() in {"utf-8", "utf8"}
_STEP = "→"  if _utf8 else "->"
_OK   = "✓"  if _utf8 else "ok"
_WARN = "⚠"  if _utf8 else "!!"
_FAIL = "✗"  if _utf8 else "xx"


def step(message: str) -> None:
    console.print(f"\n[bold cyan]{_STEP}[/bold cyan] {message}")


def success(message: str) -> None:
    console.print(f"[bold green]{_OK}[/bold green] {message}")


def warn(message: str) -> None:
    console.print(f"[bold yellow]{_WARN}[/bold yellow] {message}", style="yellow")


def error(message: str) -> None:
    console.print(f"[bold red]{_FAIL}[/bold red] {message}", style="red")


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
