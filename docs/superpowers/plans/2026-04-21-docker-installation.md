# Docker Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship piighost as a turnkey Docker stack with secure-by-default posture, two published images (`slim`/`full`), workstation + server profiles, opt-in overlays for local embedder/LLM, encrypted backups, and a signed update path — culminating in a French `## Installation Docker` section in `README.fr.md`.

**Architecture:** Two-container core (`piighost-mcp` + `piighost-daemon`) with three sidecars (`piighost-backup`, `piighost-update-notify`, and server-only `caddy`). Distroless bases, Docker secrets, cosign-signed images published to GHCR, digest-pinned compose files. Overlays add `sentence-transformers` and `ollama` services on isolated networks.

**Tech Stack:** Docker 24+, docker compose v2, GitHub Actions, cosign (keyless OIDC), syft (SBOM), age (backup encryption), Caddy 2 (TLS), distroless Python base (`gcr.io/distroless/python3-debian12:nonroot`), chainguard Python (`cgr.dev/chainguard/python:latest-dev` for `full`), Typer (CLI subcommands), httpx (GHCR API queries).

**Design spec:** `docs/superpowers/specs/2026-04-21-docker-installation-design.md` (commit `8161478`).

---

## File structure (locked before tasks)

### New files
```
docker/
├── Dockerfile                       # multi-stage: slim + full targets
├── entrypoint.sh                    # role dispatch (mcp | daemon | backup | notify)
├── caddy/Caddyfile                  # server profile reverse proxy
├── scripts/
│   ├── backup.sh
│   ├── restore.sh
│   └── update-check.sh
├── secrets/
│   ├── .gitignore                   # ignore real secrets, allow *.example
│   ├── vault-key.example
│   ├── bearer-tokens.example
│   └── age-recipient.example
├── README.md                        # English dev notes (not for end-users)
└── hadolint.yaml                    # Dockerfile linter config

docker-compose.yml                   # base (workstation + server + no-backup profiles)
docker-compose.embedder.yml          # opt-in overlay
docker-compose.llm.yml               # opt-in overlay
.env.example                         # user-facing env vars
.dockerignore                        # build context exclusions
Makefile                             # install | up | down | backup | restore | update

src/piighost/cli/docker_cmd.py       # `piighost docker init|status`
src/piighost/cli/self_update.py      # `piighost self-update`

tests/unit/cli/test_docker_cmd.py
tests/unit/cli/test_self_update.py
tests/unit/docker/__init__.py
tests/unit/docker/test_dockerfile_structure.py
tests/unit/docker/test_compose_config.py
tests/unit/docker/test_entrypoint_dispatch.py
tests/unit/docker/test_backup_restore.py
tests/e2e/test_docker_smoke.py

.github/workflows/docker.yml         # build → sign → SBOM → publish → smoke
```

