import pytest

from conftest import load_guardrail

g = load_guardrail("01_pii_input")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("My SSN is 123-45-6789.", ["ssn"]),
        ("Call me at 555-123-4567", ["phone"]),
        ("Call me at (555) 123-4567", ["phone"]),
        ("Card 4111 1111 1111 1111", ["credit_card"]),
        ("Email me at a@b.co", ["email"]),
        ("Why was my payment declined?", []),
        ("Meeting on 2024-01-15 at 10am", []),
    ],
)
def test_detect_pii(text, expected):
    assert g.detect_pii(text) == expected


def test_detect_pii_reports_every_type_found():
    text = "SSN 123-45-6789, email a@b.co, phone 555-123-4567"
    assert g.detect_pii(text) == ["ssn", "email", "phone"]


def test_sanitize_redacts_all_pii():
    text = "SSN 123-45-6789, card 4111 1111 1111 1111, mail a@b.co, tel 555-123-4567"
    out = g.sanitize_pii(text)
    assert "123-45-6789" not in out
    assert "4111" not in out
    assert "a@b.co" not in out
    assert "555-123-4567" not in out
    assert "[REDACTED_SSN]" in out
    assert "[REDACTED_CARD]" in out
    assert "[REDACTED_EMAIL]" in out
    assert "[REDACTED_PHONE]" in out


def test_sanitize_leaves_clean_text_untouched():
    text = "Why was my payment declined?"
    assert g.sanitize_pii(text) == text
