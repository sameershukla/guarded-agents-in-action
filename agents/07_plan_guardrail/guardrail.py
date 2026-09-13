# Plan guardrail: validates an entire multi-step plan BEFORE any step of
# it is executed. Earlier guardrails in this project (02, 03, 04) checked
# one proposed tool call at a time; this one looks at the whole sequence
# of tool calls together, since some problems only show up across steps
# -- doing a refund without first looking up the invoice, or a plan that
# tries to issue two refunds at once.

ALLOWED_TOOLS = {
    "lookup_invoice",
    "issue_refund",
    "send_notification",
}


def validate_tool_arguments(
    tool_name: str,
    arguments: dict
) -> dict:
    # Each tool has its own required arguments and its own allowed set of
    # argument names; anything outside that set is rejected, since a
    # model-supplied extra argument (or a typo) is a sign something is
    # off with the plan.
    if tool_name == "lookup_invoice":

        if "invoice_id" not in arguments:
            return {
                "valid": False,
                "reason": (
                    "lookup_invoice requires invoice_id."
                )
            }

        allowed_keys = {
            "invoice_id"
        }

    elif tool_name == "issue_refund":

        if "invoice_id" not in arguments:
            return {
                "valid": False,
                "reason": (
                    "issue_refund requires invoice_id."
                )
            }

        if "amount" not in arguments:
            return {
                "valid": False,
                "reason": (
                    "issue_refund requires amount."
                )
            }

        allowed_keys = {
            "invoice_id",
            "amount",
        }

    elif tool_name == "send_notification":

        if "message" not in arguments:
            return {
                "valid": False,
                "reason": (
                    "send_notification requires message."
                )
            }

        allowed_keys = {
            "message"
        }

    else:
        # Not one of the tools this plan guardrail knows about at all.
        return {
            "valid": False,
            "reason": (
                f"Unknown tool: {tool_name}"
            )
        }

    # Any argument name outside the allowed set for this tool is rejected,
    # even if the required arguments are all present.
    extra_keys = (
        set(arguments.keys())
        - allowed_keys
    )

    if extra_keys:

        return {
            "valid": False,
            "reason": (
                f"Unexpected arguments for "
                f"{tool_name}: "
                f"{sorted(extra_keys)}"
            )
        }

    return {
        "valid": True,
        "reason": "Tool arguments are valid."
    }


def validate_plan(
    plan: list[dict]
) -> dict:
    # Walk the plan step by step, checking each tool call individually
    # first (allow-list membership, then argument shape/values).
    refund_count = 0

    for step in plan:

        tool_name = step["tool"]

        arguments = step.get(
            "arguments",
            {}
        )

        # Deny by default: any tool outside the allow-list stops the
        # whole plan, not just that one step.
        if tool_name not in ALLOWED_TOOLS:

            return {
                "allowed": False,
                "reason": (
                    f"Tool {tool_name} "
                    "is not allowed."
                )
            }

        argument_check = (
            validate_tool_arguments(
                tool_name,
                arguments
            )
        )

        if not argument_check["valid"]:

            return {
                "allowed": False,
                "reason": (
                    argument_check["reason"]
                )
            }

        # Reuse the same amount rule as the simpler financial guardrails:
        # zero/negative amounts are invalid, and anything above $500
        # needs a human, so it can't be part of an auto-executed plan.
        if tool_name == "issue_refund":

            refund_count += 1

            amount = arguments[
                "amount"
            ]

            if amount <= 0:

                return {
                    "allowed": False,
                    "reason": (
                        "Refund amount must "
                        "be greater than zero."
                    )
                }

            if amount > 500:

                return {
                    "allowed": False,
                    "reason": (
                        "Refund above $500 "
                        "requires human approval."
                    )
                }

    # Cross-step rule: a single plan should never bundle more than one
    # refund, to limit how much damage one bad plan can do.
    if refund_count > 1:

        return {
            "allowed": False,
            "reason": (
                "The plan contains more "
                "than one refund action."
            )
        }

    # Cross-step rule: cap the overall size of a plan, regardless of
    # which tools it uses.
    if len(plan) > 5:

        return {
            "allowed": False,
            "reason": (
                "The plan contains too many actions."
            )
        }

    tool_names = [
        step["tool"]
        for step in plan
    ]

    # Cross-step rule: a refund must never be issued blind -- the plan
    # must also look up the invoice first, and that lookup must come
    # before the refund step, not after it.
    if "issue_refund" in tool_names:

        if "lookup_invoice" not in tool_names:

            return {
                "allowed": False,
                "reason": (
                    "Invoice must be checked "
                    "before issuing a refund."
                )
            }

        refund_index = (
            tool_names.index(
                "issue_refund"
            )
        )

        lookup_index = (
            tool_names.index(
                "lookup_invoice"
            )
        )

        if lookup_index > refund_index:

            return {
                "allowed": False,
                "reason": (
                    "Invoice lookup must happen "
                    "before the refund."
                )
            }

    # The plan passed every per-step and cross-step check.
    return {
        "allowed": True,
        "reason": "Plan passed all checks."
    }
