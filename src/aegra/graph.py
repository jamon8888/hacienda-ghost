from __future__ import annotations

import os

from pydantic import BaseModel, Field

from datetime import UTC, datetime

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from dataclasses import field
from typing import Sequence

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from langgraph.managed import IsLastStep
from typing import Annotated


SYSTEM_PROMPT = """You are a helpful AI assistant.

System time: {system_time}"""


class Context(BaseModel):
    """Runtime configuration injected into the graph.

    Defaults can be overridden per-request via the LangGraph SDK
    or globally via environment variables.
    """

    system_prompt: str = Field(
        default=SYSTEM_PROMPT,
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


class InputState(BaseModel):
    """Input schema — only the fields the caller may provide."""

    messages: Annotated[Sequence[AnyMessage], add_messages] = field(
        default_factory=list
    )


class State(InputState):
    """Internal state — extends InputState with runtime-managed fields."""

    is_last_step: IsLastStep = field(default=False)


def load_chat_model(fully_specified_name: str) -> BaseChatModel:
    """Load a chat model from a fully specified name.

    Args:
        fully_specified_name: String in the format 'provider/model'
            e.g. 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-4-20250514'.

    Returns:
        A BaseChatModel instance.

    Raises:
        ValueError: If fully_specified_name is not in 'provider/model' format.
    """
    if not fully_specified_name or not fully_specified_name.strip():
        raise ValueError(
            "fully_specified_name must be in 'provider/model' format, got empty string"
        )
    if fully_specified_name.count("/") != 1:
        raise ValueError(
            f"fully_specified_name must be in 'provider/model' format, got '{fully_specified_name}'"
        )
    provider, model = fully_specified_name.split("/", maxsplit=1)
    if not provider.strip() or not model.strip():
        raise ValueError(
            f"fully_specified_name must be in 'provider/model' format, got '{fully_specified_name}'"
        )
    return init_chat_model(model, model_provider=provider)


async def chatbot(state: State, runtime: Runtime[Context]) -> dict:
    """Process messages and generate a response."""
    model = load_chat_model(runtime.context.model)
    system_message = SystemMessage(
        content=runtime.context.system_prompt.format(
            system_time=datetime.now(tz=UTC).isoformat(),
        )
    )
    response = await model.ainvoke([system_message, *state.messages])
    return {"messages": [response]}


graph: CompiledStateGraph[State, Context, InputState, State] = (
    StateGraph(State, input_schema=InputState, context_schema=Context)
    .add_node("chatbot", chatbot)
    .add_edge("__start__", "chatbot")
    .add_edge("chatbot", "__end__")
    .compile(name="aegra")
)
