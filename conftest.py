import os
import sys

# Windows-only safety: force torch's DLL graph to load before pyarrow /
# sentence-transformers attempt their own lazy imports during pytest
# collection. The historical segfaults were a load-order race in the
# native libs; eager-importing torch first sidesteps the race when it's
# present and is a no-op when the index extra isn't installed.
if sys.platform == "win32":
    try:
        import torch  # noqa: F401
    except ImportError:
        pass

# Heavyweight directories that load GLiNER2 / sentence-transformers /
# lancedb at collection time. They are skipped on Windows by default to
# avoid the historical native-lib segfaults; set
# ``PIIGHOST_TEST_HEAVY=1`` to opt in (e.g. on CI runners that have
# verified the toolchain).
collect_ignore_glob: list[str] = []
if sys.platform == "win32" and not os.environ.get("PIIGHOST_TEST_HEAVY"):
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
