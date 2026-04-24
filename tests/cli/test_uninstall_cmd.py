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
