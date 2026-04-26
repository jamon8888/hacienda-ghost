"""CI helper: assert dist/mcpb/*.mcpb match pyproject.toml version.

Run after every version bump; fails non-zero if a bundle is stale."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]["version"]
    failures: list[str] = []
    for variant in ("core", "full"):
        bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
        if not bundle.exists():
            failures.append(f"missing: {bundle}")
            continue
        with zipfile.ZipFile(bundle) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("version") != version:
            failures.append(
                f"{bundle.name}: manifest version "
                f"{manifest.get('version')!r} != pyproject {version!r}"
            )
    if failures:
        print("MCPB consistency check failed:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"MCPB consistency OK ({version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
