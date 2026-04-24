from __future__ import annotations

from typing import Any

import pytest

from piighost.proxy.rewrite_request import rewrite_request_body


class FakeAnonymizer:
    """Deterministic stub: lowercases, replaces 'jean dupont' with <PERSON:1>."""

    async def anonymize(self, text: str, *, project: str) -> tuple[str, dict[str, Any]]:
        anon = text.replace("Jean Dupont", "<PERSON:1>")
        meta = {"entities": [{"label": "PERSON", "count": 1}]} if "<PERSON:1>" in anon else {"entities": []}
        return anon, meta


@pytest.mark.asyncio
async def test_rewrite_user_string_message() -> None:
    body = {
        "model": "claude-opus-4-7",
        "messages": [{"role": "user", "content": "Jean Dupont lives in Paris"}],
    }
    rewritten, meta = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["messages"][0]["content"] == "<PERSON:1> lives in Paris"
    assert meta["entities"] == [{"label": "PERSON", "count": 1}]


@pytest.mark.asyncio
async def test_rewrite_user_block_content() -> None:
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Jean Dupont"}],
            }
        ],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["messages"][0]["content"][0]["text"] == "<PERSON:1>"


@pytest.mark.asyncio
async def test_rewrite_tool_result_block() -> None:
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "abc",
                        "content": "File says Jean Dupont",
                    }
                ],
            }
        ],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["messages"][0]["content"][0]["content"] == "File says <PERSON:1>"


@pytest.mark.asyncio
async def test_rewrite_system_prompt_string() -> None:
    body = {
        "system": "Context: Jean Dupont is our client",
        "messages": [{"role": "user", "content": "hi"}],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["system"] == "Context: <PERSON:1> is our client"


@pytest.mark.asyncio
async def test_rewrite_tool_use_input() -> None:
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"path": "/clients/Jean Dupont/file.txt"},
                    }
                ],
            }
        ],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["messages"][0]["content"][0]["input"]["path"] == "/clients/<PERSON:1>/file.txt"


@pytest.mark.asyncio
async def test_scalar_fields_untouched() -> None:
    body = {
        "model": "claude-opus-4-7",
        "max_tokens": 1024,
        "temperature": 0.5,
        "messages": [{"role": "user", "content": "hi"}],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    assert rewritten["model"] == "claude-opus-4-7"
    assert rewritten["max_tokens"] == 1024
    assert rewritten["temperature"] == 0.5


@pytest.mark.asyncio
async def test_tool_schemas_untouched() -> None:
    body = {
        "tools": [{"name": "Read", "description": "Read Jean Dupont's file", "input_schema": {}}],
        "messages": [{"role": "user", "content": "hi"}],
    }
    rewritten, _ = await rewrite_request_body(body, FakeAnonymizer(), project="p1")
    # Tool descriptions are schemas; they pass through unchanged per spec §4.1.
    assert rewritten["tools"][0]["description"] == "Read Jean Dupont's file"
