"""E2E: multi-project isolation — different tokens, scoped queries, no cross-project rehydrate."""

from __future__ import annotations

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


def test_tokens_differ_across_projects(svc):
    a = asyncio.run(svc.anonymize("Alice works here", project="client-a"))
    b = asyncio.run(svc.anonymize("Alice works here", project="client-b"))
    a_token = a.entities[0].token
    b_token = b.entities[0].token
    assert a_token != b_token


def test_same_value_same_project_same_token(svc):
    a1 = asyncio.run(svc.anonymize("Alice is here", project="client-a"))
    a2 = asyncio.run(svc.anonymize("Then Alice left", project="client-a"))
    assert a1.entities[0].token == a2.entities[0].token


def test_rehydrate_fails_in_wrong_project(svc):
    r = asyncio.run(svc.anonymize("Alice works here", project="client-a"))
    # Ensure client-b exists so rehydrate does not raise ProjectNotFound
    asyncio.run(svc.anonymize("Hello world", project="client-b"))
    rehydrated = asyncio.run(svc.rehydrate(r.anonymized, project="client-b", strict=False))
    assert r.entities[0].token in rehydrated.unknown_tokens
    assert "Alice" not in rehydrated.text


def test_query_scoped_to_project(svc, tmp_path):
    docs_a = tmp_path / "client-a-docs"
    docs_a.mkdir()
    (docs_a / "a.txt").write_text("Alice works on GDPR compliance contracts")

    docs_b = tmp_path / "client-b-docs"
    docs_b.mkdir()
    (docs_b / "b.txt").write_text("Bob handles medical records review")

    asyncio.run(svc.index_path(docs_a, project="client-a"))
    asyncio.run(svc.index_path(docs_b, project="client-b"))

    result_a = asyncio.run(svc.query("GDPR compliance", project="client-a", k=5))
    result_b = asyncio.run(svc.query("GDPR compliance", project="client-b", k=5))

    paths_a = {h.file_path for h in result_a.hits}
    paths_b = {h.file_path for h in result_b.hits}
    assert str(docs_a / "a.txt") in paths_a
    assert str(docs_a / "a.txt") not in paths_b


def test_vault_search_scoped_to_project(svc):
    asyncio.run(svc.anonymize("Alice", project="client-a"))
    asyncio.run(svc.anonymize("Bob", project="client-b"))

    a_results = asyncio.run(svc.vault_search("Alice", project="client-a", reveal=True))
    b_results = asyncio.run(svc.vault_search("Alice", project="client-b", reveal=True))

    assert any(e.original == "Alice" for e in a_results)
    assert not any(e.original == "Alice" for e in b_results)


def test_vault_stats_are_per_project(svc):
    asyncio.run(svc.anonymize("Alice lives in Paris", project="client-a"))
    # Auto-create client-b so vault_stats can look it up without raising ProjectNotFound
    asyncio.run(svc.anonymize("Hello world", project="client-b"))
    a_stats = asyncio.run(svc.vault_stats(project="client-a"))
    b_stats = asyncio.run(svc.vault_stats(project="client-b"))
    assert a_stats.total >= 1
    assert b_stats.total == 0


def test_index_path_auto_derives_project(svc, tmp_path):
    docs = tmp_path / "client-xyz" / "contracts"
    docs.mkdir(parents=True)
    (docs / "contract.txt").write_text("Alice signed the GDPR contract in Paris")

    report = asyncio.run(svc.index_path(docs))
    assert report.project == "client-xyz"

    result = asyncio.run(svc.query("GDPR contract", project="client-xyz", k=5))
    assert len(result.hits) >= 1


def test_list_projects_includes_all_created(svc):
    asyncio.run(svc.anonymize("A", project="client-a"))
    asyncio.run(svc.anonymize("B", project="client-b"))
    projects = asyncio.run(svc.list_projects())
    names = {p.name for p in projects}
    assert {"default", "client-a", "client-b"} <= names
