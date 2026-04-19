"""LangChain integration for PIIGhost (document-pipeline components)."""

import importlib.util

if importlib.util.find_spec("langchain") is None:
    raise ImportError(
        "You must install langchain to use piighost.integrations.langchain, "
        "please install piighost[langchain]"
    )

__all__: list[str] = []
