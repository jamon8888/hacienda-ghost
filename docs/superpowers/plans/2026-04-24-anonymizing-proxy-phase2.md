# Anonymizing Proxy Phase 2 — Strict Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add strict mode to the piighost anonymizing proxy — port 443 binding, `/etc/hosts` redirect of `api.anthropic.com -> 127.0.0.1`, and background service registration — so that Claude Desktop and Cowork are covered without any per-app configuration.

**Architecture:** A new `src/piighost/install/service/` package dispatches to platform-specific service managers (launchd / systemd / schtasks). A new `src/piighost/install/hosts_file.py` edits the system hosts file with a sentinel block and atomic backup. `piighost install --mode=strict` orchestrates both, generating a leaf cert for `api.anthropic.com` instead of `localhost`. A new `piighost uninstall` command reverses everything in strict reverse order.

**Tech Stack:** Python 3.12, stdlib only (subprocess, pathlib, os, xml.etree, shutil), typer, existing `cryptography` + `uvicorn` + `starlette` from Phase 1 `proxy` extras group. No new dependencies.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| **Create** | `src/piighost/install/hosts_file.py` | Sentinel-block hosts editor with atomic write + sudo fallback |
| **Create** | `src/piighost/install/service/__init__.py` | `ServiceSpec` dataclass + platform-dispatching `install_service`, `uninstall_service`, `service_running` |
| **Create** | `src/piighost/install/service/darwin.py` | macOS LaunchDaemon at `/Library/LaunchDaemons/com.piighost.proxy.plist` |
| **Create** | `src/piighost/install/service/linux.py` | systemd user-level unit with `AmbientCapabilities=CAP_NET_BIND_SERVICE` |
| **Create** | `src/piighost/install/service/windows.py` | `netsh http add urlacl` + `schtasks /create /sc ONLOGON` |
| **Create** | `src/piighost/cli/commands/uninstall.py` | `piighost uninstall [--purge-ca] [--purge-vault]` |
| **Modify** | `src/piighost/install/__init__.py` | Replace `--mode=strict` stub with `_run_strict_mode()` |
| **Modify** | `src/piighost/cli/commands/proxy.py` | Add `proxy logs` subcommand |
| **Modify** | `src/piighost/cli/commands/doctor.py` | Add informational hosts-file check |
| **Modify** | `src/piighost/cli/main.py` | Register `uninstall` command |
| **Create** | `tests/install/test_hosts_file.py` | Unit tests for sentinel block logic |
| **Create** | `tests/install/test_service_dispatch.py` | Tests for `ServiceSpec` and platform dispatch |
| **Create** | `tests/install/test_service_darwin.py` | macOS plist generation (mocked subprocess) |
| **Create** | `tests/install/test_service_linux.py` | systemd unit generation (mocked subprocess) |
| **Create** | `tests/install/test_service_windows.py` | schtasks/netsh args (mocked subprocess) |
| **Create** | `tests/install/test_install_strict_mode.py` | Strict mode orchestration with all side-effects mocked |
| **Create** | `tests/cli/test_uninstall_cmd.py` | CLI-level uninstall tests |
| **Modify** | `tests/cli/test_proxy_cmd.py` | Tests for `proxy logs` |
| **Modify** | `tests/cli/test_doctor.py` | Tests for hosts-file informational check |
| **Modify** | `.github/workflows/proxy-install-ci.yml` | Add strict-mode smoke, `PIIGHOST_SKIP_SERVICE=1` |

---

## Task 1: hosts_file.py — Sentinel-Block Hosts File Editor

**Files:**
- Create: `src/piighost/install/hosts_file.py`
- Create: `tests/install/test_hosts_file.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_hosts_file.py
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from piighost.install.hosts_file import add_redirect, has_redirect, remove_redirect


def _make_hosts(tmp_path: Path, content: str = "") -> Path:
    p = tmp_path / "hosts"
    p.write_text(content, encoding="utf-8")
    return p


def test_add_redirect_inserts_sentinel_block(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path, "127.0.0.1 localhost\n")
    add_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert "# BEGIN piighost" in text
    assert "127.0.0.1 api.anthropic.com" in text
    assert "# END piighost" in text


def test_has_redirect_true_after_add(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is True


def test_has_redirect_false_on_empty(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is False


def test_remove_redirect_strips_sentinel(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path, "127.0.0.1 localhost\n")
    add_redirect("api.anthropic.com", hosts_path=hosts)
    remove_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert "BEGIN piighost" not in text
    assert "api.anthropic.com" not in text
    assert "127.0.0.1 localhost" in text


def test_add_redirect_is_idempotent(tmp_path: Path) -> None:
    hosts = _make_hosts(tmp_path)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    text = hosts.read_text(encoding="utf-8")
    assert text.count("# BEGIN piighost") == 1


def test_add_redirect_creates_backup(tmp_path: Path) -> None:
    original = "127.0.0.1 localhost\n"
    hosts = _make_hosts(tmp_path, original)
    add_redirect("api.anthropic.com", hosts_path=hosts)
    bak = hosts.with_suffix(".piighost.bak")
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == original


def test_remove_redirect_noop_on_missing_file(tmp_path: Path) -> None:
    hosts = tmp_path / "no_such_hosts"
    remove_redirect("api.anthropic.com", hosts_path=hosts)  # must not raise


def test_has_redirect_false_on_missing_file(tmp_path: Path) -> None:
    hosts = tmp_path / "no_such_hosts"
    assert has_redirect("api.anthropic.com", hosts_path=hosts) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_hosts_file.py -v
```

