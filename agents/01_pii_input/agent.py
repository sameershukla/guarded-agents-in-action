# INPUT GUARDRAIL EXAMPLE
#
# This module wires together a small LangGraph pipeline that demonstrates
# an *input guardrail*: untrusted user input is inspected and cleaned
# BEFORE it is allowed to reach the LLM, rather than trusting the model
# to handle sensitive data safely on its own. Concretely, it:
#   1. Scans a user's raw message for PII (SSN, credit card, email, phone).
#   2. Redacts any PII found before the text ever reaches the LLM.
#   3. Sends the sanitized message to a Claude model acting as a customer
#      support assistant and prints the results at each stage.

from typing import TypedDict  # Used to define a typed dict schema for the graph's shared state.

from langchain_anthropic import ChatAnthropic  # LangChain wrapper around the Anthropic Claude API.
from langgraph.graph import StateGraph, START, END  # LangGraph primitives for building the node graph.

from guardrail import detect_pii, sanitize_pii  # Local PII-detection and PII-redaction helper functions.


class AgentState(TypedDict):
    # The state object that flows through every node in the graph.
    user_input: str        # The raw, unmodified text the user submitted.
    sanitized_input: str   # user_input with any detected PII redacted.
    contains_pii: bool     # True if at least one PII type was detected.
    pii_types: list[str]   # Names of the PII categories found (e.g. "ssn", "email").
    response: str          # The LLM's reply after processing the sanitized input.


# The Claude model instance used to generate the assistant's reply.
model = ChatAnthropic(model="claude-sonnet-4-6")

# Node: 1 -- the input guardrail's detection step.
def pii_guardrail_node(state: AgentState):
    # Detect which types of PII (if any) appear in the user's raw input.
    pii_types = detect_pii(
        state["user_input"]
    )

    # Update the graph state with whether PII was found and which kinds.
    return {
        "contains_pii": len(pii_types) > 0,
        "pii_types": pii_types,
    }

# Node: 2 -- the input guardrail's enforcement step (blocks PII from
# propagating further by rewriting it).
def sanitize_node(state: AgentState):
    # Replace any detected PII in the raw input with redaction placeholders.
    sanitized_input = sanitize_pii(
        state["user_input"]
    )

    # Store the cleaned text back into the state so downstream nodes use it
    # instead of the original, unredacted message.
    return {
        "sanitized_input": sanitized_input
    }

# Node: 3 -- runs only after the input guardrail has already cleaned the
# input; this node never sees the original, unredacted user message.
def agent_node(state: AgentState):
    # Build the prompt sent to the LLM, using only the sanitized text so
    # that no raw PII is ever forwarded to the model.
    prompt = f"""
    You are a helpful customer support assistant.
    User message: {state["sanitized_input"]}
    """

    # Call the Claude model with the constructed prompt.
    response = model.invoke(prompt)

    # Store the model's reply text into the state.
    return {
        "response": response.content
    }


# Construct the Graph
# Create a new state graph whose shared state shape is AgentState.
builder = StateGraph(AgentState)

# Register the PII-detection step as a node named "pii_guardrail".
builder.add_node(
    "pii_guardrail",
    pii_guardrail_node
)

# Register the PII-redaction step as a node named "sanitize".
builder.add_node(
    "sanitize",
    sanitize_node
)

# Register the LLM-invocation step as a node named "agent".
builder.add_node(
    "agent",
    agent_node
)


# Execution starts at the "pii_guardrail" node.
builder.add_edge(
    START,
    "pii_guardrail"
)

# After detecting PII, always proceed to sanitize the input.
builder.add_edge(
    "pii_guardrail",
    "sanitize"
)

# After sanitizing, pass the cleaned input to the agent node.
builder.add_edge(
    "sanitize",
    "agent"
)

# After the agent responds, the graph run is complete.
builder.add_edge(
    "agent",
    END
)


# Compile the builder into an executable graph.
graph = builder.compile()


def run_agent(user_input: str):
    # Seed the initial state with the user's raw message and empty/default
    # values for everything the graph will populate as it runs.
    initial_state = {
        "user_input": user_input,
        "sanitized_input": "",
        "contains_pii": False,
        "pii_types": [],
        "response": "",
    }

    # Run the full pii_guardrail -> sanitize -> agent pipeline and collect
    # the final state.
    result = graph.invoke(
        initial_state
    )

    # Print the original (unredacted) user message.
    print("\nOriginal Input:")
    print(result["user_input"])

    # Print whether any PII was detected in that message.
    print("\nContains PII:")
    print(result["contains_pii"])

    # Print which categories of PII were found, if any.
    print("\nPII Types:")
    print(result["pii_types"])

    # Print the redacted version of the message that was actually sent to the LLM.
    print("\nSanitized Input:")
    print(result["sanitized_input"])

    # Print the LLM's final response to the sanitized message.
    print("\nAgent Response:")
    print(result["response"])


if __name__ == "__main__":
    # Demo run: a message containing an SSN, to show detection/redaction
    # working before the text reaches the model.
    run_agent(
        "My SSN is 123-45-6789. "
        "Why was my payment declined?"
    )