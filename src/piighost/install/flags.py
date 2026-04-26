"""Parse CLI flags / env vars into an InstallPlan.

This module is the non-interactive producer. It is also called by
the interactive flow when the user has supplied any explicit flags
(in which case those flags become defaults that the prompts may
still override).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from piighost.install.clients import detect_all
from piighost.install.plan import Client, Embedder, InstallPlan, Mode


@dataclass(frozen=True)
class DeprecationNotice:
    flag: str
    severity: Literal["deprecated", "advanced"]
    message: str


@dataclass(frozen=True)
class FlagsResult:
    plan: InstallPlan
    deprecations: list[DeprecationNotice]


_VALID_CLIENTS = {c.value: c for c in Client}


def parse_flags(
    *,
    mode: str | None,
    vault_dir: Path | None,
    embedder: str | None,
    mistral_api_key: str | None,
    clients: str | None,
    user_service: bool | None,
    warmup: bool,
    force: bool,
    dry_run: bool,
    yes: bool,
    env: dict[str, str],
) -> FlagsResult:
    """Pure function: arguments → InstallPlan + deprecation notices.

    Defaults applied here so producers (CLI, interactive) share one
    set of rules. The caller is responsible for printing the
    deprecation notices to the user.
    """
    deprecations: list[DeprecationNotice] = []

    resolved_mode, mode_deprecation = _resolve_mode(mode)
    if mode_deprecation is not None:
        deprecations.append(mode_deprecation)

    resolved_embedder = _resolve_embedder(embedder)
    resolved_key = mistral_api_key or env.get("MISTRAL_API_KEY") or None
    if resolved_embedder is Embedder.MISTRAL and not resolved_key:
        raise ValueError(
            "embedder=mistral requires mistral_api_key "
            "(pass --mistral-api-key or set MISTRAL_API_KEY env var)."
        )

    resolved_clients = _resolve_clients(clients)
    resolved_vault = vault_dir or (Path.home() / ".piighost" / "vault")

    if user_service is None:
        # Default: on for FULL/STRICT, off for MCP_ONLY
        resolved_user_service = resolved_mode is not Mode.MCP_ONLY
    else:
        resolved_user_service = user_service

    if resolved_mode is Mode.STRICT and not resolved_user_service:
        raise ValueError(
            "strict mode requires the auto-restart service. "
            "Remove --no-user-service or pick --mode=full."
        )

    plan = InstallPlan(
        mode=resolved_mode,
        vault_dir=resolved_vault,
        embedder=resolved_embedder,
        mistral_api_key=resolved_key,
        clients=resolved_clients,
        install_user_service=resolved_user_service,
        warmup_models=warmup,
        force=force,
        dry_run=dry_run,
    )
    return FlagsResult(plan=plan, deprecations=deprecations)


def _resolve_mode(raw: str | None) -> tuple[Mode, DeprecationNotice | None]:
    if raw is None:
        return Mode.FULL, None
    if raw == "light":
        return Mode.FULL, DeprecationNotice(
            flag="--mode=light",
            severity="deprecated",
            message=(
                "[deprecated] --mode=light is now '--mode=full'. "
                "This alias will be removed in 0.10.0."
            ),
        )
    if raw == "strict":
        return Mode.STRICT, DeprecationNotice(
            flag="--mode=strict",
            severity="advanced",
            message=(
                "[advanced] strict mode requires admin and modifies your "
                "hosts file. Most users want '--mode=full'. See "
                "docs/install-paths.md."
            ),
        )
    if raw == "full":
        return Mode.FULL, None
    if raw == "mcp-only":
        return Mode.MCP_ONLY, None
    raise ValueError(
        f"unknown mode {raw!r}. Valid: full, mcp-only, strict, light (deprecated)."
    )


def _resolve_embedder(raw: str | None) -> Embedder:
    if raw is None:
        return Embedder.LOCAL
    try:
        return Embedder(raw)
    except ValueError as exc:
        raise ValueError(
            f"unknown embedder {raw!r}. Valid: local, mistral, none."
        ) from exc


def _resolve_clients(raw: str | None) -> frozenset[Client]:
    if raw is None:
        # Auto-detect: include any client whose config dir already exists
        return frozenset(loc.client for loc in detect_all() if loc.exists)
    out: set[Client] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token not in _VALID_CLIENTS:
            raise ValueError(
                f"unknown client {token!r}. Valid: "
                + ", ".join(sorted(_VALID_CLIENTS))
            )
        out.add(_VALID_CLIENTS[token])
    return frozenset(out)
