import pytest

from conftest import load_guardrail

g = load_guardrail("07_plan_guardrail")


def lookup(inv="INV-1001"):
    return {"tool": "lookup_invoice", "arguments": {"invoice_id": inv}}


def refund(inv="INV-1001", amount=300):
    return {"tool": "issue_refund", "arguments": {"invoice_id": inv, "amount": amount}}


def notify(msg="done"):
    return {"tool": "send_notification", "arguments": {"message": msg}}


def test_well_formed_plan_is_allowed():
    assert g.validate_plan([lookup(), refund(), notify()])["allowed"] is True


def test_unknown_tool_blocks_plan():
    r = g.validate_plan([{"tool": "delete_db", "arguments": {}}])
    assert r["allowed"] is False
    assert "not allowed" in r["reason"]


def test_missing_required_argument_blocks_plan():
    r = g.validate_plan([{"tool": "issue_refund", "arguments": {"amount": 10}}])
    assert r["allowed"] is False
    assert "requires invoice_id" in r["reason"]


def test_extra_argument_blocks_plan():
    step = {"tool": "lookup_invoice", "arguments": {"invoice_id": "INV-1", "force": True}}
    r = g.validate_plan([step])
    assert r["allowed"] is False
    assert "Unexpected arguments" in r["reason"]


@pytest.mark.parametrize("amount", [0, -10])
def test_non_positive_refund_blocks_plan(amount):
    assert g.validate_plan([lookup(), refund(amount=amount)])["allowed"] is False


def test_refund_above_limit_blocks_plan():
    r = g.validate_plan([lookup(), refund(amount=900)])
    assert r["allowed"] is False
    assert "human approval" in r["reason"]


def test_refund_without_lookup_blocks_plan():
    r = g.validate_plan([refund()])
    assert r["allowed"] is False
    assert "checked before" in r["reason"]


def test_lookup_after_refund_blocks_plan():
    r = g.validate_plan([refund(), lookup()])
    assert r["allowed"] is False
    assert "before the refund" in r["reason"]


def test_two_refunds_block_plan():
    r = g.validate_plan([lookup(), refund(amount=100), refund(amount=100)])
    assert r["allowed"] is False
    assert "more than one refund" in r["reason"]


def test_too_many_steps_block_plan():
    r = g.validate_plan([lookup()] + [notify()] * 5)
    assert r["allowed"] is False
    assert "too many actions" in r["reason"]
