# MEMORY GUARDRAIL EXAMPLE
#
# This module lets an agent remember facts about the user across a
# conversation (via a save_memory tool), but never writes anything into
# long term memory before a *memory guardrail* has checked it. Unlike the
# earlier financial guardrails, which validate one proposed action at a
# time, this agent can face several save_memory calls in a single model
# turn (e.g. one per fact the user asked it to remember), so the guardrail
# and the node that follows it both work over a list of candidates,
# approving some and rejecting others independently.

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

from guardrail import validate_memory


# ---------------------------------------------------------
# SIMPLE MEMORY STORE
# ---------------------------------------------------------

# Stand-in for a real long term memory store (a database, vector store,
# etc). Only memories that pass the guardrail ever get written here.
MEMORY_STORE = {}


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

    # Every save_memory call proposed in the latest turn, each tagged
    # with the guardrail's allow/reject decision.
    memory_candidates: list[dict]

    # Subset of memory_candidates the guardrail allowed to be persisted.
    approved_memories: list[dict]

    # Subset of memory_candidates the guardrail rejected (e.g. contained PII).
    rejected_memories: list[dict]


# ---------------------------------------------------------
# MEMORY TOOL
# ---------------------------------------------------------

@tool
def save_memory(
    key: str,
    value: str
) -> str:
    """
    Save useful information about the user
    for future conversations.
    """
    # The actual (simulated) side effect: only reachable for candidates
    # that end up in approved_memories and get invoked by
    # process_memories_node.
    MEMORY_STORE[key] = value

    return (
        f"Memory saved: {key} = {value}"
    )


# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

# Base Claude model used to drive the conversation.
model = ChatAnthropic(
    model="claude-sonnet-4-6"
)

# Give the model access to the save_memory tool so it can propose
# remembering facts via structured tool calls instead of free text.
model_with_tools = model.bind_tools(
    [save_memory]
)


# ---------------------------------------------------------
# AGENT NODE
# ---------------------------------------------------------

def agent_node(state: AgentState):
    # Instructions asking the model to split multiple facts into separate
    # tool calls (so the guardrail can approve/reject each independently),
    # and to only claim success once the tool result confirms it.
    system_message = SystemMessage(
        content="""
You are a helpful assistant.

When the user explicitly asks you to remember
multiple useful facts, create a separate
save_memory tool call for each fact.

For example:

Preferred language should be one memory.

A personal identifier should be another memory.

Do not claim that any memory was saved unless
the tool result confirms it.
"""
    )

    # Ask the model to respond given the system prompt plus the full
    # conversation so far; it may reply with text or one or more tool calls.
    response = model_with_tools.invoke(
        [
            system_message,
            *state["messages"]
        ]
    )

    # Append the model's response (text or tool call(s)) to the conversation.
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
        # One or more save_memory calls were requested -- send them
        # through the memory guardrail before anything is persisted.
        return "memory_guardrail"

    # No tool call means the model just replied with text; end the turn.
    return END


# ---------------------------------------------------------
# MEMORY GUARDRAIL NODE
# ---------------------------------------------------------

def memory_guardrail_node(
    state: AgentState
):
    # This is the enforcement point of the memory guardrail: every
    # save_memory call the model proposed in this turn is checked against
    # policy BEFORE process_memories_node is allowed to actually save any
    # of them.
    last_message = state["messages"][-1]

    memory_candidates = []

    approved_memories = []

    rejected_memories = []


    # The model may have asked to remember several facts at once; check
    # each proposed save_memory call independently.
    for tool_call in last_message.tool_calls:

        key = tool_call["args"]["key"]

        value = tool_call["args"]["value"]

        # Delegate the actual policy check (sensitive data detection) to
        # the guardrail module.
        decision = validate_memory(
            key,
            value
        )

        # Keep the tool_call_id attached so the eventual ToolMessage
        # (saved or rejected) can be matched back to this specific call.
        candidate = {
            "tool_call_id": tool_call["id"],
            "key": key,
            "value": value,
            "allowed": decision["allowed"],
            "reason": decision["reason"],
            "sensitive_types": decision[
                "sensitive_types"
            ],
        }

        memory_candidates.append(
            candidate
        )

        # Sort the candidate into the approved or rejected bucket based
        # on the guardrail's verdict.
        if decision["allowed"]:

            approved_memories.append(
                candidate
            )

        else:

            rejected_memories.append(
                candidate
            )


    # Record every candidate plus the approved/rejected split so
    # process_memories_node knows exactly what to do with each one.
    return {
        "memory_candidates":
            memory_candidates,

        "approved_memories":
            approved_memories,

        "rejected_memories":
            rejected_memories,
    }


# ---------------------------------------------------------
# ROUTE AFTER GUARDRAIL
# ---------------------------------------------------------