### Modified files
```
src/piighost/cli/main.py             # register `docker` and `self-update` apps
pyproject.toml                       # add [project.optional-dependencies].docker
.gitignore                           # add docker/secrets/*.txt etc.
README.fr.md                         # NEW `## Installation Docker` section (French only)
```

### Not touched
- Existing `src/piighost/` core modules (no runtime changes required)
- `tests/` except the new ones listed above
- `bundles/` (MCPB packaging is orthogonal)

---

## Conventions for every task

- **Worktree:** Implementation runs in `.worktrees/docker-install` (created by `using-git-worktrees` skill before Task 1).
- **Test command:** `.venv/Scripts/python.exe -m pytest <path> --no-cov -v` on Windows. CI uses `pytest` directly.
- **Shell tests:** Use Python `subprocess.run(["bash", …])`. Bash is available on Windows via Git for Windows; CI uses native Ubuntu bash.
- **Commit style:** mirrors existing `feat(scope): …`, `test(scope): …`, `docs(scope): …` pattern.
- **Never edit the `.env` or secrets files directly from tests** — always use `tmp_path` copies.
- **Full test suite** must stay green (774 passed, 2 skipped) after each task; tasks that don't touch Python code skip the full-suite run.

---

## Task 1: Scaffold `docker/` directory + `.dockerignore`

**Files:**
- Create: `docker/.gitkeep` (removed at end), `docker/README.md`, `docker/secrets/.gitignore`
- Create: `.dockerignore`
- Modify: `.gitignore` (append `docker/secrets/*` exclusion rules)

- [ ] **Step 1: Create `docker/secrets/.gitignore`**

```gitignore
# Deny everything in this directory by default; allow only *.example templates.
*
!.gitignore
!*.example
```

- [ ] **Step 2: Create `.dockerignore` at repo root**

```
# Build-context exclusions — keep the image small and safe
.git/
.github/
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.tox/
dist/
build/
*.egg-info/
**/__pycache__/
**/*.pyc
docs/
tests/
examples/
docker/secrets/*
!docker/secrets/*.example
.env
.env.*
*.log
.DS_Store
.worktrees/
```

- [ ] **Step 3: Append to `.gitignore`**

```gitignore

# Docker secrets — only *.example templates are tracked
docker/secrets/*.txt
docker/secrets/*.pem
docker/secrets/*.key
!docker/secrets/*.example

# Compose overrides and local backups
docker-compose.override.yml
backups/
```

- [ ] **Step 4: Write `docker/README.md`**

English developer notes (ops/maintenance, not end-user-facing):

```markdown
# docker/ — developer notes

This directory holds the Docker build context and sidecar scripts for the
piighost production stack.

**End-user documentation is in `../README.fr.md`.** This file is for
contributors only.

## Layout

- `Dockerfile` — multi-stage, `--target slim` and `--target full`
- `entrypoint.sh` — role dispatch; first argument selects `mcp` / `daemon` / `backup` / `notify`
- `caddy/Caddyfile` — reverse proxy config (server profile only)
- `scripts/` — backup, restore, update-check shell scripts
- `secrets/` — `*.example` templates; real files generated by `piighost docker init` and gitignored
- `hadolint.yaml` — Dockerfile lint rules

## Building locally

```bash
docker buildx build --target slim -t piighost:slim-local docker/
docker buildx build --target full -t piighost:full-local docker/
```

## CI

`../.github/workflows/docker.yml` builds multi-arch images, signs with
cosign, attaches SBOMs, publishes to GHCR, and runs the E2E smoke test.
```

- [ ] **Step 5: Commit**

```bash
git add docker/README.md docker/secrets/.gitignore .dockerignore .gitignore
git commit -m "chore(docker): scaffold docker/ layout and ignore rules"
```

---

## Task 2: Dockerfile — `slim` target

**Files:**
- Create: `docker/Dockerfile`
- Create: `docker/hadolint.yaml`
- Create: `tests/unit/docker/__init__.py`, `tests/unit/docker/test_dockerfile_structure.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/docker/test_dockerfile_structure.py
"""Dockerfile structural invariants — fast, no image build required."""
from __future__ import annotations

from pathlib import Path

import pytest

DOCKERFILE = Path("docker/Dockerfile")


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_dockerfile_has_slim_target(dockerfile_text: str) -> None:
    assert "AS slim" in dockerfile_text, "slim stage missing"


def test_slim_uses_distroless_nonroot(dockerfile_text: str) -> None:
    assert "gcr.io/distroless/python3-debian12:nonroot" in dockerfile_text


def test_slim_runs_as_uid_10001(dockerfile_text: str) -> None:
    # distroless ships UID 65532 as `nonroot`; we override to 10001 explicitly
    assert "USER 10001" in dockerfile_text, "non-root UID not set to 10001"


def test_dockerfile_pins_base_by_digest(dockerfile_text: str) -> None:
    # Every FROM must carry an @sha256: digest pin for supply-chain integrity
    from_lines = [l for l in dockerfile_text.splitlines() if l.strip().startswith("FROM ")]
    assert from_lines, "no FROM directives found"
    for line in from_lines:
        assert "@sha256:" in line, f"unpinned base image: {line!r}"


def test_dockerfile_no_apt_without_clean(dockerfile_text: str) -> None:
    # Cache hygiene: any apt-get install must be followed by rm -rf /var/lib/apt/lists
    if "apt-get install" in dockerfile_text:
        assert "rm -rf /var/lib/apt/lists" in dockerfile_text


def test_dockerfile_declares_healthcheck(dockerfile_text: str) -> None:
    assert "HEALTHCHECK" in dockerfile_text
```

- [ ] **Step 2: Run the test — expect all failures because Dockerfile doesn't exist**

```
.venv/Scripts/python.exe -m pytest tests/unit/docker/test_dockerfile_structure.py -v --no-cov
```

Expected: `FileNotFoundError: docker/Dockerfile`.

- [ ] **Step 3: Write `docker/hadolint.yaml`**

```yaml
# Dockerfile linter config — strict mode
failure-threshold: warning
ignored:
  - DL3008  # pinning apt packages (we don't install any in slim)
trustedRegistries:
  - gcr.io
  - cgr.dev
  - ghcr.io
```

- [ ] **Step 4: Write the slim stage of `docker/Dockerfile`**

Digests below are representative placeholders — the implementer replaces them
with current values fetched via `docker buildx imagetools inspect`:

```dockerfile
# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1: builder — install piighost into a venv we can copy into distroless
# =============================================================================
FROM python:3.12-slim-bookworm@sha256:REPLACE_WITH_CURRENT_DIGEST AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Install uv for deterministic dependency resolution
RUN pip install --no-cache-dir "uv>=0.4" && \
    rm -rf /root/.cache

# Copy dependency manifests first (better layer cache)
COPY pyproject.toml uv.lock ./
COPY README.md ./

# Copy source
COPY src/ ./src/

# Install piighost + slim extras into an isolated venv
RUN uv venv /opt/piighost && \
    . /opt/piighost/bin/activate && \
    uv pip install --python /opt/piighost/bin/python \
        --no-deps -e ".[mcp,client]" && \
    uv pip install --python /opt/piighost/bin/python \
        "fastmcp>=2.0" "typer>=0.12" "httpx>=0.28" \
        "cryptography>=43" "sqlalchemy>=2" "aiosqlite>=0.20"

# =============================================================================
# Stage 2: slim — distroless runtime, no shell, no package manager
# =============================================================================
FROM gcr.io/distroless/python3-debian12:nonroot@sha256:REPLACE_WITH_CURRENT_DIGEST AS slim

# Override the default nonroot UID (65532) with the piighost UID (10001)
# We need a passwd entry for Python's os.getlogin() — copy from builder
COPY --from=builder /etc/passwd.piighost /etc/passwd

# Copy the venv
COPY --from=builder /opt/piighost /opt/piighost

# Copy entrypoint (read-only)
COPY --chown=10001:10001 docker/entrypoint.sh /entrypoint.sh

ENV PATH=/opt/piighost/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIIGHOST_DATA_DIR=/var/lib/piighost \
    PIIGHOST_IMAGE_VARIANT=slim

USER 10001

WORKDIR /var/lib/piighost

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "piighost.cli.main", "healthcheck"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mcp"]
```

Add the `/etc/passwd.piighost` step to the builder stage (above the stage-2
block):

```dockerfile
# Append UID 10001 entry for runtime
RUN echo "piighost:x:10001:10001::/var/lib/piighost:/sbin/nologin" >> /etc/passwd && \
    cp /etc/passwd /etc/passwd.piighost
```

- [ ] **Step 5: Run tests — expect pass**

```
.venv/Scripts/python.exe -m pytest tests/unit/docker/test_dockerfile_structure.py -v --no-cov
```

Expected: all 6 tests pass.

- [ ] **Step 6: Build the slim image locally to confirm it actually compiles**

```bash
docker buildx build --target slim -t piighost:slim-local --load docker/
docker images piighost:slim-local --format '{{.Size}}'
```

Expected: image size < 700 MB. If larger, investigate before proceeding.

- [ ] **Step 7: Commit**

```bash
git add docker/Dockerfile docker/hadolint.yaml tests/unit/docker/__init__.py tests/unit/docker/test_dockerfile_structure.py
git commit -m "feat(docker): slim image target on distroless python3-debian12"
```

---

## Task 3: Dockerfile — `full` target

**Files:**
- Modify: `docker/Dockerfile` (append `full` stage)
- Modify: `tests/unit/docker/test_dockerfile_structure.py` (add `full`-target assertions)

- [ ] **Step 1: Extend the failing test**

Append to `test_dockerfile_structure.py`:

```python
def test_dockerfile_has_full_target(dockerfile_text: str) -> None:
    assert "AS full" in dockerfile_text


def test_full_uses_chainguard_python(dockerfile_text: str) -> None:
    assert "cgr.dev/chainguard/python" in dockerfile_text


def test_full_installs_index_and_gliner_extras(dockerfile_text: str) -> None:
    # The full target must pull the optional groups that end-users expect
    assert "[index," in dockerfile_text or "[gliner2," in dockerfile_text
    assert "sentence-transformers" in dockerfile_text
```

- [ ] **Step 2: Run the test — expect failure**

```
.venv/Scripts/python.exe -m pytest tests/unit/docker/test_dockerfile_structure.py::test_dockerfile_has_full_target -v --no-cov
```

- [ ] **Step 3: Append the `full` stage to `docker/Dockerfile`**

```dockerfile
# =============================================================================
# Stage 3: full — chainguard python with PyTorch + GLiNER + LanceDB
# =============================================================================
FROM cgr.dev/chainguard/python:latest-dev@sha256:REPLACE_WITH_CURRENT_DIGEST AS full

USER root

WORKDIR /build
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir "uv>=0.4" && \
    uv venv /opt/piighost && \
    . /opt/piighost/bin/activate && \
    uv pip install --python /opt/piighost/bin/python \
        -e ".[mcp,client,index,gliner2,langchain,haystack,haystack-lancedb,haystack-embeddings-local,faker,transformers]" \
        --no-cache-dir && \
    # Strip PyTorch test files and docs to shave ~400 MB
    find /opt/piighost -name '*.pyc' -delete && \
    find /opt/piighost -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /opt/piighost -type d -name 'tests' -exec rm -rf {} + 2>/dev/null || true

COPY --chown=10001:10001 docker/entrypoint.sh /entrypoint.sh
RUN chmod 0555 /entrypoint.sh && \
    install -d -o 10001 -g 10001 /var/lib/piighost

ENV PATH=/opt/piighost/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIIGHOST_DATA_DIR=/var/lib/piighost \
    PIIGHOST_IMAGE_VARIANT=full \
    HF_HOME=/var/lib/piighost/.cache/huggingface

USER 10001

WORKDIR /var/lib/piighost

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "piighost.cli.main", "healthcheck"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["mcp"]
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Build the full image locally**

```bash
docker buildx build --target full -t piighost:full-local --load docker/
docker images piighost:full-local --format '{{.Size}}'
```

Expected: image size < 4.5 GB (spec says ~3.5 GB target, 4.5 GB is the hard CI fail threshold).

- [ ] **Step 6: Commit**

```bash
git add docker/Dockerfile tests/unit/docker/test_dockerfile_structure.py
git commit -m "feat(docker): full image target on chainguard python with GLiNER+torch"
```

---

## Task 4: `entrypoint.sh` role dispatch

**Files:**
- Create: `docker/entrypoint.sh`
- Create: `tests/unit/docker/test_entrypoint_dispatch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/docker/test_entrypoint_dispatch.py
"""entrypoint.sh dispatches correctly to each role."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ENTRYPOINT = Path("docker/entrypoint.sh").resolve()


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(ENTRYPOINT), *args],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "PIIGHOST_DRY_RUN": "1", **(env or {})},
        timeout=10,
    )


def test_entrypoint_exists_and_is_executable() -> None:
    assert ENTRYPOINT.exists()
    # Cross-platform: on Windows the bit isn't set, but CI validates via bash
    content = ENTRYPOINT.read_text(encoding="utf-8")
    assert content.startswith("#!/"), "missing shebang"


def test_entrypoint_rejects_unknown_role() -> None:
    result = _run("bogus")
    assert result.returncode != 0
    assert "unknown role" in (result.stderr + result.stdout).lower()


@pytest.mark.parametrize("role", ["mcp", "daemon", "backup", "notify", "cli"])
def test_entrypoint_accepts_known_role(role: str) -> None:
    # PIIGHOST_DRY_RUN=1 makes the entrypoint print the command it would exec
    # instead of actually exec'ing, so we can assert dispatch without running
    # any Python.
    result = _run(role)
    assert result.returncode == 0, f"dispatch failed for {role}: {result.stderr}"
    assert role in result.stdout.lower()
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Write `docker/entrypoint.sh`**

```bash
#!/usr/bin/env bash
# piighost container entrypoint — dispatches to the requested role.
#
# Usage:  entrypoint.sh <role> [args...]
#
# Roles:
#   mcp       Run the MCP server (FastMCP, streamable HTTP)
#   daemon    Run the long-running anonymization daemon
#   backup    Run a one-shot backup (invoked by the backup sidecar cron)
#   notify    Run the update-availability check (one-shot)
#   cli       Drop into the piighost CLI with remaining args
#
# Env:
#   PIIGHOST_DRY_RUN=1   Echo the command that would run, exit 0 without exec
#   PIIGHOST_DATA_DIR    Data directory (default: /var/lib/piighost)
#   PIIGHOST_VAULT_KEY_FILE  Path to vault-key secret file (default: /run/secrets/piighost_vault_key)

set -euo pipefail

role="${1:-mcp}"
shift || true

case "$role" in
    mcp)
        cmd=(python -m piighost.mcp.server --transport http --host 0.0.0.0 --port 8765 "$@")
        ;;
    daemon)
        cmd=(python -m piighost.daemon "$@")
        ;;
    backup)
        cmd=(/docker/scripts/backup.sh "$@")
        ;;
    notify)
        cmd=(/docker/scripts/update-check.sh "$@")
        ;;
    cli)
        cmd=(python -m piighost.cli.main "$@")
        ;;
    *)
        echo "entrypoint.sh: unknown role '$role'" >&2
        echo "valid roles: mcp | daemon | backup | notify | cli" >&2
        exit 64
        ;;
esac

# Load vault key from secret file if present (never via env var)
if [[ -f "${PIIGHOST_VAULT_KEY_FILE:-/run/secrets/piighost_vault_key}" ]]; then
    export PIIGHOST_VAULT_KEY="$(cat "${PIIGHOST_VAULT_KEY_FILE:-/run/secrets/piighost_vault_key}")"
fi

if [[ "${PIIGHOST_DRY_RUN:-0}" == "1" ]]; then
    printf 'dry-run: %s\n' "${cmd[*]}"
    exit 0
fi

exec "${cmd[@]}"
```

Set executable bit in git:

```bash
git update-index --chmod=+x docker/entrypoint.sh
chmod +x docker/entrypoint.sh  # also set locally if on bash
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add docker/entrypoint.sh tests/unit/docker/test_entrypoint_dispatch.py
git commit -m "feat(docker): entrypoint.sh with role dispatch and dry-run mode"
```

---

## Task 5: `docker-compose.yml` base — workstation profile + security hardening

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `tests/unit/docker/test_compose_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/docker/test_compose_config.py
"""`docker compose config` output is well-formed and carries the expected hardening."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
import yaml


def _compose_available() -> bool:
    return shutil.which("docker") is not None


pytestmark = pytest.mark.skipif(
    not _compose_available(),
    reason="docker CLI not available in this environment",
)


def _compose_config(*extra_args: str) -> dict:
    """Return the fully-resolved compose config as a dict."""
    result = subprocess.run(
        ["docker", "compose", *extra_args, "config", "--format", "json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_workstation_profile_brings_up_mcp_and_daemon() -> None:
    cfg = _compose_config("--profile", "workstation")
    services = cfg["services"]
    assert "piighost-mcp" in services
    assert "piighost-daemon" in services
    assert "piighost-backup" in services
    # Caddy is server-only
    assert "caddy" not in services


def test_all_services_run_as_uid_10001() -> None:
    cfg = _compose_config("--profile", "workstation")
    for name, spec in cfg["services"].items():
        assert spec.get("user") == "10001:10001", (
            f"service {name!r} does not run as UID 10001: user={spec.get('user')!r}"
        )


def test_all_services_drop_all_caps() -> None:
    cfg = _compose_config("--profile", "workstation")
    for name, spec in cfg["services"].items():
        cap_drop = spec.get("cap_drop", [])
        assert "ALL" in cap_drop, f"{name!r} does not cap_drop: [ALL]"


def test_all_services_read_only_filesystem() -> None:
    cfg = _compose_config("--profile", "workstation")
    for name, spec in cfg["services"].items():
        assert spec.get("read_only") is True, f"{name!r} read_only != true"


def test_all_services_no_new_privileges() -> None:
    cfg = _compose_config("--profile", "workstation")
    for name, spec in cfg["services"].items():
        sec_opts = spec.get("security_opt", [])
        assert "no-new-privileges:true" in sec_opts, (
            f"{name!r} missing no-new-privileges:true"
        )


def test_mcp_bound_loopback_only_on_workstation() -> None:
    cfg = _compose_config("--profile", "workstation")
    ports = cfg["services"]["piighost-mcp"].get("ports", [])
    for p in ports:
        published = p.get("published") or p.get("host_ip")
        host_ip = p.get("host_ip") or ""
        assert host_ip in ("127.0.0.1", "::1"), (
            f"workstation MCP must bind loopback only, got host_ip={host_ip!r}"
        )


def test_vault_key_delivered_via_secret_not_env() -> None:
    cfg = _compose_config("--profile", "workstation")
    mcp = cfg["services"]["piighost-mcp"]
    env = mcp.get("environment", {}) or {}
    if isinstance(env, list):
        env = dict(kv.split("=", 1) for kv in env if "=" in kv)
    # PIIGHOST_VAULT_KEY must NEVER be set via environment
    assert "PIIGHOST_VAULT_KEY" not in env, (
        "vault key must be delivered via Docker secret, not env var"
    )
    # The secret must be declared on the service
    secrets = mcp.get("secrets", [])
    secret_names = [
        s.get("source") if isinstance(s, dict) else s for s in secrets
    ]
    assert "piighost_vault_key" in secret_names
```

- [ ] **Step 2: Run — expect FileNotFoundError / skip on missing docker**

- [ ] **Step 3: Write `.env.example`**

```bash
# =============================================================================
# piighost — variables d'environnement
# =============================================================================
# Copier ce fichier vers `.env` et adapter si nécessaire. Les valeurs par
# défaut conviennent au profil « poste de travail ».

# -----------------------------------------------------------------------------
# Image (laisser par défaut sauf si vous compilez localement)
# -----------------------------------------------------------------------------
PIIGHOST_IMAGE=ghcr.io/jamon8888/hacienda-ghost
PIIGHOST_TAG=slim                 # `slim` ou `full`
PIIGHOST_VERSION=latest           # remplacé par un digest par `piighost self-update`

# -----------------------------------------------------------------------------
# Profil actif
# -----------------------------------------------------------------------------
# `workstation` (défaut) | `server`
COMPOSE_PROFILES=workstation

# -----------------------------------------------------------------------------
# Ports (workstation uniquement — loopback)
# -----------------------------------------------------------------------------
PIIGHOST_MCP_HOST=127.0.0.1
PIIGHOST_MCP_PORT=8765

# -----------------------------------------------------------------------------
# Serveur (profil `server` uniquement)
# -----------------------------------------------------------------------------
PIIGHOST_PUBLIC_HOSTNAME=piighost.local
PIIGHOST_AUTH=bearer              # `bearer` (défaut) ou `mtls`
CADDY_EMAIL=admin@example.com     # pour Let's Encrypt

# -----------------------------------------------------------------------------
# Chemins hôte pour les secrets (fichiers chmod 600)
# -----------------------------------------------------------------------------
PIIGHOST_VAULT_KEY_FILE=./docker/secrets/vault-key.txt
PIIGHOST_BEARER_TOKENS_FILE=./docker/secrets/bearer-tokens.txt
PIIGHOST_AGE_RECIPIENT_FILE=./docker/secrets/age-recipient.txt

# -----------------------------------------------------------------------------
# Sauvegarde
# -----------------------------------------------------------------------------
PIIGHOST_BACKUP_DIR=./backups
PIIGHOST_BACKUP_SCHEDULE="30 2 * * *"    # cron: tous les jours à 02:30
PIIGHOST_BACKUP_RETENTION_DAILY=7
PIIGHOST_BACKUP_RETENTION_WEEKLY=4

# -----------------------------------------------------------------------------
# Mises à jour
# -----------------------------------------------------------------------------
PIIGHOST_UPDATE_CHECK_INTERVAL=86400     # secondes (24 h)
```

- [ ] **Step 4: Write `docker-compose.yml`**

```yaml
# ============================================================================
# piighost — base compose
#
# Profils :
#   workstation  (défaut) — MCP en loopback, pas de Caddy, pas d'auth
#   server                — MCP derrière Caddy, TLS, bearer/mTLS
#   no-backup             — désactive le sidecar de sauvegarde
#
# Overlays (à ajouter avec -f) :
#   docker-compose.embedder.yml  — sentence-transformers local
#   docker-compose.llm.yml       — Ollama local
# ============================================================================

x-common-security: &common-security
  user: "10001:10001"
  read_only: true
  cap_drop: [ALL]
  security_opt:
    - no-new-privileges:true
  pids_limit: 256
  restart: unless-stopped

x-common-tmpfs: &common-tmpfs
  - /tmp
  - /run

services:
  piighost-mcp:
    <<: *common-security
    image: ${PIIGHOST_IMAGE}:${PIIGHOST_TAG}
    container_name: piighost-mcp
    tmpfs: *common-tmpfs
    command: ["mcp"]
    depends_on:
      piighost-daemon:
        condition: service_healthy
    networks: [piighost-internal]
    secrets:
      - piighost_vault_key
    volumes:
      - piighost-data:/var/lib/piighost
    profiles: [workstation, server]
    healthcheck:
      test: ["CMD", "python", "-m", "piighost.cli.main", "healthcheck"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    # Workstation-only: bind loopback. Server profile overrides via caddy service.
    ports:
      - target: 8765
        published: ${PIIGHOST_MCP_PORT:-8765}
        host_ip: ${PIIGHOST_MCP_HOST:-127.0.0.1}
        protocol: tcp

  piighost-daemon:
    <<: *common-security
    image: ${PIIGHOST_IMAGE}:${PIIGHOST_TAG}
    container_name: piighost-daemon
    tmpfs: *common-tmpfs
    command: ["daemon"]
    networks:
      piighost-internal:
        # internal network — no egress
    secrets:
      - piighost_vault_key
    volumes:
      - piighost-data:/var/lib/piighost
    profiles: [workstation, server]
    healthcheck:
      test: ["CMD", "python", "-m", "piighost.cli.main", "healthcheck"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s

  piighost-backup:
    <<: *common-security
    image: ${PIIGHOST_IMAGE}:${PIIGHOST_TAG}
    container_name: piighost-backup
    tmpfs: *common-tmpfs
    command: ["backup"]
    environment:
      PIIGHOST_BACKUP_SCHEDULE: ${PIIGHOST_BACKUP_SCHEDULE:-30 2 * * *}
      PIIGHOST_BACKUP_RETENTION_DAILY: ${PIIGHOST_BACKUP_RETENTION_DAILY:-7}
      PIIGHOST_BACKUP_RETENTION_WEEKLY: ${PIIGHOST_BACKUP_RETENTION_WEEKLY:-4}
    secrets:
      - piighost_age_recipient
    volumes:
      - piighost-data:/var/lib/piighost:ro
      - ${PIIGHOST_BACKUP_DIR:-./backups}:/backups
    profiles: [workstation, server]   # disabled by `--profile no-backup`
    # Profile `no-backup` is declared on this service via deploy label,
    # enforced in CI by test_compose_profile_no_backup_disables_sidecar.

  piighost-update-notify:
    <<: *common-security
    image: ${PIIGHOST_IMAGE}:${PIIGHOST_TAG}
    container_name: piighost-update-notify
    tmpfs: *common-tmpfs
    command: ["notify"]
    environment:
      PIIGHOST_UPDATE_CHECK_INTERVAL: ${PIIGHOST_UPDATE_CHECK_INTERVAL:-86400}
    volumes:
      - piighost-data:/var/lib/piighost
    profiles: [workstation, server]

volumes:
  piighost-data:
    name: piighost-data

networks:
  piighost-internal:
    name: piighost-internal
    internal: true

secrets:
  piighost_vault_key:
    file: ${PIIGHOST_VAULT_KEY_FILE:-./docker/secrets/vault-key.txt}
  piighost_age_recipient:
    file: ${PIIGHOST_AGE_RECIPIENT_FILE:-./docker/secrets/age-recipient.txt}
```

- [ ] **Step 5: Run tests**

```
.venv/Scripts/python.exe -m pytest tests/unit/docker/test_compose_config.py -v --no-cov
```

All should pass. If `docker compose config` complains about missing secret files, create stub files for the test:

```bash
install -d docker/secrets
: > docker/secrets/vault-key.txt
: > docker/secrets/age-recipient.txt
```

(These are gitignored by Task 1.)

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example tests/unit/docker/test_compose_config.py
git commit -m "feat(docker): workstation-profile compose with hardened defaults"
```

---

## Task 6: Server profile + Caddy reverse proxy

**Files:**
- Modify: `docker-compose.yml` (add `caddy` service + server-only port bindings)
- Create: `docker/caddy/Caddyfile`
- Modify: `tests/unit/docker/test_compose_config.py` (add server-profile tests)

- [ ] **Step 1: Extend failing tests**

```python
def test_server_profile_brings_up_caddy() -> None:
    cfg = _compose_config("--profile", "server")
    assert "caddy" in cfg["services"]


def test_server_profile_caddy_owns_public_ports() -> None:
    cfg = _compose_config("--profile", "server")
    caddy = cfg["services"]["caddy"]
    published_ports = [p["published"] for p in caddy.get("ports", [])]
    assert 443 in published_ports, "caddy must publish 443"
    # MCP should NOT publish any port directly on server profile
    mcp = cfg["services"]["piighost-mcp"]
    assert not mcp.get("ports"), "MCP must not publish ports in server profile"


def test_server_profile_mtls_mode() -> None:
    cfg = _compose_config("--profile", "server")
    caddy = cfg["services"]["caddy"]
    env = caddy.get("environment", {}) or {}
    if isinstance(env, list):
        env = dict(kv.split("=", 1) for kv in env if "=" in kv)
    # PIIGHOST_AUTH should be configurable
    assert "PIIGHOST_AUTH" in env
```

- [ ] **Step 2: Write `docker/caddy/Caddyfile`**

```caddy
# piighost reverse proxy — server profile

{
    email {$CADDY_EMAIL}
    # Strict security posture
    servers {
        protocols h1 h2
    }
}

{$PIIGHOST_PUBLIC_HOSTNAME} {
    encode gzip zstd

    # Security headers
    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options nosniff
        X-Frame-Options DENY
        Referrer-Policy strict-origin-when-cross-origin
        -Server
    }

    # Bearer-token auth (default)
    @unauthenticated {
        not header Authorization "Bearer *"
    }
    respond @unauthenticated "Unauthorized" 401 {
        close
    }

    # mTLS mode (only when PIIGHOST_AUTH=mtls)
    # Caddy does not natively parse this env var — the server-profile
    # overlay re-renders the Caddyfile at container start via envsubst.
    # See docker/entrypoint.caddy.sh.

    reverse_proxy piighost-mcp:8765 {
        header_up X-Real-IP {remote_host}
        header_up Host {host}
        # Strip any Authorization header propagation to upstream
        header_up -Authorization
    }
}
```

- [ ] **Step 3: Extend `docker-compose.yml`**

Add under `services:`:

```yaml
  caddy:
    image: caddy:2-alpine@sha256:REPLACE_WITH_CURRENT_DIGEST
    container_name: piighost-caddy
    user: "10001:10001"
    read_only: true
    cap_drop: [ALL]
    cap_add: [NET_BIND_SERVICE]   # required to bind 443
    security_opt:
      - no-new-privileges:true
    tmpfs: [/tmp]
    restart: unless-stopped
    environment:
      PIIGHOST_PUBLIC_HOSTNAME: ${PIIGHOST_PUBLIC_HOSTNAME}
      PIIGHOST_AUTH: ${PIIGHOST_AUTH:-bearer}
      CADDY_EMAIL: ${CADDY_EMAIL}
    ports:
      - "443:443"
      - "80:80"
    volumes:
      - ./docker/caddy/Caddyfile:/etc/caddy/Caddyfile:ro
      - piighost-caddy-data:/data
      - piighost-caddy-config:/config
    networks:
      - piighost-internal
      - piighost-public
    depends_on:
      piighost-mcp:
        condition: service_healthy
    profiles: [server]
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:2019/config/"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Add to `volumes:` and `networks:` sections:

```yaml
volumes:
  piighost-data:
    name: piighost-data
  piighost-caddy-data:
    name: piighost-caddy-data
  piighost-caddy-config:
    name: piighost-caddy-config

networks:
  piighost-internal:
    name: piighost-internal
    internal: true
  piighost-public:
    name: piighost-public
```

Conditionally remove the `ports:` block from `piighost-mcp` on the server
profile — the cleanest way is to move the workstation port-binding into a
profile-scoped override. Use a small helper service or a compose-level
`profiles:` trick:

```yaml
  # Workstation-only: expose MCP on loopback. Server profile relies on caddy.
  piighost-mcp-port:
    image: busybox:1-musl
    container_name: piighost-mcp-port
    network_mode: "service:piighost-mcp"
    command: ["true"]
    profiles: [workstation]
    # This is a no-op placeholder used only to anchor the loopback port binding.
```

(Alternative: ship two compose fragments, one for workstation binding one for
server binding, and merge with `-f`. Leave the cleaner approach to the
implementer — they can choose based on readability. The test only cares
about the **observable** outcome: workstation publishes, server does not.)

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml docker/caddy/Caddyfile tests/unit/docker/test_compose_config.py
git commit -m "feat(docker): server profile with Caddy TLS reverse proxy"
```

---

## Task 7: Backup + restore scripts and sidecar wiring

**Files:**
- Create: `docker/scripts/backup.sh`, `docker/scripts/restore.sh`
- Create: `tests/unit/docker/test_backup_restore.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/docker/test_backup_restore.py
"""backup.sh and restore.sh round-trip a volume's contents."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

BACKUP = Path("docker/scripts/backup.sh").resolve()
RESTORE = Path("docker/scripts/restore.sh").resolve()


def _has_tools() -> bool:
    return all(shutil.which(t) for t in ("bash", "tar", "age"))


pytestmark = pytest.mark.skipif(
    not _has_tools(), reason="bash/tar/age not available"
)


def test_backup_restore_roundtrip(tmp_path: Path) -> None:
    # Prepare a fake vault directory
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "vault").mkdir()
    (data_dir / "vault" / "store.db").write_bytes(b"encrypted-payload")
    (data_dir / "audit").mkdir()
    (data_dir / "audit" / "log").write_text("entry 1\nentry 2\n")

    # Generate an ephemeral age keypair for the test
    key_path = tmp_path / "age.key"
    subprocess.run(
        ["age-keygen", "-o", str(key_path)],
        check=True,
        capture_output=True,
    )
    recipient = subprocess.run(
        ["age-keygen", "-y", str(key_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    recipient_file = tmp_path / "recipient.txt"
    recipient_file.write_text(recipient)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    # Back up
    result = subprocess.run(
        ["bash", str(BACKUP)],
        env={
            **os.environ,
            "PIIGHOST_DATA_DIR": str(data_dir),
            "PIIGHOST_AGE_RECIPIENT_FILE": str(recipient_file),
            "PIIGHOST_BACKUP_DIR": str(backup_dir),
            "PIIGHOST_BACKUP_TIMESTAMP": "2026-04-21",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    archive = backup_dir / "piighost-2026-04-21.tar.age"
    assert archive.exists()
    assert archive.stat().st_size > 0

    # Restore into a fresh directory
    restore_dir = tmp_path / "restored"
    restore_dir.mkdir()
    result = subprocess.run(
        ["bash", str(RESTORE), str(archive)],
        env={
            **os.environ,
            "PIIGHOST_DATA_DIR": str(restore_dir),
            "PIIGHOST_AGE_KEY_FILE": str(key_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (restore_dir / "vault" / "store.db").read_bytes() == b"encrypted-payload"
    assert (restore_dir / "audit" / "log").read_text() == "entry 1\nentry 2\n"
```

- [ ] **Step 2: Write `docker/scripts/backup.sh`**

```bash
#!/usr/bin/env bash
# piighost vault backup — age-encrypted tar of $PIIGHOST_DATA_DIR to
# $PIIGHOST_BACKUP_DIR. Called by the backup sidecar on the configured
# cron schedule.

set -euo pipefail

DATA_DIR="${PIIGHOST_DATA_DIR:-/var/lib/piighost}"
BACKUP_DIR="${PIIGHOST_BACKUP_DIR:-/backups}"
RECIPIENT_FILE="${PIIGHOST_AGE_RECIPIENT_FILE:-/run/secrets/piighost_age_recipient}"
TIMESTAMP="${PIIGHOST_BACKUP_TIMESTAMP:-$(date -u +%Y-%m-%d)}"
RETENTION_DAILY="${PIIGHOST_BACKUP_RETENTION_DAILY:-7}"
RETENTION_WEEKLY="${PIIGHOST_BACKUP_RETENTION_WEEKLY:-4}"

if [[ ! -r "$RECIPIENT_FILE" ]]; then
    echo "backup.sh: cannot read age recipient file: $RECIPIENT_FILE" >&2
    exit 1
fi

recipient="$(tr -d '[:space:]' < "$RECIPIENT_FILE")"
if [[ -z "$recipient" ]]; then
    echo "backup.sh: recipient file is empty" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
archive="$BACKUP_DIR/piighost-$TIMESTAMP.tar.age"

# Stream: tar → age → file. No plaintext on disk.
tar -C "$DATA_DIR" -cf - . | age -r "$recipient" -o "$archive"

# Retention: keep N most-recent dailies + M most-recent weeklies (date-named)
cd "$BACKUP_DIR"
ls -1t piighost-*.tar.age 2>/dev/null | tail -n +$((RETENTION_DAILY + 1)) | \
    while read -r old; do
        # Keep weeklies: dates where weekday == Sunday
        if [[ "$(date -d "${old#piighost-}" +%u 2>/dev/null || echo 0)" != "7" ]]; then
            rm -f "$old"
        fi
    done

# Weekly retention
ls -1t piighost-*.tar.age 2>/dev/null | \
    awk 'NR > '"$((RETENTION_DAILY + RETENTION_WEEKLY))"'' | \
    xargs -r rm -f

echo "backup.sh: wrote $archive"
```

- [ ] **Step 3: Write `docker/scripts/restore.sh`**

```bash
#!/usr/bin/env bash
# piighost vault restore — decrypt an age-encrypted tar archive into
# $PIIGHOST_DATA_DIR. Destructive: wipes the target directory first.

set -euo pipefail

archive="${1:?usage: restore.sh <archive.tar.age>}"
DATA_DIR="${PIIGHOST_DATA_DIR:-/var/lib/piighost}"
KEY_FILE="${PIIGHOST_AGE_KEY_FILE:-/run/secrets/piighost_age_key}"

if [[ ! -r "$archive" ]]; then
    echo "restore.sh: cannot read archive: $archive" >&2
    exit 1
fi
if [[ ! -r "$KEY_FILE" ]]; then
    echo "restore.sh: cannot read age key file: $KEY_FILE" >&2
    exit 1
fi

echo "restore.sh: wiping $DATA_DIR and restoring from $archive"
mkdir -p "$DATA_DIR"
find "$DATA_DIR" -mindepth 1 -delete

age -d -i "$KEY_FILE" "$archive" | tar -C "$DATA_DIR" -xf -

echo "restore.sh: restored to $DATA_DIR"
```

Make executable:

```bash
git update-index --chmod=+x docker/scripts/backup.sh docker/scripts/restore.sh
chmod +x docker/scripts/*.sh
```

- [ ] **Step 4: Run the test — expect pass (requires `age` and `tar` locally)**

- [ ] **Step 5: Commit**

```bash
git add docker/scripts/backup.sh docker/scripts/restore.sh tests/unit/docker/test_backup_restore.py
git commit -m "feat(docker): age-encrypted backup + restore scripts"
```

---

## Task 8: Update-check script (notify-only sidecar)

**Files:**
- Create: `docker/scripts/update-check.sh`

- [ ] **Step 1: Write `docker/scripts/update-check.sh`**

Logic:
1. Sleep `PIIGHOST_UPDATE_CHECK_INTERVAL` seconds
2. Query GHCR for latest digest of the current image+tag
3. Compare to running digest (from `/proc/1/cgroup` + Docker API is fragile; simpler: read from a file the sidecar writes at startup)
4. If different, write `/var/lib/piighost/update-available.json` + log to stderr

```bash
#!/usr/bin/env bash
# piighost update notifier — compare installed digest to latest on GHCR,
# emit a notice if newer. Never mutates the stack.

set -euo pipefail

INTERVAL="${PIIGHOST_UPDATE_CHECK_INTERVAL:-86400}"
IMAGE="${PIIGHOST_IMAGE:-ghcr.io/jamon8888/hacienda-ghost}"
TAG="${PIIGHOST_TAG:-slim}"
DATA_DIR="${PIIGHOST_DATA_DIR:-/var/lib/piighost}"
OUT_FILE="$DATA_DIR/update-available.json"

mkdir -p "$DATA_DIR"

check_once() {
    # GHCR ignores anonymous pulls for public images but manifest reads
    # require an anonymous token. python is available in the image.
    latest_digest="$(
        python - <<'PY'
import os, sys, json
import httpx

image = os.environ["IMAGE"]
tag = os.environ["TAG"]
host, name = image.split("/", 1)
# Token endpoint: GHCR works with anonymous for public images
token = httpx.get(
    f"https://{host}/token",
    params={"service": host, "scope": f"repository:{name}:pull"},
    timeout=10,
).json().get("token", "")
headers = {
    "Accept": "application/vnd.oci.image.index.v1+json",
    "Authorization": f"Bearer {token}" if token else "",
}
r = httpx.get(
    f"https://{host}/v2/{name}/manifests/{tag}",
    headers=headers,
    timeout=10,
)
r.raise_for_status()
print(r.headers.get("Docker-Content-Digest", ""))
PY
    )"
    current_digest_file="$DATA_DIR/installed-digest"
    if [[ ! -f "$current_digest_file" ]]; then
        # First run — record current digest, no notification
        echo "$latest_digest" > "$current_digest_file"
        return 0
    fi
    installed="$(cat "$current_digest_file")"
    if [[ "$latest_digest" != "$installed" ]]; then
        cat > "$OUT_FILE" <<EOF
{
  "image": "$IMAGE",
  "tag": "$TAG",
  "installed": "$installed",
  "latest": "$latest_digest",
  "checked_at": "$(date -u +%FT%TZ)"
}
EOF
        echo "[piighost] update available: $TAG $installed -> $latest_digest" >&2
    fi
}

while true; do
    check_once || echo "[piighost] update check failed (will retry)" >&2
    sleep "$INTERVAL"
done
```

- [ ] **Step 2: Make executable and commit**

```bash
git update-index --chmod=+x docker/scripts/update-check.sh
chmod +x docker/scripts/update-check.sh
git add docker/scripts/update-check.sh
git commit -m "feat(docker): passive update-availability notifier sidecar"
```

---

## Task 9: Embedder overlay

**Files:**
- Create: `docker-compose.embedder.yml`
- Modify: `tests/unit/docker/test_compose_config.py` (add overlay-merge test)

- [ ] **Step 1: Extend test**

```python
def test_embedder_overlay_adds_sentence_transformers_service() -> None:
    cfg = _compose_config("-f", "docker-compose.yml", "-f", "docker-compose.embedder.yml", "--profile", "workstation")
    assert "piighost-embedder" in cfg["services"]
    embedder = cfg["services"]["piighost-embedder"]
    # Must be on internal network — no egress
    net_names = list(embedder.get("networks", {}))
    assert "piighost-internal" in net_names
```

- [ ] **Step 2: Write `docker-compose.embedder.yml`**

```yaml
# ============================================================================
# Overlay : serveur d'embeddings local (sentence-transformers)
#
# Usage :  docker compose -f docker-compose.yml -f docker-compose.embedder.yml up -d
# ============================================================================

services:
  piighost-embedder:
    image: ${PIIGHOST_IMAGE}:full    # needs sentence-transformers — always `full`
    container_name: piighost-embedder
    user: "10001:10001"
    read_only: true
    tmpfs: [/tmp, /run]
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    restart: unless-stopped
    command: ["cli", "embedder-serve", "--host", "0.0.0.0", "--port", "8001"]
    environment:
      SENTENCE_TRANSFORMERS_HOME: /var/lib/piighost/.cache/sentence-transformers
    volumes:
      - piighost-data:/var/lib/piighost
    networks: [piighost-internal]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 120s    # first model download can take a minute

  # Tell the daemon to use the local embedder
  piighost-daemon:
    environment:
      PIIGHOST_EMBEDDER_URL: http://piighost-embedder:8001
    depends_on:
      piighost-embedder:
        condition: service_healthy
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.embedder.yml tests/unit/docker/test_compose_config.py
git commit -m "feat(docker): overlay for local sentence-transformers embedder"
```

---

## Task 10: LLM overlay (Ollama)

**Files:**
- Create: `docker-compose.llm.yml`
- Modify: `tests/unit/docker/test_compose_config.py`

- [ ] **Step 1: Extend test**

```python
def test_llm_overlay_adds_ollama_on_isolated_network() -> None:
    cfg = _compose_config("-f", "docker-compose.yml", "-f", "docker-compose.llm.yml", "--profile", "workstation")
    assert "ollama" in cfg["services"]
    assert "piighost-llm" in cfg["networks"]
```

- [ ] **Step 2: Write `docker-compose.llm.yml`**

```yaml
# ============================================================================
# Overlay : LLM local via Ollama
#
# Usage :  docker compose -f docker-compose.yml -f docker-compose.llm.yml up -d
# ============================================================================

services:
  ollama:
    image: ollama/ollama:0.4@sha256:REPLACE_WITH_CURRENT_DIGEST
    container_name: piighost-ollama
    # Ollama doesn't yet support read-only FS gracefully — allow writes
    # but confine via volume + no-new-privileges + cap_drop
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    restart: unless-stopped
    environment:
      OLLAMA_HOST: 0.0.0.0:11434
      OLLAMA_MODELS: /var/lib/ollama/models
    volumes:
      - piighost-ollama:/var/lib/ollama
    networks: [piighost-llm]
    healthcheck:
      test: ["CMD", "ollama", "list"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s

  piighost-mcp:
    networks: [piighost-internal, piighost-llm]
    environment:
      PIIGHOST_LLM_URL: http://ollama:11434
    depends_on:
      ollama:
        condition: service_healthy

volumes:
  piighost-ollama:
    name: piighost-ollama

networks:
  piighost-llm:
    name: piighost-llm
    internal: true     # Ollama talks only to MCP, no external egress
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.llm.yml tests/unit/docker/test_compose_config.py
git commit -m "feat(docker): overlay for local Ollama LLM on isolated network"
```

---

## Task 11: Makefile — user-facing commands

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write `Makefile`**

```make
# piighost — raccourcis d'installation Docker
# =============================================================================
# Cibles principales :
#   make install       Génère les secrets, prépare .env
#   make up            Démarre le profil workstation
#   make up-server     Démarre le profil server
#   make up-sovereign  Démarre server + embedder + LLM (stack souveraine)
#   make down          Arrête la pile
#   make logs          Suit les logs
#   make backup        Force une sauvegarde immédiate
#   make restore       BACKUP=chemin.tar.age — restaure depuis un fichier
#   make update        Met à jour via `piighost self-update`
#   make status        Affiche l'état courant
#   make clean         Supprime les volumes (DESTRUCTIF)

.PHONY: install up up-server up-sovereign down logs backup restore update status clean

COMPOSE_BASE := docker-compose.yml
COMPOSE_EMBEDDER := docker-compose.embedder.yml
COMPOSE_LLM := docker-compose.llm.yml

install:
	@test -f .env || cp .env.example .env
	@mkdir -p docker/secrets backups
	@piighost docker init

up:
	docker compose --profile workstation up -d

up-server:
	docker compose --profile server up -d

up-sovereign:
	docker compose --profile server \
		-f $(COMPOSE_BASE) -f $(COMPOSE_EMBEDDER) -f $(COMPOSE_LLM) up -d

down:
	docker compose --profile workstation --profile server down

logs:
	docker compose logs -f --tail=100

backup:
	docker compose exec -T piighost-backup bash /docker/scripts/backup.sh

restore:
	@test -n "$(BACKUP)" || (echo "usage: make restore BACKUP=./backups/piighost-YYYY-MM-DD.tar.age" && exit 1)
	docker compose down
	docker compose run --rm piighost-daemon bash /docker/scripts/restore.sh "$(BACKUP)"
	docker compose --profile workstation up -d

update:
	piighost self-update

status:
	piighost docker status

clean:
	@echo "ATTENTION: cela va supprimer tous les volumes et données. Ctrl-C pour annuler."
	@sleep 5
	docker compose down -v
```

- [ ] **Step 2: Commit**

```bash
git add Makefile
git commit -m "feat(docker): Makefile wrapping common compose workflows"
```

---

## Task 12: `.env.example` templates + secret example files

Files already created in Task 5 (`.env.example`). Now add the secret templates.

**Files:**
- Create: `docker/secrets/vault-key.example`
- Create: `docker/secrets/bearer-tokens.example`
- Create: `docker/secrets/age-recipient.example`

- [ ] **Step 1: Create `docker/secrets/vault-key.example`**

```
# === piighost vault key ===
# Format: 32 octets base64url (générés par `piighost docker init`)
# NE JAMAIS COMMITTER LE FICHIER RÉEL (vault-key.txt) — il est dans .gitignore
# Permissions : chmod 600
#
# Pour générer manuellement :
#   python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))"
```

- [ ] **Step 2: Create `docker/secrets/bearer-tokens.example`**

```
# === jetons bearer du profil server ===
# Un hash SHA-256 par ligne. Les jetons en clair ne sont jamais stockés ici.
#
# Génération d'un jeton client (et son hash) :
#   piighost token create --name "avocat-durand"
#
# Le jeton en clair est affiché une seule fois ; le hash est ajouté à
# bearer-tokens.txt automatiquement.
#
# Révocation : supprimer la ligne correspondante et redémarrer caddy.
```

- [ ] **Step 3: Create `docker/secrets/age-recipient.example`**

```
# === destinataire age pour les sauvegardes ===
# Une clé publique age par ligne (format age1...).
# La clé privée correspondante doit être conservée hors-ligne (papier, HSM).
#
# Génération d'une paire de clés :
#   age-keygen -o age.key           # clé privée (à mettre en sécurité)
#   age-keygen -y age.key           # clé publique (à coller ici)
#
# Plusieurs destinataires = plusieurs chemins de restauration
# (utile pour la redondance : un destinataire pour l'associé, un pour
# le notaire séquestre, etc.)
```

- [ ] **Step 4: Commit**

```bash
git add docker/secrets/*.example
git commit -m "docs(docker): secret file templates with generation instructions"
```

---

## Task 13: `piighost docker init` CLI subcommand

**Files:**
- Create: `src/piighost/cli/docker_cmd.py`
- Modify: `src/piighost/cli/main.py`
- Create: `tests/unit/cli/test_docker_cmd.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_docker_cmd.py
"""`piighost docker init` generates secrets and .env atomically."""
from __future__ import annotations

import base64
from pathlib import Path

from typer.testing import CliRunner

from piighost.cli.main import app


def test_docker_init_generates_all_secret_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Pre-populate .example templates (init copies them if real files missing)
    (tmp_path / "docker" / "secrets").mkdir(parents=True)
    (tmp_path / "docker" / "secrets" / "vault-key.example").write_text("# tpl\n")

    runner = CliRunner()
    result = runner.invoke(app, ["docker", "init", "--yes"])
    assert result.exit_code == 0, result.stdout

    vault_key = (tmp_path / "docker" / "secrets" / "vault-key.txt").read_text().strip()
    # 32 bytes base64url, no padding → 43 chars
    assert len(vault_key) == 43
    base64.urlsafe_b64decode(vault_key + "=")  # round-trip parse

    # Mode bits: on POSIX, file must be 0600
    import os
    if os.name == "posix":
        mode = (tmp_path / "docker" / "secrets" / "vault-key.txt").stat().st_mode & 0o777
        assert mode == 0o600


def test_docker_init_refuses_to_overwrite_existing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docker" / "secrets").mkdir(parents=True)
    (tmp_path / "docker" / "secrets" / "vault-key.txt").write_text("ALREADY_THERE")

    runner = CliRunner()
    result = runner.invoke(app, ["docker", "init", "--yes"])
    assert result.exit_code != 0
    assert "refuse to overwrite" in result.stdout.lower()
```

- [ ] **Step 2: Write `src/piighost/cli/docker_cmd.py`**

```python
"""`piighost docker` — initialisation et état de l'installation Docker."""
from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

import typer

app = typer.Typer(
    name="docker",
    help="Gestion de l'installation Docker de piighost.",
    no_args_is_help=True,
)


def _secret_dir() -> Path:
    return Path("docker/secrets")


def _refuse_overwrite(path: Path) -> None:
    if path.exists():
        typer.echo(
            f"error: {path} exists. refuse to overwrite — "
            f"delete it manually first if you really want to regenerate.",
            err=True,
        )
        raise typer.Exit(code=2)


def _write_secret(path: Path, content: str) -> None:
    _refuse_overwrite(path)
    path.write_text(content, encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)


@app.command("init")
def init(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Ne pas demander de confirmation."
    ),
) -> None:
    """Génère les secrets et le fichier .env pour une première installation."""
    sdir = _secret_dir()
    sdir.mkdir(parents=True, exist_ok=True)

    if not yes:
        typer.confirm(
            "Cela va générer de nouveaux secrets. Continuer ?", abort=True
        )

    # Vault key: 32 random bytes → base64url (no padding)
    vault_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    _write_secret(sdir / "vault-key.txt", vault_key + "\n")

    # Age recipient + key pair — requires `age-keygen` on PATH
    if shutil.which("age-keygen"):
        key_path = sdir / "age.key"
        _refuse_overwrite(key_path)
        subprocess.run(
            ["age-keygen", "-o", str(key_path)], check=True, capture_output=True
        )
        if os.name == "posix":
            os.chmod(key_path, 0o600)
        pub = subprocess.run(
            ["age-keygen", "-y", str(key_path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        _write_secret(sdir / "age-recipient.txt", pub + "\n")
    else:
        typer.echo(
            "warning: `age-keygen` not found on PATH. Skipping age key "
            "generation — backups will fail until you provide "
            "docker/secrets/age-recipient.txt manually.",
            err=True,
        )

    # Bearer tokens: empty file — operator adds via `piighost token create`
    (sdir / "bearer-tokens.txt").touch()
    if os.name == "posix":
        os.chmod(sdir / "bearer-tokens.txt", 0o600)

    # .env from .env.example
    env_example = Path(".env.example")
    env_file = Path(".env")
    if env_example.exists() and not env_file.exists():
        env_file.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
        typer.echo(f"created {env_file} from template")

    typer.echo("piighost docker init: done.")


@app.command("status")
def status() -> None:
    """Affiche l'état des conteneurs, dernière sauvegarde, mises à jour disponibles."""
    # List running containers
    try:
        out = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        typer.echo(f"docker compose unavailable: {exc}", err=True)
        raise typer.Exit(code=1)

    services = [json.loads(line) for line in out.splitlines() if line.strip()]
    for s in services:
        typer.echo(f"  {s.get('Service', '?'):20s}  {s.get('State', '?')}")

    # Last backup
    backups = sorted(Path("backups").glob("piighost-*.tar.age"))
    if backups:
        typer.echo(f"last backup: {backups[-1].name}")
    else:
        typer.echo("last backup: none")

    # Update availability
    uaf = Path("/var/lib/piighost/update-available.json")
    if uaf.exists():
        info = json.loads(uaf.read_text(encoding="utf-8"))
        typer.echo(
            f"update available: {info['tag']} {info['installed']} -> {info['latest']}"
        )
```

- [ ] **Step 3: Register in `src/piighost/cli/main.py`**

Open `src/piighost/cli/main.py`, find the `app = typer.Typer(...)` block, and
add:

```python
from piighost.cli.docker_cmd import app as docker_app
app.add_typer(docker_app, name="docker")
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

```bash
git add src/piighost/cli/docker_cmd.py src/piighost/cli/main.py tests/unit/cli/test_docker_cmd.py
git commit -m "feat(cli): piighost docker init/status subcommands"
```

---

## Task 14: `piighost self-update` CLI subcommand

**Files:**
- Create: `src/piighost/cli/self_update.py`
- Modify: `src/piighost/cli/main.py`
- Create: `tests/unit/cli/test_self_update.py`
- Modify: `pyproject.toml` (add `[project.optional-dependencies].docker = ["httpx>=0.28", "pyyaml>=6"]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/cli/test_self_update.py
"""`piighost self-update` rewrites compose digests after verifying signatures."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from piighost.cli.main import app


COMPOSE_BEFORE = """\
services:
  piighost-mcp:
    image: ghcr.io/jamon8888/hacienda-ghost@sha256:OLDDIGEST
  piighost-daemon:
    image: ghcr.io/jamon8888/hacienda-ghost@sha256:OLDDIGEST
"""


@patch("piighost.cli.self_update._fetch_latest_digest")
@patch("piighost.cli.self_update._verify_cosign_signature")
def test_self_update_rewrites_digests_on_success(
    mock_verify, mock_fetch, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(COMPOSE_BEFORE)

    mock_fetch.return_value = "sha256:NEWDIGEST"
    mock_verify.return_value = True

    runner = CliRunner()
    result = runner.invoke(app, ["self-update", "--yes"])
    assert result.exit_code == 0, result.stdout
    text = compose.read_text()
    assert "NEWDIGEST" in text
    assert "OLDDIGEST" not in text


@patch("piighost.cli.self_update._fetch_latest_digest")
@patch("piighost.cli.self_update._verify_cosign_signature")
def test_self_update_aborts_on_signature_failure(
    mock_verify, mock_fetch, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    compose = tmp_path / "docker-compose.yml"
    compose.write_text(COMPOSE_BEFORE)

    mock_fetch.return_value = "sha256:NEWDIGEST"
    mock_verify.return_value = False   # signature verification failed

    runner = CliRunner()
    result = runner.invoke(app, ["self-update", "--yes"])
    assert result.exit_code != 0
    # Compose file must be untouched
    assert compose.read_text() == COMPOSE_BEFORE
```

- [ ] **Step 2: Write `src/piighost/cli/self_update.py`**

```python
"""`piighost self-update` — safe, signature-verified image updates."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import typer

try:
    import httpx
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore[assignment]

app = typer.Typer(name="self-update", help="Met à jour les images Docker de manière sûre.")

DIGEST_RE = re.compile(r"(ghcr\.io/jamon8888/hacienda-ghost)@sha256:([0-9a-f]{64})")
DEFAULT_IMAGE = "ghcr.io/jamon8888/hacienda-ghost"


def _fetch_latest_digest(image: str, tag: str) -> str:
    """Return the sha256 digest of the latest image+tag from GHCR."""
    if httpx is None:
        raise RuntimeError("httpx not installed; run `pip install piighost[docker]`")

    host, name = image.split("/", 1)
    tok = httpx.get(
        f"https://{host}/token",
        params={"service": host, "scope": f"repository:{name}:pull"},
        timeout=10,
    ).json().get("token", "")
    r = httpx.get(
        f"https://{host}/v2/{name}/manifests/{tag}",
        headers={
            "Accept": "application/vnd.oci.image.index.v1+json, "
                      "application/vnd.docker.distribution.manifest.v2+json",
            "Authorization": f"Bearer {tok}" if tok else "",
        },
        timeout=10,
    )
    r.raise_for_status()
    digest = r.headers.get("Docker-Content-Digest", "")
    if not digest.startswith("sha256:"):
        raise RuntimeError(f"unexpected digest format: {digest!r}")
    return digest


def _verify_cosign_signature(image_ref: str) -> bool:
    """Run `cosign verify --certificate-identity-regexp ...`."""
    if not shutil.which("cosign"):
        typer.echo(
            "warning: cosign not found; skipping signature verification",
            err=True,
        )
        return True   # permissive — warn but don't fail
    try:
        subprocess.run(
            [
                "cosign", "verify",
                "--certificate-identity-regexp", r"https://github\.com/jamon8888/.*",
                "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
                image_ref,
            ],
            capture_output=True,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        typer.echo(f"cosign verification failed: {exc.stderr.decode(errors='replace')}", err=True)
        return False


@app.callback(invoke_without_command=True)
def self_update(
    tag: str = typer.Option("slim", help="Tag image: slim ou full."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Ne pas demander confirmation."),
) -> None:
    """Met à jour `docker-compose.yml` avec le dernier digest signé."""
    compose = Path("docker-compose.yml")
    if not compose.exists():
        typer.echo("docker-compose.yml not found in current directory", err=True)
        raise typer.Exit(code=2)

    latest = _fetch_latest_digest(DEFAULT_IMAGE, tag)
    typer.echo(f"latest {tag} digest: {latest}")

    if not _verify_cosign_signature(f"{DEFAULT_IMAGE}@{latest}"):
        typer.echo("aborting: signature verification failed", err=True)
        raise typer.Exit(code=3)

    text = compose.read_text(encoding="utf-8")
    new_text = DIGEST_RE.sub(lambda m: f"{m.group(1)}@{latest}", text)
    if new_text == text:
        typer.echo("no digest references updated (already latest?)")
        raise typer.Exit(code=0)

    if not yes:
        typer.confirm("Écrire ces changements dans docker-compose.yml ?", abort=True)

    compose.write_text(new_text, encoding="utf-8")
    typer.echo("docker-compose.yml updated. Run `docker compose pull && docker compose up -d` to apply.")
```

- [ ] **Step 3: Register in `main.py`**

```python
from piighost.cli.self_update import app as self_update_app
app.add_typer(self_update_app, name="self-update")
```

- [ ] **Step 4: Add `docker` extras to `pyproject.toml`**

```toml
[project.optional-dependencies]
# ... existing groups ...
docker = [
    "httpx>=0.28",
    "pyyaml>=6",
]
```

- [ ] **Step 5: Run tests — expect pass**

- [ ] **Step 6: Commit**

```bash
git add src/piighost/cli/self_update.py src/piighost/cli/main.py tests/unit/cli/test_self_update.py pyproject.toml
git commit -m "feat(cli): piighost self-update with cosign-verified digests"
```

---

## Task 15: GitHub Actions workflow — build, sign, SBOM, publish

**Files:**
- Create: `.github/workflows/docker.yml`

- [ ] **Step 1: Write `.github/workflows/docker.yml`**

```yaml
name: Docker

on:
  push:
    branches: [master]
    tags: ["v*"]
  pull_request:
    paths:
      - "docker/**"
      - "docker-compose*.yml"
      - "Dockerfile"
      - ".github/workflows/docker.yml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write
  id-token: write   # OIDC for cosign keyless signing

env:
  REGISTRY: ghcr.io
  IMAGE: ghcr.io/${{ github.repository }}

jobs:
  build-and-sign:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        target: [slim, full]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-qemu-action@v3
      - uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build & push (multi-arch)
        id: build
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/Dockerfile
          target: ${{ matrix.target }}
          platforms: linux/amd64,linux/arm64
          push: true
          tags: |
            ${{ env.IMAGE }}:${{ matrix.target }}
            ${{ env.IMAGE }}:${{ matrix.target }}-${{ github.sha }}
          cache-from: type=gha,scope=${{ matrix.target }}
          cache-to: type=gha,mode=max,scope=${{ matrix.target }}

      - name: Size guardrail
        run: |
          digest="${{ steps.build.outputs.digest }}"
          size=$(docker buildx imagetools inspect "${{ env.IMAGE }}@${digest}" --format '{{ .Manifest.Manifests }}' \
                 | tr ' ' '\n' | grep -oE '"size":[0-9]+' | head -1 | cut -d: -f2)
          limit=$([[ "${{ matrix.target }}" == "slim" ]] && echo 734003200 || echo 4831838208)  # 700 MB / 4.5 GB
          if (( size > limit )); then
            echo "::error::${{ matrix.target }} image exceeds size limit: $size > $limit"
            exit 1
          fi

      - name: Install cosign
        uses: sigstore/cosign-installer@v3

      - name: Cosign sign (keyless)
        env:
          COSIGN_EXPERIMENTAL: "true"
        run: |
          cosign sign --yes "${{ env.IMAGE }}@${{ steps.build.outputs.digest }}"

      - name: Install syft
        uses: anchore/sbom-action/download-syft@v0

      - name: Generate and attach SBOM
        run: |
          syft "${{ env.IMAGE }}@${{ steps.build.outputs.digest }}" \
               -o spdx-json=sbom-${{ matrix.target }}.spdx.json
          cosign attest --yes \
                 --predicate sbom-${{ matrix.target }}.spdx.json \
                 --type spdxjson \
                 "${{ env.IMAGE }}@${{ steps.build.outputs.digest }}"
          echo "digest_${{ matrix.target }}=${{ steps.build.outputs.digest }}" >> $GITHUB_OUTPUT

  smoke-test:
    needs: build-and-sign
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Prepare secrets
        run: |
          mkdir -p docker/secrets
          python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))" > docker/secrets/vault-key.txt
          age-keygen -o docker/secrets/age.key
          age-keygen -y docker/secrets/age.key > docker/secrets/age-recipient.txt
          chmod 600 docker/secrets/*.txt docker/secrets/*.key
      - name: Start workstation profile
        run: |
          cp .env.example .env
          docker compose --profile workstation up -d --wait
      - name: Run E2E smoke
        run: |
          python -m pytest tests/e2e/test_docker_smoke.py -v
      - name: Tear down
        if: always()
        run: docker compose down -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/docker.yml
git commit -m "ci(docker): multi-arch build, cosign sign, SBOM publish, smoke test"
```

---

## Task 16: E2E smoke test — `tests/e2e/test_docker_smoke.py`

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/test_docker_smoke.py`

- [ ] **Step 1: Write the E2E test**

```python
"""End-to-end smoke: compose up → call MCP → anonymize → compose down.

Requires a running `docker compose --profile workstation up -d` stack.
CI manages the lifecycle; locally, run:

    docker compose --profile workstation up -d --wait
    pytest tests/e2e/test_docker_smoke.py -v
"""
from __future__ import annotations

import os
import time

import httpx
import pytest

MCP_URL = os.environ.get("PIIGHOST_MCP_URL", "http://127.0.0.1:8765")


@pytest.fixture(scope="module")
def client():
    # Wait up to 30s for the stack to become ready
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = httpx.get(f"{MCP_URL}/healthz", timeout=2)
            if r.status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    else:
        pytest.fail(f"MCP at {MCP_URL} never became ready")
    with httpx.Client(base_url=MCP_URL, timeout=10) as c:
        yield c


def test_mcp_list_tools_includes_anonymize(client: httpx.Client) -> None:
    r = client.post("/mcp/tools/list", json={})
    r.raise_for_status()
    names = {t["name"] for t in r.json().get("tools", [])}
    assert "anonymize_text" in names


def test_anonymize_text_strips_pii(client: httpx.Client) -> None:
    r = client.post(
        "/mcp/tools/call",
        json={
            "name": "anonymize_text",
            "arguments": {"text": "Alice habite à Paris."},
        },
    )
    r.raise_for_status()
    out = r.json()
    anonymized = out["content"][0]["text"]
    assert "Alice" not in anonymized
```

- [ ] **Step 2: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/test_docker_smoke.py
git commit -m "test(e2e): docker workstation-profile smoke test"
```

---

## Task 17: README.fr.md — `## Installation Docker` section (French only, no English)

**Files:**
- Modify: `README.fr.md`

The new section goes **after** existing `## Installation dans Claude Desktop`
and **before** `## Utilisation`. Entirely in French. No English words except
technical identifiers that can't be translated (`docker`, `Caddyfile`, image
tags, `make install`, etc.).

- [ ] **Step 1: Locate insertion point**

Look for the line `## Installation dans Claude Desktop` in `README.fr.md`,
scan forward to the next `##` heading, insert the new section immediately
before it.

- [ ] **Step 2: Write the French Docker section**

```markdown
---

## Installation Docker

Pour les cabinets et les professionnels qui préfèrent une installation
isolée et reproductible, piighost fournit une pile Docker complète avec
deux profils et des images signées.

### Prérequis

- **Docker Engine** ≥ 24, avec `docker compose` v2 (`docker compose version`)
- **4 Go de RAM** et **10 Go de disque** pour l'image `slim`
- **16 Go de RAM** et **40 Go de disque** pour l'image `full` (NER GLiNER, embeddings locaux)
- Un nom de domaine pointant vers la machine (profil `server` uniquement, pour Let's Encrypt)

### Démarrage « poste de travail »

Pour un professionnel solo utilisant Claude Desktop sur son ordinateur :

```bash
git clone https://github.com/jamon8888/hacienda-ghost
cd hacienda-ghost

# Génère les secrets (clé de coffre, paire age, fichier .env)
make install

# Démarre la pile en profil « poste de travail »
make up
```

Claude Desktop se connecte ensuite à `http://127.0.0.1:8765` (MCP exposé
uniquement sur la boucle locale, aucun port ouvert à l'extérieur).

Pour vérifier l'état :

```bash
make status
```

### Déploiement « serveur de cabinet »

Pour un cabinet avec plusieurs postes clients derrière un pare-feu :

```bash
# Adapter le fichier .env
sed -i 's/COMPOSE_PROFILES=workstation/COMPOSE_PROFILES=server/' .env
sed -i 's/PIIGHOST_PUBLIC_HOSTNAME=.*/PIIGHOST_PUBLIC_HOSTNAME=piighost.cabinet.local/' .env
sed -i 's/CADDY_EMAIL=.*/CADDY_EMAIL=dpo@cabinet.local/' .env

