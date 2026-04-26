from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _root_version() -> str:
    if sys.version_info >= (3, 11):
        import tomllib
    else:
        import tomli as tomllib  # type: ignore
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


@pytest.mark.parametrize("variant", ["core", "full"])
def test_bundle_manifest_version_matches_pyproject(variant):
    bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
    if not bundle.exists():
        pytest.skip(f"{bundle} not built; run scripts/build_mcpb.py first")
    with zipfile.ZipFile(bundle) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["version"] == _root_version()


@pytest.mark.parametrize("variant,extras", [("core", "mcp"), ("full", "mcp,index,gliner2")])
def test_bundle_pyproject_pins_correct_extras(variant, extras):
    bundle = ROOT / "dist" / "mcpb" / f"piighost-{variant}.mcpb"
    if not bundle.exists():
        pytest.skip(f"{bundle} not built; run scripts/build_mcpb.py first")
    with zipfile.ZipFile(bundle) as zf:
        body = zf.read("pyproject.toml").decode("utf-8")
    assert f"piighost[{extras}]=={_root_version()}" in body
