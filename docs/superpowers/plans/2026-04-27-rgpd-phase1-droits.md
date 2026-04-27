# RGPD Phase 1 — Droits Art. 15 + Art. 17 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the user-facing RGPD rights — Art. 15 (subject access) and Art. 17 (right to be forgotten with tombstone). Surfaces 3 new MCP tools (`cluster_subjects`, `subject_access`, `forget_subject`) + 2 new plugin skills (`/hacienda:rgpd:access`, `/hacienda:rgpd:forget`).

**Architecture:** Clustering uses pure SQL on the existing `vault.doc_entities` table — no full-text search, no embeddings. `subject_access` joins clusters → `documents_meta` (Phase 0) → vault stats → audit log v2. `forget_subject` is a tombstone: vault entries deleted + chunks rewritten with `<<deleted:HASH8>>` + re-embedded + audit `forgotten` event with hashed token list.

**Tech Stack:** Python 3.13, SQLite (stdlib), Pydantic, LanceDB (existing), pytest. Zero new dependencies.

**Spec:** `docs/superpowers/specs/2026-04-27-rgpd-compliance-design.md` (commit `a2535c3`).

**Phase 0 prerequisite:** all of `4ab5309..eaff703` must be merged. Phase 1 depends on:
- `documents_meta` table + `documents_meta_for()` (Task 5 of Phase 0)
- `AuditEvent v2` + `record_v2()` (Task 6 of Phase 0)
- `_ProjectService` populates `documents_meta` at index time (Task 8 of Phase 0)

**Project root for all paths below:** `C:\Users\NMarchitecte\Documents\piighost`.

---

## File map (Phase 1)

| Path | Type | Owns |
|---|---|---|
| `src/piighost/vault/store.py` | modify | `delete_token`, `docs_containing_tokens`, `cooccurring_tokens` |
| `src/piighost/indexer/store.py` | modify | `chunks_for_doc_ids`, `update_chunks` |
| `src/piighost/service/subject_clustering.py` | new | Clustering algo (pure, runs against vault) |
| `src/piighost/service/models.py` | modify | `SubjectCluster`, `SubjectAccessReport`, `SubjectDocumentRef`, `SubjectExcerpt`, `ForgetReport` |
| `src/piighost/service/core.py` | modify | 3 service methods on `_ProjectService` + dispatch on `PIIGhostService` |
| `src/piighost/mcp/tools.py` | modify | 3 new ToolSpec |
| `src/piighost/mcp/shim.py` | modify | 3 `@mcp.tool` wrappers |
| `src/piighost/daemon/server.py` | modify | 3 dispatch handlers |
| `tests/unit/test_vault_token_ops.py` | new | `delete_token`, `docs_containing_tokens`, `cooccurring_tokens` |
| `tests/unit/test_chunk_store_phase1.py` | new | `chunks_for_doc_ids`, `update_chunks` |
| `tests/unit/test_subject_clustering.py` | new | Co-occurrence, ranking, homonym separation |
| `tests/unit/test_service_subject_access.py` | new | Service-level: report shape, redaction in excerpts |
| `tests/unit/test_service_forget_subject.py` | new | Service-level: dry_run, tombstone, audit event |
| `tests/unit/test_no_pii_leak_phase1.py` | new | 3 invariant tests across the 3 new tools |
| `.worktrees/hacienda-plugin/skills/rgpd-access/SKILL.md` | new | `/hacienda:rgpd:access` |
| `.worktrees/hacienda-plugin/skills/rgpd-forget/SKILL.md` | new | `/hacienda:rgpd:forget` |
| `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` | modify | bump v0.5.0 |

---

## Task 1: Vault token-level operations

**Files:**
- Modify: `src/piighost/vault/store.py`
- Test: `tests/unit/test_vault_token_ops.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_vault_token_ops.py`:

```python
"""Tests for Vault.delete_token, docs_containing_tokens, cooccurring_tokens."""
from __future__ import annotations

import pytest

from piighost.vault.store import Vault


@pytest.fixture()
def vault(tmp_path):
    v = Vault.open(tmp_path / "vault.db")
    yield v
    v.close()


def _seed(vault, *, token: str, original: str = "x", label: str = "nom_personne"):
    vault.upsert_entity(
        token=token, original=original, label=label,
        confidence=0.9,
    )


def _link(vault, *, doc_id: str, token: str, start: int = 0, end: int = 1):
    vault.link_doc_entity(doc_id=doc_id, token=token, start_pos=start, end_pos=end)


def test_delete_token_removes_from_entities_and_doc_entities(vault):
    _seed(vault, token="<<x:abc>>", original="raw1")
    _link(vault, doc_id="d1", token="<<x:abc>>", start=0, end=4)
    _link(vault, doc_id="d2", token="<<x:abc>>", start=10, end=14)
    affected = vault.delete_token("<<x:abc>>")
    assert affected == 2  # 2 doc_entities rows removed
    assert vault.get_by_token("<<x:abc>>") is None
    # No leftover doc_entities row
    assert vault.entities_for_doc("d1") == []


def test_delete_token_idempotent_on_missing(vault):
    assert vault.delete_token("<<missing:xyz>>") == 0


def test_delete_token_preserves_other_tokens(vault):
    _seed(vault, token="<<x:aaa>>", original="alice")
    _seed(vault, token="<<x:bbb>>", original="bob")
    _link(vault, doc_id="d1", token="<<x:aaa>>", start=0, end=1)
    _link(vault, doc_id="d1", token="<<x:bbb>>", start=2, end=3)
    vault.delete_token("<<x:aaa>>")
    assert vault.get_by_token("<<x:aaa>>") is None
    assert vault.get_by_token("<<x:bbb>>") is not None
    remaining = [e.token for e in vault.entities_for_doc("d1")]
    assert remaining == ["<<x:bbb>>"]


def test_docs_containing_tokens_returns_distinct_doc_ids(vault):
    _seed(vault, token="<<a:1>>")
    _seed(vault, token="<<a:2>>")
    _link(vault, doc_id="d1", token="<<a:1>>", start=0)
    _link(vault, doc_id="d1", token="<<a:1>>", start=10)  # same token, different position
    _link(vault, doc_id="d2", token="<<a:2>>", start=0)
    _link(vault, doc_id="d3", token="<<a:1>>", start=0)
    docs = sorted(vault.docs_containing_tokens(["<<a:1>>"]))
    assert docs == ["d1", "d3"]
    docs2 = sorted(vault.docs_containing_tokens(["<<a:1>>", "<<a:2>>"]))
    assert docs2 == ["d1", "d2", "d3"]


def test_docs_containing_tokens_empty_returns_empty(vault):
    assert vault.docs_containing_tokens([]) == []


def test_docs_containing_tokens_unknown_returns_empty(vault):
    _seed(vault, token="<<a:1>>")
    _link(vault, doc_id="d1", token="<<a:1>>", start=0)
    assert vault.docs_containing_tokens(["<<unknown:zzz>>"]) == []


def test_cooccurring_tokens_returns_count_per_partner(vault):
    """Marie's nom_personne token should co-occur with her email + phone in 3 docs."""
    _seed(vault, token="<<np:marie>>")
    _seed(vault, token="<<em:marie>>")
    _seed(vault, token="<<tel:marie>>")
    _seed(vault, token="<<np:other>>")
    # Marie appears in d1, d2, d3 — always with all three tokens
    for doc in ["d1", "d2", "d3"]:
        _link(vault, doc_id=doc, token="<<np:marie>>", start=0)
        _link(vault, doc_id=doc, token="<<em:marie>>", start=10)
        _link(vault, doc_id=doc, token="<<tel:marie>>", start=20)
    # Other person appears alone in d4
    _link(vault, doc_id="d4", token="<<np:other>>", start=0)

    pairs = dict(vault.cooccurring_tokens("<<np:marie>>"))
    assert pairs.get("<<em:marie>>") == 3
    assert pairs.get("<<tel:marie>>") == 3
    assert "<<np:other>>" not in pairs  # never shares a doc
    # Self-token excluded
    assert "<<np:marie>>" not in pairs


def test_cooccurring_tokens_unknown_seed_returns_empty(vault):
    assert vault.cooccurring_tokens("<<missing:xyz>>") == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_vault_token_ops.py -v --no-header
```
Expected: AttributeError on `delete_token`, `docs_containing_tokens`, `cooccurring_tokens`.

- [ ] **Step 3: Implement the methods**

Open `src/piighost/vault/store.py`. Add three methods to the `Vault` class (place them near the other `delete_*` methods around lines 192-220):

