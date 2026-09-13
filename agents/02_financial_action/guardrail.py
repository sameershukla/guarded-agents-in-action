# Action guardrail: validates a tool call BEFORE it is executed.
#
# Unlike an input guardrail (which cleans untrusted user text before it
# reaches the LLM), this is an *action guardrail* — it sits between the
# LLM deciding to call a tool and that tool actually running, and enforces
# business rules on financial actions (currently just refunds) so the
# model can never trigger a disallowed transaction on its own authority.

def validate_financial_action(
    tool_name: str,
    tool_args: dict
) -> dict:
    # Only the issue_refund tool is recognized by this guardrail; any other
    # tool name is rejected outright (fail closed / deny-by-default).
    if tool_name != "issue_refund":
        return {
            "allowed": False,
            "reason": f"Tool {tool_name} is not allowed."
        }

    # Pull the requested refund amount out of the tool's arguments,
    # defaulting to 0 if the model omitted it.
    amount = tool_args.get("amount", 0)

    # Reject zero, negative, or missing refund amounts.
    if amount <= 0:
        return {
            "allowed": False,
            "reason": "Refund amount must be greater than zero."
        }

    # Enforce a hard policy ceiling: refunds over $500 need a human/
    # additional approval step and cannot be auto-approved by the agent.
    if amount > 500:
        return {
            "allowed": False,
            "reason": (
                "Refunds above $500 require additional approval."
            )
        }

    # The requested refund is for the correct tool, has a positive amount,
    # and is within the auto-approval limit, so allow it.
    return {
        "allowed": True,
        "reason": "Refund is within the allowed limit."
    }
