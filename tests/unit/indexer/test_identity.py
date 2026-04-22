import hashlib
from piighost.indexer.identity import content_hash, content_hash_full, file_fingerprint


def test_hash_is_16_chars(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello world")
    assert len(content_hash(f)) == 16


def test_hash_is_deterministic(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello world")
    assert content_hash(f) == content_hash(f)


def test_hash_differs_for_different_content(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("hello")
    b.write_text("world")
    assert content_hash(a) != content_hash(b)


def test_hash_same_content_different_path(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "sub" / "b.txt"
    b.parent.mkdir()
    a.write_text("identical content")
    b.write_text("identical content")
    assert content_hash(a) == content_hash(b)


def test_hash_is_hex_string(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"\x00\x01\x02\xff")
    h = content_hash(f)
    int(h, 16)  # raises ValueError if not valid hex


def test_content_hash_full_returns_64_chars(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"hello world")
    result = content_hash_full(f)
    assert len(result) == 64
    assert result == hashlib.sha256(b"hello world").hexdigest()


def test_content_hash_full_is_prefix_of_full_hash(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"test data")
    short = content_hash(f)
    full = content_hash_full(f)
    assert full.startswith(short)


def test_file_fingerprint_returns_mtime_and_size(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"fingerprint test")
    mtime, size = file_fingerprint(f)
    stat = f.stat()
    assert mtime == stat.st_mtime
    assert size == stat.st_size
    assert isinstance(mtime, float)
    assert isinstance(size, int)


def test_content_hash_unchanged_backward_compat(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_bytes(b"backward compat")
    result = content_hash(f)
    assert len(result) == 16
