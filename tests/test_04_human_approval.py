import pytest

from conftest import load_agent, load_guardrail

g = load_guardrail("04_human_approval")
RiskLevel = g.RiskLevel


# ---------------------------------------------------------
# GUARDRAIL: invalid actions must never be escalated to a human
# ---------------------------------------------------------

def test_unknown_tool_is_invalid_not_high():
    d = g.assess_financial_risk("delete_account", {"amount": 10})
    assert d["risk_level"] == RiskLevel.INVALID


@pytest.mark.parametrize("amount", [0, -1, "900", None])
def test_bad_amount_is_invalid_not_high(amount):
    d = g.assess_financial_risk("issue_refund", {"amount": amount})
    assert d["risk_level"] == RiskLevel.INVALID


def test_large_refund_is_high():
    d = g.assess_financial_risk("issue_refund", {"amount": 900})
    assert d["risk_level"] == RiskLevel.HIGH
    assert "human approval" in d["reason"]


# ---------------------------------------------------------
# AGENT: routing and node behaviour
# ---------------------------------------------------------

@pytest.fixture(scope="module")
def agent():
    return load_agent("04_human_approval")


@pytest.mark.parametrize(
    "level, target",
    [
        (RiskLevel.LOW, "execute_tool"),
        (RiskLevel.MEDIUM, "additional_validation"),
        (RiskLevel.HIGH, "human_approval"),
        (RiskLevel.INVALID, "block_tool"),
    ],
)
def test_route_by_risk(agent, level, target):
    assert agent.route_by_risk({"risk_level": level}) == target


def test_invalid_call_reaches_block_with_guardrail_reason(agent, ai_tool_call_message):
    msg = ai_tool_call_message(("issue_refund", {"invoice_id": "INV-1", "amount": -5}))
    state = {
        "messages": [msg],
        "risk_level": RiskLevel.INVALID,
        "guardrail_reason": "Refund amount must be greater than zero.",
        "validation_passed": False,
        "validation_reason": "",
        "human_approved": False,
    }
    out = agent.block_tool_node(state)
    assert "greater than zero" in out["messages"][0].content


def test_human_rejection_reason(agent, ai_tool_call_message):
    msg = ai_tool_call_message(("issue_refund", {"invoice_id": "INV-1", "amount": 900}))
    state = {
        "messages": [msg],
        "risk_level": RiskLevel.HIGH,
        "guardrail_reason": "Refund requires human approval.",
        "validation_passed": False,
        "validation_reason": "",
        "human_approved": False,
    }
    out = agent.block_tool_node(state)
    assert "Human approval was not granted" in out["messages"][0].content


@pytest.mark.parametrize("approved, target", [(True, "execute_tool"), (False, "block_tool")])
def test_route_after_human(agent, approved, target):
    assert agent.route_after_human({"human_approved": approved}) == target


def test_only_literal_true_approves(agent, monkeypatch):
    # A truthy resume value such as "no" must not count as approval.
    for resume_value, expected in [(True, True), ("no", False), ("yes", False), (1, False)]:
        monkeypatch.setattr(agent, "interrupt", lambda payload, _v=resume_value: _v)
        state = {
            "tool_name": "issue_refund",
            "tool_args": {"amount": 900},
            "risk_level": RiskLevel.HIGH,
            "guardrail_reason": "",
        }
        assert agent.human_approval_node(state)["human_approved"] is expected
