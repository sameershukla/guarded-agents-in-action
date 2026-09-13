# ACTION GUARDRAIL EXAMPLE
#
# This module builds a LangGraph agent that can issue refunds via a tool
# call, but wraps every tool call in an *action guardrail*: before the
# `issue_refund` tool actually runs, `action_guardrail_node` validates it
# against business rules (see guardrail.py) and only lets it execute if
# it's approved. This is different from an input guardrail (which cleans
# untrusted text before the LLM sees it) — here the LLM's own proposed
# ACTION is what gets checked, since a refund tool call has a real-world
# financial side effect that must not be trusted blindly.

from typing import Annotated, TypedDict
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from guardrail import validate_financial_action

# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------

class AgentState(TypedDict):
    # Full conversation history; add_messages appends new messages rather
    # than overwriting the list on each node's return.
    messages: Annotated[list[AnyMessage], add_messages]

    tool_name: str        # Name of the tool the LLM most recently tried to call.
    tool_args: dict        # Arguments the LLM supplied for that tool call.
    action_allowed: bool   # Whether the action guardrail approved the call.
    guardrail_reason: str  # Human-readable explanation for the guardrail's decision.


# ---------------------------------------------------------
# TOOL
# ---------------------------------------------------------

@tool
def issue_refund(
    invoice_id: str,
    amount: float
) -> str:
    """
    Issue a refund for an invoice.
    """
    # The actual (simulated) side effect: this only runs for calls that
    # make it past the action guardrail in execute_tool_node.
    return (
        f"Refund of ${amount:.2f} "
        f"issued for invoice {invoice_id}."
    )

# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

# Base Claude model used to drive the conversation.
model = ChatAnthropic(model="claude-sonnet-4-6")

# Give the model access to the issue_refund tool so it can request refunds
# via structured tool calls instead of free text.
model_with_tools = model.bind_tools(
    [issue_refund]
)

# ---------------------------------------------------------
# AGENT NODE
# ---------------------------------------------------------

def agent_node(state: AgentState):
    # Instructions constraining the assistant to only claim success once
    # the tool itself confirms the refund went through.
    system_message = SystemMessage(
        content="""
        You are a customer support agent.
        You can help customers with refunds.
        Use the available refund tool when the user asks
        you to issue a refund.
        Do not claim that a refund succeeded unless the
        tool confirms that it succeeded.
        """
    )
    # Ask the model to respond given the system prompt plus the full
    # conversation so far; it may reply with text or a tool call.
    response = model_with_tools.invoke(
        [
            system_message,
            *state["messages"]
        ]
    )

    # Append the model's response (text or tool call) to the conversation.
    return {
        "messages": [response]
    }

# ---------------------------------------------------------
# ROUTE AFTER AGENT
# ---------------------------------------------------------

def route_after_agent(state: AgentState):
    # Inspect the model's latest message to decide where to go next.
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        # The model wants to call a tool (e.g. issue_refund) — route
        # through the action guardrail before letting it execute.
        return "action_guardrail"

    # No tool call means the model just replied with text; end the turn.
    return END

# ---------------------------------------------------------
# ACTION GUARDRAIL NODE
# ---------------------------------------------------------

def action_guardrail_node(state: AgentState):
    # This is the enforcement point of the action guardrail: it intercepts
    # the LLM's proposed tool call and checks it against policy BEFORE any
    # tool actually runs.
    last_message = state["messages"][-1]

    # Only the first requested tool call is validated/executed in this
    # example (the model is expected to request one refund at a time).
    tool_call = last_message.tool_calls[0]

    tool_name = tool_call["name"]
    tool_args = tool_call["args"]

    # Delegate the actual policy check (tool allow-list, amount limits,
    # etc.) to the guardrail module.
    decision = validate_financial_action(
        tool_name,
        tool_args
    )

    # Record the tool call and the guardrail's verdict/reason in state so
    # downstream nodes can act on it.
    return {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "action_allowed": decision["allowed"],
        "guardrail_reason": decision["reason"],
    }

# ---------------------------------------------------------
# ROUTE AFTER GUARDRAIL
# ---------------------------------------------------------