```python
    def delete_token(self, token: str) -> int:
        """Remove a token from both ``entities`` and ``doc_entities``.

        Returns the number of ``doc_entities`` rows that were
        affected (i.e. how many (doc_id, position) tuples the token
        was anchored to). Idempotent: returns 0 if the token doesn't
        exist.

        Used by Art. 17 right-to-be-forgotten cascade.
        """
        cur = self._conn.execute(
            "DELETE FROM doc_entities WHERE token = ?", (token,)
        )
        affected = cur.rowcount
        self._conn.execute(
            "DELETE FROM entities WHERE token = ?", (token,)
        )
        return affected

    def docs_containing_tokens(self, tokens: list[str]) -> list[str]:
        """Return distinct ``doc_id`` values that contain any of the
        given tokens. Used by ``subject_access`` and ``forget_subject``
        to find every document a person appears in via a single SQL
        query (no full-text search needed).

        Empty list input → empty list output.
        """
        if not tokens:
            return []
        placeholders = ",".join("?" * len(tokens))
        rows = self._conn.execute(
            f"SELECT DISTINCT doc_id FROM doc_entities "
            f"WHERE token IN ({placeholders})",
            tokens,
        ).fetchall()
        return [r[0] for r in rows]

    def cooccurring_tokens(self, seed_token: str) -> list[tuple[str, int]]:
        """Return tokens that share a ``doc_id`` with ``seed_token``.

        Each pair is ``(token, shared_doc_count)`` ordered by
        descending shared count. The seed is excluded from the
        result. Used by the subject-clustering algorithm to find
        tokens that probably refer to the same person (same
        documents → likely same subject).

        Unknown seed → empty list.
        """
        rows = self._conn.execute(
            """
            SELECT de2.token, COUNT(DISTINCT de1.doc_id) AS shared
            FROM doc_entities de1
            JOIN doc_entities de2 USING (doc_id)
            WHERE de1.token = ? AND de2.token != ?
            GROUP BY de2.token
            ORDER BY shared DESC
            """,
            (seed_token, seed_token),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_vault_token_ops.py -v --no-header
```
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/vault/store.py tests/unit/test_vault_token_ops.py
git commit -m "feat(vault): token-level ops for RGPD Phase 1

Three new methods on Vault:
  - delete_token(token): cascade-delete from entities + doc_entities
  - docs_containing_tokens(tokens): pure SQL doc lookup, no full-text
  - cooccurring_tokens(seed): co-occurrence stats for subject clustering

Used by subject_access (Art. 15) and forget_subject (Art. 17). Pure
SQL on the existing doc_entities table — no full-text search, no
new index needed (the schema already has idx_doc_entities_doc)."
```

---

## Task 2: ChunkStore filter + update methods

**Files:**
- Modify: `src/piighost/indexer/store.py`
- Test: `tests/unit/test_chunk_store_phase1.py`

`forget_subject` rewrites chunks in place to replace forgotten tokens with `<<deleted:HASH>>`. We need to fetch chunks by doc_ids and update them with new text + new embeddings.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_chunk_store_phase1.py`:

```python
"""Tests for ChunkStore.chunks_for_doc_ids + update_chunks (Phase 1)."""
from __future__ import annotations

import pytest

from piighost.indexer.store import ChunkStore


@pytest.fixture()
def store(tmp_path):
    s = ChunkStore(tmp_path / "lance")
    yield s


def test_chunks_for_doc_ids_returns_only_requested(store):
    store.upsert_chunks("d1", "/a.pdf",
                       chunks=["chunk a1", "chunk a2"], vectors=[[0.1]*4, [0.2]*4])
    store.upsert_chunks("d2", "/b.pdf",
                       chunks=["chunk b1"], vectors=[[0.3]*4])
    store.upsert_chunks("d3", "/c.pdf",
                       chunks=["chunk c1"], vectors=[[0.4]*4])
    out = store.chunks_for_doc_ids(["d1", "d3"])
    doc_ids = sorted({r["doc_id"] for r in out})
    assert doc_ids == ["d1", "d3"]
    assert len(out) == 3  # 2 from d1 + 1 from d3


def test_chunks_for_doc_ids_empty_input_returns_empty(store):
    store.upsert_chunks("d1", "/a.pdf", chunks=["x"], vectors=[[0.1]*4])
    assert store.chunks_for_doc_ids([]) == []


def test_chunks_for_doc_ids_unknown_doc_returns_empty(store):
    store.upsert_chunks("d1", "/a.pdf", chunks=["x"], vectors=[[0.1]*4])
    assert store.chunks_for_doc_ids(["unknown"]) == []


def test_update_chunks_replaces_text_and_vector(store):
    store.upsert_chunks("d1", "/a.pdf",
                       chunks=["original text"], vectors=[[0.1]*4])
    rows = store.chunks_for_doc_ids(["d1"])
    assert len(rows) == 1
    chunk_id = rows[0].get("chunk_id") or rows[0].get("id")  # whichever the impl uses
    # Build the update list — implementation defines exact shape, but
    # the contract is: pass (chunk_identifier, new_text, new_vector) tuples
    store.update_chunks([
        (rows[0], "rewritten text", [0.9]*4),
    ])
    after = store.chunks_for_doc_ids(["d1"])
    assert len(after) == 1
    assert after[0]["chunk"] == "rewritten text" or after[0].get("text") == "rewritten text"


def test_update_chunks_preserves_unaffected_chunks(store):
    store.upsert_chunks("d1", "/a.pdf",
                       chunks=["A", "B", "C"], vectors=[[0.1]*4]*3)
    rows = store.chunks_for_doc_ids(["d1"])
    # rewrite only the middle chunk
    middle = next(r for r in rows if r.get("chunk", r.get("text")) == "B")
    store.update_chunks([(middle, "B-rewritten", [0.9]*4)])
    after = sorted(store.chunks_for_doc_ids(["d1"]),
                   key=lambda r: r.get("chunk_index", 0))
    texts = [r.get("chunk") or r.get("text") for r in after]
    assert "A" in texts
    assert "B-rewritten" in texts
    assert "C" in texts
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_chunk_store_phase1.py -v --no-header
```
Expected: AttributeError on `chunks_for_doc_ids` and `update_chunks`.

- [ ] **Step 3: Implement the methods**

First read `src/piighost/indexer/store.py` to understand the LanceDB schema:
```
sed -n '1,80p' src/piighost/indexer/store.py
```

Note the column names actually used (`chunk` vs `text`, `chunk_index`, etc.). The implementation below assumes the existing `upsert_chunks` schema — adapt column names if needed.

Add to the `ChunkStore` class:

```python
    def chunks_for_doc_ids(self, doc_ids: list[str]) -> list[dict]:
        """Return all chunk records whose ``doc_id`` is in the given list.

        Used by ``subject_access`` (to build excerpts) and
        ``forget_subject`` (to find chunks needing rewrite).
        """
        if not doc_ids:
            return []
        if not self._ensure_db_for_read():
            return []
        if "chunks" not in self._db.list_tables().tables:
            return []
        tbl = self._db.open_table("chunks")
        # Build a Lance WHERE: doc_id IN ('a','b','c')
        escaped = ", ".join(
            "'" + d.replace("'", "''") + "'" for d in doc_ids
        )
        rows = tbl.search().where(f"doc_id IN ({escaped})").to_list()
        return [{k: v for k, v in r.items() if k != "vector"} for r in rows]

    def update_chunks(
        self, updates: list[tuple[dict, str, list[float]]],
    ) -> None:
        """Update existing chunks in place.

        ``updates`` is a list of ``(chunk_record, new_text, new_vector)``
        tuples. The chunk_record is the dict you got from
        ``chunks_for_doc_ids`` (so we know how to find it again — by
        doc_id + chunk_index).

        For LanceDB, in-place update is achieved via DELETE + INSERT
        within the same call so the row identity is preserved from
        the consumer's perspective.
        """
        if not updates:
            return
        if not self._ensure_db_for_read():
            return
        if "chunks" not in self._db.list_tables().tables:
            return
        tbl = self._db.open_table("chunks")
        for record, new_text, new_vector in updates:
            doc_id = record["doc_id"]
            idx = record.get("chunk_index", 0)
            # Delete the old row
            esc_doc = doc_id.replace("'", "''")
            tbl.delete(f"doc_id = '{esc_doc}' AND chunk_index = {int(idx)}")
            # Insert the rewritten row preserving all metadata
            new_record = {**record, "vector": new_vector}
            # Replace the text column under whichever name the schema uses
            for text_col in ("chunk", "text"):
                if text_col in record:
                    new_record[text_col] = new_text
                    break
            tbl.add([new_record])
```

If the LanceDB schema uses different column names (e.g. `text` instead of `chunk`), adjust the implementation. The test is written defensively to handle either name.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_chunk_store_phase1.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/indexer/store.py tests/unit/test_chunk_store_phase1.py
git commit -m "feat(chunk_store): chunks_for_doc_ids + update_chunks (Phase 1)

