"""PIIGhostRehydrator restores original content from metadata mapping."""

import json

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.exceptions import RehydrationError  # noqa: E402
from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostRehydrator,
)


def _mapping(token: str, original: str, label: str = "PERSON") -> str:
    return json.dumps([{"token": token, "original": original, "label": label}])


def test_rehydrates_content() -> None:
    rehydrator = PIIGhostRehydrator()
    docs = [
        Document(
            page_content="Hello <PERSON:abc>",
            metadata={"piighost_mapping": _mapping("<PERSON:abc>", "Alice")},
        )
    ]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "Hello Alice"


def test_missing_mapping_lenient() -> None:
    rehydrator = PIIGhostRehydrator()
    docs = [Document(page_content="Hello <PERSON:abc>", metadata={})]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "Hello <PERSON:abc>"


def test_missing_mapping_strict_raises() -> None:
    rehydrator = PIIGhostRehydrator(fail_on_missing_mapping=True)
    docs = [Document(page_content="x", metadata={})]

    with pytest.raises(RehydrationError):
        rehydrator.transform_documents(docs)


def test_longest_token_first_no_partial_collision() -> None:
    rehydrator = PIIGhostRehydrator()
    raw = json.dumps(
        [
            {"token": "<PERSON:a>", "original": "Alice", "label": "PERSON"},
            {"token": "<PERSON:ab>", "original": "Alice Bob", "label": "PERSON"},
        ]
    )
    docs = [
        Document(
            page_content="see <PERSON:ab> and <PERSON:a>",
            metadata={"piighost_mapping": raw},
        )
    ]

    out = rehydrator.transform_documents(docs)

    assert out[0].page_content == "see Alice Bob and Alice"
