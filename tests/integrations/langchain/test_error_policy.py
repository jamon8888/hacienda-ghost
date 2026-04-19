"""Error-policy matrix for the four LangChain components."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.documents import Document  # noqa: E402

from piighost.classifier.base import ClassificationSchema  # noqa: E402
from piighost.exceptions import RehydrationError  # noqa: E402
from piighost.integrations.langchain.transformers import (  # noqa: E402
    PIIGhostDocumentAnonymizer,
    PIIGhostDocumentClassifier,
    PIIGhostQueryAnonymizer,
    PIIGhostRehydrator,
)


class _BrokenDetector:
    async def detect(self, text: str) -> list:
        raise RuntimeError("detector boom")


class _BrokenClassifier:
    async def classify(
        self, text: str, schemas: dict[str, ClassificationSchema]
    ) -> dict[str, list[str]]:
        raise RuntimeError("classifier boom")


@pytest.fixture
def broken_pipeline(pipeline):
    pipeline._detector = _BrokenDetector()
    return pipeline


class TestDocumentAnonymizerErrors:
    def test_lenient_default_writes_meta(self, broken_pipeline) -> None:
        anon = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline)
        docs = [Document(page_content="Hello Alice", metadata={"source": "d1"})]
        out = anon.transform_documents(docs)
        assert out[0].metadata["piighost_error"].startswith("detection_failed:")
        assert out[0].page_content == "Hello Alice"

    def test_strict_reraises(self, broken_pipeline) -> None:
        anon = PIIGhostDocumentAnonymizer(pipeline=broken_pipeline, strict=True)
        docs = [Document(page_content="Hello Alice", metadata={"source": "d1"})]
        with pytest.raises(RuntimeError, match="detector boom"):
            anon.transform_documents(docs)


class TestQueryAnonymizerStrictAlways:
    def test_always_raises(self, broken_pipeline) -> None:
        anon = PIIGhostQueryAnonymizer(pipeline=broken_pipeline)
        with pytest.raises(RuntimeError, match="detector boom"):
            anon.invoke("Hello Alice")


class TestClassifierErrors:
    def test_lenient_writes_classifier_error(self) -> None:
        schemas: dict[str, ClassificationSchema] = {
            "x": {"labels": ["a"], "multi_label": False}
        }
        comp = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),  # type: ignore[arg-type]
            schemas=schemas,
        )
        docs = [Document(page_content="hi", metadata={})]
        out = comp.transform_documents(docs)
        assert out[0].metadata["classifier_error"].startswith("classify_failed:")

    def test_strict_reraises(self) -> None:
        schemas: dict[str, ClassificationSchema] = {
            "x": {"labels": ["a"], "multi_label": False}
        }
        comp = PIIGhostDocumentClassifier(
            classifier=_BrokenClassifier(),  # type: ignore[arg-type]
            schemas=schemas,
            strict=True,
        )
        docs = [Document(page_content="hi", metadata={})]
        with pytest.raises(RuntimeError, match="classifier boom"):
            comp.transform_documents(docs)


class TestRehydratorFailFlag:
    def test_lenient_returns_unchanged(self) -> None:
        r = PIIGhostRehydrator()
        docs = [Document(page_content="<PERSON:a>", metadata={})]
        out = r.transform_documents(docs)
        assert out[0].page_content == "<PERSON:a>"

    def test_strict_raises(self) -> None:
        r = PIIGhostRehydrator(fail_on_missing_mapping=True)
        docs = [Document(page_content="<PERSON:a>", metadata={})]
        with pytest.raises(RehydrationError):
            r.transform_documents(docs)
