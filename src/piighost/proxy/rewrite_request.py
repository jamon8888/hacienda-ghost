"""Anonymize Anthropic /v1/messages request bodies in place.

See docs/superpowers/specs/2026-04-24-anonymizing-proxy-cross-host.md §4.1
for the field table (what's rewritten vs passed through).
"""
from __future__ import annotations

import copy
import json
from typing import Any, Protocol


class Anonymizer(Protocol):
    async def anonymize(
        self, text: str, *, project: str
    ) -> tuple[str, dict[str, Any]]: ...


async def _anon_text(
    anonymizer: Anonymizer, text: str, *, project: str, agg: dict[str, Any]
) -> str:
    anon, meta = await anonymizer.anonymize(text, project=project)
    for entry in meta.get("entities", []):
        agg.setdefault("entities", []).append(entry)
    return anon


async def rewrite_request_body(
    body: dict[str, Any],
    anonymizer: Anonymizer,
    *,
    project: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deep-copied, anonymized request body and aggregated metadata."""
    out = copy.deepcopy(body)
    meta: dict[str, Any] = {"entities": []}

    # system (string or list of blocks per Anthropic schema)
    system = out.get("system")
    if isinstance(system, str):
        out["system"] = await _anon_text(anonymizer, system, project=project, agg=meta)
    elif isinstance(system, list):
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                block["text"] = await _anon_text(
                    anonymizer, block.get("text", ""), project=project, agg=meta
                )

    # messages[].content
    for msg in out.get("messages", []):
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = await _anon_text(
                anonymizer, content, project=project, agg=meta
            )
        elif isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    block["text"] = await _anon_text(
                        anonymizer, block.get("text", ""), project=project, agg=meta
                    )
                elif btype == "tool_result":
                    tc = block.get("content")
                    if isinstance(tc, str):
                        block["content"] = await _anon_text(
                            anonymizer, tc, project=project, agg=meta
                        )
                    elif isinstance(tc, list):
                        for inner in tc:
                            if isinstance(inner, dict) and inner.get("type") == "text":
                                inner["text"] = await _anon_text(
                                    anonymizer,
                                    inner.get("text", ""),
                                    project=project,
                                    agg=meta,
                                )
                elif btype == "tool_use":
                    raw = json.dumps(block.get("input", {}), ensure_ascii=False)
                    anon_raw = await _anon_text(
                        anonymizer, raw, project=project, agg=meta
                    )
                    block["input"] = json.loads(anon_raw)

    return out, meta
