# PLAN GUARDRAIL EXAMPLE
#
# This module has the model produce an entire multi-step PLAN up front
# (using structured output, not free-form tool calling), then validates
# the whole plan through a *plan guardrail* before executing any of it.
# This is different from the earlier action/risk guardrails, which
# checked one proposed tool call at a time as the conversation went along
# -- here, the model reasons about a whole sequence of actions, and the
# guardrail can reject the plan based on relationships between steps
# (ordering, counts, totals), not just each step in isolation.

from typing import TypedDict

from pydantic import BaseModel, Field

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

from guardrail import validate_plan


# ---------------------------------------------------------
# PLAN MODELS
# ---------------------------------------------------------

# Pydantic schema the model's structured output is forced to conform to,
# so a "plan" is always a list of well-typed tool/arguments pairs rather
# than free text the code would have to parse.
class PlanStep(BaseModel):
    tool: str = Field(
        description="Tool to execute"
    )

    arguments: dict = Field(
        default_factory=dict,
        description="Arguments for the tool"
    )


class Plan(BaseModel):
    steps: list[PlanStep]


# ---------------------------------------------------------
# STATE
# ---------------------------------------------------------

class AgentState(TypedDict):
    user_request: str  # The user's original request.

    plan: list[dict]  # The model's proposed plan, as plain dicts.

    plan_allowed: bool     # Whether the plan guardrail approved the whole plan.
    guardrail_reason: str  # Explanation for that decision.

    execution_results: list[str]  # Output of each executed step, in order.

    response: str  # The final message shown to the user.


# ---------------------------------------------------------
# MODEL
# ---------------------------------------------------------

# Base Claude model used to produce the plan.
model = ChatAnthropic(
    model="claude-sonnet-4-6"
)

# Force the model's output to conform to the Plan schema instead of
# returning free-form text or ad hoc tool calls.
planner_model = model.with_structured_output(
    Plan
)


# ---------------------------------------------------------
# SAMPLE TOOLS
# ---------------------------------------------------------

# Plain functions standing in for real integrations. These only run
# inside executor_node, and only for a plan the guardrail has approved.

def lookup_invoice(
    invoice_id: str
) -> str:

    return (
        f"Invoice {invoice_id} "
        "was found and is eligible for refund."
    )


def issue_refund(
    invoice_id: str,
    amount: float
) -> str:

    return (
        f"Refund of ${amount:.2f} "
        f"issued for invoice {invoice_id}."
    )


def send_notification(
    message: str
) -> str:

    return (
        f"Notification sent: {message}"
    )


# ---------------------------------------------------------
# PLANNER NODE
# ---------------------------------------------------------

def planner_node(
    state: AgentState
):
    # Ask the model to turn the user's request into a full plan up front,
    # rather than deciding one tool call at a time. The prompt itself
    # tries to steer good ordering (lookup before refund), but that is
    # only a suggestion to the model -- plan_guardrail_node is what
    # actually enforces it.
    system_message = SystemMessage(
        content="""
You are a financial support planner.

Create a plan using only these tools:

lookup_invoice
issue_refund
send_notification

Tool arguments must follow these rules:

lookup_invoice:
{
  "invoice_id": "string"
}

issue_refund:
{
  "invoice_id": "string",
  "amount": number
}

send_notification:
{
  "message": "string"
}

Important:

Before issuing a refund,
first look up the invoice.

Do not add extra arguments to any tool.

Return only the structured plan.
"""
    )

    human_message = HumanMessage(
        content=state["user_request"]
    )

    # Structured output guarantees this comes back as a Plan instance,
    # not text that would need to be parsed.
    plan = planner_model.invoke(
        [
            system_message,
            human_message,
        ]
    )

    # Convert to plain dicts so the rest of the graph (and the guardrail,
    # which has no dependency on pydantic) can work with simple data.
    plan_as_dicts = [
        step.model_dump()
        for step in plan.steps
    ]

    return {
        "plan": plan_as_dicts
    }


# ---------------------------------------------------------
# PLAN GUARDRAIL NODE
# ---------------------------------------------------------

def plan_guardrail_node(
    state: AgentState
):
    # This is the enforcement point of the plan guardrail: the entire
    # proposed plan is checked as a whole BEFORE any step of it runs.
    decision = validate_plan(
        state["plan"]
    )

    return {
        "plan_allowed":
            decision["allowed"],

        "guardrail_reason":
            decision["reason"],
    }


# ---------------------------------------------------------
# ROUTE AFTER GUARDRAIL
# ---------------------------------------------------------

def route_after_guardrail(
    state: AgentState
):
    # Approved plans move on to execution; anything else is blocked
    # wholesale, since a plan is validated as a single unit, not step by
    # step.
    if state["plan_allowed"]:
        return "executor"

    return "block_plan"


