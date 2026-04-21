"""Build piighost-core.mcpb and piighost-full.mcpb from bundles/{core,full}/."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parent.parent
BUNDLES = ROOT / "bundles"
DIST = ROOT / "dist" / "mcpb"

_EXTRAS = {"core": "mcp", "full": "mcp,index,gliner2"}


def _read_root_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


def _render_manifest(variant: str, version: str) -> str:
    manifest_path = BUNDLES / variant / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["version"] = version
    return json.dumps(manifest, indent=2) + "\n"


def _render_pyproject(variant: str, version: str) -> str:
    extras = _EXTRAS[variant]
    return (
        f'[project]\n'
        f'name = "piighost-{variant}-bundle"\n'
        f'version = "{version}"\n'
        f'description = "Embedded dependencies for piighost-{variant} MCPB"\n'
        f'requires-python = ">=3.10"\n'
        f'dependencies = [\n'
        f'    "piighost[{extras}]=={version}",\n'
        f']\n'
    )


_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)
_FILE_ATTR = 0o644 << 16


def _zinfo(arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(filename=arcname, date_time=_ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = _FILE_ATTR
    return info


def build(variant: str, version: str) -> Path:
    src = BUNDLES / variant
    out = DIST / f"piighost-{variant}.mcpb"
    out.parent.mkdir(parents=True, exist_ok=True)

    rendered = {
        "manifest.json": _render_manifest(variant, version),
        "pyproject.toml": _render_pyproject(variant, version),
    }

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            arcname = str(path.relative_to(src)).replace("\\", "/")
            if arcname in rendered:
                data = rendered[arcname].encode("utf-8")
            else:
                data = path.read_bytes()
            zf.writestr(_zinfo(arcname), data)
    return out


if __name__ == "__main__":
    version = _read_root_version()
    for variant in ("core", "full"):
        print(f"Built: {build(variant, version)}")
