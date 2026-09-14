import pytest

from conftest import load_guardrail

g = load_guardrail("03_risk_routing")
RiskLevel = g.RiskLevel


def test_unknown_tool_is_high_risk():
    d = g.assess_financial_risk("delete_account", {"amount": 10})
    assert d["risk_level"] == RiskLevel.HIGH


@pytest.mark.parametrize("amount", [0, -1])
def test_non_positive_amount_is_high_risk(amount):
    d = g.assess_financial_risk("issue_refund", {"amount": amount})
    assert d["risk_level"] == RiskLevel.HIGH


@pytest.mark.parametrize(
    "amount, level",
    [
        (0.01, RiskLevel.LOW),
        (100, RiskLevel.LOW),
        (100.01, RiskLevel.MEDIUM),
        (500, RiskLevel.MEDIUM),
        (500.01, RiskLevel.HIGH),
        (900, RiskLevel.HIGH),
    ],
)
def test_amount_tiers(amount, level):
    d = g.assess_financial_risk("issue_refund", {"amount": amount})
    assert d["risk_level"] == level


def test_additional_validation_accepts_well_formed_invoice():
    assert g.perform_additional_validation({"invoice_id": "INV-1001"})["valid"] is True


@pytest.mark.parametrize("args", [{}, {"invoice_id": ""}, {"invoice_id": "ABC-1"}])
def test_additional_validation_rejects_bad_invoice(args):
    assert g.perform_additional_validation(args)["valid"] is False
