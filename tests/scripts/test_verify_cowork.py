# tests/scripts/test_verify_cowork.py
from __future__ import annotations

import importlib.util
import socket
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest


def _load_script() -> ModuleType:
    """Import scripts/verify_cowork.py as a module without installing it."""
    script_path = Path(__file__).parents[2] / "scripts" / "verify_cowork.py"
    spec = importlib.util.spec_from_file_location("verify_cowork", script_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_loads() -> None:
    mod = _load_script()
    assert hasattr(mod, "run_probe")


def test_probe_passes_when_intercepted(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    import http.client
    mock_conn = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b'{"intercepted": true, "proxy": "piighost"}'
    mock_conn.getresponse.return_value = mock_resp

    with patch("socket.gethostbyname", return_value="127.0.0.1"), \
         patch("http.client.HTTPSConnection", return_value=mock_conn):
        result = mod.run_probe()

    assert result["dns_ok"] is True
    assert result["intercepted"] is True
    assert result["passed"] is True


def test_probe_fails_when_dns_not_redirected(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    with patch("socket.gethostbyname", return_value="99.84.238.101"):
        result = mod.run_probe()

    assert result["dns_ok"] is False
    assert result["passed"] is False


def test_probe_fails_on_connection_refused(monkeypatch) -> None:
    mod = _load_script()
    monkeypatch.setenv("PIIGHOST_PROBE_URL", "https://api.anthropic.com/piighost-probe")

    import http.client
    with patch("socket.gethostbyname", return_value="127.0.0.1"), \
         patch("http.client.HTTPSConnection") as mock_cls:
        mock_cls.return_value.request.side_effect = ConnectionRefusedError("connection refused")
        result = mod.run_probe()

    assert result["intercepted"] is False
    assert result["passed"] is False
