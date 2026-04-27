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