def route_after_guardrail(
    state: AgentState
):
    # If any save_memory calls were proposed (approved or rejected),
    # process them; otherwise there is nothing to do this turn.
    if state["memory_candidates"]:
        return "process_memories"

    return END


# ---------------------------------------------------------
# PROCESS MEMORY NODE
# ---------------------------------------------------------

def process_memories_node(
    state: AgentState
):
    # Turns the guardrail's approved/rejected split into real effects:
    # approved candidates are actually persisted, rejected ones are not,
    # and every candidate gets a ToolMessage reply either way.
    tool_messages = []


    # -------------------------------------
    # SAVE APPROVED MEMORIES
    # -------------------------------------

    for memory in state[
        "approved_memories"
    ]:
        # Reached only for candidates the guardrail allowed -- safe to
        # actually write into MEMORY_STORE now.
        result = save_memory.invoke(
            {
                "key": memory["key"],
                "value": memory["value"],
            }
        )

        tool_messages.append(
            ToolMessage(
                content=result,
                tool_call_id=
                    memory["tool_call_id"]
            )
        )


    # -------------------------------------
    # REJECT SENSITIVE MEMORIES
    # -------------------------------------

    for memory in state[
        "rejected_memories"
    ]:
        # The tool is never invoked for these; instead we synthesize a
        # ToolMessage explaining why the memory was not saved.
        tool_messages.append(
            ToolMessage(
                content=(
                    "Memory was not saved. "
                    f"Reason: {memory['reason']}"
                ),
                tool_call_id=
                    memory["tool_call_id"]
            )
        )


    # Every save_memory tool call (approved or rejected) needs a matching
    # ToolMessage, or the model's next turn would be missing a reply to
    # one of its own tool calls.
    return {
        "messages": tool_messages
    }


# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------

# Create the state graph over AgentState.
builder = StateGraph(
    AgentState
)


# The LLM-driving node: decides what to say or which memories to save.
builder.add_node(
    "agent",
    agent_node
)

# Checks every proposed save_memory call for sensitive data.
builder.add_node(
    "memory_guardrail",
    memory_guardrail_node
)

# Actually saves approved memories and synthesizes replies for rejected ones.
builder.add_node(
    "process_memories",
    process_memories_node
)


# Every run starts at the agent node.
builder.add_edge(
    START,
    "agent"
)


# After the agent responds: if it proposed any save_memory calls, send
# them through the memory guardrail; otherwise the turn is over.
builder.add_conditional_edges(
    "agent",
    route_after_agent,
    {
        "memory_guardrail":
            "memory_guardrail",

        END:
            END,
    }
)


# After the guardrail classifies the candidates: process them (save the
# approved ones, reject the rest) if there were any, otherwise end.
builder.add_conditional_edges(
    "memory_guardrail",
    route_after_guardrail,
    {
        "process_memories":
            "process_memories",

        END:
            END,
    }
)


# After processing memories, control returns to the agent so it can
# incorporate the ToolMessages (saved or rejected) into its next reply.
builder.add_edge(
    "process_memories",
    "agent"
)


# Compile the graph into an executable pipeline.
graph = builder.compile()


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(
    user_input: str
):
    # Seed the conversation with the user's message and empty lists for
    # the memory-guardrail-related state fields.
    initial_state = {

        "messages": [
            HumanMessage(
                content=user_input
            )
        ],

        "memory_candidates": [],

        "approved_memories": [],

        "rejected_memories": [],
    }


    # Run the agent <-> memory guardrail <-> process loop until the model
    # produces a final text reply.
    result = graph.invoke(
        initial_state
    )


    # Echo the original request.
    print("\nUser:")
    print(user_input)


    # Show every save_memory call the model proposed this turn.
    print("\nMemory Candidates:")

    for memory in result[
        "memory_candidates"
    ]:

        print(
            memory["key"],
            "=",
            memory["value"]
        )


    # Show which of those candidates the guardrail allowed to be saved.
    print("\nApproved Memories:")

    for memory in result[
        "approved_memories"
    ]:

        print(
            memory["key"],
            "=",
            memory["value"]
        )


    # Show which candidates were rejected, and why.
    print("\nRejected Memories:")

    for memory in result[
        "rejected_memories"
    ]:

        print(
            memory["key"],
            "=",
            memory["value"],
            "| Reason:",
            memory["reason"]
        )


    # Show what actually made it into long term memory.
    print("\nMemory Store:")

    print(
        MEMORY_STORE
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
    # Demo run: two facts are requested at once. The preferred language
    # should become two separate save_memory calls, of which the language
    # fact should be approved and the SSN fact should be rejected by the
    # memory guardrail.
    run_agent(
        "Please remember that my preferred "
        "language is English and my SSN is "
        "123-45-6789."
    )