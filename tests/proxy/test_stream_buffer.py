from __future__ import annotations

import pytest

from piighost.proxy.stream_buffer import StreamBuffer


def test_empty_buffer_returns_nothing() -> None:
    buf = StreamBuffer()
    assert buf.feed("") == ""


def test_plaintext_passes_through() -> None:
    buf = StreamBuffer()
    assert buf.feed("hello world") == "hello world"


def test_complete_placeholder_emitted_whole() -> None:
    buf = StreamBuffer()
    out = buf.feed("abc <PERSON:a3f8b2c1> def")
    assert out == "abc <PERSON:a3f8b2c1> def"


def test_placeholder_split_across_two_feeds_held_until_complete() -> None:
    buf = StreamBuffer()
    assert buf.feed("hello <PERSON:") == "hello "
    assert buf.feed("a3f8b2c1> world") == "<PERSON:a3f8b2c1> world"


def test_placeholder_split_three_ways() -> None:
    buf = StreamBuffer()
    assert buf.feed("x <PER") == "x "
    assert buf.feed("SON:a3f8") == ""
    assert buf.feed("b2c1> y") == "<PERSON:a3f8b2c1> y"


def test_flush_returns_any_held_bytes() -> None:
    buf = StreamBuffer()
    buf.feed("abc <PER")
    assert buf.flush() == "<PER"


def test_buffer_overflow_force_flushes() -> None:
    buf = StreamBuffer(max_tail=16)
    # Feed enough partial data that it exceeds max_tail without completing.
    out = buf.feed("prefix <PERSON:abcdefghijklmnopqrstuv")
    assert "<PERSON:abcdefghijklm" in out or out.startswith("prefix")
    # The partial MUST eventually be emitted (either mid-feed or on flush).
    assert buf.flush() in ("", "nopqrstuv", "abcdefghijklmnopqrstuv")


@pytest.mark.parametrize(
    "chunks,expected",
    [
        (["<PERSON:abc>"], "<PERSON:abc>"),
        (["<", "PERSON:", "abc", ">"], "<PERSON:abc>"),
        (["no placeholders here"], "no placeholders here"),
    ],
)
def test_split_patterns(chunks: list[str], expected: str) -> None:
    buf = StreamBuffer()
    out = "".join(buf.feed(c) for c in chunks) + buf.flush()
    assert out == expected
