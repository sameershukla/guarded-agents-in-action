from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_guardrail

g = load_guardrail("09_blast_radius")

CUSTOMER = "CUST-101"


def args(amount=100, customer_id=CUSTOMER, invoice_id="INV-1"):
    return {"customer_id": customer_id, "invoice_id": invoice_id, "amount": amount}


# ---------------------------------------------------------
# INDIVIDUAL ACTION CHECK
# ---------------------------------------------------------

def test_valid_refund_passes_individual_check():
    assert g.validate_refund_action("issue_refund", args(500), CUSTOMER)["allowed"] is True


def test_unknown_tool_is_denied():
    assert g.validate_refund_action("delete_account", args(), CUSTOMER)["allowed"] is False


@pytest.mark.parametrize("amount", [0, -1, "100", 500.01])
def test_bad_amount_is_denied(amount):
    assert g.validate_refund_action("issue_refund", args(amount), CUSTOMER)["allowed"] is False


def test_customer_id_mismatch_is_denied():
    # Regression: the model could name a different customer in the tool
    # call than the one the ledger tracks, bypassing the per-customer cap.
    r = g.validate_refund_action("issue_refund", args(customer_id="CUST-999"), CUSTOMER)
    assert r["allowed"] is False
    assert "customer_id" in r["reason"]


def test_missing_customer_id_is_denied():
    a = args()
    del a["customer_id"]
    assert g.validate_refund_action("issue_refund", a, CUSTOMER)["allowed"] is False


# ---------------------------------------------------------
# CUMULATIVE (BLAST RADIUS) CHECK
# ---------------------------------------------------------

def entry(amount, agent_id="agent-001", customer_id=CUSTOMER, minutes_ago=1):
    return {
        "agent_id": agent_id,
        "customer_id": customer_id,
        "invoice_id": "INV-x",
        "amount": amount,
        "timestamp": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    }


def test_empty_ledger_allows():
    r = g.check_blast_radius([], "agent-001", CUSTOMER, 500)
    assert r["allowed"] is True
    assert r["projected_hourly_count"] == 1


def test_customer_daily_limit():
    ledger = [entry(500), entry(400)]
    assert g.check_blast_radius(ledger, "agent-001", CUSTOMER, 100)["allowed"] is True
    r = g.check_blast_radius(ledger, "agent-001", CUSTOMER, 101)
    assert r["allowed"] is False
    assert "Customer daily" in r["reason"]


def test_customer_limit_counts_refunds_from_other_agents():
    ledger = [entry(900, agent_id="agent-002")]
    r = g.check_blast_radius(ledger, "agent-001", CUSTOMER, 200)
    assert r["allowed"] is False
    assert "Customer daily" in r["reason"]


def test_agent_hourly_limit():
    # Different customers so the customer cap doesn't trigger first.
    ledger = [entry(500, customer_id=f"C{i}") for i in range(4)]  # 2000 in the last hour
    r = g.check_blast_radius(ledger, "agent-001", "C-new", 1)
    assert r["allowed"] is False
    assert "hourly refund limit" in r["reason"]


def test_agent_daily_limit_ignores_hour_window():
    # 4900 spread over the day but nothing in the last hour.
    ledger = [entry(490, customer_id=f"C{i}", minutes_ago=120 + i) for i in range(10)]
    assert g.check_blast_radius(ledger, "agent-001", "C-new", 100)["allowed"] is True
    r = g.check_blast_radius(ledger, "agent-001", "C-new", 101)
    assert r["allowed"] is False
    assert "daily refund limit" in r["reason"]


def test_max_refunds_per_hour():
    ledger = [entry(1, customer_id=f"C{i}") for i in range(5)]
    r = g.check_blast_radius(ledger, "agent-001", "C-new", 1)
    assert r["allowed"] is False
    assert "Maximum refunds per hour" in r["reason"]


def test_old_entries_fall_out_of_windows():
    ledger = [entry(500, customer_id=f"C{i}", minutes_ago=60 * 25) for i in range(10)]
    assert g.check_blast_radius(ledger, "agent-001", CUSTOMER, 500)["allowed"] is True
