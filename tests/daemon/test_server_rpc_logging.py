"""Each /rpc call must log an audit-log entry with timing and status."""
from __future__ import annotations

import json
from unittest.mock import patch

from starlette.testclient import TestClient

from piighost.daemon.server import build_app


def test_rpc_success_logged(tmp_path) -> None:
    app, token = build_app(tmp_path)
    with patch("piighost.daemon.server._dispatch", return_value={"ok": True}):
        with TestClient(app) as client:
            client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": 1, "method": "vault_stats", "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    matching = [json.loads(line) for line in log.splitlines() if '"event": "rpc"' in line]
    assert any(e.get("method") == "vault_stats" and e.get("status") == "ok" for e in matching)


def test_rpc_error_logged(tmp_path) -> None:
    app, token = build_app(tmp_path)
    with patch("piighost.daemon.server._dispatch", side_effect=ValueError("boom")):
        with TestClient(app) as client:
            client.post(
                "/rpc",
                json={"jsonrpc": "2.0", "id": 1, "method": "anonymize", "params": {}},
                headers={"Authorization": f"Bearer {token}"},
            )
    log = (tmp_path / "daemon.log").read_text(encoding="utf-8")
    matching = [json.loads(line) for line in log.splitlines() if '"event": "rpc"' in line]
    assert any(e.get("method") == "anonymize" and e.get("status") == "error" for e in matching)
