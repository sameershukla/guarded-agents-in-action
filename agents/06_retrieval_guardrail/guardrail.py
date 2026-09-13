# Retrieval guardrail: checks a document BEFORE its content is placed
# into the model's context. A RAG (retrieval augmented generation) system
# pulls documents from some external store and feeds them to the model as
# trusted context, but "trusted" is not automatic. This guardrail enforces
# two separate concerns: does this user's role even permit reading this
# document (access control), and does the document's own text try to
# hijack the model's instructions (indirect prompt injection).

import re


# ---------------------------------------------------------
# INDIRECT PROMPT INJECTION PATTERNS
# ---------------------------------------------------------

# Phrases commonly used to try to override a system prompt or exfiltrate
# secrets from inside retrieved content (rather than from the user
# directly) -- this is what makes the attack "indirect".
INJECTION_PATTERNS = [
    re.compile(
        r"ignore\s+(all\s+)?previous\s+instructions",
        re.IGNORECASE
    ),
    re.compile(
        r"ignore\s+(all\s+)?prior\s+instructions",
        re.IGNORECASE
    ),
    re.compile(
        r"reveal\s+.*(?:password|account|ssn|secret)",
        re.IGNORECASE
    ),
    re.compile(
        r"send\s+.*(?:password|api\s*key|secret|credentials?)"
        r".*\s+to\s+",
        re.IGNORECASE
    ),
]


# ---------------------------------------------------------
# ACCESS CONTROL
# ---------------------------------------------------------

def check_access(
    document: dict,
    user_role: str
) -> dict:
    # Every document declares which roles are allowed to see it in its
    # metadata; default to nobody if that list is missing.
    allowed_roles = document[
        "metadata"
    ].get(
        "allowed_roles",
        []
    )

    # Deny by default: a role not explicitly listed cannot read this
    # document, regardless of whether its content would otherwise be safe.
    if user_role not in allowed_roles:

        return {
            "allowed": False,
            "reason": (
                f"Role '{user_role}' is not "
                "authorized for this document."
            )
        }

    return {
        "allowed": True,
        "reason": "Access allowed."
    }


# ---------------------------------------------------------
# INDIRECT PROMPT INJECTION
# ---------------------------------------------------------

def detect_indirect_injection(
    text: str
) -> dict:
    # Scan the document's own content for known injection phrasing. This
    # matters because retrieved text is normally treated as trustworthy
    # reference material, so a malicious phrase hidden inside a document
    # could otherwise be read by the model as an instruction.
    for pattern in INJECTION_PATTERNS:

        if pattern.search(text):

            return {
                "safe": False,
                "reason": (
                    "Possible indirect prompt "
                    "injection detected."
                )
            }

    return {
        "safe": True,
        "reason": "No injection detected."
    }


# ---------------------------------------------------------
# COMPLETE DOCUMENT VALIDATION
# ---------------------------------------------------------

def validate_document(
    document: dict,
    user_role: str
) -> dict:
    # Access control is checked first: an unauthorized document is
    # rejected before its content is even scanned for injection attempts.
    access_result = check_access(
        document,
        user_role
    )

    if not access_result["allowed"]:

        return {
            "safe": False,
            "reason": access_result["reason"]
        }

    # Only a document the user is allowed to see gets its content
    # inspected for indirect prompt injection.
    injection_result = detect_indirect_injection(
        document["content"]
    )

    if not injection_result["safe"]:

        return {
            "safe": False,
            "reason": injection_result["reason"]
        }

    # Passed both checks: safe to include in the model's context.
    return {
        "safe": True,
        "reason": "Document passed retrieval guardrails."
    }