Expected: `ModuleNotFoundError: No module named 'piighost.install.hosts_file'`

- [ ] **Step 3: Implement hosts_file.py**

```python
# src/piighost/install/hosts_file.py
"""Sentinel-block hosts file editor for strict-mode proxy install."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_SENTINEL_BEGIN = "# BEGIN piighost"
_SENTINEL_END = "# END piighost"


def _default_hosts_path() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


def _resolve(hosts_path: Path | None) -> Path:
    return hosts_path if hosts_path is not None else _default_hosts_path()


def has_redirect(host: str, *, hosts_path: Path | None = None) -> bool:
    path = _resolve(hosts_path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return _SENTINEL_BEGIN in text and f" {host}" in text


def add_redirect(
    host: str,
    ip: str = "127.0.0.1",
    *,
    hosts_path: Path | None = None,
) -> None:
    path = _resolve(hosts_path)
    original = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    # Remove any existing sentinel block to guarantee idempotency.
    cleaned = _remove_sentinel(original)
    block = f"\n{_SENTINEL_BEGIN}\n{ip} {host}\n{_SENTINEL_END}\n"
    new_content = cleaned.rstrip("\n") + "\n" + block

    bak = path.with_suffix(".piighost.bak")
    _write_file(bak, original)
    _write_file(path, new_content)


def remove_redirect(host: str, *, hosts_path: Path | None = None) -> None:
    path = _resolve(hosts_path)
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8", errors="replace")
    new_content = _remove_sentinel(original)
    if new_content != original:
        _write_file(path, new_content)


def _remove_sentinel(text: str) -> str:
    out: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        if stripped == _SENTINEL_BEGIN:
            inside = True
            continue
        if stripped == _SENTINEL_END:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _write_file(path: Path, content: str) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except PermissionError:
        if sys.platform == "win32":
            raise
        subprocess.run(
            ["sudo", "tee", str(path)],
            input=content.encode(),
            check=True,
            stdout=subprocess.DEVNULL,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/install/test_hosts_file.py -v
```

Expected: 8 passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/hosts_file.py tests/install/test_hosts_file.py
git commit -m "feat: add sentinel-block hosts file editor for strict mode"
```

---

## Task 2: service/__init__.py — ServiceSpec + Platform Dispatcher

**Files:**
- Create: `src/piighost/install/service/__init__.py`
- Create: `tests/install/test_service_dispatch.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_service_dispatch.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from piighost.install.service import ServiceSpec, install_service, service_running, uninstall_service


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="com.piighost.proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_service_spec_fields(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert spec.port == 443
    assert spec.user == "alice"
    assert spec.name == "com.piighost.proxy"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")
