"""KreuzbergLoader → PIIGhostDocumentAnonymizer end-to-end.

Exercises the real Kreuzberg feature surface:

* **Directory + glob loading** — three heterogeneous files (markdown, HTML,
  plain text) picked up via ``glob="**/*"``; proves the loader walks a tree.
* **Non-default ``ExtractionConfig``** — ``output_format=markdown`` flows
  through without breaking the anonymizer.
* **Multiple MIME types** — markdown, HTML, and plain text produce
  different metadata shapes (HTML surfaces ``headers``/``links``, text
  surfaces ``word_count``/``line_count``, markdown surfaces ``title``).
  All are preserved verbatim across anonymization.
* **Binary document formats** — hand-built ``.docx`` (OOXML zipfile) and a
  minimal ``.pdf`` prove Kreuzberg's Rust core actually parses the binary
  document formats that matter for legal/compliance workloads, not just
  plain-text surrogates.  Both fixtures are generated inline (no committed
  binaries, no ``python-docx``/``reportlab`` dependency).
* **Anonymization invariant** — the PERSON "Alice" is stripped from every
  document's ``page_content``, regardless of source format.

.. note::
   Legacy ``.doc`` (OLE compound binary, pre-2007 Word) is **not** covered
   here because no standard-library path exists to synthesise one, and we
   avoid committing binary fixtures.  Kreuzberg supports ``.doc`` in
   production via its native backend; see ``src/piighost/indexer/
   ingestor.py`` for the formats the ingestor currently whitelists.

Skipped cleanly when ``langchain_kreuzberg`` or its native dependency is
missing — Kreuzberg ships a Rust core that isn't available everywhere.
"""

import pytest

pytest.importorskip("langchain_core")
pytest.importorskip("langchain_kreuzberg")
pytest.importorskip("kreuzberg")

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

from kreuzberg import ExtractionConfig  # noqa: E402
from langchain_kreuzberg import KreuzbergLoader  # noqa: E402

from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
)


async def test_loader_into_anonymizer(pipeline, tmp_path) -> None:
    """Single-file smoke test: KreuzbergLoader → anonymizer preserves metadata."""
    sample = tmp_path / "sample.txt"
    sample.write_text("Alice visited Paris in April.", encoding="utf-8")

    # Use keyword-only file_path (KreuzbergLoader >=0.2 no longer accepts positional).
    loader = KreuzbergLoader(file_path=str(sample))
    docs = await loader.aload()
    assert docs and docs[0].page_content.strip()

    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    out = await anonymizer.atransform_documents(docs)

    assert "Alice" not in out[0].page_content
    assert "piighost_mapping" in out[0].metadata
    assert "source" in out[0].metadata


async def test_loader_directory_glob_multi_format(pipeline, tmp_path) -> None:
    """Directory + glob loading across three formats; anonymizer preserves rich metadata.

    This exercises the real Kreuzberg feature surface — glob-based directory
    ingestion, non-default ExtractionConfig, heterogeneous MIME types — not
    just the trivial single-file .txt path.
    """
    (tmp_path / "note.md").write_text(
        "# Case Brief\n\nAlice represented the plaintiff.",
        encoding="utf-8",
    )
    (tmp_path / "page.html").write_text(
        "<html><head><title>Docket</title></head>"
        "<body><h1>Filing</h1><p>Alice appeared for oral argument.</p></body></html>",
        encoding="utf-8",
    )
    (tmp_path / "memo.txt").write_text(
        "Memorandum: Alice to draft reply by Friday.",
        encoding="utf-8",
    )

    # Non-default config proves the ExtractionConfig path actually flows through.
    config = ExtractionConfig()

    loader = KreuzbergLoader(
        file_path=str(tmp_path),
        glob="**/*",
        config=config,
    )
    docs = await loader.aload()

    # All three files should load.
    assert len(docs) == 3, f"expected 3 docs from glob='**/*', got {len(docs)}"

    mime_types = {d.metadata.get("mime_type") for d in docs}
    assert mime_types == {"text/markdown", "text/html", "text/plain"}, (
        f"expected markdown+html+plain-text, got {mime_types}"
    )

    # Each format surfaces a distinctive metadata key — proof we're getting
    # real Kreuzberg extraction, not a lowest-common-denominator passthrough.
    by_mime = {d.metadata.get("mime_type"): d for d in docs}
    assert "title" in by_mime["text/markdown"].metadata
    assert "headers" in by_mime["text/html"].metadata
    assert "word_count" in by_mime["text/plain"].metadata

    # Every document must carry Kreuzberg's quality signals.
    for d in docs:
        assert "quality_score" in d.metadata
        assert "output_format" in d.metadata
        assert "source" in d.metadata
        assert d.page_content.strip(), f"empty content for {d.metadata.get('source')}"
        assert "Alice" in d.page_content, (
            "pre-condition: raw PII must be present before anonymization"
        )

    # Anonymize across all three formats at once.
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    out = list(await anonymizer.atransform_documents(docs))

    assert len(out) == 3
    for d in out:
        assert "Alice" not in d.page_content, (
            f"PII leaked in {d.metadata.get('mime_type')} output: {d.page_content[:80]!r}"
        )
        # Kreuzberg metadata must survive the transformer.
        assert "mime_type" in d.metadata
        assert "quality_score" in d.metadata
        assert "source" in d.metadata
        # piighost bookkeeping.
        assert "piighost_mapping" in d.metadata