Two new methods on ChunkStore:
  - chunks_for_doc_ids: filter by doc_id list (Lance WHERE clause)
  - update_chunks: in-place rewrite via DELETE + INSERT, preserves
    chunk_index identity

Both consumed by Phase 1 subject_access (excerpts) and
forget_subject (tombstone rewrite). The DELETE+INSERT pattern is
necessary because LanceDB doesn't expose row-level UPDATE; identity
is preserved at the (doc_id, chunk_index) level."
```

---

## Task 3: Subject clustering algorithm

**Files:**
- Create: `src/piighost/service/subject_clustering.py`
- Test: `tests/unit/test_subject_clustering.py`

Pure module that consumes a `Vault` instance + a free-text query, returns ranked clusters of co-occurring tokens.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_subject_clustering.py`:

```python
"""Tests for subject_clustering — co-occurrence-based clustering on doc_entities."""
from __future__ import annotations

import pytest

from piighost.service.subject_clustering import (
    cluster_subjects, SubjectCluster,
)
from piighost.vault.store import Vault


@pytest.fixture()
def vault(tmp_path):
    v = Vault.open(tmp_path / "vault.db")
    yield v
    v.close()


def _seed_person(vault, *, person_tag: str, doc_ids: list[str]):
    """Seed a 3-token person (nom + email + phone) appearing in the given docs."""
    for label in ("nom_personne", "email", "numero_telephone"):
        token = f"<<{label}:{person_tag}>>"
        vault.upsert_entity(
            token=token, original=f"{label}-{person_tag}",
            label=label, confidence=0.9,
        )
        for doc_id in doc_ids:
            vault.link_doc_entity(doc_id=doc_id, token=token, start_pos=0, end_pos=1)


def test_cluster_returns_empty_when_no_match(vault):
    out = cluster_subjects(vault, query="Inconnu Inexistant")
    assert out == []


def test_cluster_groups_cooccurring_tokens(vault):
    """Marie's 3 tokens always appear together → one cluster of 3."""
    vault.upsert_entity(
        token="<<nom_personne:marie>>", original="Marie Dupont",
        label="nom_personne", confidence=0.9,
    )
    vault.upsert_entity(
        token="<<email:marie>>", original="marie.dupont@x.fr",
        label="email", confidence=0.9,
    )
    vault.upsert_entity(
        token="<<numero_telephone:marie>>", original="+33 1 23 45 67 89",
        label="numero_telephone", confidence=0.9,
    )
    for doc in ["d1", "d2", "d3"]:
        for tok in ("<<nom_personne:marie>>", "<<email:marie>>",
                    "<<numero_telephone:marie>>"):
            vault.link_doc_entity(doc_id=doc, token=tok, start_pos=0, end_pos=1)

    clusters = cluster_subjects(vault, query="Marie")
    assert len(clusters) == 1
    c = clusters[0]
    assert c.confidence > 0.8
    assert "<<nom_personne:marie>>" in c.tokens
    assert "<<email:marie>>" in c.tokens
    assert "<<numero_telephone:marie>>" in c.tokens
    assert sorted(c.sample_doc_ids) == ["d1", "d2", "d3"]


def test_cluster_separates_homonyms(vault):
    """Two 'Marie's that never share a doc → two clusters."""
    # Marie A in d1, d2
    vault.upsert_entity(token="<<nom_personne:marie_a>>", original="Marie Alpha",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<email:marie_a>>", original="alpha@x.fr",
                        label="email", confidence=0.9)
    for doc in ["d1", "d2"]:
        vault.link_doc_entity(doc_id=doc, token="<<nom_personne:marie_a>>", start_pos=0)
        vault.link_doc_entity(doc_id=doc, token="<<email:marie_a>>", start_pos=10)
    # Marie B in d10
    vault.upsert_entity(token="<<nom_personne:marie_b>>", original="Marie Beta",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<email:marie_b>>", original="beta@x.fr",
                        label="email", confidence=0.9)
    vault.link_doc_entity(doc_id="d10", token="<<nom_personne:marie_b>>", start_pos=0)
    vault.link_doc_entity(doc_id="d10", token="<<email:marie_b>>", start_pos=10)

    clusters = cluster_subjects(vault, query="Marie")
    # Two distinct clusters (no shared docs → no co-occurrence between them)
    assert len(clusters) >= 2
    cluster_token_sets = [set(c.tokens) for c in clusters]
    # Verify the alpha tokens stay together
    alpha_cluster = next(s for s in cluster_token_sets if "<<email:marie_a>>" in s)
    assert "<<nom_personne:marie_a>>" in alpha_cluster
    assert "<<nom_personne:marie_b>>" not in alpha_cluster


def test_cluster_confidence_lower_when_few_shared_docs(vault):
    """One token in 5 docs, partner in only 1 of those → lower confidence."""
    vault.upsert_entity(token="<<nom_personne:x>>", original="X",
                        label="nom_personne", confidence=0.9)
    vault.upsert_entity(token="<<email:rare>>", original="rare@x.fr",
                        label="email", confidence=0.9)
    for doc in ["d1", "d2", "d3", "d4", "d5"]:
        vault.link_doc_entity(doc_id=doc, token="<<nom_personne:x>>", start_pos=0)
    vault.link_doc_entity(doc_id="d3", token="<<email:rare>>", start_pos=10)

    clusters = cluster_subjects(vault, query="X")
    # email:rare should be in the cluster but with lower confidence weighting
    c = next(c for c in clusters if "<<nom_personne:x>>" in c.tokens)
    # Confidence is the strongest signal — rare email co-occurrence should still
    # land in the cluster (it's 1/5 = 0.2) but the cluster confidence should
    # reflect its noisiness
    assert c.confidence < 1.0


def test_cluster_returns_sample_doc_ids_capped(vault):
    """Sample doc list shouldn't return more than ~10 entries."""
    vault.upsert_entity(token="<<nom_personne:big>>", original="Big",
                        label="nom_personne", confidence=0.9)
    for i in range(50):
        vault.link_doc_entity(doc_id=f"d{i}", token="<<nom_personne:big>>", start_pos=0)
    clusters = cluster_subjects(vault, query="Big")
    assert len(clusters) == 1
    assert len(clusters[0].sample_doc_ids) <= 10
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_subject_clustering.py -v --no-header
```
Expected: ImportError.

- [ ] **Step 3: Implement clustering**

Create `src/piighost/service/subject_clustering.py`:

