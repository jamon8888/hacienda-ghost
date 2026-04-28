"""End-to-end test for the 3 RGPD MCP tools through the daemon dispatch
path (Starlette ASGI -> /rpc -> svc).

Closes Phase 2 followup #9 + Phase 4 followup #4. Existing unit tests
bypass the MCP boundary (call PIIGhostService directly). This test
goes /rpc -> daemon._dispatch -> service to catch param-name drift,
JSON serialization edge cases, and dispatcher bugs.

We do NOT test the FastMCP @mcp.tool wrappers in mcp/shim.py — those
are a thin pass-through and would require subprocess + handshake.
The cost-to-coverage ratio isn't there yet.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

# Defer the heavy starlette import until inside the test (matches the
# rest of the codebase's lazy-import discipline; also keeps test
# collection fast on environments where starlette isn't installed).


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    vault = tmp_path / "vault"
    vault.mkdir()
    # Disable the cross-encoder reranker — the dev venv on Windows
    # doesn't always have transformers installed, and the daemon's
    # build_app() reads ServiceConfig from config.toml (falling back
    # to .default() which uses cross_encoder). Stub everything we can.
    (vault / "config.toml").write_text(
        '[reranker]\nbackend = "none"\n',
        encoding="utf-8",
    )
    return vault


def _rpc(client, token: str, method: str, params: dict) -> dict:
    """Call the daemon's /rpc endpoint and return the parsed result.

    Raises RuntimeError if the daemon returns an {error} body.
    """
    resp = client.post(
        "/rpc",
        headers={"authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body and body["error"] is not None:
        raise RuntimeError(f"RPC error: {body['error']}")
    return body["result"]


def test_mcp_shim_processing_register_round_trip(vault_dir):
    """processing_register dispatched through the MCP boundary returns
    a dict that deserializes cleanly to ProcessingRegister."""
    from piighost.daemon.server import build_app
    from starlette.testclient import TestClient

    async def _run():
        app, token = build_app(vault_dir)
        # TestClient internally drives lifespan via with-block
        with TestClient(app) as client:
            _rpc(client, token, "create_project", {"name": "shim-reg"})
            result = _rpc(client, token, "processing_register", {"project": "shim-reg"})

            from piighost.service.models import ProcessingRegister
            register = ProcessingRegister.model_validate(result)
            assert register.project == "shim-reg"
            assert register.v == 1

    asyncio.run(_run())


def test_mcp_shim_dpia_screening_round_trip(vault_dir):
    """dpia_screening dispatched through MCP returns a valid DPIAScreening dict."""
    from piighost.daemon.server import build_app
    from starlette.testclient import TestClient

    async def _run():
        app, token = build_app(vault_dir)
        with TestClient(app) as client:
            _rpc(client, token, "create_project", {"name": "shim-dpia"})
            result = _rpc(client, token, "dpia_screening", {"project": "shim-dpia"})

            from piighost.service.models import DPIAScreening
            dpia = DPIAScreening.model_validate(result)
            assert dpia.project == "shim-dpia"
            assert dpia.verdict in ("dpia_required", "dpia_recommended", "dpia_not_required")

    asyncio.run(_run())


def test_mcp_shim_render_compliance_doc_round_trip(vault_dir):
    """render_compliance_doc dispatched through MCP writes a real file
    and returns a RenderResult dict."""
    pytest.importorskip("jinja2")
    from piighost.daemon.server import build_app
    from starlette.testclient import TestClient

    async def _run():
        app, token = build_app(vault_dir)
        with TestClient(app) as client:
            _rpc(client, token, "create_project", {"name": "shim-render"})
            register = _rpc(client, token, "processing_register", {"project": "shim-render"})

            output = Path.home() / ".piighost" / "exports" / "shim-render.md"
            result = _rpc(client, token, "render_compliance_doc", {
                "data": register, "format": "md", "profile": "generic",
                "output_path": str(output), "project": "shim-render",
            })

            from piighost.service.models import RenderResult
            rr = RenderResult.model_validate(result)
            assert rr.path == str(output)
            assert rr.format == "md"
            assert output.exists()
            assert output.stat().st_size > 0

    asyncio.run(_run())


def test_mcp_shim_unknown_method_returns_clean_error(vault_dir):
    """An unknown RPC method bubbles up as a clean {error} payload, not a 500."""
    from piighost.daemon.server import build_app
    from starlette.testclient import TestClient

    async def _run():
        app, token = build_app(vault_dir)
        with TestClient(app) as client:
            resp = client.post(
                "/rpc",
                headers={"authorization": f"Bearer {token}"},
                json={"jsonrpc": "2.0", "id": 1, "method": "definitely_not_a_method", "params": {}},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "error" in body and body["error"] is not None
            assert "Unknown method" in body["error"]["message"]

    asyncio.run(_run())


def test_mcp_shim_unauthorized_returns_401(vault_dir):
    """Bonus: missing/wrong bearer token returns 401."""
    from piighost.daemon.server import build_app
    from starlette.testclient import TestClient

    async def _run():
        app, _real_token = build_app(vault_dir)
        with TestClient(app) as client:
            # No auth header at all
            resp1 = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "list_projects", "params": {}})
            assert resp1.status_code == 401
            # Wrong token
            resp2 = client.post(
                "/rpc",
                headers={"authorization": "Bearer fake-token"},
                json={"jsonrpc": "2.0", "id": 1, "method": "list_projects", "params": {}},
            )
            assert resp2.status_code == 401

    asyncio.run(_run())
