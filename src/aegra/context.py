"""Configurable runtime context for aegra."""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from aegra import prompts


class Context(BaseModel):
    """Runtime configuration injected into the graph.

    Defaults can be overridden per-request via the LangGraph SDK
    or globally via environment variables.
    """

    system_prompt: str = Field(
        default=prompts.SYSTEM_PROMPT,
        description="The system prompt for the agent",
    )
    model: str = Field(
        default="openai/gpt-4o-mini", description="LLM model as 'provider/model'"
    )

    def __post_init__(self) -> None:
        """Override defaults with environment variables when set."""
        env_model = os.environ.get("MODEL")
        if env_model:
            self.model = env_model
        env_prompt = os.environ.get("SYSTEM_PROMPT")
        if env_prompt:
            self.system_prompt = env_prompt