# ---------------------------------------------------------
# EXECUTOR NODE
# ---------------------------------------------------------

def executor_node(
    state: AgentState
):
    # Reached only for a plan the guardrail approved -- safe to run every
    # step for real now, in the order the model proposed.
    results = []

    for step in state["plan"]:

        tool_name = step["tool"]

        arguments = step.get(
            "arguments",
            {}
        )

        if tool_name == "lookup_invoice":

            result = lookup_invoice(
                invoice_id=
                    arguments["invoice_id"]
            )

        elif tool_name == "issue_refund":

            result = issue_refund(
                invoice_id=
                    arguments["invoice_id"],

                amount=
                    arguments["amount"]
            )

        elif tool_name == "send_notification":

            result = send_notification(
                message=
                    arguments["message"]
            )

        else:
            # Should not happen for a plan that passed validate_plan's
            # allow-list check, but kept as a safe fallback.
            result = (
                f"Unknown tool: {tool_name}"
            )

        results.append(
            result
        )

    return {
        "execution_results":
            results
    }


# ---------------------------------------------------------
# BLOCK PLAN NODE
# ---------------------------------------------------------

def block_plan_node(
    state: AgentState
):
    # Reached when the guardrail rejected the plan -- none of its steps
    # ever run; this synthesizes a single explanatory result instead.
    return {
        "execution_results": [
            (
                "Plan was not executed. "
                f"Reason: "
                f"{state['guardrail_reason']}"
            )
        ]
    }


# ---------------------------------------------------------
# FINAL RESPONSE NODE
# ---------------------------------------------------------

def final_response_node(
    state: AgentState
):
    # Turn the per-step results (or the block reason) into the final
    # message shown to the user.
    results = "\n".join(
        state["execution_results"]
    )

    if state["plan_allowed"]:

        response = (
            "Plan executed successfully.\n\n"
            f"{results}"
        )

    else:

        response = results

    return {
        "response": response
    }


# ---------------------------------------------------------
# GRAPH
# ---------------------------------------------------------

# Create the state graph over AgentState.
builder = StateGraph(
    AgentState
)


# Produces the full structured plan from the user's request.
builder.add_node(
    "planner",
    planner_node
)

# Validates the whole plan (per-step and cross-step rules) before execution.
builder.add_node(
    "plan_guardrail",
    plan_guardrail_node
)

# Runs every step of an approved plan, in order.
builder.add_node(
    "executor",
    executor_node
)

# Short-circuits with a denial message for a rejected plan.
builder.add_node(
    "block_plan",
    block_plan_node
)

# Formats whichever outcome occurred into the final user-facing message.
builder.add_node(
    "final_response",
    final_response_node
)


# Every run starts by generating a plan.
builder.add_edge(
    START,
    "planner"
)


# Every generated plan is checked by the guardrail before anything runs.
builder.add_edge(
    "planner",
    "plan_guardrail"
)


# After the guardrail: execute the whole plan if allowed, otherwise block
# it outright.
builder.add_conditional_edges(
    "plan_guardrail",
    route_after_guardrail,
    {
        "executor":
            "executor",

        "block_plan":
            "block_plan",
    }
)


builder.add_edge(
    "executor",
    "final_response"
)


builder.add_edge(
    "block_plan",
    "final_response"
)


builder.add_edge(
    "final_response",
    END
)


# Compile the graph into an executable pipeline.
graph = builder.compile()


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_agent(
    user_request: str
):
    # Seed the state with the user's request; everything else starts
    # empty and gets filled in as the graph runs.
    initial_state = {

        "user_request":
            user_request,

        "plan":
            [],

        "plan_allowed":
            False,

        "guardrail_reason":
            "",

        "execution_results":
            [],

        "response":
            "",
    }

    # Run the planner -> guardrail -> (executor | block_plan) -> final
    # response pipeline.
    result = graph.invoke(
        initial_state
    )

    print("\nUser Request:")
    print(
        result["user_request"]
    )

    print("\nProposed Plan:")

    for index, step in enumerate(
        result["plan"],
        start=1
    ):

        print(
            index,
            step
        )

    print("\nPlan Allowed:")
    print(
        result["plan_allowed"]
    )

    print("\nGuardrail Reason:")
    print(
        result["guardrail_reason"]
    )

    print("\nExecution Results:")

    for item in result[
        "execution_results"
    ]:

        print(item)

    print("\nFinal Response:")

    print(
        result["response"]
    )


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":
    # Demo run: expects a well-formed plan (lookup, then refund, then
    # notify) that passes every guardrail check and executes end to end.
    run_agent(
        "Please refund $300 for "
        "invoice INV-1001 and notify "
        "the customer."
    )