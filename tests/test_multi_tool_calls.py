# Regression tests for finding: agents that validate only tool_calls[0]
# must still reply to EVERY tool call, or the next model turn fails with
# a missing tool_result error.

import pytest

from conftest import load_agent

AGENTS = [
    "02_financial_action",
    "03_risk_routing",
    "04_human_approval",
    "09_blast_radius",
]


@pytest.fixture(params=AGENTS, scope="module")
def agent(request):
    return load_agent(request.param)


def two_calls(make):
    return make(
        ("issue_refund", {"customer_id": "CUST-101", "invoice_id": "INV-1", "amount": 50}),
        ("issue_refund", {"customer_id": "CUST-101", "invoice_id": "INV-2", "amount": 60}),
    )


def full_state(msg):
    # Superset of every agent's state keys so the same state works for all.
    return {
        "messages": [msg],
        "agent_id": "agent-001",
        "customer_id": "CUST-101",
        "tool_name": "issue_refund",
        "tool_args": msg.tool_calls[0]["args"],
        "action_allowed": False,
        "action_reason": "blocked for test",
        "guardrail_reason": "blocked for test",
        "risk_level": "high",
        "validation_passed": False,
        "validation_reason": "",
        "human_approved": False,
        "blast_radius_allowed": False,
        "blast_radius_reason": "",
    }


def _ids(messages):
    return [m.tool_call_id for m in messages]


def test_execute_replies_to_every_call(agent, ai_tool_call_message):
    msg = two_calls(ai_tool_call_message)
    out = agent.execute_tool_node(full_state(msg))
    assert _ids(out["messages"]) == ["call-0", "call-1"]
    assert "issued" in out["messages"][0].content
    assert "not executed" in out["messages"][1].content.lower()


def test_block_replies_to_every_call(agent, ai_tool_call_message):
    msg = two_calls(ai_tool_call_message)
    out = agent.block_tool_node(full_state(msg))
    assert _ids(out["messages"]) == ["call-0", "call-1"]
    assert all("not executed" in m.content.lower() for m in out["messages"])


def test_single_call_unchanged(agent, ai_tool_call_message):
    msg = ai_tool_call_message(
        ("issue_refund", {"customer_id": "CUST-101", "invoice_id": "INV-1", "amount": 50}),
    )
    out = agent.block_tool_node(full_state(msg))
    assert _ids(out["messages"]) == ["call-0"]
