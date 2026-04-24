import sys

# pyarrow triggers a Windows access violation during DLL loading on some
# configurations; skip collection entirely rather than crashing pytest.
collect_ignore: list[str] = []
if sys.platform == "win32":
    collect_ignore.append("tests/integrations/langchain/test_lancedb_roundtrip.py")
