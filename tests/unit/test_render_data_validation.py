"""Pydantic validation gate for render_compliance_doc.

The renderer must reject dicts that don't match a known compliance model.
This blocks adversarial input from a poisoned RAG context.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from piighost.service.config import ServiceConfig, RerankerSection
from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    cfg = ServiceConfig(reranker=RerankerSection(backend="none"))
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))


def test_render_rejects_arbitrary_dict(vault_dir, monkeypatch):
    """A dict that doesn't match any compliance model is rejected."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-test"))
    output = Path.home() / ".piighost" / "exports" / "out.md"
    with pytest.raises(ValueError, match="(does not match|invalid|unknown)"):
        asyncio.run(svc.render_compliance_doc(
            data={"foo": "bar", "controller": {"name": "<script>alert(1)</script>"}},
            format="md", profile="generic",
            output_path=str(output),
        ))
    asyncio.run(svc.close())


def test_render_accepts_valid_processing_register(vault_dir, monkeypatch):
    """A real ProcessingRegister.model_dump() passes validation."""
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-ok"))
    register = asyncio.run(svc.processing_register(project="validation-ok"))
    output = Path.home() / ".piighost" / "exports" / "registre.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=register.model_dump(),
        format="md", profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    asyncio.run(svc.close())


def test_render_accepts_valid_dpia_screening(vault_dir, monkeypatch):
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-dpia"))
    dpia = asyncio.run(svc.dpia_screening(project="validation-dpia"))
    output = Path.home() / ".piighost" / "exports" / "dpia.md"
    result = asyncio.run(svc.render_compliance_doc(
        data=dpia.model_dump(),
        format="md", profile="generic",
        output_path=str(output),
    ))
    assert result.path == str(output)
    asyncio.run(svc.close())


def test_render_rejects_extra_keys_at_top_level(vault_dir, monkeypatch):
    """Extra top-level keys outside the model schema are rejected.

    This catches a class of attack where the attacker crafts a dict that
    LOOKS like a ProcessingRegister but smuggles extra fields (e.g.
    `__html_payload`) that happen to be referenced by a malicious
    user-override template.
    """
    pytest.importorskip("jinja2")
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("validation-extra"))
    register = asyncio.run(svc.processing_register(project="validation-extra"))
    poisoned = register.model_dump()
    poisoned["__html_payload"] = "<script>alert(1)</script>"
    output = Path.home() / ".piighost" / "exports" / "poisoned.md"
    with pytest.raises(ValueError):
        asyncio.run(svc.render_compliance_doc(
            data=poisoned,
            format="md", profile="generic",
            output_path=str(output),
        ))
    asyncio.run(svc.close())
