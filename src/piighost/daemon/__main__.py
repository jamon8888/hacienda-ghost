"""`python -m piighost.daemon --vault <dir>` — the actual daemon entry."""

from __future__ import annotations

import argparse
import os
import socket
import time
from pathlib import Path

import uvicorn

from piighost.daemon.handshake import DaemonHandshake, write_handshake
from piighost.daemon.server import build_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", type=Path, required=True)
    args = parser.parse_args()

    vault_dir = args.vault.resolve()

    # Allocate an OS-assigned port on loopback.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app, token = build_app(vault_dir)
    # Lifespan reads app.state.port for the daemon_started event; must be
    # set before uvicorn.run(), which is when the lifespan begins.
    app.state.port = port
    hs = DaemonHandshake(
        pid=os.getpid(), port=port, token=token, started_at=int(time.time())
    )
    write_handshake(vault_dir, hs)

    uvicorn.run(app, host="127.0.0.1", port=port, log_config=None, access_log=False)


if __name__ == "__main__":
    main()