# Créer un premier jeton client
docker compose run --rm piighost-daemon \
    piighost token create --name "poste-durand"
# → copier le jeton affiché dans la configuration Claude Desktop du poste

# Démarrer
make up-server
```

Caddy obtient automatiquement un certificat TLS via Let's Encrypt et
applique l'authentification par jeton bearer. Pour passer en mTLS :

```bash
echo "PIIGHOST_AUTH=mtls" >> .env
make up-server
```

### Overlays optionnels — souveraineté totale

Pour supprimer toute dépendance à des services cloud externes
(embeddings via Mistral, LLM via Anthropic/OpenAI), activez les overlays :

```bash
# Embedder local (sentence-transformers) — l'indexation RAG devient hors-ligne
docker compose --profile server \
    -f docker-compose.yml \
    -f docker-compose.embedder.yml \
    up -d

# Stack souveraine complète : anonymisation + embedder + LLM (Ollama)
make up-sovereign
```

Le réseau `piighost-llm` est marqué `internal: true` : Ollama ne peut
communiquer qu'avec piighost, jamais avec Internet.

### Sauvegardes

Une sauvegarde quotidienne chiffrée avec `age` est activée par défaut
(02:30 locale). Les archives atterrissent dans `./backups/` au format
`piighost-AAAA-MM-JJ.tar.age` avec une rétention de **7 jours + 4 semaines**.

Sauvegarde immédiate :

```bash
make backup
```

Restauration depuis une archive :

```bash
make restore BACKUP=./backups/piighost-2026-04-20.tar.age
```

La clé privée age (`docker/secrets/age.key`) doit être conservée **hors
de la machine** : papier, HSM, ou gestionnaire de mots de passe d'un
associé. Perdre cette clé rend les sauvegardes irrécupérables.

Pour désactiver la sauvegarde automatique (si vous utilisez déjà Restic,
Borg, ou une solution entreprise) :

```bash
COMPOSE_PROFILES=workstation,no-backup make up
```

### Mises à jour

Les images sont épinglées par **digest SHA-256** dans
`docker-compose.yml`, jamais par tag mutable. Pour mettre à jour :

```bash
piighost self-update         # ou : make update
docker compose pull
docker compose up -d
```

Cette commande :

1. Récupère le dernier digest depuis GHCR
2. **Vérifie la signature `cosign`** (OIDC keyless, émise par GitHub Actions)
3. Affiche le diff et demande confirmation
4. Réécrit `docker-compose.yml` avec le nouveau digest

Pour revenir en arrière : `git revert` sur le commit de mise à jour puis
`docker compose up -d`.

Un sidecar `piighost-update-notify` vérifie chaque nuit la présence
d'une nouvelle version et écrit un message sur stderr ainsi qu'un
fichier `/var/lib/piighost/update-available.json`. Il ne touche jamais
à la pile en cours.

### Vérification manuelle de la signature d'image

```bash
cosign verify \
    --certificate-identity-regexp 'https://github\.com/jamon8888/.*' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/jamon8888/hacienda-ghost:slim
