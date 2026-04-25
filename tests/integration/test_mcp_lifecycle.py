"""End-to-end MCP lifecycle smoke tests.

Marked slow; opt in via:  pytest -m slow
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from piighost.daemon.handshake import read_handshake


pytestmark = pytest.mark.slow


def _piighost_exe() -> list[str]:
    """Return the command prefix to invoke the piighost CLI.

    Uses the ``piighost`` script installed in the same Scripts directory as
    the currently-running ``sys.executable``.  This guarantees we hit the
    editable-install (or worktree) version of the code, not a different
    piighost found earlier on PATH (e.g. a ``uv tools`` install).

    Falls back to a bare ``piighost`` search when the co-located script is
    absent (e.g. in a CI environment where only the entry-point is on PATH).

    Note: ``python -m piighost.cli.main`` is NOT used here because
    ``piighost/cli/main.py`` has no ``if __name__ == '__main__'`` guard, so
    running it as ``-m`` silently exits 0 without executing the Typer app.
    """
    # Primary: co-located with sys.executable (same venv / editable install)
    scripts_dir = Path(sys.executable).parent / "Scripts"
    colocated = scripts_dir / "piighost.exe"
    if colocated.exists():
        return [str(colocated)]
    # Fallback: POSIX venv bin directory
    bin_dir = Path(sys.executable).parent
    for name in ("piighost", "piighost.exe"):
        candidate = bin_dir / name
        if candidate.exists():
            return [str(candidate)]
    # Last resort: rely on PATH (may pick wrong version on PATH-heavy systems)
    return ["piighost"]


@pytest.fixture()
def fresh_vault(tmp_path: Path) -> Path:
    # The vault directory must exist before `piighost serve` is invoked:
    # find_vault_dir() raises VaultNotFound for a non-existent --vault path.
    vault = tmp_path / ".piighost"
    vault.mkdir(parents=True, exist_ok=True)
    return vault


def _spawn_shim(vault: Path) -> subprocess.Popen:
    cmd = _piighost_exe() + ["serve", "--vault", str(vault), "--transport", "stdio"]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _wait_for_daemon(vault: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            hs = read_handshake(vault)
        except PermissionError:
            # Windows: daemon.json may be transiently locked during atomic replace
            time.sleep(0.1)
            continue
        if hs and psutil.pid_exists(hs.pid):
            return
        time.sleep(0.2)
    raise TimeoutError(f"daemon did not start within {timeout}s")


def _drain_and_wait(proc: subprocess.Popen, timeout: float = 10.0) -> None:
    """Terminate *proc*, then drain its pipes with communicate() to avoid
    a deadlock when the subprocess wrote more than the OS pipe buffer
    (typically 64 KiB) to stdout/stderr before exiting.

    Using ``proc.wait()`` after ``proc.terminate()`` can deadlock if the
    subprocess's Rich-formatted output filled the pipe buffer and is blocking
    the subprocess on a ``write(2)`` call.  ``communicate()`` drains the
    pipes while waiting, so the subprocess can flush and exit.
    """
    if proc.poll() is None:
        proc.terminate()
    try:
        proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()


def test_five_shims_share_one_daemon(fresh_vault: Path) -> None:
    shims = [_spawn_shim(fresh_vault) for _ in range(5)]
    try:
        _wait_for_daemon(fresh_vault)
        # Count daemon processes for THIS vault only (must be exactly 1).
        # Filter by vault path in the command line to exclude daemons from
        # other concurrent test runs or user sessions.
        vault_str = str(fresh_vault)
        daemons = [
            p for p in psutil.process_iter(["cmdline"])
            if p.info["cmdline"]
            and "piighost.daemon" in " ".join(p.info["cmdline"])
            and vault_str in " ".join(p.info["cmdline"])
        ]
        assert len(daemons) == 1
    finally:
        for s in shims:
            _drain_and_wait(s)


def test_kill_9_shim_is_reaped_within_70s(fresh_vault: Path) -> None:
    shim = _spawn_shim(fresh_vault)
    try:
        _wait_for_daemon(fresh_vault)
        # SIGKILL the shim — on Windows shim.kill() calls TerminateProcess
        if sys.platform == "win32":
            shim.kill()
        else:
            os.kill(shim.pid, signal.SIGKILL)
        # Reaper runs every 60s — give it 70s wall clock
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            if not psutil.pid_exists(shim.pid):
                return
            time.sleep(1)
        pytest.fail(f"shim pid={shim.pid} survived 70s, reaper did not kill it")
    finally:
        # Collect the shim (may already be dead after SIGKILL)
        try:
            shim.communicate(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            shim.kill()
            try:
                shim.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass


def test_disabled_flag_blocks_auto_spawn(fresh_vault: Path) -> None:
    (fresh_vault / "daemon.disabled").touch()

    shim = _spawn_shim(fresh_vault)
    try:
        # Use communicate() rather than wait() to drain the pipe buffers.
        # The Rich-formatted traceback can exceed the OS pipe buffer (64 KiB)
        # causing the subprocess to block on write(2) while we block on wait();
        # communicate() drains both concurrently and avoids the deadlock.
        stdout, stderr_bytes = shim.communicate(timeout=15)
        rc = shim.returncode
        assert rc != 0, "shim must exit non-zero when daemon is disabled"
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        assert "stopped by user" in stderr.lower() or "DaemonDisabled" in stderr
    finally:
        if shim.poll() is None:
            shim.terminate()
            try:
                shim.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                shim.kill()
                shim.communicate()
