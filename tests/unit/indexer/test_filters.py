from piighost.indexer.filters import QueryFilter


def test_empty_filter_is_empty():
    f = QueryFilter()
    assert f.is_empty()
    assert f.to_lance_where() is None


def test_file_path_prefix_builds_like_clause():
    f = QueryFilter(file_path_prefix="/projects/client-a")
    assert not f.is_empty()
    assert f.to_lance_where() == "file_path LIKE '/projects/client-a%'"


def test_doc_ids_build_in_clause():
    f = QueryFilter(doc_ids=("abc123", "def456"))
    assert f.to_lance_where() == "doc_id IN ('abc123', 'def456')"


def test_combined_filter_joins_with_and():
    f = QueryFilter(file_path_prefix="/a", doc_ids=("abc",))
    where = f.to_lance_where()
    assert "file_path LIKE '/a%'" in where
    assert "doc_id IN ('abc')" in where
    assert " AND " in where


def test_matches_respects_prefix():
    f = QueryFilter(file_path_prefix="/a/")
    assert f.matches("x", "/a/docs.txt") is True
    assert f.matches("x", "/b/docs.txt") is False


def test_matches_respects_doc_ids():
    f = QueryFilter(doc_ids=("abc", "def"))
    assert f.matches("abc", "/x.txt") is True
    assert f.matches("zzz", "/x.txt") is False


def test_matches_empty_filter_allows_all():
    f = QueryFilter()
    assert f.matches("x", "/anywhere.txt") is True


def test_single_quote_in_prefix_is_escaped():
    f = QueryFilter(file_path_prefix="/o'brien/")
    assert "o''brien" in f.to_lance_where()


def test_filter_is_hashable():
    f = QueryFilter(file_path_prefix="/a", doc_ids=("x",))
    {f}  # no TypeError


def test_filter_is_frozen():
    import dataclasses
    f = QueryFilter()
    assert dataclasses.is_dataclass(f)
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.file_path_prefix = "/new"
