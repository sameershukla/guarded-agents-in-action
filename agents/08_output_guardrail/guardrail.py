# Output guardrail: inspects the model's DRAFT reply BEFORE it is ever
# shown to the user. Every earlier guardrail in this project checked
# something going into the model (input, retrieved documents) or an
# action it wanted to take; this is the last line of defense, catching
# problems in what the model is about to say.

import re


# ---------------------------------------------------------
# PII PATTERNS
# ---------------------------------------------------------

# The model itself might restate or invent PII in its answer; these
# patterns catch that in the output, independent of whatever guarded the
# input on the way in.
SSN_PATTERN = re.compile(
    r"\b\d{3}-\d{2}-\d{4}\b"
)

CREDIT_CARD_PATTERN = re.compile(
    r"\b(?:\d[ -]*?){13,16}\b"
)


# ---------------------------------------------------------
# FINANCIAL ADVICE PATTERNS
# ---------------------------------------------------------

# Phrasing associated with risky, overly definitive financial
# recommendations that a support assistant should not be making.
FINANCIAL_ADVICE_PATTERNS = [

    re.compile(
        r"\bput all\b.*\b(?:money|savings|retirement)\b",
        re.IGNORECASE
    ),

    re.compile(
        r"\binvest all\b",
        re.IGNORECASE
    ),

    re.compile(
        r"\bguaranteed return\b",
        re.IGNORECASE
    ),

    re.compile(
        r"\byou should buy\b",
        re.IGNORECASE
    ),

    re.compile(
        r"\byou should sell\b",
        re.IGNORECASE
    ),
]


# ---------------------------------------------------------
# PII DETECTION
# ---------------------------------------------------------

def detect_output_pii(
    text: str
) -> list[str]:
    # Collect the names of every PII category found in the model's draft
    # response.
    pii_types = []

    if SSN_PATTERN.search(text):
        pii_types.append("ssn")

    if CREDIT_CARD_PATTERN.search(text):
        pii_types.append("credit_card")

    return pii_types


# ---------------------------------------------------------
# FINANCIAL ADVICE DETECTION
# ---------------------------------------------------------

def detect_risky_financial_advice(
    text: str
) -> bool:
    # True if the response matches any known risky-advice phrasing.
    for pattern in FINANCIAL_ADVICE_PATTERNS:

        if pattern.search(text):
            return True

    return False


# ---------------------------------------------------------
# SANITIZE OUTPUT
# ---------------------------------------------------------

def sanitize_output(
    text: str
) -> str:
    # Used only for the "sanitize" decision (PII present, but otherwise
    # fine): redact the sensitive values rather than discarding the
    # whole response.
    text = SSN_PATTERN.sub(
        "[REDACTED_SSN]",
        text
    )

    text = CREDIT_CARD_PATTERN.sub(
        "[REDACTED_CARD]",
        text
    )

    return text


# ---------------------------------------------------------
# COMPLETE OUTPUT VALIDATION
# ---------------------------------------------------------

def validate_output(
    text: str
) -> dict:
    # Three possible outcomes, checked in order of severity: PII can be
    # fixed by redacting it (sanitize), risky advice cannot be fixed by
    # editing so the whole response is replaced (block), and anything
    # else is safe to show as-is (allow).
    pii_types = detect_output_pii(
        text
    )

    if pii_types:

        return {
            "decision": "sanitize",
            "reason": "PII detected in model output.",
            "pii_types": pii_types,
        }

    risky_advice = (
        detect_risky_financial_advice(
            text
        )
    )

    if risky_advice:

        return {
            "decision": "block",
            "reason": (
                "Potentially unsafe financial "
                "advice detected."
            ),
            "pii_types": [],
        }

    return {
        "decision": "allow",
        "reason": "Output passed guardrail checks.",
        "pii_types": [],
    }
