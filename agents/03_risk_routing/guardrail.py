# Risk-routing guardrail: classifies a proposed tool call into a risk
# tier (LOW / MEDIUM / HIGH) instead of a simple allow/deny, so the agent
# graph can route each tier through a different level of scrutiny —
# auto-execute, extra validation, or an outright block.

from enum import Enum


class RiskLevel(str, Enum):
    # Small, well-understood refunds: safe to auto-execute.
    LOW = "low"
    # Larger refunds: allowed, but only after an extra validation check.
    MEDIUM = "medium"
    # Disallowed tools, invalid amounts, or refunds large enough to need a
    # human: never auto-executed.
    HIGH = "high"


def assess_financial_risk(
    tool_name: str,
    tool_args: dict
) -> dict:
    # Any tool other than issue_refund is treated as high risk and
    # rejected outright (fail closed / deny-by-default).
    if tool_name != "issue_refund":
        return {
            "risk_level": RiskLevel.HIGH,
            "reason": f"Tool {tool_name} is not allowed."
        }

    # Pull the requested refund amount, defaulting to 0 if missing.
    amount = tool_args.get("amount", 0)

    # Zero, negative, or missing amounts are invalid and high risk.
    if amount <= 0:
        return {
            "risk_level": RiskLevel.HIGH,
            "reason": "Refund amount must be greater than zero."
        }

    # Small refunds (<= $100) are low risk and can be auto-approved.
    if amount <= 100:
        return {
            "risk_level": RiskLevel.LOW,
            "reason": "Refund is within the low risk limit."
        }

    # Mid-size refunds ($100-$500) are medium risk: allowed, but only
    # after passing an additional validation step.
    if amount <= 500:
        return {
            "risk_level": RiskLevel.MEDIUM,
            "reason": "Refund requires additional validation."
        }

    # Anything above $500 is high risk and requires human approval —
    # the agent cannot execute it on its own.
    return {
        "risk_level": RiskLevel.HIGH,
        "reason": "Refund requires human approval."
    }


def perform_additional_validation(
    tool_args: dict
) -> dict:
    # Extra scrutiny applied only to MEDIUM-risk refunds: sanity-check the
    # invoice ID format before allowing execution.
    invoice_id = tool_args.get("invoice_id", "")

    # An empty/missing invoice ID can't be validated.
    if not invoice_id:
        return {
            "valid": False,
            "reason": "Invoice ID is missing."
        }

    # Enforce the expected invoice ID naming convention (e.g. "INV-1001").
    if not invoice_id.startswith("INV"):
        return {
            "valid": False,
            "reason": "Invoice ID format is invalid."
        }

    # Invoice ID is present and well-formed; validation passes.
    return {
        "valid": True,
        "reason": "Additional validation passed."
    }