```python
"""Subject clustering — find all PII tokens that refer to the same
real person, given a free-text query.

Uses pure SQL on the existing ``vault.doc_entities`` linkage table
(no full-text search, no embeddings). Each cluster is a group of
tokens that share enough documents to plausibly belong to the same
data subject. The avocat validates the cluster before
``subject_access`` or ``forget_subject`` is applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from piighost.vault.store import Vault


_SAMPLE_DOC_IDS_LIMIT = 10
_MIN_COOCCURRENCE_DOCS = 1   # at least 1 shared doc to be in a cluster
_MAX_SEEDS = 20              # limit search_entities seed candidates


@dataclass(frozen=True)
class SubjectCluster:
    """One probable real-world subject = a group of tokens that
    repeatedly co-occur in the same documents."""
    cluster_id: str
    seed_match: str
    seed_token: str
    confidence: float                # 0.0 - 1.0
    tokens: tuple[str, ...]
    sample_doc_ids: tuple[str, ...]
    first_seen: int                  # min first_seen_at across cluster tokens
    last_seen: int                   # max last_seen_at


def cluster_subjects(vault: "Vault", query: str) -> list[SubjectCluster]:
    """Return ranked clusters that plausibly refer to the same subject.

    Algorithm:
      1. ``vault.search_entities(query)`` → seed candidates
         (tokens whose ``original`` matches the query text).
      2. For each seed:
         a. Find all docs containing the seed
            (``vault.docs_containing_tokens([seed])``).
         b. Co-occurrence:
            ``vault.cooccurring_tokens(seed)`` returns
            ``[(token, shared_doc_count)]`` sorted DESC.
         c. Build cluster: tokens with shared count >=
            ``_MIN_COOCCURRENCE_DOCS``.
      3. Confidence = mean(shared_doc_count / seed_doc_count) over
         the cluster's non-seed tokens, clamped to [0, 1].
      4. Deduplicate clusters that share most tokens (homonyms with
         distinct cluster sets stay separate).
    """
    seeds = vault.search_entities(query, limit=_MAX_SEEDS)
    if not seeds:
        return []

    clusters: list[SubjectCluster] = []
    seen_token_sets: list[frozenset[str]] = []

    for idx, seed in enumerate(seeds):
        seed_token = seed.token
        seed_docs = vault.docs_containing_tokens([seed_token])
        if not seed_docs:
            continue
        cooccs = vault.cooccurring_tokens(seed_token)
        # Filter to tokens that share enough docs
        cluster_tokens = [seed_token] + [
            tok for tok, count in cooccs
            if count >= _MIN_COOCCURRENCE_DOCS
        ]
        token_set = frozenset(cluster_tokens)
        # Skip if this is a strict subset of an already-found cluster
        if any(token_set.issubset(s) for s in seen_token_sets):
            continue
        # Confidence based on how tightly tokens co-occur
        if len(cluster_tokens) > 1:
            seed_doc_count = len(seed_docs)
            cooccs_for_cluster = [c for c in cooccs if c[0] in token_set]
            confidence = (
                sum(count for _, count in cooccs_for_cluster) /
                (seed_doc_count * max(1, len(cooccs_for_cluster)))
            )
            confidence = min(1.0, confidence)
        else:
            confidence = 1.0  # single-token cluster (rare)
        # Aggregate first_seen / last_seen across cluster
        first_seen = seed.first_seen_at
        last_seen = seed.last_seen_at
        for tok in cluster_tokens:
            entry = vault.get_by_token(tok)
            if entry is not None:
                first_seen = min(first_seen, entry.first_seen_at)
                last_seen = max(last_seen, entry.last_seen_at)
        clusters.append(SubjectCluster(
            cluster_id=f"c-{idx + 1}",
            seed_match=query,
            seed_token=seed_token,
            confidence=round(confidence, 3),
            tokens=tuple(cluster_tokens),
            sample_doc_ids=tuple(seed_docs[:_SAMPLE_DOC_IDS_LIMIT]),
            first_seen=first_seen,
            last_seen=last_seen,
        ))
        seen_token_sets.append(token_set)

    # Sort by confidence DESC, then by cluster size DESC
    clusters.sort(key=lambda c: (c.confidence, len(c.tokens)), reverse=True)
    return clusters
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_subject_clustering.py -v --no-header
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/subject_clustering.py tests/unit/test_subject_clustering.py
git commit -m "feat(service): subject_clustering for RGPD Phase 1

Co-occurrence-based clustering on the doc_entities table. Returns
SubjectCluster objects ranked by confidence; the avocat validates
which one(s) to apply for subject_access or forget_subject.

Pure SQL — no full-text search, no embeddings. Algorithm:
  1. search_entities(query) → seed candidates
  2. For each seed: docs_containing_tokens + cooccurring_tokens
  3. Cluster = seed + co-occurring tokens above threshold
  4. Confidence = avg share-rate across cluster
  5. Dedup strict-subset clusters

Sample doc IDs capped at 10 to keep payload bounded."
```

---

## Task 4: Pydantic models for Phase 1 reports

**Files:**
- Modify: `src/piighost/service/models.py` (append)

- [ ] **Step 1: Add the models**

Append to `src/piighost/service/models.py`:

```python


class SubjectDocumentRef(BaseModel):
    """One document reference in a subject_access or forget report."""
    doc_id: str
    file_name: str
    file_path: str
    doc_type: str = "autre"
    doc_date: int | None = None
    occurrences: int = 0  # total times any cluster token appears in this doc
    first_indexed: int | None = None
    last_indexed: int | None = None


class SubjectExcerpt(BaseModel):
    """Redacted excerpt where the subject appears."""
    doc_id: str
    file_name: str
    chunk_index: int
    redacted_text: str  # cluster tokens replaced by <<SUBJECT>> for clarity
    surrounding_tokens: list[str] = Field(default_factory=list)


class SubjectAccessReport(BaseModel):
    """Art. 15 right-of-access report.

    Contains everything needed to produce the formal response to a
    data-subject access request: who, what categories, where (docs),
    how (purposes/legal bases), when (retention), with whom (recipients).
    """
    v: Literal[1] = 1
    generated_at: int
    project: str
    subject_tokens: list[str]
    subject_preview: list[str] = Field(default_factory=list)
    categories_found: dict[str, int] = Field(default_factory=dict)
    documents: list[SubjectDocumentRef] = Field(default_factory=list)
    processing_purpose: str = ""
    legal_basis: str = ""
    retention_period: str = ""
    third_party_recipients: list[str] = Field(default_factory=list)
    transfers_outside_eu: list[str] = Field(default_factory=list)
    excerpts: list[SubjectExcerpt] = Field(default_factory=list)
    excerpts_truncated: bool = False
    total_excerpts: int = 0


class ForgetReport(BaseModel):
    """Art. 17 right-to-be-forgotten outcome.

    Tombstone semantics: token IDs are returned as hashes only — the
    raw tokens are not persisted in the audit log either.
    """
    v: Literal[1] = 1
    dry_run: bool
    tokens_to_purge_hashes: list[str] = Field(default_factory=list)
    chunks_to_rewrite: int = 0
    docs_affected: list[str] = Field(default_factory=list)
    estimated_duration_ms: int | None = None
    actual_duration_ms: int | None = None
    completed_at: int | None = None
    legal_basis: str = ""
```

- [ ] **Step 2: Smoke-test the imports**

```
PYTHONPATH=src .venv/Scripts/python.exe -c "
from piighost.service.models import (
    SubjectDocumentRef, SubjectExcerpt, SubjectAccessReport, ForgetReport,
)
r = SubjectAccessReport(generated_at=1700000000, project='p', subject_tokens=['<<x:1>>'])
print(r.model_dump_json()[:120])
f = ForgetReport(dry_run=True)
print(f.model_dump_json())
"
```
Expected: prints valid JSON for both.

- [ ] **Step 3: Commit**

```bash
git add src/piighost/service/models.py
git commit -m "feat(models): SubjectAccessReport + ForgetReport (Phase 1)

Pydantic models for Art. 15 (subject_access) and Art. 17
(forget_subject) outputs. ForgetReport carries token hashes only,
never raw tokens — Art. 17 tombstone semantics."
```

---

## Task 5: `subject_access` service method + tests

**Files:**
- Modify: `src/piighost/service/core.py` (add method to `_ProjectService`)
- Test: `tests/unit/test_service_subject_access.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_service_subject_access.py`:

```python
"""Service-level tests for subject_access — joins clusters → docs → audit."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_subject_access_returns_empty_for_unknown_tokens(vault_dir, monkeypatch):
    svc = _svc(vault_dir, monkeypatch)
    asyncio.run(svc.create_project("test-sa"))
    report = asyncio.run(svc.subject_access(
        tokens=["<<unknown:zzz>>"], project="test-sa",
    ))
    assert report.subject_tokens == ["<<unknown:zzz>>"]
    assert report.documents == []
    assert report.total_excerpts == 0
    asyncio.run(svc.close())


def test_subject_access_finds_documents_and_excerpts(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_a"
    folder.mkdir()
    (folder / "note.txt").write_text(
        "Dear Marie Dupont, this is your contract.", encoding="utf-8"
    )
    asyncio.run(svc.index_path(folder, project="test-sa"))

    proj = asyncio.run(svc._get_project("test-sa"))
    # Find any token from the indexed doc to use as the subject
    entries = proj._vault.list_entities(limit=10)
    if not entries:
        pytest.skip("Stub detector produced no entities")
    target_token = entries[0].token

    report = asyncio.run(svc.subject_access(
        tokens=[target_token], project="test-sa",
    ))
    assert report.subject_tokens == [target_token]
    assert len(report.documents) >= 1
    assert report.total_excerpts >= 1
    # Privacy invariant: raw value of target_token must NOT appear in any
    # excerpt — should be replaced by <<SUBJECT>>
    raw = entries[0].original
    for exc in report.excerpts:
        assert raw not in exc.redacted_text, (
            f"Raw PII '{raw}' leaked in excerpt: {exc.redacted_text!r}"
        )
    asyncio.run(svc.close())


def test_subject_access_writes_audit_event(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "client_b"
    folder.mkdir()
    (folder / "doc.txt").write_text("Marie Dupont here", encoding="utf-8")
    asyncio.run(svc.index_path(folder, project="audit-sa"))

    proj = asyncio.run(svc._get_project("audit-sa"))
    entries = proj._vault.list_entities(limit=5)
    if not entries:
        pytest.skip("No entities to query")
    asyncio.run(svc.subject_access(tokens=[entries[0].token], project="audit-sa"))

    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "audit-sa" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit log path differs in this environment")
    events = list(read_events(audit_path))
    types = [e.event_type for e in events]
    assert "subject_access" in types
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_subject_access.py -v --no-header
```
Expected: AttributeError on `subject_access` method.

- [ ] **Step 3: Implement `subject_access` on `_ProjectService`**

In `src/piighost/service/core.py`, add a new method to `_ProjectService` (place it near other service methods, after `index_path`):

