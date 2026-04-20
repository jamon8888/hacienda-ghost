import asyncio

import pytest

from piighost.exceptions import ProjectNotEmpty
from piighost.service.core import PIIGhostService


@pytest.fixture()
def svc(tmp_path, monkeypatch):
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    service = asyncio.run(PIIGhostService.create(vault_dir=tmp_path / "vault"))
    yield service
    asyncio.run(service.close())


def test_list_projects_includes_default(svc):
    projects = asyncio.run(svc.list_projects())
    names = {p.name for p in projects}
    assert "default" in names


def test_create_project(svc):
    info = asyncio.run(svc.create_project("client-a", description="A"))
    assert info.name == "client-a"
    assert info.description == "A"
    assert info.placeholder_salt == "client-a"

    projects = asyncio.run(svc.list_projects())
    assert any(p.name == "client-a" for p in projects)


def test_delete_empty_project(svc):
    asyncio.run(svc.create_project("client-a"))
    result = asyncio.run(svc.delete_project("client-a"))
    assert result is True
    names = {p.name for p in asyncio.run(svc.list_projects())}
    assert "client-a" not in names


def test_delete_default_refused(svc):
    with pytest.raises(ValueError, match="default project cannot be deleted"):
        asyncio.run(svc.delete_project("default"))


def test_delete_nonempty_refused_without_force(svc):
    asyncio.run(svc.anonymize("Alice", project="client-a"))
    with pytest.raises(ProjectNotEmpty):
        asyncio.run(svc.delete_project("client-a"))


def test_delete_nonempty_force_succeeds(svc):
    asyncio.run(svc.anonymize("Alice", project="client-a"))
    result = asyncio.run(svc.delete_project("client-a", force=True))
    assert result is True


def test_lru_eviction_closes_old_services(svc):
    for i in range(10):
        asyncio.run(svc.create_project(f"proj-{i}"))
        asyncio.run(svc.anonymize("Alice", project=f"proj-{i}"))
    assert len(svc._cache) <= PIIGhostService.LRU_SIZE
