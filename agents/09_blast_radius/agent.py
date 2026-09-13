# BLAST RADIUS GUARDRAIL EXAMPLE
#
# This module adds a second guardrail stage on top of the familiar
# action guardrail from 02_financial_action: after an individual refund
# passes validate_refund_action, it must also pass check_blast_radius,
# which looks at REFUND_LEDGER -- every refund issued so far -- to make
# sure this refund would not push the agent's or the customer's recent
# totals over a cumulative limit. Only a refund that clears BOTH checks
# gets executed and recorded in the ledger, which is what lets future
# checks see it.

from datetime import datetime, timezone
from typing import Annotated, TypedDict

from langchain_anthropic import ChatAnthropic

from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from langchain_core.tools import tool

from langgraph.graph import (
    StateGraph,
    START,
    END,
)

from langgraph.graph.message import add_messages

from guardrail import (
    validate_refund_action,
    check_blast_radius,
)


# ---------------------------------------------------------
# BLAST RADIUS LEDGER
# ---------------------------------------------------------

# Stand-in for a real audit log / database of past actions. Every
# executed refund is appended here by record_ledger_node, and
# check_blast_radius reads it to compute recent totals.
REFUND_LEDGER = []


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------

class AgentState(TypedDict):

    # Full conversation history; add_messages appends rather than
    # overwriting on each node's return.
    messages: Annotated[
        list[AnyMessage],
        add_messages
    ]

    agent_id: str     # Identifies which agent/session is issuing refunds.
    customer_id: str  # Identifies which customer is receiving the refund.

    tool_name: str  # Name of the tool the LLM most recently tried to call.
    tool_args: dict  # Arguments the LLM supplied for that tool call.

    action_allowed: bool  # Result of the individual (single-action) check.
    action_reason: str    # Explanation for that result.

    blast_radius_allowed: bool  # Result of the cumulative (ledger-based) check.
    blast_radius_reason: str    # Explanation for that result.


# ---------------------------------------------------------
# TOOL
# ---------------------------------------------------------

@tool
def issue_refund(
    customer_id: str,
    invoice_id: str,
    amount: float
) -> str:
    """
    Issue a refund for a customer invoice.
    """
    # The actual (simulated) side effect: only reachable for calls that
    # passed both the action guardrail and the blast radius guardrail.
    return (
        f"Refund of ${amount:.2f} "
        f"issued for invoice {invoice_id} "
        f"for customer {customer_id}."
    )


# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

# Base Claude model used to drive the conversation.
model = ChatAnthropic(
    model="claude-sonnet-4-6"
)

# Give the model access to the issue_refund tool so it can request
# refunds via structured tool calls instead of free text.
model_with_tools = model.bind_tools(
    [issue_refund]
)


# ---------------------------------------------------------
# AGENT NODE
# ---------------------------------------------------------

def agent_node(
    state: AgentState
):
    # Instructions constraining the assistant to only claim success once
    # the tool itself confirms the refund went through.
    system_message = SystemMessage(
        content="""
You are a customer support agent.

You can issue refunds using the refund tool.

When the user asks for a refund,
use the issue_refund tool.

Do not claim that a refund succeeded
unless the tool confirms success.
"""
    )


    # Ask the model to respond given the system prompt plus the full
    # conversation so far; it may reply with text or a tool call.
    response = model_with_tools.invoke(
        [
            system_message,
            *state["messages"],
        ]
    )


    # Append the model's response (text or tool call) to the conversation.
    return {
        "messages": [response]
    }


# ---------------------------------------------------------
# ROUTE AFTER AGENT
# ---------------------------------------------------------

def route_after_agent(
    state: AgentState
):
    # Inspect the model's latest message to decide where to go next.
    last_message = state["messages"][-1]

    if last_message.tool_calls:
        # A tool call was requested -- send it through the individual
        # action check before it can run.
        return "action_guardrail"

    # No tool call means the model just replied with text; end the turn.
    return END


