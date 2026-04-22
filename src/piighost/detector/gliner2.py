import importlib.util

from piighost.detector.base import BaseNERDetector
from piighost.models import Detection, Span

if importlib.util.find_spec("gliner2") is None:
    raise ImportError(
        "You must install gliner2 to use Gliner2Detector, please install piighost[gliner2] for use middleware"
    )

from gliner2 import GLiNER2


class Gliner2Detector(BaseNERDetector):
    """Detect entities using a GLiNER2 model.

    Wraps a ``GLiNER2`` model instance so that callers can inject a
    pre-loaded model (useful for tests and shared workers).

    Args:
        model: A loaded ``GLiNER2`` model instance.
        labels: Entity types this detector is configured to find. A list
            applies identity mapping (the label is passed both to GLiNER2
            and emitted in :class:`Detection.label`). A ``{external: internal}``
            dict passes the *internal* labels to GLiNER2 at query time and
            rewrites the result back to the *external* label. This is
            useful when a specific query string performs better than the
            external name (e.g. ``{"COMPANY": "company"}``).
        threshold: Minimum confidence score to keep a prediction.
        flat_ner: Whether to use flat NER mode (no nested entities).
        batch_size: Number of texts per batch for ``detect_batch()``.
            Defaults to ``1`` (sequential, backward-compatible).
        quantize: If ``True``, calls ``model.quantize()`` at init
            (fp16, GPU only).
        compile_model: If ``True``, calls ``model.compile()`` at init
            (torch.compile with fused kernels, GPU primary).

    Example:
        >>> from gliner2 import GLiNER2
        >>> model = GLiNER2.from_pretrained("fastino/gliner2-base-v1")
        >>> detector = Gliner2Detector(model=model, labels=["PERSON", "LOCATION"])
        >>> # GPU-optimised, batch of 8:
        >>> detector = Gliner2Detector(
        ...     model=model,
        ...     labels={"PERSON": "person"},
        ...     batch_size=8,
        ...     quantize=True,
        ...     compile_model=True,
        ... )
    """

    model: GLiNER2
    threshold: float
    flat_ner: bool
    batch_size: int

    def __init__(
        self,
        model: GLiNER2,
        labels: list[str] | dict[str, str],
        threshold: float = 0.5,
        flat_ner: bool = True,
        batch_size: int = 1,
        quantize: bool = False,
        compile_model: bool = False,
    ) -> None:
        super().__init__(labels)
        self.model = model
        self.threshold = threshold
        self.flat_ner = flat_ner
        self.batch_size = batch_size

        if quantize:
            self.model.quantize()
        if compile_model:
            self.model.compile()

    async def detect(self, text: str) -> list[Detection]:
        """Run GLiNER2 prediction and convert results to ``Detection`` objects.

        Args:
            text: The input text to search for entities.

        Returns:
            Detections whose score meets the configured threshold, with
            labels remapped to the external vocabulary.
        """
        raw_entities = self.model.extract_entities(
            text,
            entity_types=self.internal_labels,
            threshold=self.threshold,
            include_spans=True,
            include_confidence=True,
        )["entities"]

        detections: list[Detection] = []
        for entity_type, list_entity in raw_entities.items():
            external = self._map_label(entity_type)
            if external is None:
                continue
            for entity in list_entity:
                detections.append(
                    Detection(
                        text=entity["text"],
                        label=external,
                        position=Span(
                            start_pos=entity["start"],
                            end_pos=entity["end"],
                        ),
                        confidence=entity["confidence"],
                    )
                )

        return detections

    async def detect_batch(self, texts: list[str]) -> list[list[Detection]]:
        """Run batch GLiNER2 inference over multiple texts.

        Uses ``model.batch_extract_entities()`` to process all texts in
        a single model forward pass (GPU: significant throughput gain;
        CPU: reduced framework overhead).

        Args:
            texts: List of input texts to process.

        Returns:
            One ``list[Detection]`` per input text, in the same order.
        """
        if not texts:
            return []

        raw_results = self.model.batch_extract_entities(
            texts,
            entity_types=self.internal_labels,
            threshold=self.threshold,
            include_spans=True,
            include_confidence=True,
            batch_size=self.batch_size,
        )

        all_detections: list[list[Detection]] = []
        for raw in raw_results:
            detections: list[Detection] = []
            for entity_type, list_entity in raw["entities"].items():
                external = self._map_label(entity_type)
                if external is None:
                    continue
                for entity in list_entity:
                    detections.append(
                        Detection(
                            text=entity["text"],
                            label=external,
                            position=Span(
                                start_pos=entity["start"],
                                end_pos=entity["end"],
                            ),
                            confidence=entity["confidence"],
                        )
                    )
            all_detections.append(detections)

        return all_detections
