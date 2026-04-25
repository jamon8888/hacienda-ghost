import sys

# On Windows, torch/sentence-transformers/pyarrow cause segfaults or access
# violations during DLL loading. Skip any test that loads actual ML models.
collect_ignore: list[str] = []
if sys.platform == "win32":
    collect_ignore.extend([
        # pyarrow / lancedb DLL crash
        "tests/integrations/langchain/test_lancedb_roundtrip.py",
        # CLI tests that invoke commands which load GLiNER2 / sentence-transformers
        "tests/cli/test_detect.py",
        "tests/cli/test_anonymize.py",
        "tests/cli/test_rehydrate.py",
        # Benchmarks load the full pipeline with real models
        "tests/benchmarks/bench_pipeline.py",
        "tests/benchmarks/bench_linker.py",
    ])
