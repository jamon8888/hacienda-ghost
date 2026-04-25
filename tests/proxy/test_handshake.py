from __future__ import annotations

from pathlib import Path

from piighost.proxy.handshake import ProxyHandshake, read_handshake, write_handshake


def test_write_read_roundtrip(tmp_path: Path) -> None:
    import os

    # Use a guaranteed-alive PID (the test runner itself) so read_handshake's
    # PID-liveness validation doesn't reject the synthetic record.
    hs = ProxyHandshake(pid=os.getpid(), port=8443, token="abc123")
    write_handshake(tmp_path, hs)
    got = read_handshake(tmp_path)
    assert got == hs


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_handshake(tmp_path) is None


def test_write_uses_atomic_rename(tmp_path: Path) -> None:
    hs = ProxyHandshake(pid=1, port=8443, token="t")
    write_handshake(tmp_path, hs)
    file = tmp_path / "proxy.handshake.json"
    assert file.exists()
    assert not (tmp_path / "proxy.handshake.json.tmp").exists()


def test_read_returns_none_when_pid_is_dead(tmp_path: Path) -> None:
    """A handshake left over from a crashed proxy must not look 'alive'.

    Self-healing: when the recorded PID is not running on the host, treat
    the handshake as absent and remove the stale file so subsequent reads
    don't keep returning a phantom state.
    """
    # PID 999999 is well above typical pid_max (32768 on Linux, 99999 on
    # default macOS) and certainly not running in the test environment.
    hs = ProxyHandshake(pid=999_999, port=8443, token="t")
    write_handshake(tmp_path, hs)
    assert (tmp_path / "proxy.handshake.json").exists()

    assert read_handshake(tmp_path) is None
    # Stale file should be removed so status/doctor stop showing phantom data.
    assert not (tmp_path / "proxy.handshake.json").exists()


def test_read_returns_handshake_when_pid_is_alive(tmp_path: Path) -> None:
    """The current process is alive, so a handshake bound to its PID must read back."""
    import os

    hs = ProxyHandshake(pid=os.getpid(), port=8443, token="t")
    write_handshake(tmp_path, hs)

    got = read_handshake(tmp_path)
    assert got == hs
    assert (tmp_path / "proxy.handshake.json").exists()
