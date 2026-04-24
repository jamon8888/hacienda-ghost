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
    import re
    path = _resolve(hosts_path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    if _SENTINEL_BEGIN not in text:
        return False
    pattern = re.compile(rf"^\s*\S+\s+{re.escape(host)}\s*$", re.MULTILINE)
    return bool(pattern.search(text))


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

    bak = path.with_name(path.name + ".piighost.bak")
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
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
    except PermissionError:
        if sys.platform == "win32":
            raise
        import tempfile
        fd, tmp_path = tempfile.mkstemp(prefix="piighost_hosts_")
        try:
            os.write(fd, content.encode())
            os.close(fd)
            subprocess.run(
                ["sudo", "install", "-m", "0644", "-o", "root", tmp_path, str(path)],
                check=True,
            )
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
