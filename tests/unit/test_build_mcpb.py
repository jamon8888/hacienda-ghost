import hashlib
import json
import os
import zipfile
from pathlib import Path
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[2]


def _root_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    return data["project"]["version"]


def test_build_script_importable():
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_mcpb  # noqa: F401


def test_build_core_produces_valid_zip(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_mcpb

    monkeypatch.setattr(build_mcpb, "DIST", tmp_path)

    version = _root_version()
    out = build_mcpb.build("core", version)
    assert out.exists()

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "manifest.json" in names
        assert "pyproject.toml" in names
        assert "src/server.py" in names
        assert "icon.png" in names

        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["name"] == "piighost-core"
        assert manifest["version"] == version

        pyproject_text = zf.read("pyproject.toml").decode("utf-8")
        assert f'piighost[mcp]=={version}' in pyproject_text


def test_build_full_produces_valid_zip(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_mcpb

    monkeypatch.setattr(build_mcpb, "DIST", tmp_path)

    version = _root_version()
    out = build_mcpb.build("full", version)
    assert out.exists()

    with zipfile.ZipFile(out) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["name"] == "piighost-full"
        assert manifest["version"] == version

        pyproject_text = zf.read("pyproject.toml").decode("utf-8")
        assert f'piighost[mcp,index,gliner2]=={version}' in pyproject_text


def test_build_both_variants(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_mcpb

    monkeypatch.setattr(build_mcpb, "DIST", tmp_path)
    version = _root_version()

    core_out = build_mcpb.build("core", version)
    full_out = build_mcpb.build("full", version)

    assert core_out.exists()
    assert full_out.exists()
    assert core_out != full_out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_deterministic(variant: str, tmp_path: Path, monkeypatch) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_mcpb

    version = _root_version()
    icon = ROOT / "bundles" / variant / "icon.png"

    dist_a = tmp_path / "a"
    dist_b = tmp_path / "b"
    dist_a.mkdir()
    dist_b.mkdir()

    monkeypatch.setattr(build_mcpb, "DIST", dist_a)
    out_a = build_mcpb.build(variant, version)
    hash_a = _sha256(out_a)

    st = icon.stat()
    os.utime(icon, (st.st_atime + 5, st.st_mtime + 5))

    monkeypatch.setattr(build_mcpb, "DIST", dist_b)
    out_b = build_mcpb.build(variant, version)
    hash_b = _sha256(out_b)

    assert hash_a == hash_b, f"{variant} build is not deterministic: {hash_a} != {hash_b}"


def test_build_core_is_deterministic(tmp_path, monkeypatch):
    _assert_deterministic("core", tmp_path, monkeypatch)


def test_build_full_is_deterministic(tmp_path, monkeypatch):
    _assert_deterministic("full", tmp_path, monkeypatch)
