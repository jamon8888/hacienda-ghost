from __future__ import annotations

import subprocess
import time


class DockerError(RuntimeError):
    pass


def docker_available() -> bool:
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
        )
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def compose_pull_and_up(*, dry_run: bool) -> None:
    if dry_run:
        return
    _compose_pull()
    _compose_up()
    if not _wait_for_healthy(timeout_s=180):
        raise DockerError("Services did not become healthy within 3 minutes.")


def _compose_pull() -> None:
    cmd = [
        "docker", "compose",
        "-f", "docker-compose.yml",
        "-f", "docker-compose.embedder.yml",
        "pull",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise DockerError(
            f"docker compose pull failed (exit {exc.returncode}). "
            f"Use --no-docker to skip Docker and install via uv instead."
        ) from exc


def _compose_up() -> None:
    cmd = [
        "docker", "compose",
        "-f", "docker-compose.yml",
        "-f", "docker-compose.embedder.yml",
        "up", "-d",
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise DockerError(f"docker compose up failed (exit {exc.returncode}).") from exc


def _wait_for_healthy(timeout_s: int = 180, poll_s: int = 5) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "{{.Health}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            statuses = [s.strip() for s in result.stdout.splitlines() if s.strip()]
            if statuses and all(s == "healthy" for s in statuses):
                return True
        except subprocess.CalledProcessError:
            pass
        time.sleep(poll_s)
    return False
