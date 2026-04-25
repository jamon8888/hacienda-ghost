from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def test_doctor_exits_nonzero_when_no_proxy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    r = runner.invoke(app, ["doctor"])
    # Proxy not installed → doctor reports missing components but does not crash.
    assert r.exit_code != 0
    assert "proxy" in r.stdout.lower()


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
    import os
    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    # Use the test runner's own PID so read_handshake's liveness check passes.
    write_handshake(tmp_path / ".piighost", ProxyHandshake(pid=os.getpid(), port=8443, token="tok"))

    r = runner.invoke(app, ["doctor"])
    assert "api.anthropic.com" in r.stdout
    assert "127.0.0.1" in r.stdout


def test_doctor_hosts_no_redirect_is_info_not_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda host, **kw: False)

    r = runner.invoke(app, ["doctor"])
    assert "light mode" in r.stdout or "not installed" in r.stdout


def test_doctor_reports_active_mode_when_no_paused_flag(monkeypatch, tmp_path: Path) -> None:
    """Doctor should surface the active/paused mode so the user knows whether
    PII is being scrubbed without having to remember which command they ran.
    """
    import os

    monkeypatch.setenv("HOME", str(tmp_path))
    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda host, **kw: True)

    proxy_dir = tmp_path / ".piighost" / "proxy"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "ca.pem").write_bytes(b"fake-ca")

    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    write_handshake(tmp_path / ".piighost",
                    ProxyHandshake(pid=os.getpid(), port=8443, token="t"))

    r = runner.invoke(app, ["doctor"])
    assert "active" in r.stdout.lower() or "anonymizing" in r.stdout.lower()


def test_doctor_reports_paused_mode_when_flag_present(monkeypatch, tmp_path: Path) -> None:
    """When <vault>/paused exists, doctor must clearly indicate that
    anonymization is OFF — otherwise users will assume their PII is protected.
    """
    import os

    monkeypatch.setenv("HOME", str(tmp_path))
    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda host, **kw: True)

    proxy_dir = tmp_path / ".piighost" / "proxy"
    proxy_dir.mkdir(parents=True)
    (proxy_dir / "ca.pem").write_bytes(b"fake-ca")

    from piighost.proxy.handshake import ProxyHandshake, write_handshake
    write_handshake(tmp_path / ".piighost",
                    ProxyHandshake(pid=os.getpid(), port=8443, token="t"))
    (tmp_path / ".piighost" / "paused").touch()

    r = runner.invoke(app, ["doctor"])
    assert "paused" in r.stdout.lower(), (
        f"doctor must surface paused state; got: {r.stdout}"
    )
