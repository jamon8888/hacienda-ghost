"""LegalCache — SQLite TTL cache for OpenLégi responses."""
from __future__ import annotations

import json
import time

import pytest

from piighost.legal.cache import LegalCache


@pytest.fixture()
def cache(tmp_path):
    return LegalCache(vault_dir=tmp_path)


def test_set_then_get(cache):
    cache.set("verify_legal_ref", {"ref_id": 1}, response={"status": "OK"}, ttl_seconds=3600)
    hit = cache.get("verify_legal_ref", {"ref_id": 1})
    assert hit == {"status": "OK"}


def test_get_returns_none_on_miss(cache):
    assert cache.get("verify_legal_ref", {"ref_id": 99}) is None


def test_canonical_key_matches_dict_order(cache):
    """{a:1, b:2} and {b:2, a:1} must produce the same cache key."""
    cache.set("search_legal", {"a": 1, "b": 2}, response={"v": "x"}, ttl_seconds=60)
    hit = cache.get("search_legal", {"b": 2, "a": 1})
    assert hit == {"v": "x"}


def test_ttl_expiration(cache, monkeypatch):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=1)
    fake_now = time.time() + 5  # 5s in the future
    monkeypatch.setattr("time.time", lambda: fake_now)
    assert cache.get("verify_legal_ref", {"k": 1}) is None


def test_clear_all(cache):
    cache.set("verify_legal_ref", {"k": 1}, response={}, ttl_seconds=60)
    cache.set("search_legal", {"q": "x"}, response={}, ttl_seconds=60)
    n = cache.clear()
    assert n == 2
    assert cache.get("verify_legal_ref", {"k": 1}) is None
    assert cache.get("search_legal", {"q": "x"}) is None


def test_hits_counter_increments(cache):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=60)
    cache.get("verify_legal_ref", {"k": 1})
    cache.get("verify_legal_ref", {"k": 1})
    cache.get("verify_legal_ref", {"k": 1})
    stats = cache.stats()
    assert stats["total_hits"] == 3


def test_cache_survives_reopen(cache, tmp_path):
    cache.set("verify_legal_ref", {"k": 1}, response={"v": 1}, ttl_seconds=3600)
    cache.close()
    cache2 = LegalCache(vault_dir=tmp_path)
    assert cache2.get("verify_legal_ref", {"k": 1}) == {"v": 1}
