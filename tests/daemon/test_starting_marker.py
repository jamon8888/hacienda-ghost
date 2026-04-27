"""Tests for the daemon.starting marker — the "I'm mid-warmup" signal
that prevents concurrent shims from killing each other's daemons during
the 60-90s eager model load.

These tests don't spawn a real daemon. They exercise the marker
read/write helpers and the lifecycle decisions that consume them
(``_is_alive_with_retry``, ``_cleanup_stale``, ``_wait_for_startup``)
in isolation.
"""
from __future__ import annotations

import os
import time

import pytest

from piighost.daemon import lifecycle
from piighost.daemon.handshake import (
    DaemonHandshake,
    StartingMarker,
    clear_starting_marker,
    read_starting_marker,
    write_handshake,
    write_starting_marker,
)


# --- handshake.py: starting-marker round-trip ---------------------------


def test_starting_marker_round_trip(tmp_path):
    write_starting_marker(tmp_path, StartingMarker(pid=12345, started_at=1700000000))
    got = read_starting_marker(tmp_path)
    assert got == StartingMarker(pid=12345, started_at=1700000000)


def test_starting_marker_missing_returns_none(tmp_path):
    assert read_starting_marker(tmp_path) is None


def test_clear_starting_marker_is_idempotent(tmp_path):
    # Clearing when nothing is there is fine.
    clear_starting_marker(tmp_path)
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))
    clear_starting_marker(tmp_path)
    clear_starting_marker(tmp_path)  # second clear is also fine
    assert read_starting_marker(tmp_path) is None


def test_starting_marker_atomic_overwrite(tmp_path):
    write_starting_marker(tmp_path, StartingMarker(pid=1, started_at=1))
    write_starting_marker(tmp_path, StartingMarker(pid=2, started_at=2))
    got = read_starting_marker(tmp_path)
    assert got == StartingMarker(pid=2, started_at=2)


def test_starting_marker_corrupt_file_returns_none(tmp_path):
    (tmp_path / "daemon.starting").write_text("not json")
    assert read_starting_marker(tmp_path) is None


# --- lifecycle._is_starting ---------------------------------------------


def test_is_starting_false_when_no_marker(tmp_path):
    assert lifecycle._is_starting(tmp_path) is False


def test_is_starting_true_when_marker_has_live_pid(tmp_path):
    # Use our own pid — it's guaranteed alive.
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))
    assert lifecycle._is_starting(tmp_path) is True


def test_is_starting_false_when_marker_pid_is_dead(tmp_path):
    # PID 1 doesn't exist on Windows (and is init on POSIX, which can't be
    # "dead" — pick a high number unlikely to be assigned).
    write_starting_marker(tmp_path, StartingMarker(pid=999_999, started_at=int(time.time())))
    assert lifecycle._is_starting(tmp_path) is False


def test_is_starting_false_when_marker_is_too_old(tmp_path, monkeypatch):
    # Live pid, but started 1 hour ago — past the startup grace window.
    stale_ts = int(time.time()) - 3600
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=stale_ts))
    assert lifecycle._is_starting(tmp_path) is False


# --- lifecycle._is_alive_with_retry: starting -> alive ------------------


def test_is_alive_with_retry_treats_starting_as_alive(tmp_path, monkeypatch):
    """During lifespan-startup the daemon's HTTP /health returns nothing
    (the port isn't bound yet), but the process is alive and the marker
    exists. _is_alive_with_retry must return True so the caller doesn't
    declare the daemon stale and kill it."""
    # _is_alive will be called against an unreachable daemon; force it
    # to fail without a real network call so the test stays fast.
    monkeypatch.setattr(lifecycle, "_is_alive", lambda hs: False)

    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))
    hs = DaemonHandshake(pid=os.getpid(), port=1, token="t", started_at=int(time.time()))

    # retries=1, delay=0 to keep the test fast
    assert lifecycle._is_alive_with_retry(hs, tmp_path, retries=1, delay=0.0) is True


def test_is_alive_with_retry_false_when_no_health_and_no_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(lifecycle, "_is_alive", lambda hs: False)
    hs = DaemonHandshake(pid=os.getpid(), port=1, token="t", started_at=int(time.time()))
    assert lifecycle._is_alive_with_retry(hs, tmp_path, retries=1, delay=0.0) is False


# --- lifecycle._cleanup_stale: refuses to kill mid-startup --------------


def test_cleanup_stale_skips_when_starting_marker_present(tmp_path, monkeypatch):
    """If another shim is mid-spawn (marker exists with live pid), do
    NOT terminate the handshake's pid — that would sabotage the warm-up."""
    write_handshake(
        tmp_path,
        DaemonHandshake(pid=os.getpid(), port=1, token="t", started_at=int(time.time())),
    )
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))

    terminate_calls: list[int] = []

    class _FakeProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def terminate(self) -> None:
            terminate_calls.append(self.pid)

    import psutil
    monkeypatch.setattr(psutil, "Process", _FakeProc)

    hs = DaemonHandshake(pid=os.getpid(), port=1, token="t", started_at=int(time.time()))
    lifecycle._cleanup_stale(tmp_path, hs)

    assert terminate_calls == []
    # Handshake must still be on disk too — we didn't conclude staleness.
    assert (tmp_path / "daemon.json").exists()


def test_cleanup_stale_kills_when_no_marker(tmp_path, monkeypatch):
    """No starting marker + handshake's pid is dead-or-stale → terminate
    + remove handshake."""
    hs = DaemonHandshake(pid=999_999, port=1, token="t", started_at=int(time.time()))
    write_handshake(tmp_path, hs)

    # Make pid_exists False to skip the terminate path; we just want to
    # verify the handshake gets unlinked.
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: False)

    lifecycle._cleanup_stale(tmp_path, hs)
    assert not (tmp_path / "daemon.json").exists()


# --- lifecycle._wait_for_startup ----------------------------------------


def test_wait_for_startup_returns_immediately_if_no_marker(tmp_path):
    start = time.monotonic()
    lifecycle._wait_for_startup(tmp_path, timeout_sec=5.0)
    assert time.monotonic() - start < 0.2  # well under timeout


def test_wait_for_startup_returns_when_marker_disappears(tmp_path):
    """Background-clear the marker after a short delay; the wait returns."""
    import threading
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))

    def _clear_after_delay() -> None:
        time.sleep(0.3)
        clear_starting_marker(tmp_path)

    t = threading.Thread(target=_clear_after_delay, daemon=True)
    t.start()

    start = time.monotonic()
    lifecycle._wait_for_startup(tmp_path, timeout_sec=5.0)
    elapsed = time.monotonic() - start

    t.join(timeout=2.0)
    assert 0.2 < elapsed < 4.0  # bounded by the background clear, not the timeout


def test_wait_for_startup_times_out_when_marker_persists(tmp_path):
    """If the marker never goes away (e.g. crashed warmup that we
    haven't aged out yet), _wait_for_startup must still return when
    its own timeout elapses — no infinite hangs."""
    write_starting_marker(tmp_path, StartingMarker(pid=os.getpid(), started_at=int(time.time())))
    start = time.monotonic()
    lifecycle._wait_for_startup(tmp_path, timeout_sec=0.5)
    elapsed = time.monotonic() - start
    assert 0.4 <= elapsed <= 1.5