def route_after_guardrail(state: AgentState):
    # Branch based on the guardrail's decision: approved calls proceed to
    # actually run the tool, denied calls are short-circuited.
    if state["action_allowed"]:
        return "execute_tool"

    return "block_tool"

# ---------------------------------------------------------
# EXECUTE TOOL NODE
# ---------------------------------------------------------

def execute_tool_node(state: AgentState):
    # Reached only when the action guardrail approved the call — safe to
    # actually perform the refund now.
    last_message = state["messages"][-1]

    tool_call = last_message.tool_calls[0]

    # Invoke the real tool with the model-supplied arguments.
    result = issue_refund.invoke(
        tool_call["args"]
    )

    # Wrap the tool's output in a ToolMessage tied back to the original
    # tool_call id so the model can see the result in its next turn.
    tool_message = ToolMessage(
        content=result,
        tool_call_id=tool_call["id"]
    )

    return {
        "messages": [tool_message]
    }

# ---------------------------------------------------------
# BLOCK TOOL NODE
# ---------------------------------------------------------

def block_tool_node(state: AgentState):
    # Reached when the action guardrail rejected the call — the tool never
    # runs; instead we synthesize a ToolMessage explaining the denial.
    last_message = state["messages"][-1]

    tool_call = last_message.tool_calls[0]

    tool_message = ToolMessage(
        content=(
            "Refund was not executed. "
            f"Reason: {state['guardrail_reason']}"
        ),
        tool_call_id=tool_call["id"]
    )

    return {
        "messages": [tool_message]
    }

# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------

# Create the state graph over AgentState.
builder = StateGraph(AgentState)


# The LLM-driving node: decides what to say or which tool to call.
builder.add_node(
    "agent",
    agent_node
)

# The action guardrail: validates any requested tool call against policy.
builder.add_node(
    "action_guardrail",
    action_guardrail_node
)

# Runs the tool for real, only reachable for approved calls.
builder.add_node(
    "execute_tool",
    execute_tool_node
)

# Short-circuits the tool call with a denial message, for rejected calls.
builder.add_node(
    "block_tool",
    block_tool_node
)


# Every run starts at the agent node.
builder.add_edge(
    START,
    "agent"
)


# After the agent responds: if it requested a tool call, send it through
# the action guardrail; otherwise the conversation turn is over.
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "action_guardrail": "action_guardrail",
        END: END,
    }
)


# After the guardrail evaluates the call: route to actual execution if
# allowed, or to the blocking/denial path if not.
builder.add_conditional_edges(
    "action_guardrail",
    route_after_guardrail,
    {
        "execute_tool": "execute_tool",
        "block_tool": "block_tool",
    }
)


# Whether the tool ran or was blocked, control returns to the agent so it
# can incorporate the ToolMessage (result or denial reason) into its next
# reply to the user.
builder.add_edge(
    "execute_tool",
    "agent"
)

builder.add_edge(
    "block_tool",
    "agent"
)


# Compile the graph into an executable pipeline.
graph = builder.compile()


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(user_input: str):
    # Seed the conversation with the user's message and default/empty
    # values for the guardrail-related state fields.
    initial_state = {
        "messages": [
            HumanMessage(
                content=user_input
            )
        ],
        "tool_name": "",
        "tool_args": {},
        "action_allowed": False,
        "guardrail_reason": "",
    }

    # Run the agent <-> guardrail <-> tool loop until the model produces a
    # final text reply (no further tool calls).
    result = graph.invoke(
        initial_state
    )

    # Echo the original request.
    print("\nUser:")
    print(user_input)

    # Show whether the action guardrail approved the most recent tool call.
    print("\nGuardrail Decision:")
    print(result["action_allowed"])

    # Show the guardrail's justification for that decision.
    print("\nGuardrail Reason:")
    print(result["guardrail_reason"])

    # Show the assistant's final reply to the user.
    print("\nAgent:")
    print(
        result["messages"][-1].content
    )


if __name__ == "__main__":
    # Demo run: requests a refund above the $500 auto-approval limit, so
    # the action guardrail should block it.
    run_agent(
        "Please refund $2000 "
        "for invoice INV-1001."
    )