"""Install / uninstall a local root CA into the OS trust store.

Dispatches to platform-specific modules. See spec §5.1 step 2 and §5.4 step 6.
"""
from __future__ import annotations

import sys
from pathlib import Path


def install_ca(ca_path: Path) -> None:
    if sys.platform == "darwin":
        from piighost.install.trust_store import darwin
        darwin.install(ca_path)
    elif sys.platform == "win32":
        from piighost.install.trust_store import windows
        windows.install(ca_path)
    else:
        from piighost.install.trust_store import linux
        linux.install(ca_path)


def uninstall_ca(ca_path: Path) -> None:
    if sys.platform == "darwin":
        from piighost.install.trust_store import darwin
        darwin.uninstall(ca_path)
    elif sys.platform == "win32":
        from piighost.install.trust_store import windows
        windows.uninstall(ca_path)
    else:
        from piighost.install.trust_store import linux
        linux.uninstall(ca_path)
