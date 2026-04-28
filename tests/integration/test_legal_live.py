"""Live OpenLégi smoke — hits real https://mcp.openlegi.fr.

Gated by RUN_LIVE_OPENLEGI=1 env var AND PIIGHOST_PISTE_TOKEN env var.
Skipped in normal CI. Run manually after major OpenLégi changes or
when shipping a release that depends on the real endpoint shape.
"""
from __future__ import annotations

import asyncio
import os

import pytest

from piighost.service.config import ServiceConfig, RerankerSection, OpenLegiSection
from piighost.service.core import PIIGhostService
from piighost.service.credentials import CredentialsService


pytestmark = pytest.mark.live


def _skip_if_not_live():
    if os.environ.get("RUN_LIVE_OPENLEGI") != "1":
        pytest.skip("Set RUN_LIVE_OPENLEGI=1 to enable live OpenLégi tests")
    if not os.environ.get("PIIGHOST_PISTE_TOKEN"):
        pytest.skip("Set PIIGHOST_PISTE_TOKEN=<your token> to enable live tests")


@pytest.fixture()
def vault_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return tmp_path / "vault"


def test_live_search_legal_for_article_1240(vault_dir, monkeypatch):
    """Real OpenLégi must return at least one hit for article 1240 du Code civil."""
    _skip_if_not_live()

    CredentialsService().set_openlegi_token(os.environ["PIIGHOST_PISTE_TOKEN"])

    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    hits = asyncio.run(svc.legal_search(query="1240", source="code", max_results=3))

    # At least one real hit (Art. 1240 — responsabilité délictuelle)
    real_hits = [h for h in hits if h.get("source") != "_error"]
    assert real_hits, f"no real hits returned: {hits}"

    # Each hit has the expected shape
    for h in real_hits:
        assert "title" in h
        assert h.get("source") == "code"

    asyncio.run(svc.close())


def test_live_verify_legal_ref_for_known_article(vault_dir, monkeypatch):
    """A real, known article must return VERIFIE_EXACT."""
    _skip_if_not_live()

    CredentialsService().set_openlegi_token(os.environ["PIIGHOST_PISTE_TOKEN"])

    cfg = ServiceConfig(
        reranker=RerankerSection(backend="none"),
        openlegi=OpenLegiSection(enabled=True),
    )
    svc = asyncio.run(PIIGhostService.create(vault_dir=vault_dir, config=cfg))

    result = asyncio.run(svc.legal_verify_ref(ref={
        "ref_id": 1, "ref_type": "ARTICLE_CODE",
        "raw_text": "article 1240 du Code civil",
        "numero": "1240", "code": "Code civil", "position": 0,
    }))

    assert result["status"] == "VERIFIE_EXACT", result
    asyncio.run(svc.close())
