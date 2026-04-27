"""Auto-spawn, stale detection, and clean shutdown for the piighost daemon."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import portalocker
import psutil

from piighost.daemon.exceptions import DaemonDisabled, DaemonStartTimeout
from piighost.daemon.handshake import (
    DaemonHandshake,
    read_handshake,
    read_starting_marker,
)

_DISABLED_FILENAME = "daemon.disabled"

# Maximum time we tolerate a daemon being in the "starting" state before
# we give up waiting and treat its handshake as stale. Eager model warm-up
# takes 60-90s on a cold cache; we add headroom for Windows + slow disks.
_STARTUP_GRACE_SEC = 180.0


def _disabled_path(vault_dir: Path) -> Path:
    return vault_dir / _DISABLED_FILENAME


def _is_alive(hs: DaemonHandshake) -> bool:
    if not psutil.pid_exists(hs.pid):
        return False
    try:
        resp = httpx.get(
            f"http://127.0.0.1:{hs.port}/health",
            headers={"Authorization": f"Bearer {hs.token}"},
            timeout=1.5,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def _is_starting(vault_dir: Path) -> bool:
    """Return True iff a ``daemon.starting`` marker exists with a live pid.

    The marker is written by the daemon entry-point before ``uvicorn.run()``
    and cleared by the lifespan once eager model warm-up completes. While
    it is present, ``/health`` is not yet responding (lifespan-startup
    blocks the HTTP server) — but the daemon is alive and will become
    responsive shortly. Other shims must not declare it stale.
    """
    marker = read_starting_marker(vault_dir)
    if marker is None:
        return False
    if not psutil.pid_exists(marker.pid):
        return False
    # Refuse to wait forever on a stuck startup. If the marker is older
    # than _STARTUP_GRACE_SEC, treat it as a crashed startup (the daemon
    # presumably hung mid-warm) and let cleanup proceed.
    age = time.time() - marker.started_at
    return age <= _STARTUP_GRACE_SEC


def _is_alive_with_retry(
    hs: DaemonHandshake,
    vault_dir: Path,
    *,
    retries: int = 3,
    delay: float = 0.4,
) -> bool:
    """Like _is_alive but retries on transient HTTP failures, and treats
    "starting" as alive (the daemon's HTTP server is mid-lifespan-startup
    behind a 60-90s eager model warm).

    Prevents a second lock-holder from killing a live daemon whose port is
    momentarily slow to respond (common on Windows under concurrent load)
    or whose port simply isn't bound yet because warm-up is still running.
    """
    for _ in range(retries):
        if _is_alive(hs):
            return True
        if _is_starting(vault_dir):
            return True
        time.sleep(delay)
    return False


def ensure_daemon(vault_dir: Path, *, timeout_sec: float = 180.0) -> DaemonHandshake:
    """Return a running daemon handshake, spawning if necessary.

    Raises ``DaemonDisabled`` if ``<vault>/daemon.disabled`` exists; the
    user has explicitly stopped the daemon and does not want auto-spawn.

    A cross-platform advisory lock (``daemon.lock``) serializes concurrent
    callers so only the first one spawns; others wait, then read the
    handshake the first wrote.
    """
    if _disabled_path(vault_dir).exists():
        raise DaemonDisabled(
            "piighost daemon was stopped by user. "
            "Run: piighost daemon start"
        )

    vault_dir.mkdir(parents=True, exist_ok=True)
    lock_path = vault_dir / "daemon.lock"
    with portalocker.Lock(str(lock_path), timeout=timeout_sec):
        hs = read_handshake(vault_dir)
        if hs and _is_alive_with_retry(hs, vault_dir):
            # If the daemon is mid-startup, wait for it to finish before
            # returning the handshake. Callers (CLI/MCP) need a daemon
            # that's actually accepting requests, not one that's about
            # to be.
            _wait_for_startup(vault_dir, timeout_sec=timeout_sec)
            return hs
        if hs:
            _cleanup_stale(vault_dir, hs)
        try:
            return _spawn(vault_dir, timeout_sec=timeout_sec)
        except TimeoutError as exc:
            raise DaemonStartTimeout(str(exc)) from exc


def _cleanup_stale(vault_dir: Path, hs: DaemonHandshake) -> None:
    """Kill the daemon advertised by ``hs`` and clear the handshake.

    Refuses to kill if a ``daemon.starting`` marker exists with a live
    pid — that means another shim is mid-spawn and we'd be sabotaging
    its eager warm-up.
    """
    if _is_starting(vault_dir):
        return
    if psutil.pid_exists(hs.pid):
        try:
            psutil.Process(hs.pid).terminate()
        except psutil.Error:
            pass
    try:
        (vault_dir / "daemon.json").unlink(missing_ok=True)
    except OSError:
        pass


def _wait_for_startup(vault_dir: Path, *, timeout_sec: float) -> None:
    """Block until ``daemon.starting`` disappears (or its pid dies / it
    ages out). No-op if the marker is already gone.

    Returns silently in all cases — the caller is expected to follow up
    with ``_is_alive`` if it cares whether the daemon is actually
    serving. The point of this helper is to avoid returning a handshake
    to a caller while the daemon is still loading models for 60-90s.
    """
    deadline = time.monotonic() + timeout_sec
    delay = 0.1
    while time.monotonic() < deadline:
        if not _is_starting(vault_dir):
            return
        time.sleep(delay)
        delay = min(delay * 1.5, 1.0)


def _spawn(vault_dir: Path, *, timeout_sec: float) -> DaemonHandshake:
    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        start_new_session = True

    log_path = vault_dir / "daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(log_path, "ab")
    try:
        subprocess.Popen(
            [sys.executable, "-m", "piighost.daemon", "--vault", str(vault_dir)],
            stdout=log_fh,
            stderr=log_fh,
            stdin=subprocess.DEVNULL,
            start_new_session=start_new_session,
            creationflags=creationflags,
            env=os.environ.copy(),
            close_fds=True,
        )
    finally:
        # The child has already inherited the fd; close our handle.
        log_fh.close()

    deadline = time.monotonic() + timeout_sec
    delay = 0.05
    while time.monotonic() < deadline:
        hs = read_handshake(vault_dir)
        if hs and _is_alive(hs):
            return hs
        time.sleep(delay)
        delay = min(delay * 1.6, 0.8)
    raise TimeoutError(
        f"daemon did not become healthy within {timeout_sec}s; "
        f"see {log_path}"
    )


def stop_daemon(vault_dir: Path) -> bool:
    """Stop the running daemon and disable auto-spawn.

    Always writes ``<vault>/daemon.disabled`` so future ``ensure_daemon``
    calls raise ``DaemonDisabled`` instead of restarting the daemon.
    Returns ``True`` if a running daemon was found and stopped.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    _disabled_path(vault_dir).touch()

    hs = read_handshake(vault_dir)
    if hs is None:
        return False
    try:
        httpx.post(
            f"http://127.0.0.1:{hs.port}/shutdown",
            headers={"Authorization": f"Bearer {hs.token}"},
            timeout=3.0,
        )
    except httpx.HTTPError:
        pass
    # Give the server a beat, then force-kill if still alive.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not psutil.pid_exists(hs.pid):
            break
        time.sleep(0.1)
    else:
        try:
            psutil.Process(hs.pid).kill()
        except psutil.Error:
            pass
    (vault_dir / "daemon.json").unlink(missing_ok=True)
    return True


def start_daemon(vault_dir: Path, *, timeout_sec: float = 15.0) -> DaemonHandshake:
    """Remove the daemon.disabled flag (if any) and ensure the daemon is up.

    Idempotent — safe to call when the daemon is already running.
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    _disabled_path(vault_dir).unlink(missing_ok=True)
    return ensure_daemon(vault_dir, timeout_sec=timeout_sec)


def status(vault_dir: Path) -> DaemonHandshake | None:
    """Return the handshake if a live daemon is reachable, else ``None``."""

    hs = read_handshake(vault_dir)
    if hs is None:
        return None
    return hs if _is_alive(hs) else None