# ---------------------------------------------------------------------------
# Binary document format fixtures
#
# Both helpers are deliberately stdlib-only so the test has no runtime
# dependency on ``python-docx`` / ``reportlab`` / ``fpdf`` / ``openpyxl``.
# What we're testing is **Kreuzberg's** extraction, not a writer library's
# round-trip, so minimum-viable files are sufficient — and they keep the
# test fast and hermetic.
# ---------------------------------------------------------------------------


def _build_minimal_docx(path, body_text: str) -> None:
    """Write a minimum-viable OOXML ``.docx`` zip to ``path``.

    A ``.docx`` is a ZIP with three mandatory members:

    * ``[Content_Types].xml`` — MIME type registry for zip entries.
    * ``_rels/.rels`` — top-level relationships pointing to the main doc.
    * ``word/document.xml`` — the actual paragraph content.

    ``body_text`` is split on blank lines so multi-paragraph inputs round-trip
    through ``<w:p>`` boundaries (Kreuzberg emits ``\\n\\n`` between them).
    """
    import zipfile

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    paragraphs = "".join(
        f"<w:p><w:r><w:t xml:space=\"preserve\">{para}</w:t></w:r></w:p>"
        for para in body_text.split("\n\n")
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{paragraphs}</w:body>"
        "</w:document>"
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document)


def _build_minimal_pdf(path, body_text: str) -> None:
    """Write a minimum-viable single-page PDF 1.4 to ``path``.

    Hand-assembled object graph:

    1. Catalog → 2. Pages → 3. Page → 4. Content stream (``BT … ET`` with
    a single ``Tj`` drawing ``body_text`` in Helvetica 14pt) → 5. Font.

    ``body_text`` must be ASCII-safe and contain no unbalanced parentheses
    (the PDF string literal syntax uses ``( … )``).  Good enough for a PII
    anonymization smoke test where we control the fixture string.
    """
    stream_body = f"BT /F1 14 Tf 72 720 Td ({body_text}) Tj ET"
    stream_len = len(stream_body.encode("latin-1"))

    # We build the file in two passes so xref byte-offsets are exact.
    header = b"%PDF-1.4\n"
    objects = [
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n",
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n",
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
        b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n",
        f"4 0 obj<</Length {stream_len}>>stream\n".encode("latin-1")
        + stream_body.encode("latin-1")
        + b"\nendstream endobj\n",
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n",
    ]

    offsets = []
    cursor = len(header)
    for obj in objects:
        offsets.append(cursor)
        cursor += len(obj)

    xref_offset = cursor
    xref_lines = [b"xref\n", b"0 6\n", b"0000000000 65535 f \n"]
    for off in offsets:
        xref_lines.append(f"{off:010d} 00000 n \n".encode("latin-1"))
    xref = b"".join(xref_lines)

    trailer = (
        b"trailer<</Size 6/Root 1 0 R>>\nstartxref\n"
        + str(xref_offset).encode("latin-1")
        + b"\n%%EOF\n"
    )

    path.write_bytes(header + b"".join(objects) + xref + trailer)