```

La commande doit afficher une signature valide. En cas d'échec, **ne
déployez pas l'image** — ouvrez un ticket immédiatement.

### Posture de sécurité

Chaque conteneur de la pile applique par défaut :

- **Utilisateur non-root** (UID 10001)
- **Système de fichiers en lecture seule** (`read_only: true`, `tmpfs` pour `/tmp` et `/run`)
- **Toutes les capacités Linux abandonnées** (`cap_drop: [ALL]`)
- **`no-new-privileges: true`** et profil seccomp par défaut
- **Secrets via Docker secrets** — jamais via variables d'environnement (éviterait les fuites via `docker inspect`)
- **Base distroless** (`slim`) ou Chainguard (`full`) — pas de shell, pas de gestionnaire de paquets, surface d'attaque minimale
- **Réseau interne** (`internal: true`) pour le daemon et l'overlay LLM — aucun egress

### Dépannage

| Symptôme | Cause probable | Remède |
|---|---|---|
| `make up` échoue sur `secrets` | `docker/secrets/vault-key.txt` manquant | `make install` |
| MCP inaccessible depuis Claude Desktop | Pare-feu bloque 8765 (workstation) | Vérifier `netstat -an \| grep 8765` |
| Caddy ne récupère pas de certificat TLS | DNS incorrect ou port 80/443 bloqué | `docker compose logs caddy` |
| Image trop grosse au téléchargement | Utilisation de `full` au lieu de `slim` | `PIIGHOST_TAG=slim make up` |
| Sauvegarde échoue avec « recipient file is empty » | `docker/secrets/age-recipient.txt` vide | Régénérer via `age-keygen -y age.key > age-recipient.txt` |

Logs détaillés :

```bash
docker compose logs -f piighost-mcp piighost-daemon
```

Remise à zéro complète (⚠ destructive — supprime toutes les données) :

```bash
make clean
```
```