def test_dispatch_darwin(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.darwin", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()


@pytest.mark.skipif(sys.platform in ("darwin", "win32"), reason="Linux only")
def test_dispatch_linux(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.linux", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_dispatch_windows(tmp_path: Path) -> None:
    mock = MagicMock()
    with patch("piighost.install.service.windows", mock):
        install_service(_spec(tmp_path))
        mock.install.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_service_dispatch.py -v
```

Expected: `ModuleNotFoundError: No module named 'piighost.install.service'`

- [ ] **Step 3: Implement service/__init__.py**

```python
# src/piighost/install/service/__init__.py
"""Platform-agnostic background service management for the piighost proxy."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ServiceSpec:
    name: str
    bin_path: str
    vault_dir: Path
    cert_path: Path
    key_path: Path
    port: int = 443
    user: str = field(
        default_factory=lambda: os.environ.get("USER") or os.environ.get("USERNAME") or ""
    )


def install_service(spec: ServiceSpec) -> None:
    _dispatch().install(spec)


def uninstall_service(spec: ServiceSpec) -> None:
    _dispatch().uninstall(spec)


def service_running(spec: ServiceSpec) -> bool:
    return _dispatch().running(spec)


def _dispatch():
    if sys.platform == "darwin":
        from piighost.install.service import darwin
        return darwin
    if sys.platform == "win32":
        from piighost.install.service import windows
        return windows
    from piighost.install.service import linux
    return linux
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/install/test_service_dispatch.py -v
```

Expected: 1 passed (platform-specific tests skipped on non-matching OS).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/service/__init__.py tests/install/test_service_dispatch.py
git commit -m "feat: add ServiceSpec dataclass and platform-dispatch service manager"
```

---

## Task 3: service/darwin.py — macOS LaunchDaemon

**Files:**
- Create: `src/piighost/install/service/darwin.py`
- Create: `tests/install/test_service_darwin.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_service_darwin.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")

from piighost.install.service import ServiceSpec
from piighost.install.service import darwin as darwin_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="com.piighost.proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_plist_content_contains_label(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = darwin_mod._plist_content(spec)
    assert "com.piighost.proxy" in content
    assert "/usr/local/bin/piighost" in content
    assert "443" in content
    assert str(tmp_path / ".piighost") in content
    assert str(tmp_path / "leaf.pem") in content


def test_plist_content_is_valid_xml(tmp_path: Path) -> None:
    from xml.etree import ElementTree as ET
    spec = _spec(tmp_path)
    content = darwin_mod._plist_content(spec)
    ET.fromstring(content)  # must not raise


def test_install_calls_sudo(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        darwin_mod.install(spec)
        argv_list = [c.args[0] for c in mock_run.call_args_list]
        assert any("launchctl" in str(a) for a in argv_list)
        assert any("sudo" in str(a) for a in argv_list)


def test_uninstall_calls_unload(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run, \
         patch("piighost.install.service.darwin._PLIST_PATH") as mock_path:
        mock_path.exists.return_value = True
        mock_run.return_value = MagicMock(returncode=0)
        darwin_mod.uninstall(spec)
        argv_list = [c.args[0] for c in mock_run.call_args_list]
        assert any("unload" in str(a) for a in argv_list)


def test_running_returns_true_when_launchctl_exits_0(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert darwin_mod.running(spec) is True


def test_running_returns_false_when_launchctl_exits_nonzero(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.darwin.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1)
        assert darwin_mod.running(spec) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_service_darwin.py -v
```

Expected: All skipped on Linux/Windows; `ModuleNotFoundError` on macOS.

- [ ] **Step 3: Implement service/darwin.py**

```python
# src/piighost/install/service/darwin.py
"""macOS LaunchDaemon install/uninstall for piighost proxy (port 443).

Runs as root so it can bind port 443 on loopback. The vault directory is
passed explicitly so the daemon can locate the vault without relying on HOME.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from piighost.install.service import ServiceSpec

_PLIST_PATH = Path("/Library/LaunchDaemons/com.piighost.proxy.plist")
_LABEL = "com.piighost.proxy"


def _plist_content(spec: ServiceSpec) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{spec.bin_path}</string>
        <string>proxy</string>
        <string>run</string>
        <string>--port</string>
        <string>{spec.port}</string>
        <string>--vault</string>
        <string>{spec.vault_dir}</string>
        <string>--cert</string>
        <string>{spec.cert_path}</string>
        <string>--key</string>
        <string>{spec.key_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{spec.vault_dir}/proxy/proxy.log</string>
    <key>StandardErrorPath</key>
    <string>{spec.vault_dir}/proxy/proxy.err</string>
</dict>
</plist>
"""


def install(spec: ServiceSpec) -> None:
    content = _plist_content(spec)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".plist", delete=False) as fh:
        fh.write(content)
        tmp = fh.name
    subprocess.run(["sudo", "cp", tmp, str(_PLIST_PATH)], check=True)
    subprocess.run(["sudo", "chmod", "644", str(_PLIST_PATH)], check=True)
    subprocess.run(["sudo", "launchctl", "load", "-w", str(_PLIST_PATH)], check=True)


def uninstall(spec: ServiceSpec) -> None:
    if _PLIST_PATH.exists():
        subprocess.run(
            ["sudo", "launchctl", "unload", str(_PLIST_PATH)],
            check=False,
        )
        subprocess.run(["sudo", "rm", "-f", str(_PLIST_PATH)], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["launchctl", "list", _LABEL],
        capture_output=True,
    )
    return result.returncode == 0
```

- [ ] **Step 4: Run tests to verify they pass (macOS) or skip (other OS)**

```
python -m pytest tests/install/test_service_darwin.py -v
```

Expected: 6 passed on macOS; 6 skipped on Linux/Windows.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/service/darwin.py tests/install/test_service_darwin.py
git commit -m "feat: add macOS LaunchDaemon service installer"
```

---

## Task 4: service/linux.py — systemd User Service

**Files:**
- Create: `src/piighost/install/service/linux.py`
- Create: `tests/install/test_service_linux.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_service_linux.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux only")

from piighost.install.service import ServiceSpec
from piighost.install.service import linux as linux_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="piighost-proxy",
        bin_path="/usr/local/bin/piighost",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_unit_content_has_ambient_capabilities(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = linux_mod._unit_content(spec)
    assert "AmbientCapabilities=CAP_NET_BIND_SERVICE" in content


def test_unit_content_has_bin_and_port(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    content = linux_mod._unit_content(spec)
    assert "/usr/local/bin/piighost" in content
    assert "proxy run" in content
    assert "--port 443" in content


def test_install_writes_unit_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.install(spec)
    unit_dir = tmp_path / "config" / "systemd" / "user"
    assert (unit_dir / "piighost-proxy.service").exists()


def test_install_calls_systemctl_enable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.install(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("enable" in a for a in argv_list)


def test_uninstall_calls_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    unit_dir = tmp_path / "config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "piighost-proxy.service").write_text("", encoding="utf-8")
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        linux_mod.uninstall(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("disable" in a for a in argv_list)
    assert not (unit_dir / "piighost-proxy.service").exists()


def test_running_returns_true_on_exit_0(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        assert linux_mod.running(spec) is True


def test_running_returns_false_on_nonzero(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.linux.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=3)
        assert linux_mod.running(spec) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_service_linux.py -v
```

Expected: All skipped on macOS/Windows; `ModuleNotFoundError` on Linux.

- [ ] **Step 3: Implement service/linux.py**

```python
# src/piighost/install/service/linux.py
"""Linux systemd user-level service install/uninstall for piighost proxy.

Uses AmbientCapabilities=CAP_NET_BIND_SERVICE so the process can bind port 443
without running as root. The unit lives in ~/.config/systemd/user/.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from piighost.install.service import ServiceSpec

_SERVICE_NAME = "piighost-proxy.service"


def _unit_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "systemd" / "user"


def _unit_content(spec: ServiceSpec) -> str:
    return (
        "[Unit]\n"
        "Description=piighost anonymizing HTTPS proxy\n"
        "After=network.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={spec.bin_path} proxy run"
        f" --port {spec.port}"
        f" --vault {spec.vault_dir}"
        f" --cert {spec.cert_path}"
        f" --key {spec.key_path}\n"
        "Restart=on-failure\n"
        "AmbientCapabilities=CAP_NET_BIND_SERVICE\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def install(spec: ServiceSpec) -> None:
    unit_dir = _unit_dir()
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / _SERVICE_NAME).write_text(_unit_content(spec), encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", _SERVICE_NAME], check=True)


def uninstall(spec: ServiceSpec) -> None:
    subprocess.run(
        ["systemctl", "--user", "disable", "--now", _SERVICE_NAME],
        check=False,
    )
    unit_path = _unit_dir() / _SERVICE_NAME
    if unit_path.exists():
        unit_path.unlink()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["systemctl", "--user", "is-active", _SERVICE_NAME],
        capture_output=True,
    )
    return result.returncode == 0
```

- [ ] **Step 4: Run tests to verify they pass (Linux) or skip (other OS)**

```
python -m pytest tests/install/test_service_linux.py -v
```

Expected: 6 passed on Linux; 6 skipped on macOS/Windows.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/service/linux.py tests/install/test_service_linux.py
git commit -m "feat: add Linux systemd user service with CAP_NET_BIND_SERVICE"
```

---

## Task 5: service/windows.py — Windows Scheduled Task + netsh

**Files:**
- Create: `src/piighost/install/service/windows.py`
- Create: `tests/install/test_service_windows.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_service_windows.py
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")

from piighost.install.service import ServiceSpec
from piighost.install.service import windows as windows_mod


def _spec(tmp_path: Path) -> ServiceSpec:
    return ServiceSpec(
        name="piighost-proxy",
        bin_path=r"C:\tools\piighost.exe",
        vault_dir=tmp_path / ".piighost",
        cert_path=tmp_path / "leaf.pem",
        key_path=tmp_path / "leaf.key",
        port=443,
        user="alice",
    )


def test_urlacl_url(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    assert windows_mod._urlacl_url(spec) == "https://127.0.0.1:443/"


def test_install_calls_netsh_and_schtasks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("USERNAME", "alice")
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.install(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("netsh" in a for a in argv_list)
        assert any("schtasks" in a and "/create" in a for a in argv_list)


def test_install_schtasks_uses_onlogon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec = _spec(tmp_path)
    monkeypatch.setenv("USERNAME", "alice")
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.install(spec)
        schtasks_call = next(
            c for c in mock_run.call_args_list if "schtasks" in str(c.args[0])
        )
        args_flat = " ".join(str(x) for x in schtasks_call.args[0])
        assert "ONLOGON" in args_flat
        assert "HIGHEST" in args_flat


def test_uninstall_deletes_task_and_urlacl(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        windows_mod.uninstall(spec)
        argv_list = [" ".join(str(x) for x in c.args[0]) for c in mock_run.call_args_list]
        assert any("schtasks" in a and "/delete" in a for a in argv_list)
        assert any("netsh" in a and "delete" in a for a in argv_list)


def test_running_true_when_query_shows_running(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=b"Status: Running")
        assert windows_mod.running(spec) is True


def test_running_false_when_task_missing(tmp_path: Path) -> None:
    spec = _spec(tmp_path)
    with patch("piighost.install.service.windows.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout=b"")
        assert windows_mod.running(spec) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_service_windows.py -v
```

Expected: All skipped on macOS/Linux; `ModuleNotFoundError` on Windows.

- [ ] **Step 3: Implement service/windows.py**

```python
# src/piighost/install/service/windows.py
"""Windows scheduled task + netsh urlacl install for piighost proxy."""
from __future__ import annotations

import os
import subprocess

from piighost.install.service import ServiceSpec

_TASK_NAME = "piighost-proxy"


def _urlacl_url(spec: ServiceSpec) -> str:
    return f"https://127.0.0.1:{spec.port}/"


def install(spec: ServiceSpec) -> None:
    url = _urlacl_url(spec)
    username = os.environ.get("USERNAME") or spec.user
    subprocess.run(
        ["netsh", "http", "add", "urlacl", f"url={url}", f"user={username}"],
        check=True,
    )
    # schtasks requires a single /tr string, not a list.
    tr_cmd = (
        f'"{spec.bin_path}" proxy run'
        f" --port {spec.port}"
        f' --vault "{spec.vault_dir}"'
        f' --cert "{spec.cert_path}"'
        f' --key "{spec.key_path}"'
    )
    subprocess.run(
        [
            "schtasks", "/create",
            "/tn", _TASK_NAME,
            "/sc", "ONLOGON",
            "/rl", "HIGHEST",
            "/tr", tr_cmd,
            "/f",
        ],
        check=True,
    )


def uninstall(spec: ServiceSpec) -> None:
    subprocess.run(["schtasks", "/delete", "/tn", _TASK_NAME, "/f"], check=False)
    url = _urlacl_url(spec)
    subprocess.run(["netsh", "http", "delete", "urlacl", f"url={url}"], check=False)


def running(spec: ServiceSpec) -> bool:
    result = subprocess.run(
        ["schtasks", "/query", "/tn", _TASK_NAME, "/fo", "LIST"],
        capture_output=True,
    )
    if result.returncode != 0:
        return False
    return b"Running" in result.stdout
```

- [ ] **Step 4: Run tests to verify they pass (Windows) or skip (other OS)**

```
python -m pytest tests/install/test_service_windows.py -v
```

Expected: 6 passed on Windows; 6 skipped on macOS/Linux.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/service/windows.py tests/install/test_service_windows.py
git commit -m "feat: add Windows schtasks+netsh service installer"
```

---

## Task 6: _run_strict_mode() — Strict Install Orchestration

**Files:**
- Modify: `src/piighost/install/__init__.py`
- Create: `tests/install/test_install_strict_mode.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/install/test_install_strict_mode.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_strict_mode_generates_anthropic_leaf_cert(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "add_redirect", lambda *a, **kw: None)

    r = runner.invoke(app, ["install", "--mode=strict"])
    assert r.exit_code == 0, f"stdout: {r.stdout}"

    leaf = tmp_path / ".piighost" / "proxy" / "leaf.pem"
    assert leaf.exists(), f"leaf.pem not found at {leaf}"

    from cryptography import x509
    cert = x509.load_pem_x509_certificate(leaf.read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    dns_names = san.value.get_values_for_type(x509.DNSName)
    assert "api.anthropic.com" in dns_names


def test_strict_mode_calls_add_redirect(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")

    redirected: list[str] = []

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "add_redirect", lambda host, **kw: redirected.append(host))

    r = runner.invoke(app, ["install", "--mode=strict"])
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert "api.anthropic.com" in redirected


def test_strict_mode_calls_install_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "add_redirect", lambda *a, **kw: None)

    installed: list = []
    import piighost.install.service as svc
    monkeypatch.setattr(svc, "install_service", lambda spec: installed.append(spec))

    r = runner.invoke(app, ["install", "--mode=strict"])
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert len(installed) == 1
    assert installed[0].port == 443


def test_strict_mode_skip_service_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PIIGHOST_SKIP_TRUSTSTORE", "1")
    monkeypatch.setenv("PIIGHOST_SKIP_SERVICE", "1")

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "add_redirect", lambda *a, **kw: None)

    installed: list = []
    import piighost.install.service as svc
    monkeypatch.setattr(svc, "install_service", lambda spec: installed.append(spec))

    r = runner.invoke(app, ["install", "--mode=strict"])
    assert r.exit_code == 0
    assert len(installed) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/install/test_install_strict_mode.py -v
```

Expected: All fail — `--mode=strict` currently exits with code 2.

- [ ] **Step 3: Replace the strict stub and add _run_strict_mode() in install/__init__.py**

Replace lines 41–43 (the `if mode == "strict":` block) with:

```python
    if mode == "strict":
        _run_strict_mode()
        return
```

Add the following function after `_run_light_mode()`:

```python
def _run_strict_mode() -> None:
    """Phase 2 strict-mode: CA for api.anthropic.com + hosts file + background service."""
    import shutil
    import sys

    vault = Path(os.path.expanduser("~")) / ".piighost"
    proxy_dir = vault / "proxy"
    proxy_dir.mkdir(parents=True, exist_ok=True)

    step("Generating local root CA and leaf certificate for api.anthropic.com")
    root = ca_mod.generate_root(common_name="piighost local CA")
    leaf = ca_mod.generate_leaf(root, hostnames=["api.anthropic.com"])
    (proxy_dir / "ca.pem").write_bytes(root.cert_pem)
    (proxy_dir / "ca.key").write_bytes(root.key_pem)
    (proxy_dir / "leaf.pem").write_bytes(leaf.cert_pem)
    (proxy_dir / "leaf.key").write_bytes(leaf.key_pem)
    success("CA and leaf cert written to ~/.piighost/proxy/")

    step("Installing CA into OS trust store")
    if os.environ.get("PIIGHOST_SKIP_TRUSTSTORE") == "1":
        info("PIIGHOST_SKIP_TRUSTSTORE=1 -- skipping trust store installation.")
    else:
        try:
            trust_store.install_ca(proxy_dir / "ca.pem")
            success("CA installed in OS trust store.")
        except Exception as exc:
            warn(f"Trust store install failed: {exc} -- install manually.")

    step("Editing hosts file (127.0.0.1 api.anthropic.com)")
    from piighost.install import hosts_file as hf
    try:
        hf.add_redirect("api.anthropic.com")
        success("Hosts file updated.")
    except Exception as exc:
        warn(f"Hosts file edit failed: {exc}")

    step("Installing background service (port 443)")
    if os.environ.get("PIIGHOST_SKIP_SERVICE") == "1":
        info("PIIGHOST_SKIP_SERVICE=1 -- skipping service installation.")
    else:
        from piighost.install import service as svc
        bin_path = shutil.which("piighost") or f"{sys.executable} -m piighost"
        spec = svc.ServiceSpec(
            name="com.piighost.proxy",
            bin_path=bin_path,
            vault_dir=vault,
            cert_path=proxy_dir / "leaf.pem",
            key_path=proxy_dir / "leaf.key",
            port=443,
        )
        try:
            svc.install_service(spec)
            success("Background service installed and started.")
        except Exception as exc:
            warn(f"Service install failed: {exc}")

    success("\nStrict mode installed. Verify with: piighost doctor")
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/install/test_install_strict_mode.py -v
```

Expected: 4 passed, 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/install/__init__.py tests/install/test_install_strict_mode.py
git commit -m "feat: implement --mode=strict install orchestration"
```

---

## Task 7: proxy logs — Tail Audit NDJSON

**Files:**
- Modify: `src/piighost/cli/commands/proxy.py`
- Modify: `tests/cli/test_proxy_cmd.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/cli/test_proxy_cmd.py`:

```python
# Append to tests/cli/test_proxy_cmd.py
import datetime
from pathlib import Path


def test_proxy_logs_shows_last_n_lines(tmp_path: Path) -> None:
    now = datetime.datetime.now()
    month_dir = tmp_path / ".piighost" / "audit" / f"{now.year}-{now.month:02d}"
    month_dir.mkdir(parents=True)
    log_file = month_dir / "sessions.ndjson"
    entries = [f'{{"ts": "2026-04-24T{i:02d}:00:00Z", "status": "ok"}}' for i in range(5)]
    log_file.write_text("\n".join(entries), encoding="utf-8")

    r = runner.invoke(
        app,
        ["proxy", "logs", "--vault", str(tmp_path / ".piighost"), "--tail", "3"],
    )
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert entries[2] in r.stdout
    assert entries[3] in r.stdout
    assert entries[4] in r.stdout
    assert entries[0] not in r.stdout
    assert entries[1] not in r.stdout


def test_proxy_logs_exits_nonzero_when_no_log(tmp_path: Path) -> None:
    r = runner.invoke(app, ["proxy", "logs", "--vault", str(tmp_path / ".piighost")])
    assert r.exit_code != 0


def test_proxy_help_shows_logs() -> None:
    r = runner.invoke(app, ["proxy", "--help"])
    assert "logs" in r.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/cli/test_proxy_cmd.py -v
```

Expected: 3 new tests fail; `test_proxy_help_shows_subcommands` passes.

- [ ] **Step 3: Add logs command to proxy.py**

Append to `src/piighost/cli/commands/proxy.py`:

```python
@proxy_app.command("logs")
def logs(
    vault: Annotated[Path, typer.Option(help="Vault dir")] = Path.home() / ".piighost",
    tail: Annotated[int, typer.Option("--tail", "-n", help="Last N lines to show")] = 50,
) -> None:
    """Tail the proxy audit log (current month)."""
    import datetime

    now = datetime.datetime.now()
    log_file = vault / "audit" / f"{now.year}-{now.month:02d}" / "sessions.ndjson"
    if not log_file.exists():
        typer.echo(f"No audit log at {log_file}")
        raise typer.Exit(code=1)
    lines = log_file.read_text(encoding="utf-8").splitlines()
    for line in lines[-tail:]:
        typer.echo(line)
```

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/cli/test_proxy_cmd.py -v
```

Expected: 4 passed (3 new + 1 existing), 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/cli/commands/proxy.py tests/cli/test_proxy_cmd.py
git commit -m "feat: add proxy logs subcommand for tailing audit NDJSON"
```

---

## Task 8: doctor — Hosts-File Informational Check

**Files:**
- Modify: `src/piighost/cli/commands/doctor.py`
- Modify: `tests/cli/test_doctor.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/cli/test_doctor.py`:

```python
# Append to tests/cli/test_doctor.py
import json
from pathlib import Path


def test_doctor_reports_hosts_redirect_present(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda host, **kw: True)

    proxy_dir = tmp_path / ".piighost" / "proxy"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "ca.pem").write_bytes(b"fake-ca")

    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://localhost:8443"}}),
        encoding="utf-8",
    )
    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    write_handshake(tmp_path / ".piighost", ProxyHandshake(pid=1, port=8443, token="tok"))

    r = runner.invoke(app, ["doctor"])
    assert "api.anthropic.com" in r.stdout
    assert "127.0.0.1" in r.stdout


def test_doctor_hosts_no_redirect_is_info_not_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda host, **kw: False)

    r = runner.invoke(app, ["doctor"])
    assert "light mode" in r.stdout or "not installed" in r.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/cli/test_doctor.py -v
```

Expected: 2 new tests fail.

- [ ] **Step 3: Add hosts-file check to doctor.py**

In `src/piighost/cli/commands/doctor.py`, after the CA cert check block (after the `if not ca.exists():` block), add:

```python
    typer.echo("Checking hosts file redirect (strict mode)...")
    from piighost.install.hosts_file import has_redirect
    if has_redirect("api.anthropic.com"):
        typer.echo("  ok: api.anthropic.com -> 127.0.0.1")
    else:
        typer.echo("  info: no hosts-file redirect (light mode or strict not installed)")
```

This block does NOT append to `failures` — it is purely informational.

- [ ] **Step 4: Run tests to verify they pass**

```
python -m pytest tests/cli/test_doctor.py -v
```

Expected: 3 passed (2 new + 1 existing), 0 failed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/cli/commands/doctor.py tests/cli/test_doctor.py
git commit -m "feat: add informational hosts-file check to piighost doctor"
```

---

## Task 9: uninstall Command

**Files:**
- Create: `src/piighost/cli/commands/uninstall.py`
- Modify: `src/piighost/cli/main.py`
- Create: `tests/cli/test_uninstall_cmd.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/cli/test_uninstall_cmd.py
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def _setup_installed(tmp_path: Path) -> None:
    proxy_dir = tmp_path / ".piighost" / "proxy"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "ca.pem").write_bytes(b"fake-ca")
    (proxy_dir / "leaf.pem").write_bytes(b"fake-leaf")
    (proxy_dir / "leaf.key").write_bytes(b"fake-key")
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://localhost:8443"}}),
        encoding="utf-8",
    )


