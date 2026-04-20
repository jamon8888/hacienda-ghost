import asyncio
from pathlib import Path
import pytest
from piighost.indexer.ingestor import list_document_paths, extract_text


def test_list_document_paths_single_file(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("hello")
    result = asyncio.run(list_document_paths(f))
    assert result == [f]


def test_list_document_paths_dir_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.md").write_text("b")
    (sub / "img.png").write_bytes(b"\x89PNG")
    result = asyncio.run(list_document_paths(tmp_path, recursive=True))
    names = {p.name for p in result}
    assert "a.txt" in names
    assert "b.md" in names
    assert "img.png" not in names


def test_list_document_paths_non_recursive(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.txt").write_text("b")
    result = asyncio.run(list_document_paths(tmp_path, recursive=False))
    names = {p.name for p in result}
    assert "a.txt" in names
    assert "b.txt" not in names


def test_extract_text_plain_txt(tmp_path):
    f = tmp_path / "hello.txt"
    f.write_text("Hello World")
    text = asyncio.run(extract_text(f))
    assert text is not None
    assert "Hello" in text


def test_extract_text_empty_file(tmp_path):
    f = tmp_path / "empty.txt"
    f.write_text("   ")
    assert asyncio.run(extract_text(f)) is None


def test_extract_text_oversized_file(tmp_path):
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    assert asyncio.run(extract_text(f, max_bytes=10 * 1024 * 1024)) is None