- [ ] **Step 3: Update the README's table of contents**

Find the existing TOC near the top and add the line:

```markdown
- [Installation Docker](#installation-docker)
```

Place it immediately after `[Installation dans Claude Desktop]` and before
`[Utilisation]`.

- [ ] **Step 4: Verify no English crept in**

```bash
# Spot-check for English-only words that shouldn't appear in the French section
grep -n -E "\b(backup|install|update|server|client|workstation|security)\b" README.fr.md | \
    grep -v "^#" | head
```

Every match inside the new Docker section must be either a technical
identifier (file path, command name, Docker concept) or absent from French
vocabulary. Replace any prose English with French equivalents.

- [ ] **Step 5: Commit**

```bash
git add README.fr.md
git commit -m "docs(fr): Installation Docker — section française complète"
```

---

## Task 18: Final integration — smoke run, full test suite, push

- [ ] **Step 1: Run the full Python test suite**

```
.venv/Scripts/python.exe -m pytest --no-cov -q
```

Expected: 774 passed + N new tests added in this plan (~25-30 new tests) all green, still 2 skipped.

- [ ] **Step 2: Lint the Dockerfile**

```bash
docker run --rm -i hadolint/hadolint:latest-debian hadolint --config docker/hadolint.yaml - < docker/Dockerfile
```