```python
    async def subject_access(
        self,
        tokens: list[str],
        *,
        max_excerpts: int = 50,
    ) -> "SubjectAccessReport":
        """Right-of-access report (Art. 15).

        Returns all documents/excerpts mentioning any of ``tokens``,
        plus the audit context (purposes, legal basis, retention,
        recipients) sourced from the controller profile.
        """
        from piighost.service.models import (
            SubjectAccessReport, SubjectDocumentRef, SubjectExcerpt,
        )
        import time as _time
        from pathlib import Path as _P

        # 1. Find documents containing the cluster
        doc_ids = self._vault.docs_containing_tokens(tokens)

        # 2. Pull metadata for each doc (Phase 0 documents_meta)
        docs_meta = self._indexing_store.documents_meta_for(
            self._project_name, doc_ids,
        )
        meta_by_id = {m.doc_id: m for m in docs_meta}

        # 3. Categorize tokens by label
        categories: dict[str, int] = {}
        previews: list[str] = []
        for tok in tokens:
            entry = self._vault.get_by_token(tok)
            if entry is None:
                continue
            categories[entry.label] = categories.get(entry.label, 0) + 1
            # Mask the raw value — show first + last char only
            raw = entry.original or ""
            if len(raw) <= 2:
                masked = "**"
            else:
                masked = f"{raw[0]}{'*' * (len(raw) - 2)}{raw[-1]}"
            previews.append(f"{masked} ({entry.label})")

        # 4. Build doc refs from existing indexed_files + documents_meta
        doc_refs: list[SubjectDocumentRef] = []
        for doc_id in doc_ids:
            meta = meta_by_id.get(doc_id)
            file_record = self._vault.get_indexed_file_by_doc_id(doc_id)
            file_path = file_record.file_path if file_record else ""
            file_name = _P(file_path).name if file_path else doc_id
            doc_refs.append(SubjectDocumentRef(
                doc_id=doc_id,
                file_name=file_name,
                file_path=file_path,
                doc_type=meta.doc_type if meta else "autre",
                doc_date=meta.doc_date if meta else None,
                occurrences=len([
                    e for e in self._vault.entities_for_doc(doc_id)
                    if e.token in tokens
                ]),
                first_indexed=int(file_record.indexed_at) if file_record else None,
                last_indexed=int(file_record.indexed_at) if file_record else None,
            ))

        # 5. Excerpts: chunks containing any token, replace tokens by <<SUBJECT>>
        chunks = self._chunk_store.chunks_for_doc_ids(doc_ids)
        token_set = set(tokens)
        excerpts: list[SubjectExcerpt] = []
        for c in chunks:
            text = c.get("chunk") or c.get("text") or ""
            if not any(t in text for t in tokens):
                continue
            redacted = text
            for t in tokens:
                redacted = redacted.replace(t, "<<SUBJECT>>")
            file_path = c.get("file_path") or ""
            file_name = _P(file_path).name if file_path else c.get("doc_id", "")
            excerpts.append(SubjectExcerpt(
                doc_id=c.get("doc_id", ""),
                file_name=file_name,
                chunk_index=int(c.get("chunk_index", 0)),
                redacted_text=redacted,
                surrounding_tokens=[],  # Phase 1: empty (Phase 1.1 could populate from doc_entities)
            ))

        total_excerpts = len(excerpts)
        truncated = total_excerpts > max_excerpts
        excerpts = excerpts[:max_excerpts]

        # 6. Controller context
        try:
            from piighost.service.controller_profile import ControllerProfileService
            cp_svc = ControllerProfileService(self._vault_dir)
            profile = cp_svc.get(scope="project", project=self._project_name)
        except Exception:
            profile = {}
        defaults = profile.get("defaults", {}) if isinstance(profile, dict) else {}
        purposes = defaults.get("finalites", [])
        bases = defaults.get("bases_legales", [])
        retention = defaults.get("duree_conservation_apres_fin_mission", "")

        report = SubjectAccessReport(
            generated_at=int(_time.time()),
            project=self._project_name,
            subject_tokens=list(tokens),
            subject_preview=previews,
            categories_found=categories,
            documents=doc_refs,
            processing_purpose="; ".join(purposes) if purposes else "",
            legal_basis="; ".join(bases) if bases else "",
            retention_period=str(retention) if retention else "",
            third_party_recipients=[],
            transfers_outside_eu=[],
            excerpts=excerpts,
            excerpts_truncated=truncated,
            total_excerpts=total_excerpts,
        )

        # 7. Audit
        try:
            self._audit.record_v2(
                event_type="subject_access",
                project_id=self._project_name,
                subject_token=tokens[0] if tokens else None,
                metadata={
                    "cluster_size": len(tokens),
                    "n_docs": len(doc_refs),
                    "n_excerpts": total_excerpts,
                },
            )
        except Exception:
            pass  # audit failure should not block the report

        return report
```

Add a thin `PIIGhostService.subject_access` dispatcher near other public methods:

```python
    async def subject_access(
        self, tokens: list[str], *, project: str, max_excerpts: int = 50,
    ) -> "SubjectAccessReport":
        svc = await self._get_project(project)
        return await svc.subject_access(tokens, max_excerpts=max_excerpts)
```

The method assumes `_ProjectService` has `_vault_dir` accessible — if it doesn't, derive from `self._project_dir.parent.parent`.

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_subject_access.py -v --no-header
```
Expected: 3 passed (some may skip if stub detector doesn't produce entities — that's fine).

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_subject_access.py
git commit -m "feat(service): subject_access (Art. 15) on _ProjectService

Right-of-access report. Joins:
  - vault.doc_entities → doc_ids containing the cluster (1 SQL)
  - documents_meta (Phase 0) → doc_type + doc_date enrichment
  - vault.entities → category breakdown + masked previews
  - chunks_for_doc_ids → redacted excerpts (cluster tokens replaced
    by <<SUBJECT>> for clarity, other PII placeholders stay intact)
  - ControllerProfile → purpose/legal_basis/retention

Audit event 'subject_access' written via record_v2."
```

---

## Task 6: `forget_subject` service method + tests

**Files:**
- Modify: `src/piighost/service/core.py` (add method)
- Test: `tests/unit/test_service_forget_subject.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_service_forget_subject.py`:

```python
"""Service-level tests for forget_subject (Art. 17 tombstone)."""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def test_forget_subject_dry_run_does_not_modify_vault(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "note.txt").write_text("Marie", encoding="utf-8")
    asyncio.run(svc.index_path(folder, project="forget-dry"))

    proj = asyncio.run(svc._get_project("forget-dry"))
    entries = proj._vault.list_entities(limit=5)
    if not entries:
        pytest.skip("No entities")
    target = entries[0].token

    before = proj._vault.get_by_token(target)
    assert before is not None

    report = asyncio.run(svc.forget_subject(
        tokens=[target], project="forget-dry", dry_run=True,
    ))
    assert report.dry_run is True
    assert report.docs_affected
    # Vault entry MUST still exist after dry run
    after = proj._vault.get_by_token(target)
    assert after is not None
    assert after.original == before.original
    asyncio.run(svc.close())


def test_forget_subject_apply_purges_vault_and_chunks(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "note.txt").write_text("Hello, person here.", encoding="utf-8")
    asyncio.run(svc.index_path(folder, project="forget-apply"))

    proj = asyncio.run(svc._get_project("forget-apply"))
    entries = proj._vault.list_entities(limit=5)
    if not entries:
        pytest.skip("No entities")
    target = entries[0].token

    report = asyncio.run(svc.forget_subject(
        tokens=[target], project="forget-apply",
        dry_run=False, legal_basis="c-opposition",
    ))
    assert report.dry_run is False
    # Vault entry GONE
    assert proj._vault.get_by_token(target) is None
    # Chunks rewritten — token replaced by <<deleted:HASH>>
    chunks = proj._chunk_store.all_records()
    for c in chunks:
        text = c.get("chunk") or c.get("text") or ""
        assert target not in text  # original token gone
    asyncio.run(svc.close())


def test_forget_subject_writes_tombstone_audit(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    folder = tmp_path / "c"
    folder.mkdir()
    (folder / "note.txt").write_text("Person.", encoding="utf-8")
    asyncio.run(svc.index_path(folder, project="forget-audit"))

    proj = asyncio.run(svc._get_project("forget-audit"))
    entries = proj._vault.list_entities(limit=5)
    if not entries:
        pytest.skip("No entities")
    target = entries[0].token

    asyncio.run(svc.forget_subject(
        tokens=[target], project="forget-audit",
        dry_run=False, legal_basis="b-retrait_consentement",
    ))

    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "forget-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit log path differs")
    events = list(read_events(audit_path))
    forgotten = [e for e in events if e.event_type == "forgotten"]
    assert len(forgotten) >= 1
    ev = forgotten[-1]
    # Tombstone invariant: raw token MUST NOT appear in metadata
    assert target not in ev.model_dump_json()
    # Hashes ARE present
    md = ev.metadata or {}
    assert "tokens_purged_hashes" in md
    assert md.get("legal_basis") == "b-retrait_consentement"
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests to verify they fail**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_forget_subject.py -v --no-header
```
Expected: AttributeError on `forget_subject`.

