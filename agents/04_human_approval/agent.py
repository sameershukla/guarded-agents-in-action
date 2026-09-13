# HUMAN APPROVAL GUARDRAIL EXAMPLE
#
# This module builds on 03_risk_routing's LOW / MEDIUM / HIGH risk
# classification, but changes what happens to a HIGH-risk refund: instead
# of blocking it outright, the graph pauses (using LangGraph's interrupt)
# and waits for a human to approve or reject it before deciding whether to
# execute or block the tool call. A MemorySaver checkpointer is required
# so the graph's state survives the pause and can be resumed later, even
# across separate invoke() calls.

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
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver

from guardrail import (
    RiskLevel,
    assess_financial_risk,
    perform_additional_validation,
)


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------

class AgentState(TypedDict):
    # Full conversation history; add_messages appends rather than
    # overwriting on each node's return.
    messages: Annotated[list[AnyMessage], add_messages]

    tool_name: str  # Name of the tool the LLM most recently tried to call.
    tool_args: dict  # Arguments the LLM supplied for that tool call.

    risk_level: str        # RiskLevel classification from the risk guardrail.
    guardrail_reason: str  # Explanation for that risk classification.

    validation_passed: bool  # Result of the extra check applied to MEDIUM-risk calls.
    validation_reason: str   # Explanation for the validation result.

    human_approved: bool  # Whether a human approved a HIGH-risk call during the interrupt.


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
    # The actual (simulated) side effect: only reachable for calls that
    # end up routed to execute_tool_node.
    return (
        f"Refund of ${amount:.2f} "
        f"issued for invoice {invoice_id}."
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

def agent_node(state: AgentState):
    # Instructions constraining the assistant to only claim success once
    # the tool itself confirms the refund went through.
    system_message = SystemMessage(
        content="""
You are a customer support agent.

You can help customers with refunds.

Use the refund tool when a user asks you
to issue a refund.

Do not claim that a refund succeeded unless
the tool confirms that it succeeded.
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
        # A tool call was requested -- send it through risk assessment
        # before it can run.
        return "risk_guardrail"

    # No tool call means the model just replied with text; end the turn.
    return END


# ---------------------------------------------------------
# RISK GUARDRAIL NODE
# ---------------------------------------------------------

def risk_guardrail_node(state: AgentState):
    # Entry point of the risk-routing guardrail: classify the LLM's
    # proposed tool call into LOW / MEDIUM / HIGH risk before deciding
    # how (or whether) it gets executed.
    last_message = state["messages"][-1]

    # Only the first requested tool call is assessed/executed in this
    # example (the model is expected to request one refund at a time).
    tool_call = last_message.tool_calls[0]

    tool_name = tool_call["name"]
    tool_args = tool_call["args"]

    # Delegate the actual risk classification (tool allow-list, amount
    # thresholds) to the guardrail module.
    decision = assess_financial_risk(
        tool_name,
        tool_args
    )

    # Record the tool call and its risk classification in state so
    # downstream routing/nodes can act on it.
    return {
        "tool_name": tool_name,
        "tool_args": tool_args,
        "risk_level": decision["risk_level"],
        "guardrail_reason": decision["reason"],
    }


# ---------------------------------------------------------
# ROUTE BY RISK
# ---------------------------------------------------------

def route_by_risk(state: AgentState):
    # LOW risk: safe to execute immediately.
    if state["risk_level"] == RiskLevel.LOW:
        return "execute_tool"

    # MEDIUM risk: needs an extra validation pass before executing.
    if state["risk_level"] == RiskLevel.MEDIUM:
        return "additional_validation"

    # HIGH risk: never auto-executed or auto-blocked -- a human must
    # decide instead.
    return "human_approval"


# ---------------------------------------------------------
# ADDITIONAL VALIDATION
# ---------------------------------------------------------

def additional_validation_node(state: AgentState):
    # Only reached for MEDIUM-risk calls; runs a stricter check (e.g.
    # invoice ID format) before allowing execution.
    result = perform_additional_validation(
        state["tool_args"]
    )

    return {
        "validation_passed": result["valid"],
        "validation_reason": result["reason"],
    }


def route_after_validation(state: AgentState):
    # Validation passed: proceed to execute the tool.
    if state["validation_passed"]:
        return "execute_tool"

    # Validation failed: block the tool call instead.
    return "block_tool"


# ---------------------------------------------------------
# HUMAN APPROVAL NODE
# ---------------------------------------------------------

def human_approval_node(state: AgentState):
    # interrupt() pauses graph execution here and surfaces this payload
    # to whoever is running the graph (see the __main__ block below). The
    # checkpointer persists state so the graph can be resumed later, from
    # the exact point it paused, once a decision comes back.
    decision = interrupt(
        {
            "question": "Approve this refund?",
            "tool": state["tool_name"],
            "arguments": state["tool_args"],
            "risk_level": state["risk_level"],
            "reason": state["guardrail_reason"],
        }
    )

    # The resumed value becomes the human's approve/reject decision.
    return {
        "human_approved": bool(decision)
    }


# ---------------------------------------------------------
# ROUTE AFTER HUMAN
# ---------------------------------------------------------

def route_after_human(state: AgentState):
    # Human approved: proceed to execute the tool.
    if state["human_approved"]:
        return "execute_tool"

    # Human rejected (or approval wasn't granted): block the tool call.
    return "block_tool"


# ---------------------------------------------------------
# EXECUTE TOOL
# ---------------------------------------------------------

def execute_tool_node(state: AgentState):
    # Reached only for LOW-risk calls, MEDIUM-risk calls that passed
    # additional validation, or HIGH-risk calls a human approved -- safe
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
        "messages": [tool_message]
    }


# ---------------------------------------------------------
# BLOCK TOOL
# ---------------------------------------------------------

def block_tool_node(state: AgentState):
    # Reached for MEDIUM-risk calls that failed validation, or HIGH-risk
    # calls a human rejected -- the tool never runs.
    last_message = state["messages"][-1]

    tool_call = last_message.tool_calls[0]

    # Default to the risk guardrail's reason, then override it with a
    # more specific reason depending on which check actually blocked it.
    reason = state["guardrail_reason"]

    if (
        state["risk_level"] == RiskLevel.MEDIUM
        and not state["validation_passed"]
    ):
        reason = state["validation_reason"]

    if (
        state["risk_level"] == RiskLevel.HIGH
        and not state["human_approved"]
    ):
        reason = "Human approval was not granted."

    tool_message = ToolMessage(
        content=(
            "Refund was not executed. "
            f"Reason: {reason}"
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

# Classifies any requested tool call into LOW / MEDIUM / HIGH risk.
builder.add_node(
    "risk_guardrail",
    risk_guardrail_node
)

# Extra scrutiny applied only to MEDIUM-risk calls.
builder.add_node(
    "additional_validation",
    additional_validation_node
)

# Pauses the graph and waits for a human decision on HIGH-risk calls.
builder.add_node(
    "human_approval",
    human_approval_node
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
# risk assessment; otherwise the conversation turn is over.
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "risk_guardrail": "risk_guardrail",
        END: END,
    }
)


# After risk assessment: LOW risk executes immediately, MEDIUM risk goes
# through additional validation, HIGH risk is escalated to a human.
builder.add_conditional_edges(
    "risk_guardrail",
    route_by_risk,
    {
        "execute_tool": "execute_tool",
        "additional_validation": "additional_validation",
        "human_approval": "human_approval",
    }
)


# After additional validation (MEDIUM-risk path only): execute if it
# passed, otherwise block.
builder.add_conditional_edges(
    "additional_validation",
    route_after_validation,
    {
        "execute_tool": "execute_tool",
        "block_tool": "block_tool",
    }
)


# After human approval (HIGH-risk path only): execute if approved,
# otherwise block.
builder.add_conditional_edges(
    "human_approval",
    route_after_human,
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


# ---------------------------------------------------------
# CHECKPOINTER
# ---------------------------------------------------------

# Required for interrupt()/Command(resume=...) to work: the checkpointer
# persists the graph's state at the point of the pause so a later
# invoke() with a Command can pick execution back up from human_approval_node
# instead of starting over.
checkpointer = MemorySaver()

graph = builder.compile(
    checkpointer=checkpointer
)


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(user_input: str):
    # thread_id identifies this conversation's checkpointed state so the
    # graph can be resumed later with the same config.
    config = {
        "configurable": {
            "thread_id": "refund-001"
        }
    }

    # Seed the conversation with the user's message and default/empty
    # values for the guardrail-, validation-, and approval-related state.
    initial_state = {
        "messages": [
            HumanMessage(
                content=user_input
            )
        ],
        "tool_name": "",
        "tool_args": {},
        "risk_level": "",
        "guardrail_reason": "",
        "validation_passed": False,
        "validation_reason": "",
        "human_approved": False,
    }

    # Run until the model gives a final reply, or the graph pauses at
    # human_approval_node (in which case the result carries "__interrupt__").
    result = graph.invoke(
        initial_state,
        config=config
    )

    # Return the config too, since resuming a paused run requires it.
    return result, config


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    # Demo run: a $900 refund is HIGH risk, so this should pause at
    # human_approval_node instead of executing or blocking immediately.
    result, config = run_agent(
        "Please refund $900 "
        "for invoice INV-1001."
    )

    if "__interrupt__" in result:
        # The graph paused; show the human the details of what it's
        # being asked to approve.
        print("\nHuman Approval Required:")

        print(
            result["__interrupt__"][0].value
        )

        # Collect the human's decision from the terminal.
        decision = input(
            "\nApprove refund? yes/no: "
        )

        approved = (
            decision.strip().lower() == "yes"
        )

        # Resume the paused graph from human_approval_node, feeding the
        # human's decision back in as the interrupt()'s return value.
        result = graph.invoke(
            Command(
                resume=approved
            ),
            config=config
        )

    # Show the assistant's final reply to the user.
    print("\nAgent Response:")
    print(
        result["messages"][-1].content
    )