import sys

# On Windows, torch/sentence-transformers/pyarrow cause segfaults or access
# violations when loading model weights. Skip all test directories that
# directly or transitively instantiate the real service (which eagerly loads
# GLiNER2 + sentence-transformers at __init__ time).
#
# Safe on Windows: classifier, linker, ph_factory, proxy, resolver, unit, vault
collect_ignore_glob: list[str] = []
if sys.platform == "win32":
    _SKIP_DIRS = [
        "tests/cli",          # invoke CLI commands → service → models
        "tests/service",      # directly instantiates service
        "tests/benchmarks",   # full pipeline with real models
        "tests/e2e",          # end-to-end with real models
        "tests/daemon",       # daemon starts the service
        "tests/integrations", # lancedb + other model tests
        "tests/pipeline",     # AnonymizationPipeline with real models
        "tests/detector",     # may use real GLiNER2 detector
        "tests/scripts",      # install scripts that load service
    ]
    for d in _SKIP_DIRS:
        collect_ignore_glob.append(f"{d}/*.py")
