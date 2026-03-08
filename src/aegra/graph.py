"""aegra — Simple chatbot with message memory."""

from datetime import UTC, datetime

from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from aegra.context import Context
from aegra.state import InputState, State
from aegra.utils import load_chat_model


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