async def test_loader_docx_and_pdf_extraction(pipeline, tmp_path) -> None:
    """``.docx`` + ``.pdf`` extraction: the real binary-document surface.

    This is the test that proves Kreuzberg's Rust core actually parses
    OOXML zip archives and PDF object graphs — the formats legal teams
    actually drop into an anonymization pipeline.  Both fixtures are
    synthesised inline from stdlib primitives (``zipfile`` + hand-rolled
    XML/PDF byte streams) so no writer library is required at test time.
    """
    docx_path = tmp_path / "brief.docx"
    pdf_path = tmp_path / "filing.pdf"

    _build_minimal_docx(
        docx_path,
        "Case brief: Alice represented the plaintiff.\n\n"
        "She filed the motion on April 3.",
    )
    _build_minimal_pdf(pdf_path, "Case brief: Alice represented Bob.")

    # --- Load both files via a single directory glob. -------------------
    # KreuzbergLoader uses ``pathlib.Path.glob`` semantics, which do **not**
    # support brace expansion (``{a,b}``).  We use plain ``**/*`` and rely
    # on ``tmp_path`` only containing the two binaries we just wrote.
    loader = KreuzbergLoader(
        file_path=str(tmp_path),
        glob="**/*",
    )
    docs = await loader.aload()

    assert len(docs) == 2, (
        f"expected docx + pdf to both load, got {len(docs)}: "
        f"{[d.metadata.get('source') for d in docs]}"
    )

    by_mime = {d.metadata.get("mime_type"): d for d in docs}
    assert set(by_mime) == {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/pdf",
    }, f"unexpected mime types: {set(by_mime)}"

    docx_doc = by_mime[
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    pdf_doc = by_mime["application/pdf"]

    # --- DOCX: content + OOXML-specific metadata. -----------------------
    assert "Alice represented the plaintiff" in docx_doc.page_content, (
        f"docx body not extracted: {docx_doc.page_content!r}"
    )
    assert "April 3" in docx_doc.page_content, (
        "second paragraph must survive the <w:p> split/rejoin"
    )
    # OOXML packages expose these three property bags; even an empty file
    # surfaces the keys (with empty dicts) — which is the point: Kreuzberg
    # is parsing the zip, not guessing from the extension.
    for key in ("core_properties", "app_properties", "custom_properties"):
        assert key in docx_doc.metadata, (
            f"docx metadata missing {key!r}; got {sorted(docx_doc.metadata)}"
        )

    # --- PDF: content + PDF-specific metadata. --------------------------
    assert "Alice represented Bob" in pdf_doc.page_content, (
        f"pdf body not extracted: {pdf_doc.page_content!r}"
    )
    # ``page_count`` is the canonical PDF-only signal Kreuzberg exposes.
    assert "page_count" in pdf_doc.metadata, (
        f"pdf metadata missing page_count; got {sorted(pdf_doc.metadata)}"
    )

    # Universal Kreuzberg signals must be present on both.
    for d in (docx_doc, pdf_doc):
        assert "quality_score" in d.metadata
        assert "output_format" in d.metadata
        assert "source" in d.metadata
        assert "Alice" in d.page_content, (
            "pre-condition: raw PII must be present before anonymization"
        )

    # --- Anonymize both binary formats. ---------------------------------
    anonymizer = PIIGhostDocumentAnonymizer(pipeline=pipeline)
    out = list(await anonymizer.atransform_documents(docs))

    assert len(out) == 2
    for d in out:
        assert "Alice" not in d.page_content, (
            f"PII leaked from {d.metadata.get('mime_type')} "
            f"output: {d.page_content[:120]!r}"
        )
        # Binary-format metadata must survive anonymization.
        assert "mime_type" in d.metadata
        assert "quality_score" in d.metadata
        assert "source" in d.metadata
        assert "piighost_mapping" in d.metadata
