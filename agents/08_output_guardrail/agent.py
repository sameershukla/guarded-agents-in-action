# OUTPUT GUARDRAIL EXAMPLE
#
# This module checks the model's reply AFTER it is generated but BEFORE
# it is returned to the user. The agent produces a draft_response first;
# only output_guardrail_node's decision determines whether that draft is
# shown as-is, cleaned up, or replaced entirely. This closes the loop
# with 01_pii_input's input guardrail: that one kept sensitive data from
# going in, this one catches sensitive data (or unsafe advice) trying to
# come back out.

from typing import TypedDict

from langchain_anthropic import ChatAnthropic

from langchain_core.messages import (
    HumanMessage,
    SystemMessage,
)

from langgraph.graph import (
    StateGraph,
    START,
    END,
)

from guardrail import (
    validate_output,
    sanitize_output,
)


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------

class AgentState(TypedDict):

    user_input: str  # The user's original question.

    draft_response: str  # The model's reply before the output guardrail checks it.

    output_decision: str   # One of "allow", "sanitize", or "block".
    guardrail_reason: str  # Explanation for that decision.
    pii_types: list[str]   # PII categories found in the draft, if any.

    final_response: str  # What actually gets shown to the user.


# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

# Base Claude model used to generate the draft response.
model = ChatAnthropic(
    model="claude-sonnet-4-6"
)


# ---------------------------------------------------------
# AGENT NODE
# ---------------------------------------------------------

def agent_node(
    state: AgentState
):
    # The system prompt explicitly tells the model its reply is a draft,
    # not the final answer -- this is only a hint though; the guardrail
    # that follows is what actually enforces that a check happens.
    system_message = SystemMessage(
        content="""
You are a helpful financial support assistant.

Answer the user's question clearly.

Do not assume that your response will be sent
directly to the user.

Another system will validate your response
before it is returned.
"""
    )

    human_message = HumanMessage(
        content=state["user_input"]
    )

    response = model.invoke(
        [
            system_message,
            human_message,
        ]
    )

    # Store as draft_response, not final_response -- nothing here is
    # shown to the user until the output guardrail has run.
    return {
        "draft_response":
            response.content
    }


# ---------------------------------------------------------
# OUTPUT GUARDRAIL NODE
# ---------------------------------------------------------

def output_guardrail_node(
    state: AgentState
):
    # This is the enforcement point of the output guardrail: the model's
    # draft is checked BEFORE any version of it is allowed to reach the
    # user.
    decision = validate_output(
        state["draft_response"]
    )

    return {
        "output_decision":
            decision["decision"],

        "guardrail_reason":
            decision["reason"],

        "pii_types":
            decision["pii_types"],
    }


# ---------------------------------------------------------
# ROUTE AFTER GUARDRAIL
# ---------------------------------------------------------

def route_after_guardrail(
    state: AgentState
):
    # Three-way branch matching validate_output's three possible
    # decisions.
    if state["output_decision"] == "allow":
        return "allow_output"

    if state["output_decision"] == "sanitize":
        return "sanitize_output"

    return "block_output"


# ---------------------------------------------------------
# ALLOW OUTPUT NODE
# ---------------------------------------------------------

def allow_output_node(
    state: AgentState
):
    # Draft passed every check unchanged; use it as-is.
    return {
        "final_response":
            state["draft_response"]
    }


# ---------------------------------------------------------
# SANITIZE OUTPUT NODE
# ---------------------------------------------------------

def sanitize_output_node(
    state: AgentState
):
    # Draft contained PII but was otherwise fine; redact the sensitive
    # values rather than discarding the whole answer.
    sanitized = sanitize_output(
        state["draft_response"]
    )

    return {
        "final_response":
            sanitized
    }


# ---------------------------------------------------------
# BLOCK OUTPUT NODE
# ---------------------------------------------------------

def block_output_node(
    state: AgentState
):
    # Draft contained something that can't be fixed by editing (e.g.
    # risky financial advice); the draft is discarded entirely and
    # replaced with a safe, generic response.
    return {
        "final_response": (
            "I cannot provide that recommendation. "
            "I can explain the risks, options, and "
            "factors you may want to consider instead."
        )
    }


# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------

# Create the state graph over AgentState.
builder = StateGraph(
    AgentState
)


# Generates the draft response.
builder.add_node(
    "agent",
    agent_node
)

# Classifies the draft as allow / sanitize / block.
builder.add_node(
    "output_guardrail",
    output_guardrail_node
)

# Passes an already-safe draft straight through.
builder.add_node(
    "allow_output",
    allow_output_node
)

# Redacts PII from a draft that is otherwise fine.
builder.add_node(
    "sanitize_output",
    sanitize_output_node
)

# Replaces a draft with a safe canned response.
builder.add_node(
    "block_output",
    block_output_node
)


# Every run starts by generating a draft.
builder.add_edge(
    START,
    "agent"
)


# Every draft is checked by the output guardrail before it can be shown.
builder.add_edge(
    "agent",
    "output_guardrail"
)


# After the guardrail: route to whichever outcome its decision calls for.
builder.add_conditional_edges(
    "output_guardrail",
    route_after_guardrail,
    {
        "allow_output":
            "allow_output",

        "sanitize_output":
            "sanitize_output",

        "block_output":
            "block_output",
    }
)


builder.add_edge(
    "allow_output",
    END
)

builder.add_edge(
    "sanitize_output",
    END
)

builder.add_edge(
    "block_output",
    END
)


# Compile the graph into an executable pipeline.
graph = builder.compile()


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(
    user_input: str
):
    # Seed the state with the user's question; everything else starts
    # empty and gets filled in as the graph runs.
    initial_state = {

        "user_input":
            user_input,

        "draft_response":
            "",

        "output_decision":
            "",

        "guardrail_reason":
            "",

        "pii_types":
            [],

        "final_response":
            "",
    }


    # Run the agent -> output guardrail -> (allow | sanitize | block) pipeline.
    result = graph.invoke(
        initial_state
    )


    print("\nUser:")
    print(
        result["user_input"]
    )


    print("\nDraft Response:")
    print(
        result["draft_response"]
    )


    print("\nOutput Decision:")
    print(
        result["output_decision"]
    )


    print("\nGuardrail Reason:")
    print(
        result["guardrail_reason"]
    )


    print("\nFinal Response:")
    print(
        result["final_response"]
    )


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    # Demo run: this question is likely to produce a draft matching the
    # "put all ... retirement" risky-advice pattern, so the expected
    # outcome is block_output_node replacing it with a safe response.
    run_agent(
        "Should I put all my retirement "
        "savings into one technology stock?"
    )