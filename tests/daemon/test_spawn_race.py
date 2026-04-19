from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from piighost.daemon.lifecycle import ensure_daemon, stop_daemon


def test_concurrent_spawn_produces_one_daemon(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    vault_dir = tmp_path / ".piighost"
    vault_dir.mkdir()
    (vault_dir / "config.toml").write_text("schema_version = 1\n", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=3) as pool:
        handshakes = list(pool.map(
            lambda _: ensure_daemon(vault_dir, timeout_sec=20.0), range(3)
        ))
    try:
        pids = {h.pid for h in handshakes}
        assert len(pids) == 1
    finally:
        stop_daemon(vault_dir)
