import sys

# On Windows, torch/sentence-transformers/pyarrow cause segfaults or access
# violations when loading model weights. Skip all tests that instantiate
# the service (which loads GLiNER2/sentence-transformers at construction time).
collect_ignore: list[str] = []
collect_ignore_glob: list[str] = []
if sys.platform == "win32":
    # All CLI tests invoke commands that instantiate the service → GLiNER2 crash
    collect_ignore_glob.append("tests/cli/*.py")
    # Benchmarks load the full pipeline with real models
    collect_ignore_glob.append("tests/benchmarks/*.py")
    # pyarrow / lancedb DLL crash
    collect_ignore.append("tests/integrations/langchain/test_lancedb_roundtrip.py")