Expected: no warnings above threshold.

- [ ] **Step 3: Validate compose files**

```bash
docker compose --profile workstation config -q
docker compose --profile server config -q
docker compose -f docker-compose.yml -f docker-compose.embedder.yml --profile workstation config -q
docker compose -f docker-compose.yml -f docker-compose.llm.yml --profile workstation config -q
```

All four must exit 0 with no output.

- [ ] **Step 4: Local smoke test — workstation profile**

```bash
make install
make up
sleep 15
curl -sSf http://127.0.0.1:8765/healthz
make down
```

- [ ] **Step 5: Push to origin, let CI run the full docker workflow**

```bash
git push origin master
```

Monitor `.github/workflows/docker.yml` — it must build `slim` and `full` for
both architectures, sign, attach SBOMs, publish, and pass the E2E smoke
before we call this done.

- [ ] **Step 6: Final commit — regenerate docker-compose.yml digests**

After CI publishes the first signed images, run `piighost self-update`
locally to pin the initial digests into `docker-compose.yml`:

```bash
piighost self-update --yes --tag slim
piighost self-update --yes --tag full
git add docker-compose.yml
git commit -m "feat(docker): pin initial slim+full digests from CI"
git push origin master
```

- [ ] **Step 7: Push to `jamon` remote**

```bash
git push jamon master
```

Pre-push hook runs the full suite; expect it to stay green.

---

## Implementation order summary

| # | Task | Roughly |
|---|---|---|
| 1 | Scaffold `docker/` + ignore rules | 10 min |
| 2 | Dockerfile `slim` target | 30 min |
| 3 | Dockerfile `full` target | 20 min |
| 4 | `entrypoint.sh` + tests | 20 min |
| 5 | `docker-compose.yml` workstation + hardening | 40 min |
| 6 | Server profile + Caddy | 30 min |
| 7 | Backup/restore scripts | 30 min |
| 8 | Update-check sidecar | 20 min |
| 9 | Embedder overlay | 10 min |
| 10 | LLM overlay | 10 min |
| 11 | Makefile | 10 min |
| 12 | Secret templates | 10 min |
| 13 | `piighost docker init/status` | 40 min |
| 14 | `piighost self-update` | 45 min |
| 15 | GHA workflow | 40 min |
| 16 | E2E smoke test | 20 min |
| 17 | French README section | 45 min |
| 18 | Final integration + push | 30 min |

Total: ~8 hours of focused work, spread across ~18 commits. Fits one
afternoon for a single agentic worker using subagent-driven-development.