def test_uninstall_removes_anthropic_base_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _setup_installed(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "remove_redirect", lambda *a, **kw: None)

    import piighost.install.service as svc
    monkeypatch.setattr(svc, "uninstall_service", lambda spec: None)

    r = runner.invoke(app, ["uninstall", "--vault", str(tmp_path / ".piighost")])
    assert r.exit_code == 0, f"stdout: {r.stdout}"

    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert "ANTHROPIC_BASE_URL" not in data.get("env", {})


def test_uninstall_calls_remove_redirect(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _setup_installed(tmp_path)

    removed: list[str] = []
    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "remove_redirect", lambda host, **kw: removed.append(host))

    import piighost.install.service as svc
    monkeypatch.setattr(svc, "uninstall_service", lambda spec: None)

    r = runner.invoke(app, ["uninstall", "--vault", str(tmp_path / ".piighost")])
    assert r.exit_code == 0
    assert "api.anthropic.com" in removed


def test_uninstall_calls_uninstall_service(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _setup_installed(tmp_path)

    uninstalled: list = []
    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "remove_redirect", lambda *a, **kw: None)

    import piighost.install.service as svc
    monkeypatch.setattr(svc, "uninstall_service", lambda spec: uninstalled.append(spec))

    r = runner.invoke(app, ["uninstall", "--vault", str(tmp_path / ".piighost")])
    assert r.exit_code == 0
    assert len(uninstalled) == 1


