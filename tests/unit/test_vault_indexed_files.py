from piighost.vault.store import Vault


def _open(tmp_path):
    return Vault.open(tmp_path / "vault.db")


def test_upsert_and_get_by_path(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    rec = v.get_indexed_file_by_path("/docs/a.txt")
    assert rec is not None
    assert rec.doc_id == "abc123"
    assert rec.chunk_count == 5
    v.close()


def test_upsert_updates_existing(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    v.upsert_indexed_file("def456", "/docs/a.txt", "def456", 2000.0, 8)
    rec = v.get_indexed_file_by_path("/docs/a.txt")
    assert rec.doc_id == "def456"
    assert rec.chunk_count == 8
    v.close()


def test_delete_indexed_file(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    removed = v.delete_indexed_file("abc123")
    assert removed is True
    assert v.get_indexed_file_by_path("/docs/a.txt") is None
    v.close()


def test_list_indexed_files(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("aaa", "/a.txt", "aaa", 1.0, 2)
    v.upsert_indexed_file("bbb", "/b.txt", "bbb", 2.0, 3)
    files = v.list_indexed_files()
    assert len(files) == 2
    v.close()


def test_count_and_total_chunks(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("aaa", "/a.txt", "aaa", 1.0, 4)
    v.upsert_indexed_file("bbb", "/b.txt", "bbb", 2.0, 6)
    assert v.count_indexed_files() == 2
    assert v.total_chunk_count() == 10
    v.close()


def test_upsert_same_doc_id_updates_in_place(tmp_path):
    v = _open(tmp_path)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "abc123", 1000.0, 5)
    v.upsert_indexed_file("abc123", "/docs/a.txt", "newHash", 2000.0, 9)
    rec = v.get_indexed_file_by_path("/docs/a.txt")
    assert rec.doc_id == "abc123"
    assert rec.chunk_count == 9
    assert rec.content_hash == "newHash"
    v.close()


def test_delete_returns_false_for_missing_doc(tmp_path):
    v = _open(tmp_path)
    assert v.delete_indexed_file("nonexistent") is False
    v.close()
