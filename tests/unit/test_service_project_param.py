import asyncio
import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


def test_anonymize_accepts_project(svc):
    result = asyncio.run(svc.anonymize("Alice lives here", project="client-a"))
    assert len(result.entities) >= 1


def test_rehydrate_accepts_project(svc):
    r = asyncio.run(svc.anonymize("Alice", project="client-a"))
    rehydrated = asyncio.run(svc.rehydrate(r.anonymized, project="client-a"))
    assert rehydrated.unknown_tokens == []


def test_query_accepts_project(svc, tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("Alice works in Paris")
    asyncio.run(svc.index_path(doc, project="client-a"))
    result = asyncio.run(svc.query("Paris", project="client-a", k=5))
    assert result.k == 5


def test_vault_stats_accepts_project(svc):
    asyncio.run(svc.anonymize("Alice", project="client-a"))
    stats = asyncio.run(svc.vault_stats(project="client-a"))
    assert stats.total >= 1


def test_default_project_still_works_without_param(svc):
    """Backward compat: methods default to project='default'."""
    result = asyncio.run(svc.anonymize("Alice lives here"))
    assert len(result.entities) >= 1


def test_index_path_auto_derives_project_when_none(svc, tmp_path):
    """When project is None and path has a derivable name, use that."""
    docs = tmp_path / "my-project" / "contracts"
    docs.mkdir(parents=True)
    (docs / "doc.txt").write_text("Alice works in Paris")
    report = asyncio.run(svc.index_path(docs))
    assert report.project == "my-project"
