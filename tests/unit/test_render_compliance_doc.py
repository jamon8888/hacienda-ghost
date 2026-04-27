"""Tests for render_compliance_doc — Markdown round-trip is the core gate.

PDF and DOCX paths are skipped if the optional [compliance] extra
isn't installed in the test environment.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    # Isolate the global controller profile (lives under Path.home()) so
    # tests do not pollute the developer's real ~/.piighost/.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Windows
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_render_registre_md(vault_dir, monkeypatch, tmp_path):
    """Generate a registre, render to MD, verify the output contains
    expected markers from the template."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={
            "controller": {"name": "Cabinet Demo", "profession": "avocat"},
            "defaults": {"finalites": ["Conseil juridique"]},
        }, scope="global",
    ))
    asyncio.run(svc.create_project("render-md"))
    register = asyncio.run(svc.processing_register(project="render-md"))

    output = tmp_path / "registre.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md",
        profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "Cabinet Demo" in content
    assert "render-md" in content
    asyncio.run(svc.close())


def test_render_dpia_md(vault_dir, monkeypatch, tmp_path):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("render-dpia"))
    dpia = asyncio.run(svc.dpia_screening(project="render-dpia"))

    output = tmp_path / "dpia.md"
    asyncio.run(svc.render_compliance_doc(
        data=dpia.model_dump(),
        format="md",
        profile="generic",
        output_path=str(output),
    ))
    content = output.read_text(encoding="utf-8")
    # The DPIA template should include the verdict + CNIL link
    assert dpia.verdict in content
    assert "cnil.fr" in content
    asyncio.run(svc.close())


def test_render_with_avocat_profile_uses_avocat_template(
    vault_dir, monkeypatch, tmp_path,
):
    """Verify profile-specific template selection."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.controller_profile_set(
        profile={"controller": {"name": "Maître X", "profession": "avocat"}},
        scope="global",
    ))
    asyncio.run(svc.create_project("render-av"))
    register = asyncio.run(svc.processing_register(project="render-av"))
    output = tmp_path / "registre_avocat.md"
    asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md",
        profile="avocat",
        output_path=str(output),
    ))
    content = output.read_text(encoding="utf-8")
    # Avocat template includes a specific mention
    assert "barreau" in content.lower() or "CNB" in content
    asyncio.run(svc.close())


def test_render_pdf_skipped_when_extra_missing(vault_dir, monkeypatch, tmp_path):
    """If weasyprint isn't installed, render(pdf) raises a clear ImportError."""
    try:
        import weasyprint  # noqa: F401
        pytest.skip("weasyprint installed — this test only runs without it")
    except ImportError:
        pass
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("render-no-pdf"))
    register = asyncio.run(svc.processing_register(project="render-no-pdf"))
    with pytest.raises((ImportError, RuntimeError)):
        asyncio.run(svc.render_compliance_doc(
            data=register.model_dump(), format="pdf",
            profile="generic", output_path=str(tmp_path / "out.pdf"),
        ))
    asyncio.run(svc.close())
