"""CredentialsService — manages ~/.piighost/credentials.toml.

PISTE token + any future per-service secrets live here, separate
from the descriptive controller.toml. The file is created with
mode 0o600 on POSIX and inherits ACL on Windows.

Public surface:
  - get_openlegi_token() -> str | None    — for daemon-side use
  - set_openlegi_token(token: str)        — wizard / setup skill
  - unset_openlegi_token()                — disable
  - has_openlegi_token() -> bool          — for status checks
  - summary() -> dict                      — non-sensitive report
                                             (controller_profile_get
                                              embeds this; never
                                              returns token text)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import tomllib


def _atomic_write(path: Path, content: str, *, mode: int = 0o600) -> None:
    """Write *content* to *path* atomically with restrictive perms (POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
        if sys.platform != "win32":
            os.chmod(path, mode)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def _serialize(data: dict) -> str:
    """Tiny TOML serialiser for the shapes we use."""
    out: list[str] = []
    for table_name, table in data.items():
        if not isinstance(table, dict):
            continue
        out.append(f"[{table_name}]")
        for k, v in table.items():
            if isinstance(v, str):
                escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                out.append(f'{k} = "{escaped}"')
            elif isinstance(v, bool):
                out.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, (int, float)):
                out.append(f"{k} = {v}")
            else:
                raise TypeError(f"Unsupported type for {table_name}.{k}: {type(v)}")
        out.append("")
    return "\n".join(out).strip() + "\n"


class CredentialsService:
    def __init__(self) -> None:
        self._path = Path.home() / ".piighost" / "credentials.toml"

    def _read(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return tomllib.loads(self._path.read_text("utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        if not data:
            if self._path.exists():
                self._path.unlink()
            return
        _atomic_write(self._path, _serialize(data))

    # OpenLégi --------------------------------------------------------

    def get_openlegi_token(self) -> str | None:
        return self._read().get("openlegi", {}).get("piste_token")

    def has_openlegi_token(self) -> bool:
        return self.get_openlegi_token() is not None

    def set_openlegi_token(self, token: str) -> None:
        data = self._read()
        data.setdefault("openlegi", {})["piste_token"] = token
        self._write(data)

    def unset_openlegi_token(self) -> None:
        data = self._read()
        if "openlegi" in data:
            data["openlegi"].pop("piste_token", None)
            if not data["openlegi"]:
                data.pop("openlegi")
        self._write(data)

    # Public summary --------------------------------------------------

    def summary(self) -> dict:
        """Non-sensitive credentials status. NEVER includes token text."""
        return {
            "openlegi": {"configured": self.has_openlegi_token()},
        }
