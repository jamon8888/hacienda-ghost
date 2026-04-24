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
    monkeypatch.delenv("PIIGHOST_SKIP_SERVICE", raising=False)

    import piighost.install.hosts_file as hf
    monkeypatch.setattr(hf, "add_redirect", lambda *a, **kw: None)

    import shutil
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/local/bin/piighost" if name == "piighost" else None)

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
