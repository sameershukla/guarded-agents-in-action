# Memory guardrail: checks a candidate save_memory call BEFORE the value
# is written into long term memory (see MEMORY_STORE in agent.py). This is
# the same detect-then-decide shape as the input guardrail in
# 01_pii_input, but applied to what an agent is allowed to remember about
# a user, not just what it forwards to the model.

import re


# Matches US Social Security Numbers in the form 123-45-6789.
SSN_PATTERN = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"
)

# Matches 13-16 digit sequences (optionally separated by spaces or dashes),
# covering common credit card number lengths/formats.
CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,16}\b"
)

# Matches standard email addresses (local-part@domain.tld).
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# Matches US-style phone numbers, with an optional leading "+1" country
# code and optional parentheses/dashes/dots/spaces as separators.
PHONE_PATTERN = re.compile(
    r"\b(?:\+?1[-.\s]?)?"
    r"(?:\(?\d{3}\)?[-.\s]?)"
    r"\d{3}[-.\s]?\d{4}\b"
)


def detect_sensitive_data(value: str) -> list[str]:
    # Collect the names of every sensitive data category found in the
    # candidate memory value.
    sensitive_types = []

    # Check for an SSN pattern match.
    if SSN_PATTERN.search(value):
        sensitive_types.append("ssn")

    # Check for a credit card number pattern match.
    if CREDIT_CARD_PATTERN.search(value):
        sensitive_types.append("credit_card")

    # Check for an email address pattern match.
    if EMAIL_PATTERN.search(value):
        sensitive_types.append("email")

    # Check for a phone number pattern match.
    if PHONE_PATTERN.search(value):
        sensitive_types.append("phone")

    # Return the list of sensitive category names found (empty if none).
    return sensitive_types


def validate_memory(
    key: str,
    value: str
) -> dict:
    # Only the value is scanned for sensitive data; the key is just a
    # label (e.g. "preferred_language") and isn't expected to carry PII.
    sensitive_types = detect_sensitive_data(
        value
    )

    # Any sensitive data found means this memory must not be persisted,
    # even though the model proposed saving it (fail closed / deny by
    # default, same as the other guardrails in this project).
    if sensitive_types:
        return {
            "allowed": False,
            "reason": "Sensitive data must not be stored.",
            "sensitive_types": sensitive_types,
        }

    # Nothing sensitive was found; safe to write into long term memory.
    return {
        "allowed": True,
        "reason": "Memory is safe to store.",
        "sensitive_types": [],
    }