# ---------------------------------------------------------
# ACTION GUARDRAIL
# ---------------------------------------------------------

def action_guardrail_node(
    state: AgentState
):
    # First guardrail stage: judges this one proposed refund purely on
    # its own terms (tool allow-list, amount limits), with no knowledge
    # of any other refund.
    last_message = state["messages"][-1]

    tool_call = last_message.tool_calls[0]

    tool_name = tool_call["name"]

    tool_args = tool_call["args"]


    decision = validate_refund_action(
        tool_name,
        tool_args
    )


    return {
        "tool_name":
            tool_name,

        "tool_args":
            tool_args,

        "action_allowed":
            decision["allowed"],

        "action_reason":
            decision["reason"],
    }


# ---------------------------------------------------------
# ROUTE AFTER ACTION CHECK
# ---------------------------------------------------------

def route_after_action_guardrail(
    state: AgentState
):
    # Only a refund that passes the individual check is even considered
    # for the cumulative (blast radius) check.
    if state["action_allowed"]:
        return "blast_radius_guardrail"

    return "block_tool"


# ---------------------------------------------------------
# BLAST RADIUS GUARDRAIL
# ---------------------------------------------------------

def blast_radius_guardrail_node(
    state: AgentState
):
    # Second guardrail stage: checks whether adding this refund to the
    # ledger would push the agent's or customer's recent totals over a
    # cumulative limit, even though the refund itself already passed the
    # individual check.
    amount = state[
        "tool_args"
    ]["amount"]


    decision = check_blast_radius(
        ledger=
            REFUND_LEDGER,

        agent_id=
            state["agent_id"],

        customer_id=
            state["customer_id"],

        proposed_amount=
            amount,
    )


    return {
        "blast_radius_allowed":
            decision["allowed"],

        "blast_radius_reason":
            decision["reason"],
    }


# ---------------------------------------------------------
# ROUTE AFTER BLAST RADIUS
# ---------------------------------------------------------

def route_after_blast_radius(
    state: AgentState
):
    # Only a refund that clears both guardrail stages is allowed to
    # actually execute.
    if state[
        "blast_radius_allowed"
    ]:
        return "execute_tool"

    return "block_tool"


# ---------------------------------------------------------
# EXECUTE TOOL
# ---------------------------------------------------------

def execute_tool_node(
    state: AgentState
):
    # Reached only for a refund that passed both guardrail stages -- safe
    # to actually perform the refund now.
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
        "messages": [
            tool_message
        ]
    }


# ---------------------------------------------------------
# RECORD LEDGER
# ---------------------------------------------------------

def record_ledger_node(
    state: AgentState
):
    # Runs immediately after a successful execution, so this refund
    # becomes part of the history check_blast_radius will see the next
    # time any agent proposes a refund.
    REFUND_LEDGER.append(
        {
            "agent_id":
                state["agent_id"],

            "customer_id":
                state["customer_id"],

            "invoice_id":
                state["tool_args"][
                    "invoice_id"
                ],

            "amount":
                state["tool_args"][
                    "amount"
                ],

            "timestamp":
                datetime.now(
                    timezone.utc
                ),
        }
    )


    return {}


# ---------------------------------------------------------
# BLOCK TOOL
# ---------------------------------------------------------

def block_tool_node(
    state: AgentState
):
    # Reached when either guardrail stage rejected the call -- the tool
    # never runs, and nothing is added to the ledger.
    last_message = state["messages"][-1]

    tool_call = last_message.tool_calls[0]


    # Report whichever guardrail actually blocked the call: the
    # individual action check, or the cumulative blast radius check.
    if not state[
        "action_allowed"
    ]:

        reason = state[
            "action_reason"
        ]

    else:

        reason = state[
            "blast_radius_reason"
        ]


    tool_message = ToolMessage(
        content=(
            "Refund was not executed. "
            f"Reason: {reason}"
        ),
        tool_call_id=tool_call["id"]
    )


    return {
        "messages": [
            tool_message
        ]
    }


# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------

# Create the state graph over AgentState.
builder = StateGraph(
    AgentState
)


# The LLM-driving node: decides what to say or which tool to call.
builder.add_node(
    "agent",
    agent_node
)

# First guardrail stage: validates the refund on its own terms.
builder.add_node(
    "action_guardrail",
    action_guardrail_node
)

# Second guardrail stage: validates the refund against cumulative limits.
builder.add_node(
    "blast_radius_guardrail",
    blast_radius_guardrail_node
)

# Runs the tool for real, only reachable once both stages approve.
builder.add_node(
    "execute_tool",
    execute_tool_node
)

# Appends the executed refund to the ledger for future blast radius checks.
builder.add_node(
    "record_ledger",
    record_ledger_node
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
# the individual action check; otherwise the conversation turn is over.
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "action_guardrail":
            "action_guardrail",

        END:
            END,
    }
)


# After the individual check: proceed to the cumulative blast radius
# check if allowed, otherwise block immediately.
builder.add_conditional_edges(
    "action_guardrail",
    route_after_action_guardrail,
    {
        "blast_radius_guardrail":
            "blast_radius_guardrail",

        "block_tool":
            "block_tool",
    }
)


# After the cumulative check: execute if allowed, otherwise block.
builder.add_conditional_edges(
    "blast_radius_guardrail",
    route_after_blast_radius,
    {
        "execute_tool":
            "execute_tool",

        "block_tool":
            "block_tool",
    }
)


# A successful execution is recorded in the ledger before control returns
# to the agent, so this refund counts toward future blast radius checks.
builder.add_edge(
    "execute_tool",
    "record_ledger"
)


builder.add_edge(
    "record_ledger",
    "agent"
)


# Blocked calls skip the ledger entirely and return straight to the agent.
builder.add_edge(
    "block_tool",
    "agent"
)


# Compile the graph into an executable pipeline.
graph = builder.compile()


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(
    user_input: str,
    agent_id: str,
    customer_id: str
):
    # Seed the conversation with the user's message, the identifiers
    # needed for blast radius tracking, and default/empty values for the
    # guardrail-related state fields.
    initial_state = {

        "messages": [
            HumanMessage(
                content=user_input
            )
        ],

        "agent_id":
            agent_id,

        "customer_id":
            customer_id,

        "tool_name":
            "",

        "tool_args":
            {},

        "action_allowed":
            False,

        "action_reason":
            "",

        "blast_radius_allowed":
            False,

        "blast_radius_reason":
            "",
    }


    # Run the agent <-> action guardrail <-> blast radius guardrail <->
    # tool loop until the model produces a final text reply.
    result = graph.invoke(
        initial_state
    )


    # Echo the original request.
    print("\nUser:")
    print(
        user_input
    )


    # Show the outcome of the individual (single-action) check.
    print("\nAction Guardrail:")
    print(
        result["action_allowed"]
    )

    print(
        result["action_reason"]
    )


    # Show the outcome of the cumulative (blast radius) check.
    print("\nBlast Radius Guardrail:")
    print(
        result[
            "blast_radius_allowed"
        ]
    )

    print(
        result[
            "blast_radius_reason"
        ]
    )


    # Show every refund recorded so far, across all runs in this process.
    print("\nCurrent Ledger:")

    for item in REFUND_LEDGER:

        print(
            item["agent_id"],
            item["customer_id"],
            item["invoice_id"],
            item["amount"],
            item["timestamp"],
        )


    # Show the assistant's final reply to the user.
    print("\nAgent Response:")

    print(
        result["messages"][-1].content
    )


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    # Demo run: a single $500 refund passes the individual limit exactly,
    # and with an empty ledger it also has plenty of room under every
    # cumulative limit, so it should execute and be recorded.
    run_agent(
        user_input=(
            "Refund $500 for invoice INV-1001 "
            "for customer CUST-101."
        ),
        agent_id="agent-001",
        customer_id="CUST-101",
    )