import asyncio

from piighost.reranker.cross_encoder import CrossEncoderReranker
from piighost.service.models import QueryHit


class _FakeCE:
    """Stand-in for sentence_transformers.CrossEncoder — deterministic scores."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def predict(self, pairs):
        # Score = length of chunk (longer chunks "win")
        return [float(len(p[1])) for p in pairs]


def _hit(chunk_id: str, chunk: str, score: float = 0.5) -> QueryHit:
    return QueryHit(
        doc_id=chunk_id,
        file_path=f"/p/{chunk_id}.txt",
        chunk=chunk,
        score=score,
        rank=0,
    )


def test_reranker_reorders_by_fake_score(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    hits = [
        _hit("short", "short"),
        _hit("middle", "middle length chunk"),
        _hit("longest", "the longest chunk of all the chunks here"),
    ]
    reranked = asyncio.run(r.rerank("query", hits))
    # Longest chunk should rank first now
    assert reranked[0].chunk.startswith("the longest")
    assert reranked[-1].chunk == "short"


def test_reranker_assigns_sequential_ranks(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    hits = [_hit("a", "aa"), _hit("b", "bbb"), _hit("c", "c")]
    reranked = asyncio.run(r.rerank("q", hits))
    assert [h.rank for h in reranked] == [0, 1, 2]


def test_reranker_empty_candidates_returns_empty(monkeypatch):
    import piighost.reranker.cross_encoder as mod
    monkeypatch.setattr(mod, "CrossEncoder", _FakeCE, raising=False)

    r = CrossEncoderReranker(model_name="fake-model")
    assert asyncio.run(r.rerank("q", [])) == []
