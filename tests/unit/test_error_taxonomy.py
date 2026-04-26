"""Tests for the error_taxonomy.classify() function — maps persisted
error_message strings to a bounded category enum, never returning the
raw input."""
from __future__ import annotations

import pytest

from piighost.service.error_taxonomy import classify


@pytest.mark.parametrize("msg", [
    "KreuzbergError: file is password-protected",
    "ValueError: PDF is encrypted; provide a password",
    "PdfReadError: could not decrypt /clients/foo/contract.pdf",
])
def test_password_protected(msg):
    assert classify(msg) == "password_protected"


@pytest.mark.parametrize("msg", [
    "ExtractionError: file is corrupt",
    "PdfReadError: invalid PDF header",
    "ValueError: malformed XLSX",
])
def test_corrupt(msg):
    assert classify(msg) == "corrupt"


@pytest.mark.parametrize("msg", [
    "ExtractionError: unsupported file type .heic",
    "RuntimeError: no extractor registered for .key",
    "TypeError: format not supported",
])
def test_unsupported_format(msg):
    assert classify(msg) == "unsupported_format"


@pytest.mark.parametrize("msg", [
    "TimeoutError: extraction timeout after 60s",
    "asyncio.TimeoutError: timed out",
])
def test_timeout(msg):
    assert classify(msg) == "timeout"


@pytest.mark.parametrize("msg", [
    "RuntimeError: something weird happened",
    "ValueError: unknown",
    "",
])
def test_other_fallback(msg):
    assert classify(msg) == "other"


def test_none_input_returns_other():
    assert classify(None) == "other"


def test_classify_is_case_insensitive():
    assert classify("ERROR: PASSWORD-PROTECTED FILE") == "password_protected"


def test_classify_never_returns_input():
    """Spec invariant: raw input must not appear in the output."""
    secret = "ExtractionError: failed on /clients/Martin Dupont/contract.pdf"
    out = classify(secret)
    assert "Martin Dupont" not in out
    assert "/clients" not in out
    assert out == "other"  # path-only message has no taxonomy keyword
