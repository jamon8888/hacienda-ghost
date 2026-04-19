from pathlib import Path

import pytest
from starlette.testclient import TestClient

from piighost.daemon.server import build_app


@pytest.fixture()
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    d = tmp_path / ".piighost"
    d.mkdir()
    (d / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")
    return d


def test_rpc_requires_token(vault_dir: Path) -> None:
    app, token = build_app(vault_dir)
    with TestClient(app) as client:
        r = client.post(
            "/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "vault_stats"}
        )
        assert r.status_code == 401


def test_rpc_anonymize(vault_dir: Path) -> None:
    app, token = build_app(vault_dir)
    with TestClient(app) as client:
        r = client.post(
            "/rpc",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "anonymize",
                "params": {"text": "Alice in Paris"},
            },
        )
        assert r.status_code == 200
        payload = r.json()
        assert "result" in payload
        assert "Alice" not in payload["result"]["anonymized"]


def test_health(vault_dir: Path) -> None:
    app, _ = build_app(vault_dir)
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True
