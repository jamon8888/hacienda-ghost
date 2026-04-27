from __future__ import annotations

from pathlib import Path

# kreuzberg is an optional dep (``[project.optional-dependencies].index``).
# Import it lazily inside ``extract_text`` so that ``list_document_paths``
# — which only uses the standard library — works without the extras
# installed (and so that tests that don't exercise extraction can be
# collected on slim CI environments).

_PLAIN_TEXT_EXTENSIONS = {
    # Files readable directly with the stdlib — no parser needed.
    # .eml is RFC 5322 text. .csv/.tsv/.jsonl are structured but plain
    # text, fine to ingest as-is for chunking/embedding (the chunker
    # treats them as line-oriented text).
    ".txt", ".md", ".rst", ".html", ".htm", ".eml",
    ".csv", ".tsv", ".jsonl",
}

_BINARY_EXTENSIONS = {
    # Office / OpenDocument binaries — require kreuzberg.
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods",
    # Outlook CFB binary container.
    ".msg",
}

_SUPPORTED_EXTENSIONS = _PLAIN_TEXT_EXTENSIONS | _BINARY_EXTENSIONS


async def list_document_paths(
    path: Path, *, recursive: bool = True
) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix.lower() in _SUPPORTED_EXTENSIONS else []
    pattern = "**/*" if recursive else "*"
    return [
        p for p in path.glob(pattern)
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS
    ]


async def extract_text(path: Path, *, max_bytes: int = 10_485_760) -> str | None:
    if path.stat().st_size > max_bytes:
        return None
    if path.suffix.lower() in _PLAIN_TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        return text.strip() if text and text.strip() else None
    try:
        import kreuzberg  # optional dep — installed via `[index]` extras
    except ImportError as exc:
        raise RuntimeError(
            "extract_text requires the 'index' extras for binary formats; "
            "install with `pip install piighost[index]`"
        ) from exc
    try:
        result = await kreuzberg.extract_file(path)
        text = result.content
        return text.strip() if text and text.strip() else None
    except Exception:
        return None


async def extract_with_metadata(path: Path) -> tuple[str | None, dict]:
    """Like ``extract_text`` but also returns the kreuzberg metadata dict.

    Returns ``(text, metadata)``. For plain-text formats, metadata is
    ``{}`` (kreuzberg is not invoked). On extraction failure both are
    returned as ``(None, {})``.

    The metadata is a flat dict in kreuzberg v4.9.4 — keys like
    ``title``, ``authors``, ``created_at``, ``format_type``,
    ``page_count``, ``is_encrypted`` etc. live at the top level
    (NOT nested under ``meta["pdf"]`` like older versions).
    """
    if path.suffix.lower() in _PLAIN_TEXT_EXTENSIONS:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return (text.strip() if text and text.strip() else None), {}
        except OSError:
            return None, {}
    try:
        import kreuzberg  # optional dep — installed via `[index]` extras
    except ImportError:
        return None, {}
    try:
        result = await kreuzberg.extract_file(path)
        text = result.content
        meta = dict(result.metadata or {})
        return ((text.strip() if text and text.strip() else None), meta)
    except Exception:
        return None, {}
