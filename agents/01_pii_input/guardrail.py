# Input guardrail helpers: PII detection and redaction.
# These functions implement the actual guardrail logic used by
# agent.py's pii_guardrail_node/sanitize_node to inspect and clean
# untrusted user input before it reaches the LLM. Each function
# scans/rewrites plain text using regexes for four PII categories:
# Social Security Numbers, credit card numbers, email addresses, and
# phone numbers.

import re  # Standard library regex module used for pattern matching.


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


def detect_pii(text: str) -> list[str]:
    # Collect the names of every PII category found in the text.
    pii_types = []

    # Check for an SSN pattern match.
    if SSN_PATTERN.search(text):
        pii_types.append("ssn")

    # Check for a credit card number pattern match.
    if CREDIT_CARD_PATTERN.search(text):
        pii_types.append("credit_card")

    # Check for an email address pattern match.
    if EMAIL_PATTERN.search(text):
        pii_types.append("email")

    # Check for a phone number pattern match.
    if PHONE_PATTERN.search(text):
        pii_types.append("phone")

    # Return the list of PII category names found (empty if none).
    return pii_types


def sanitize_pii(text: str) -> str:
    # Replace any SSN match with a redaction placeholder.
    text = SSN_PATTERN.sub(
        "[REDACTED_SSN]",
        text
    )

    # Replace any credit card number match with a redaction placeholder.
    text = CREDIT_CARD_PATTERN.sub(
        "[REDACTED_CARD]",
        text
    )

    # Replace any email address match with a redaction placeholder.
    text = EMAIL_PATTERN.sub(
        "[REDACTED_EMAIL]",
        text
    )

    # Replace any phone number match with a redaction placeholder.
    text = PHONE_PATTERN.sub(
        "[REDACTED_PHONE]",
        text
    )

    # Return the fully redacted text.
    return text