def test_uninstall_purge_vault_deletes_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _setup_installed(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "remove_redirect", lambda *a, **kw: None)

    import piighost.install.service as svc
    monkeypatch.setattr(svc, "uninstall_service", lambda spec: None)

    vault = tmp_path / ".piighost"
    r = runner.invoke(app, ["uninstall", "--purge-vault", "--vault", str(vault)])
    assert r.exit_code == 0
    assert not vault.exists()


def test_uninstall_purge_ca_calls_uninstall_ca(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    _setup_installed(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "remove_redirect", lambda *a, **kw: None)

    import piighost.install.service as svc
    monkeypatch.setattr(svc, "uninstall_service", lambda spec: None)

    removed_cas: list = []
    import piighost.install.trust_store as ts
    monkeypatch.setattr(ts, "uninstall_ca", lambda path: removed_cas.append(path))

    r = runner.invoke(
        app, ["uninstall", "--purge-ca", "--vault", str(tmp_path / ".piighost")]
    )
    assert r.exit_code == 0
    assert len(removed_cas) == 1


def test_uninstall_is_shown_in_help() -> None:
    r = runner.invoke(app, ["--help"])
    assert "uninstall" in r.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

```
python -m pytest tests/cli/test_uninstall_cmd.py -v
```

Expected: All fail — `uninstall` not registered.

- [ ] **Step 3: Create uninstall.py**

```python
# src/piighost/cli/commands/uninstall.py
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
```

- [ ] **Step 4: Register in main.py**

In `src/piighost/cli/main.py`, add the import:

```python
from piighost.cli.commands import uninstall as uninstall_cmd
```

And after `app.command("install")(install_run)`, add:

```python
app.command("uninstall")(uninstall_cmd.run)
```

- [ ] **Step 5: Run tests to verify they pass**

```
python -m pytest tests/cli/test_uninstall_cmd.py -v
```

Expected: 6 passed, 0 failed.

- [ ] **Step 6: Commit**

```bash
git add src/piighost/cli/commands/uninstall.py src/piighost/cli/main.py tests/cli/test_uninstall_cmd.py
git commit -m "feat: add piighost uninstall command (strict reverse order)"
```

---

## Task 10: CI Update and Full Regression Check

**Files:**
- Modify: `.github/workflows/proxy-install-ci.yml`

- [ ] **Step 1: Run full install + CLI test suite locally**

```
python -m pytest tests/install tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py tests/cli/test_uninstall_cmd.py -v
```

Expected: All new tests pass. Platform-gated tests (darwin/linux/windows) skip on non-matching OS.

- [ ] **Step 2: Run Phase 1 proxy tests to confirm no regressions**

```
python -m pytest tests/proxy -v
```

Expected: All proxy tests pass (0 failures).

- [ ] **Step 3: Update the CI workflow**

Replace the entire content of `.github/workflows/proxy-install-ci.yml` with:

```yaml
name: Phase 1 + 2 install smoke

on:
  push:
    branches: [main, master]
  pull_request:

jobs:
  install-smoke:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          python-version: "3.12"
      - run: uv sync --all-extras
      - name: Run proxy tests
        run: uv run pytest tests/proxy -v
      - name: Run install tests (trust-store and service mocked)
        env:
          PIIGHOST_SKIP_TRUSTSTORE: "1"
          PIIGHOST_SKIP_SERVICE: "1"
        run: uv run pytest tests/install -v
      - name: Run CLI tests (proxy, doctor, uninstall)
        run: uv run pytest tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py tests/cli/test_uninstall_cmd.py -v
```

- [ ] **Step 4: Simulate CI locally with env vars set**

On Linux/macOS:
```
PIIGHOST_SKIP_TRUSTSTORE=1 PIIGHOST_SKIP_SERVICE=1 python -m pytest tests/install tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py tests/cli/test_uninstall_cmd.py -v
```

On Windows (PowerShell):
```
$env:PIIGHOST_SKIP_TRUSTSTORE="1"; $env:PIIGHOST_SKIP_SERVICE="1"; python -m pytest tests/install tests/cli/test_proxy_cmd.py tests/cli/test_doctor.py tests/cli/test_uninstall_cmd.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/proxy-install-ci.yml
git commit -m "ci: extend install smoke to cover Phase 2 strict-mode tests"
```

---

## Self-Review

**Spec coverage check (§5.2 + §5.3 + §5.4):**

| Spec requirement | Covered in |
|---|---|
| Leaf cert for `api.anthropic.com` | Task 6 `_run_strict_mode()` |
| CA trust store install (reused from Phase 1) | Task 6 |
| macOS LaunchDaemon (root-level, binds 443) | Task 3 `darwin.py` |
| Linux systemd user unit + `AmbientCapabilities=CAP_NET_BIND_SERVICE` | Task 4 `linux.py` |
| Windows `netsh http add urlacl` + `schtasks /create /sc ONLOGON /rl HIGHEST` | Task 5 `windows.py` |
| Hosts file sentinel block `# BEGIN piighost` / `# END piighost` + `.piighost.bak` | Task 1 `hosts_file.py` |
| `127.0.0.1 api.anthropic.com` redirect | Task 6 calling `hf.add_redirect("api.anthropic.com")` |
| `PIIGHOST_SKIP_SERVICE=1` for CI | Tasks 6 + 10 |
| `piighost proxy logs` (§5.3) | Task 7 |
| `piighost doctor` hosts-file informational check | Task 8 |
| `piighost uninstall [--purge-ca] [--purge-vault]` (§5.4) | Task 9 |
| Reverse-order: service → hosts → settings → CA → vault | Task 9 |
| CI matrix (ubuntu, macos, windows) | Task 10 |

**Placeholder scan:** No TBD, TODO, or "implement later" found in any step.

**Type consistency:**
- `ServiceSpec.bin_path` (str) used consistently in `darwin.py`, `linux.py`, `windows.py`, `install/__init__.py`, `uninstall.py`.
- `hosts_file.add_redirect(host, *, hosts_path)` and `remove_redirect(host, *, hosts_path)` called correctly in all consumers.
- `trust_store.uninstall_ca(path: Path)` matches existing Phase 1 signature in `trust_store/__init__.py`.
- `svc.ServiceSpec(...)` constructed identically in `_run_strict_mode()` and `uninstall.run()`.
