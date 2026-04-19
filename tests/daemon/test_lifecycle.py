from pathlib import Path

import httpx

from piighost.daemon.lifecycle import ensure_daemon, stop_daemon


def test_spawn_and_stop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / ".piighost"
    vault_dir.mkdir()
    (vault_dir / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")

    hs = ensure_daemon(vault_dir, timeout_sec=15.0)
    try:
        r = httpx.get(
            f"http://127.0.0.1:{hs.port}/health",
            headers={"Authorization": f"Bearer {hs.token}"},
        )
        assert r.status_code == 200
    finally:
        stop_daemon(vault_dir)
    # handshake file removed after stop
    assert not (vault_dir / "daemon.json").exists()