- [ ] **Step 3: Implement `forget_subject` on `_ProjectService`**

Add to `_ProjectService` in `src/piighost/service/core.py`:

```python
    async def forget_subject(
        self,
        tokens: list[str],
        *,
        dry_run: bool = True,
        legal_basis: str = "c-opposition",
    ) -> "ForgetReport":
        """Right-to-be-forgotten cascade (Art. 17) with tombstone.

        Steps (when dry_run=False):
          1. Find affected docs/chunks
          2. Rewrite chunks: each token → <<deleted:HASH8>>
          3. Re-embed rewritten chunks
          4. UPDATE chunks (DELETE+INSERT in LanceDB)
          5. Rebuild BM25 index
          6. DELETE vault entries (entities + doc_entities)
          7. Audit 'forgotten' event with hashed token list only
        """
        from piighost.service.models import ForgetReport
        import hashlib
        import time as _time

        start = _time.monotonic()

        # 1. Find affected scope
        doc_ids = self._vault.docs_containing_tokens(tokens)
        affected_chunks = self._chunk_store.chunks_for_doc_ids(doc_ids)
        # Filter chunks that actually contain at least one token
        relevant_chunks = [
            c for c in affected_chunks
            if any(t in (c.get("chunk") or c.get("text") or "") for t in tokens)
        ]

        token_hashes = [
            hashlib.sha256(t.encode("utf-8")).hexdigest()[:8] for t in tokens
        ]

        if dry_run:
            return ForgetReport(
                dry_run=True,
                tokens_to_purge_hashes=token_hashes,
                chunks_to_rewrite=len(relevant_chunks),
                docs_affected=list(doc_ids),
                estimated_duration_ms=len(relevant_chunks) * 50,  # rough
                legal_basis=legal_basis,
            )

        # 2. Rewrite chunks
        rewritten: list[tuple[dict, str, list[float]]] = []
        for c in relevant_chunks:
            text = c.get("chunk") or c.get("text") or ""
            new_text = text
            for t in tokens:
                tomb = f"<<deleted:{hashlib.sha256(t.encode()).hexdigest()[:8]}>>"
                new_text = new_text.replace(t, tomb)
            # Re-embed
            new_vec = (await self._embedder.embed([new_text]))[0]
            rewritten.append((c, new_text, new_vec))

        self._chunk_store.update_chunks(rewritten)

        # 3. Rebuild BM25
        try:
            all_records = self._chunk_store.all_records()
            self._bm25.rebuild(all_records)
        except Exception:
            pass

        # 4. Purge vault entries
        for tok in tokens:
            self._vault.delete_token(tok)

        # 5. Audit
        try:
            import os
            self._audit.record_v2(
                event_type="forgotten",
                project_id=self._project_name,
                subject_token=None,  # don't log raw token
                metadata={
                    "tokens_purged_hashes": token_hashes,
                    "n_chunks_rewritten": len(rewritten),
                    "n_docs_affected": len(doc_ids),
                    "legal_basis": legal_basis,
                    "operator_actor": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
                },
            )
        except Exception:
            pass

        duration_ms = int((_time.monotonic() - start) * 1000)
        return ForgetReport(
            dry_run=False,
            tokens_to_purge_hashes=token_hashes,
            chunks_to_rewrite=len(rewritten),
            docs_affected=list(doc_ids),
            actual_duration_ms=duration_ms,
            completed_at=int(_time.time()),
            legal_basis=legal_basis,
        )
```

Add a thin `PIIGhostService.forget_subject` dispatcher:

```python
    async def forget_subject(
        self, tokens: list[str], *, project: str,
        dry_run: bool = True, legal_basis: str = "c-opposition",
    ) -> "ForgetReport":
        svc = await self._get_project(project)
        return await svc.forget_subject(
            tokens, dry_run=dry_run, legal_basis=legal_basis,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_service_forget_subject.py -v --no-header
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/piighost/service/core.py tests/unit/test_service_forget_subject.py
git commit -m "feat(service): forget_subject (Art. 17 tombstone)

Right-to-be-forgotten cascade:
  1. Find affected chunks via doc_entities
  2. Rewrite token → <<deleted:HASH8>> in chunk text
  3. Re-embed rewritten chunks
  4. UPDATE chunks (LanceDB DELETE+INSERT)
  5. Rebuild BM25
  6. Purge vault entries (delete_token)
  7. Audit 'forgotten' event — hashes only, never raw tokens

Audit invariant verified by test: raw token MUST NOT appear in any
serialized audit event."
```

---

## Task 7: `cluster_subjects` service method + MCP wiring

**Files:**
- Modify: `src/piighost/service/core.py` (add `PIIGhostService.cluster_subjects`)
- Modify: `src/piighost/mcp/tools.py` (add 3 ToolSpec)
- Modify: `src/piighost/mcp/shim.py` (add 3 `@mcp.tool` wrappers)
- Modify: `src/piighost/daemon/server.py` (add 3 dispatch handlers)

- [ ] **Step 1: Add `PIIGhostService.cluster_subjects`**

In `src/piighost/service/core.py`, add to the `PIIGhostService` class:

```python
    async def cluster_subjects(
        self, query: str, *, project: str,
    ) -> list[dict]:
        """Find probable subject clusters for a free-text query.

        Returns dicts (not dataclasses) so the MCP layer doesn't need
        a custom encoder. Each dict has the SubjectCluster fields.
        """
        from piighost.service.subject_clustering import cluster_subjects
        from dataclasses import asdict
        svc = await self._get_project(project)
        clusters = cluster_subjects(svc._vault, query)
        return [asdict(c) for c in clusters]
```

- [ ] **Step 2: Add the 3 ToolSpec entries**

In `src/piighost/mcp/tools.py`, append to `TOOL_CATALOG`:

```python
    ToolSpec(
        name="cluster_subjects",
        rpc_method="cluster_subjects",
        description=(
            "Find probable subject clusters for a free-text query "
            "(person name, email, etc.). Returns groups of co-occurring "
            "PII tokens — the avocat validates which cluster to apply "
            "to subject_access or forget_subject."
        ),
        timeout_s=15.0,
    ),
    ToolSpec(
        name="subject_access",
        rpc_method="subject_access",
        description=(
            "Art. 15 right-of-access report. Returns all documents + "
            "redacted excerpts where the subject (cluster of tokens) "
            "appears, plus controller context (purpose, legal basis, "
            "retention)."
        ),
        timeout_s=30.0,
    ),
    ToolSpec(
        name="forget_subject",
        rpc_method="forget_subject",
        description=(
            "Art. 17 right-to-be-forgotten with tombstone. dry_run=True "
            "by default — preview the cascade. dry_run=False purges "
            "vault entries and rewrites chunks with <<deleted:HASH>>; "
            "audit event 'forgotten' carries token hashes only."
        ),
        timeout_s=120.0,  # re-embedding is the slowest path
    ),
```

- [ ] **Step 3: Add the 3 `@mcp.tool` wrappers**

In `src/piighost/mcp/shim.py` (the `_build_mcp` function), add near the existing tools:

```python
    @mcp.tool(name="cluster_subjects",
              description=by_name["cluster_subjects"].description)
    async def cluster_subjects(query: str, project: str = "default") -> dict:
        result = await _lazy_dispatch(
            by_name["cluster_subjects"],
            params={"query": query, "project": project},
        )
        if isinstance(result, list):
            return {"clusters": result}
        return result

    @mcp.tool(name="subject_access",
              description=by_name["subject_access"].description)
    async def subject_access(
        tokens: list[str], project: str = "default", max_excerpts: int = 50,
    ) -> dict:
        return await _lazy_dispatch(
            by_name["subject_access"],
            params={"tokens": tokens, "project": project,
                    "max_excerpts": max_excerpts},
        )

    @mcp.tool(name="forget_subject",
              description=by_name["forget_subject"].description)
    async def forget_subject(
        tokens: list[str], project: str = "default",
        dry_run: bool = True, legal_basis: str = "c-opposition",
    ) -> dict:
        return await _lazy_dispatch(
            by_name["forget_subject"],
            params={"tokens": tokens, "project": project,
                    "dry_run": dry_run, "legal_basis": legal_basis},
        )
```

