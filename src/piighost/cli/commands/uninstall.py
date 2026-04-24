"""`piighost uninstall` -- reverses install in strict reverse order."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

import typer

from piighost.install.ui import step, success, warn


def run(
    purge_ca: Annotated[
        bool, typer.Option("--purge-ca", help="Remove root CA from OS trust store")
    ] = False,
    purge_vault: Annotated[
        bool, typer.Option("--purge-vault", help="Delete the entire vault directory")
    ] = False,
    vault: Annotated[
        Path, typer.Option(help="Vault directory")
    ] = Path(os.path.expanduser("~")) / ".piighost",
) -> None:
    """Uninstall piighost proxy. Reverses install in strict reverse order."""
    proxy_dir = vault / "proxy"

    step("Stopping background service")
    try:
        from piighost.install import service as svc
        spec = svc.ServiceSpec(
            name="com.piighost.proxy",
            bin_path=shutil.which("piighost") or "piighost",
            vault_dir=vault,
            cert_path=proxy_dir / "leaf.pem",
            key_path=proxy_dir / "leaf.key",
        )
        svc.uninstall_service(spec)
        success("Service stopped and deregistered.")
    except Exception as exc:
        warn(f"Service uninstall failed (continuing): {exc}")

    step("Reverting hosts file")
    try:
        from piighost.install.hosts_file import remove_redirect
        remove_redirect("api.anthropic.com")
        success("Hosts file reverted.")
    except Exception as exc:
        warn(f"Hosts file revert failed (continuing): {exc}")

    step("Removing ANTHROPIC_BASE_URL from Claude Code settings")
    try:
        from piighost.install.host_config import default_settings_path, remove_claude_code_base_url
        remove_claude_code_base_url(default_settings_path())
        success("ANTHROPIC_BASE_URL removed.")
    except Exception as exc:
        warn(f"Claude Code settings revert failed (continuing): {exc}")

    if purge_ca:
        step("Removing root CA from OS trust store")
        try:
            from piighost.install import trust_store
            trust_store.uninstall_ca(proxy_dir / "ca.pem")
            success("CA removed from trust store.")
        except Exception as exc:
            warn(f"CA removal failed (continuing): {exc}")

    if purge_vault:
        step("Deleting vault directory")
        shutil.rmtree(str(vault), ignore_errors=True)
        success(f"Vault deleted: {vault}")

    success("\nUninstall complete.")
