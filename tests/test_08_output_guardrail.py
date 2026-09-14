import pytest

from conftest import load_guardrail

g = load_guardrail("08_output_guardrail")


def test_clean_output_is_allowed():
    r = g.validate_output("Diversification generally reduces risk.")
    assert r["decision"] == "allow"


def test_pii_only_is_sanitized():
    r = g.validate_output("Your SSN on file is 123-45-6789.")
    assert r["decision"] == "sanitize"
    assert r["pii_types"] == ["ssn"]


@pytest.mark.parametrize(
    "text",
    [
        "You should put all your retirement savings into one stock.",
        "Invest all of it in crypto.",
        "This fund has a guaranteed return.",
        "You should buy TSLA now.",
        "you should sell everything",
    ],
)
def test_risky_advice_is_blocked(text):
    assert g.validate_output(text)["decision"] == "block"


def test_risky_advice_with_pii_is_still_blocked():
    # Regression: PII used to be checked first, so a draft with BOTH PII
    # and risky advice was merely sanitized and the advice got through.
    text = "Put all your savings into one stock. Your SSN is 123-45-6789."
    r = g.validate_output(text)
    assert r["decision"] == "block"
    assert r["pii_types"] == ["ssn"]


def test_sanitize_output_redacts():
    out = g.sanitize_output("SSN 123-45-6789 card 4111 1111 1111 1111")
    assert "123-45-6789" not in out
    assert "4111" not in out