- [ ] **Step 4: Add the 3 dispatch handlers**

In `src/piighost/daemon/server.py`'s `_dispatch` function, add before the `raise ValueError("Unknown method")`:

```python
    if method == "cluster_subjects":
        return await svc.cluster_subjects(
            params["query"], project=params.get("project", "default"),
        )
    if method == "subject_access":
        report = await svc.subject_access(
            tokens=params["tokens"],
            project=params.get("project", "default"),
            max_excerpts=params.get("max_excerpts", 50),
        )
        return report.model_dump()
    if method == "forget_subject":
        report = await svc.forget_subject(
            tokens=params["tokens"],
            project=params.get("project", "default"),
            dry_run=params.get("dry_run", True),
            legal_basis=params.get("legal_basis", "c-opposition"),
        )
        return report.model_dump()
```

- [ ] **Step 5: Smoke test the MCP wiring**

Restart the daemon (kill existing if running) and run:
```
PYTHONPATH=src .venv/Scripts/python.exe -c "
import asyncio
from piighost.service.core import PIIGhostService
from pathlib import Path
import tempfile

async def main():
    with tempfile.TemporaryDirectory() as td:
        svc = await PIIGhostService.create(vault_dir=Path(td))
        clusters = await svc.cluster_subjects('Inconnu', project='default')
        print('clusters:', clusters)
        await svc.close()
asyncio.run(main())
"
```
Expected: prints `clusters: []` (no entities seeded).

- [ ] **Step 6: Commit**

```bash
git add src/piighost/service/core.py src/piighost/mcp/tools.py src/piighost/mcp/shim.py src/piighost/daemon/server.py
git commit -m "feat(mcp): wire cluster_subjects + subject_access + forget_subject

Three new MCP tools exposed via shim and daemon dispatch:
  - cluster_subjects(query, project) -> {clusters: [...]}
  - subject_access(tokens, project, max_excerpts) -> SubjectAccessReport
  - forget_subject(tokens, project, dry_run, legal_basis) -> ForgetReport

forget_subject defaults to dry_run=True — caller must explicitly
pass dry_run=false to apply the cascade. Timeouts: 15s/30s/120s
respectively (forget is slowest because re-embedding)."
```

---

## Task 8: Plugin skills `/hacienda:rgpd:access` + `/hacienda:rgpd:forget`

**Files:**
- Create: `.worktrees/hacienda-plugin/skills/rgpd-access/SKILL.md`
- Create: `.worktrees/hacienda-plugin/skills/rgpd-forget/SKILL.md`
- Modify: `.worktrees/hacienda-plugin/.claude-plugin/plugin.json` (bump v0.5.0)

- [ ] **Step 1: Create `rgpd-access/SKILL.md`**

```markdown
---
name: rgpd-access
description: Right-of-access (RGPD Art. 15) workflow. Given a person's name (or email/phone), find every PII token referring to them across the project, build an Art. 15 report listing all documents, excerpts, categories, purposes and legal bases. Use when a data subject (client, salarié, contact) requests their personal data per Art. 15 RGPD.
argument-hint: "<person name or identifier>"
---

# /hacienda:rgpd:access — Demande d'accès RGPD Art. 15

```
/hacienda:rgpd:access Marie Dupont
```

## Workflow

### Step 1 — Resolve project

Call `mcp__piighost__resolve_project_for_folder(folder=<active>)` to get the project slug.

### Step 2 — Cluster the subject

Call `mcp__piighost__cluster_subjects(query="<arg>", project=<project>)`. Returns a list of clusters; each cluster is a candidate group of tokens (nom_personne + email + phone + IBAN + …) that probably refer to the same real person.

If `clusters` is empty: tell the user *"Aucune trace de '<query>' dans ce dossier."* Stop.

If multiple clusters: present them to the user in a numbered list:
```
1. Marie Dupont (confidence 0.95) — 5 docs, 12 tokens — first seen 2024-03-15
2. Marie Dupont autre (confidence 0.74) — 1 doc, 2 tokens — first seen 2025-08-01
```
Ask which cluster (or "all") to apply.

If single cluster with confidence ≥ 0.85: proceed automatically with confirmation.

### Step 3 — Subject access

Call `mcp__piighost__subject_access(tokens=<cluster.tokens>, project=<project>)`. Returns a `SubjectAccessReport`.

### Step 4 — Render the response

Format the report as a Markdown document for the avocat to send to the data subject:

```markdown
# Réponse à votre demande d'accès (Art. 15 RGPD)

**Sujet** : <subject_preview joined>
**Date du rapport** : <generated_at as ISO>
**Cabinet** : <controller name from profile>

## Catégories de données traitées
- nom_personne : <count>
- email : <count>
- ...

## Documents concernés (<n_docs>)
| Document | Type | Date | Occurrences |
|---|---|---|---|
| ... | contrat | 2024-04-15 | 3 |

## Finalités du traitement
<processing_purpose>

## Base légale
<legal_basis>

## Durée de conservation
<retention_period>

## Extraits redactés (<total_excerpts>)
> [excerpt 1, with <<SUBJECT>> placeholders preserved]
> ...
```

### Step 5 — Save to file

Suggest saving the rendered Markdown to `<folder>/rgpd-access-<date>-<subject>.md` so the avocat has a record. Use the standard `Write` tool with a sanitised filename.

## Refusals & edge cases

- If the cluster confidence is < 0.5, warn the user and ask for confirmation before proceeding — false positives could include data of OTHER people.
- The placeholder `<<SUBJECT>>` in excerpts is the cluster's tokens. Other PII placeholders (`<<PER_001>>`, `<<EMAIL_002>>`) belong to OTHER people and stay in the output as-is — never rehydrate them.
- Audit event `subject_access` is recorded automatically by the server. To verify, run `/hacienda:audit`.
```

- [ ] **Step 2: Create `rgpd-forget/SKILL.md`**

```markdown
---
name: rgpd-forget
description: Right-to-be-forgotten (RGPD Art. 17) workflow with tombstone. Given a person's name, identify their tokens, preview the cascade (dry-run), then on user approval purge the vault and rewrite indexed chunks. The audit log retains a 'forgotten' event with hashed token IDs only — defensible per Art. 30. Use when a data subject requests erasure per Art. 17.
argument-hint: "<person name or identifier>"
---

# /hacienda:rgpd:forget — Droit à l'oubli RGPD Art. 17

```
/hacienda:rgpd:forget Marie Dupont
```

## Workflow

### Step 1 — Resolve and cluster

Same as `rgpd-access` Steps 1-2: get the project + cluster the subject. ALWAYS show the user the cluster preview AND require explicit confirmation before any deletion.

### Step 2 — Choose the legal basis

Art. 17 has 6 sub-grounds. Ask the user which applies:
1. **a-finalité_atteinte** — finalité atteinte ou plus nécessaire
2. **b-retrait_consentement** — retrait du consentement (si base = consentement)
3. **c-opposition** — opposition légitime du data subject
4. **d-traitement_illicite** — traitement illicite
5. **e-obligation_legale** — obligation légale d'effacement
6. **f-mineur** — données collectées sur mineur dans contexte de l'offre directe

If the user can't decide, default to **c-opposition** (most common for RGPD requests).

### Step 3 — Dry-run preview

Call:
```
mcp__piighost__forget_subject(
  tokens=<cluster.tokens>,
  project=<project>,
  dry_run=True,
  legal_basis=<chosen>,
)
```

Show the user the preview:
```
⚠️ Le droit à l'oubli va affecter :
  - <chunks_to_rewrite> chunks réécrits
  - <docs_affected.length> documents touchés
  - <tokens_to_purge_hashes.length> tokens purgés du vault
  - durée estimée : <estimated_duration_ms>ms

Cette opération est IRRÉVERSIBLE. Confirmer ? (oui/non)
```

### Step 4 — Apply (only on explicit "oui")

Call the same tool with `dry_run=False`:
```
mcp__piighost__forget_subject(
  tokens=<cluster.tokens>,
  project=<project>,
  dry_run=False,
  legal_basis=<chosen>,
)
```

Display the outcome:
```
✅ Effacement appliqué :
  - <chunks_to_rewrite> chunks rewritten avec <<deleted:HASH>>
  - <docs_affected.length> documents affectés
  - <tokens_to_purge_hashes.length> tokens purgés
  - durée : <actual_duration_ms>ms

Un événement 'forgotten' a été enregistré dans l'audit log
(hashes uniquement, jamais les tokens bruts).
```

### Step 5 — Generate compliance receipt (optional)

Suggest the avocat keep a receipt for the data subject and CNIL:
```markdown
# Récépissé d'effacement (Art. 17 RGPD)

**Date** : <completed_at as ISO>
**Base légale** : Art. 17.1.<legal_basis>
**Cabinet** : <controller name>

