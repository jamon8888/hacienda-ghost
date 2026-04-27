"""Subject clustering — find all PII tokens that refer to the same
real person, given a free-text query.

Uses pure SQL on the existing ``vault.doc_entities`` linkage table
(no full-text search, no embeddings). Each cluster is a group of
tokens that share enough documents to plausibly belong to the same
data subject. The avocat validates the cluster before
``subject_access`` or ``forget_subject`` is applied.
"""
from __future__ import annotations

from dataclasses import dataclass
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
      4. Deduplicate clusters that are strict subsets of one another
         (homonyms with distinct cluster sets stay separate).
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
        cluster_tokens: list[str] = [seed_token]
        for tok, count in cooccs:
            if count >= _MIN_COOCCURRENCE_DOCS:
                cluster_tokens.append(tok)
        token_set = frozenset(cluster_tokens)
        # Skip if this is a strict subset of an already-found cluster
        if any(token_set.issubset(s) and token_set != s for s in seen_token_sets):
            continue
        # Confidence based on how tightly tokens co-occur with seed
        seed_doc_count = len(seed_docs)
        non_seed_cooccs = [(t, c) for t, c in cooccs if t in token_set]
        if non_seed_cooccs and seed_doc_count > 0:
            ratios = [c / seed_doc_count for _, c in non_seed_cooccs]
            confidence = min(1.0, sum(ratios) / len(ratios))
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
