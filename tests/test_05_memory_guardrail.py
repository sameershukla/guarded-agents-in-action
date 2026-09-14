import pytest

from conftest import load_guardrail

g = load_guardrail("05_memory_guardrail")


def test_safe_memory_is_allowed():
    d = g.validate_memory("preferred_language", "English")
    assert d["allowed"] is True
    assert d["sensitive_types"] == []


@pytest.mark.parametrize(
    "value, kind",
    [
        ("123-45-6789", "ssn"),
        ("4111 1111 1111 1111", "credit_card"),
        ("a@b.co", "email"),
        ("555-123-4567", "phone"),
    ],
)
def test_sensitive_value_is_rejected(value, kind):
    d = g.validate_memory("note", f"my detail is {value}")
    assert d["allowed"] is False
    assert kind in d["sensitive_types"]