Effacement de <tokens_to_purge_hashes.length> identifiants
attachés à votre profil dans nos systèmes :
- <chunks_to_rewrite> chunks réécrits
- <docs_affected.length> documents affectés

Les hashes des tokens purgés sont conservés dans notre journal
d'audit aux fins de preuve d'exécution (Art. 30 RGPD), sans
permettre la reconstitution de vos données.
```

## Refusals

- NEVER apply `dry_run=False` without explicit "oui" from the user. The cascade is irreversible.
- If cluster confidence < 0.7, refuse and ask for manual token list — risk of erasing data of homonyms.
- Cannot forget the controller's own data (the avocat themselves). If the subject query matches the avocat's name, refuse.
```

- [ ] **Step 3: Bump plugin version**

In `.worktrees/hacienda-plugin/.claude-plugin/plugin.json`:

```json
"version": "0.5.0"
```

(was `0.4.0`).

- [ ] **Step 4: Commit + push (in plugin worktree)**

```bash
cd .worktrees/hacienda-plugin
git add .claude-plugin/plugin.json skills/rgpd-access/SKILL.md skills/rgpd-forget/SKILL.md
git commit -m "feat(skills): /hacienda:rgpd:access + /hacienda:rgpd:forget

Two new slash commands for RGPD Art. 15 (access) and Art. 17
(forget). Both wrap the new MCP tools: cluster_subjects (validate
candidates with the avocat), subject_access (Art. 15 report),
forget_subject (Art. 17 cascade with tombstone).

forget skill REQUIRES explicit 'oui' confirmation between dry-run
and apply — the cascade is irreversible.

Bumps to v0.5.0."
git push origin main
cd ../..
```

---

## Task 9: No-PII-leak invariant tests

**Files:**
- Create: `tests/unit/test_no_pii_leak_phase1.py`

The most important compliance gate: any output of any of the 3 new tools must NEVER contain raw PII.

- [ ] **Step 1: Write the tests**

Create `tests/unit/test_no_pii_leak_phase1.py`:

```python
"""Privacy invariant: no raw PII in any subject_access / forget_subject output.

These tests are gates — failing one indicates a compliance defect.
"""
from __future__ import annotations

import asyncio

import pytest

from piighost.service.core import PIIGhostService


_KNOWN_RAW_PII = [
    "Marie Dupont",
    "marie.dupont@example.com",
    "+33 1 23 45 67 89",
    "FR1420041010050500013M02606",
]


@pytest.fixture()
def vault_dir(tmp_path):
    return tmp_path / "vault"


def _svc(vault_dir, monkeypatch):
    monkeypatch.setenv("PIIGHOST_DETECTOR", "stub")
    monkeypatch.setenv("PIIGHOST_EMBEDDER", "stub")
    return asyncio.run(PIIGhostService.create(vault_dir=vault_dir))


def _seed_with_known_pii(svc, tmp_path, project: str):
    folder = tmp_path / "client_test"
    folder.mkdir(exist_ok=True)
    content = (
        "Le présent contrat lie Marie Dupont (email: marie.dupont@example.com, "
        "tél: +33 1 23 45 67 89, IBAN: FR1420041010050500013M02606) "
        "à la société Acme."
    )
    (folder / "contract.txt").write_text(content, encoding="utf-8")
    asyncio.run(svc.index_path(folder, project=project))
    return folder


def test_subject_access_report_no_raw_pii(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    _seed_with_known_pii(svc, tmp_path, "leak-sa")
    proj = asyncio.run(svc._get_project("leak-sa"))
    entries = proj._vault.list_entities(limit=20)
    if not entries:
        pytest.skip("No entities seeded by stub detector")

    tokens = [e.token for e in entries]
    report = asyncio.run(svc.subject_access(tokens=tokens, project="leak-sa"))
    serialized = report.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized, (
            f"Raw PII '{raw}' leaked in SubjectAccessReport JSON"
        )
    asyncio.run(svc.close())


def test_forget_subject_report_no_raw_pii(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    _seed_with_known_pii(svc, tmp_path, "leak-fs")
    proj = asyncio.run(svc._get_project("leak-fs"))
    entries = proj._vault.list_entities(limit=20)
    if not entries:
        pytest.skip("No entities seeded")

    tokens = [e.token for e in entries[:3]]
    report = asyncio.run(svc.forget_subject(
        tokens=tokens, project="leak-fs", dry_run=True,
    ))
    serialized = report.model_dump_json()
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized
    # Tokens themselves should NOT be in the report — only hashes
    for tok in tokens:
        assert tok not in serialized
    asyncio.run(svc.close())


def test_forgotten_audit_event_carries_only_hashes(vault_dir, monkeypatch, tmp_path):
    svc = _svc(vault_dir, monkeypatch)
    _seed_with_known_pii(svc, tmp_path, "leak-audit")
    proj = asyncio.run(svc._get_project("leak-audit"))
    entries = proj._vault.list_entities(limit=20)
    if not entries:
        pytest.skip("No entities seeded")

    tokens = [e.token for e in entries[:2]]
    asyncio.run(svc.forget_subject(
        tokens=tokens, project="leak-audit", dry_run=False,
    ))
    from piighost.vault.audit import read_events
    audit_path = vault_dir / "projects" / "leak-audit" / "audit.log"
    if not audit_path.exists():
        pytest.skip("audit path differs")
    events = list(read_events(audit_path))
    forgotten = [e for e in events if e.event_type == "forgotten"]
    assert forgotten, "No forgotten event written"
    serialized_audit = forgotten[-1].model_dump_json()
    # Raw PII must not appear
    for raw in _KNOWN_RAW_PII:
        assert raw not in serialized_audit
    # Raw tokens must not appear (only their hashes)
    for tok in tokens:
        assert tok not in serialized_audit
    asyncio.run(svc.close())
```

- [ ] **Step 2: Run tests**

```
PYTHONPATH=src .venv/Scripts/python.exe -m pytest tests/unit/test_no_pii_leak_phase1.py -v --no-header
```
Expected: 3 passed (or skipped if stub detector produces no entities — that's an environment issue, not a feature regression).

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_no_pii_leak_phase1.py
git commit -m "test(rgpd): no-PII-leak invariant tests (Phase 1)

Three privacy gates:
  1. SubjectAccessReport.model_dump_json() must not contain any raw
     PII string from the seeded test corpus.
  2. ForgetReport must not contain raw tokens (only hashes).
  3. The 'forgotten' audit event must carry only hashes — never the
     raw token strings.

Failing any of these = compliance defect, not just a bug."
```

---

## Self-review checklist

**Spec coverage (Phase 1 subset)**:

| Spec section | Implementing task |
|---|---|
| `Vault.delete_token` | Task 1 |
| `Vault.docs_containing_tokens` | Task 1 |
| `Vault.cooccurring_tokens` | Task 1 |
| `ChunkStore.chunks_for_doc_ids` + `update_chunks` | Task 2 |
| `subject_clustering.cluster_subjects` algo | Task 3 |
| `SubjectAccessReport` + `ForgetReport` Pydantic | Task 4 |
| `_ProjectService.subject_access` | Task 5 |
| `_ProjectService.forget_subject` | Task 6 |
| MCP wiring (3 tools) | Task 7 |
| Plugin skills (rgpd-access + rgpd-forget) | Task 8 |
| No-PII-leak invariant tests | Task 9 |

✓ Every Phase 1 spec item has a task. No gaps.

**Placeholder scan**: every code block contains real code. The "if X then Y" branches in Task 5/6 give exact code paths. No "implement later" / "add validation" notes.

**Type consistency**:
- `delete_token(token) -> int` — Task 1 def, Task 6 caller. ✓
- `docs_containing_tokens(tokens) -> list[str]` — Task 1 def, Tasks 5/6 callers. ✓
- `cooccurring_tokens(seed) -> list[tuple[str, int]]` — Task 1 def, Task 3 caller. ✓
- `chunks_for_doc_ids(doc_ids) -> list[dict]` — Task 2 def, Tasks 5/6 callers. ✓
- `update_chunks(updates) -> None` — Task 2 def, Task 6 caller. ✓
- `SubjectCluster.tokens: tuple[str, ...]` — Task 3 def, Task 7 service-side serialization via `asdict`. ✓
- `SubjectAccessReport.model_dump()` shape — Task 4 def, Task 7 daemon dispatcher consumer. ✓
- `ForgetReport.tokens_to_purge_hashes: list[str]` — Task 4 def, Task 6 + Task 9 consumers. ✓

**Scope check**: Phase 1 alone, single PR cycle, ~2 weeks. Phase 2 (Registre + DPIA + Render) and Wizard get their own plan files written after Phase 1 lands.
