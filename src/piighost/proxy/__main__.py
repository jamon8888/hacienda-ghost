"""Entrypoint: `python -m piighost.proxy`.

Equivalent to `piighost proxy run` but without the Typer subcommand dispatcher.
Kept minimal — the real CLI surface lives in cli/commands/proxy.py.
"""
from __future__ import annotations

from piighost.cli.commands.proxy import proxy_app


def main() -> None:
    proxy_app(prog_name="piighost.proxy")


if __name__ == "__main__":
    main()
