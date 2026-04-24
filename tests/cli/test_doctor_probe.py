# tests/cli/test_doctor_probe.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app

runner = CliRunner()


def _setup_doctor_passing(tmp_path: Path) -> None:
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


def test_probe_dns_check_passes_when_resolves_to_loopback(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"intercepted": True, "proxy": "piighost"}
    mock_resp.status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: mock_resp)

    r = runner.invoke(app, ["doctor", "--probe"])
    assert r.exit_code == 0, f"stdout: {r.stdout}"
    assert "127.0.0.1" in r.stdout
    assert "intercepted" in r.stdout.lower()


def test_probe_dns_check_warns_when_resolves_to_real_ip(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: False)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "99.84.238.101")

    r = runner.invoke(app, ["doctor", "--probe"])
    # --probe warns but does not add to failures list (exit 0 allowed)
    assert "99.84.238.101" in r.stdout
    assert "not redirected" in r.stdout.lower() or "warn" in r.stdout.lower()


def test_probe_https_check_passes_when_proxy_responds(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"intercepted": True, "proxy": "piighost"}
    mock_resp.status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: mock_resp)

    r = runner.invoke(app, ["doctor", "--probe"])
    assert r.exit_code == 0
    assert "intercepted" in r.stdout.lower() or "ok" in r.stdout.lower()


def test_probe_https_check_warns_on_connection_error(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    _setup_doctor_passing(tmp_path)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "has_redirect", lambda *a, **kw: True)

    import socket
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")

    import httpx
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: (_ for _ in ()).throw(
        httpx.ConnectError("connection refused")
    ))

    r = runner.invoke(app, ["doctor", "--probe"])
    assert "connection refused" in r.stdout.lower() or "probe failed" in r.stdout.lower()
