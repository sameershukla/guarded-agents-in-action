# Blast radius guardrail: limits the CUMULATIVE effect of many individually
# approved actions, not just any single one. Every earlier guardrail in
# this project judged one action in isolation -- a $200 refund looks fine
# on its own. But a hundred $200 refunds from the same agent inside an
# hour is a very different, much larger risk, even though every one of
# them would pass an individual check. This module adds that second,
# cumulative layer on top of the individual check.

from datetime import datetime, timedelta, timezone


SINGLE_REFUND_LIMIT = 500

CUSTOMER_DAILY_LIMIT = 1000

AGENT_HOURLY_LIMIT = 2000

AGENT_DAILY_LIMIT = 5000

MAX_REFUNDS_PER_HOUR = 5


def validate_refund_action(
    tool_name: str,
    tool_args: dict
) -> dict:
    # The same kind of single-action check seen in 02_financial_action:
    # judges this one proposed refund purely on its own terms, with no
    # knowledge of any other refund that happened before or after it.
    if tool_name != "issue_refund":
        return {
            "allowed": False,
            "reason": f"Tool {tool_name} is not allowed."
        }

    amount = tool_args.get("amount", 0)

    if amount <= 0:
        return {
            "allowed": False,
            "reason": "Refund amount must be greater than zero."
        }

    if amount > SINGLE_REFUND_LIMIT:
        return {
            "allowed": False,
            "reason": (
                f"Single refund limit is "
                f"${SINGLE_REFUND_LIMIT}."
            )
        }

    return {
        "allowed": True,
        "reason": "Refund passed individual action checks."
    }


def check_blast_radius(
    ledger: list[dict],
    agent_id: str,
    customer_id: str,
    proposed_amount: float
) -> dict:
    # Only reached for actions that already passed the individual check
    # above. This function asks a different question: if this refund also
    # goes through, does any cumulative limit get exceeded across the
    # agent's recent history or this customer's recent history?
    now = datetime.now(timezone.utc)

    one_hour_ago = now - timedelta(hours=1)

    one_day_ago = now - timedelta(days=1)


    # Every refund this agent has issued in the last hour / day, and
    # every refund this customer has received in the last day, pulled
    # from the shared ledger of past actions.
    agent_hourly_actions = [
        item
        for item in ledger
        if item["agent_id"] == agent_id
        and item["timestamp"] >= one_hour_ago
    ]


    agent_daily_actions = [
        item
        for item in ledger
        if item["agent_id"] == agent_id
        and item["timestamp"] >= one_day_ago
    ]


    customer_daily_actions = [
        item
        for item in ledger
        if item["customer_id"] == customer_id
        and item["timestamp"] >= one_day_ago
    ]


    agent_hourly_total = sum(
        item["amount"]
        for item in agent_hourly_actions
    )


    agent_daily_total = sum(
        item["amount"]
        for item in agent_daily_actions
    )


    customer_daily_total = sum(
        item["amount"]
        for item in customer_daily_actions
    )


    # Check the limits against what the totals WOULD become if this
    # proposed refund were also allowed through, not just what they are now.
    projected_agent_hourly_total = (
        agent_hourly_total
        + proposed_amount
    )


    projected_agent_daily_total = (
        agent_daily_total
        + proposed_amount
    )


    projected_customer_daily_total = (
        customer_daily_total
        + proposed_amount
    )


    projected_hourly_count = (
        len(agent_hourly_actions)
        + 1
    )


    # A single customer should not be able to accumulate more refunds in
    # a day than this limit, regardless of which agent issued them.
    if projected_customer_daily_total > CUSTOMER_DAILY_LIMIT:

        return {
            "allowed": False,
            "reason": (
                "Customer daily refund limit "
                "would be exceeded."
            )
        }


    # Caps how much total refund volume a single agent can push through
    # in an hour, limiting the damage from a compromised or malfunctioning
    # agent acting quickly.
    if projected_agent_hourly_total > AGENT_HOURLY_LIMIT:

        return {
            "allowed": False,
            "reason": (
                "Agent hourly refund limit "
                "would be exceeded."
            )
        }


    # A longer-window version of the same idea, capping total daily
    # volume per agent even if it stays under the hourly limit.
    if projected_agent_daily_total > AGENT_DAILY_LIMIT:

        return {
            "allowed": False,
            "reason": (
                "Agent daily refund limit "
                "would be exceeded."
            )
        }


    # Caps the sheer number of refunds an agent can issue in an hour,
    # independent of their dollar amounts -- catches a rapid burst of
    # small refunds that would otherwise stay under the dollar limits.
    if projected_hourly_count > MAX_REFUNDS_PER_HOUR:

        return {
            "allowed": False,
            "reason": (
                "Maximum refunds per hour "
                "would be exceeded."
            )
        }


    # None of the cumulative limits would be exceeded; safe to add this
    # refund to the ledger and execute it.
    return {
        "allowed": True,
        "reason": "Blast radius checks passed.",
        "projected_agent_hourly_total":
            projected_agent_hourly_total,
        "projected_agent_daily_total":
            projected_agent_daily_total,
        "projected_customer_daily_total":
            projected_customer_daily_total,
        "projected_hourly_count":
            projected_hourly_count,
    }
