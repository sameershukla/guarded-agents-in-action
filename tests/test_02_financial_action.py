import pytest

from conftest import load_guardrail

g = load_guardrail("02_financial_action")


def test_unknown_tool_is_denied():
    d = g.validate_financial_action("delete_account", {"amount": 10})
    assert d["allowed"] is False
    assert "not allowed" in d["reason"]


@pytest.mark.parametrize("amount", [0, -1, -500.5])
def test_non_positive_amount_is_denied(amount):
    d = g.validate_financial_action("issue_refund", {"amount": amount})
    assert d["allowed"] is False


def test_missing_amount_is_denied():
    d = g.validate_financial_action("issue_refund", {"invoice_id": "INV-1"})
    assert d["allowed"] is False


@pytest.mark.parametrize("amount", [0.01, 100, 499.99, 500])
def test_amount_within_limit_is_allowed(amount):
    d = g.validate_financial_action("issue_refund", {"amount": amount})
    assert d["allowed"] is True


@pytest.mark.parametrize("amount", [500.01, 2000])
def test_amount_above_limit_is_denied(amount):
    d = g.validate_financial_action("issue_refund", {"amount": amount})
    assert d["allowed"] is False
    assert "additional approval" in d["reason"]
