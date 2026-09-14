# Test helpers for loading the per-agent modules.
#
# Every agent folder has its own `guardrail.py` and `agent.py`, and each
# agent.py does `from guardrail import ...`. Loading them by path (and
# clearing the module cache between loads) keeps the folders isolated so
# tests for agent 03 never accidentally pick up agent 04's guardrail.

import importlib.util
import os
import sys
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).resolve().parent.parent / "agents"

# Constructing ChatAnthropic at import time needs *a* key present, but it
# never makes a network call, so a dummy value is enough for unit tests.
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")


def _load(folder: str, filename: str):
    path = AGENTS_DIR / folder / filename
    module_name = f"{folder}_{path.stem}"

    # Make `from guardrail import ...` inside agent.py resolve to THIS
    # folder's guardrail, not one cached from another agent's test.
    sys.modules.pop("guardrail", None)
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
        sys.modules.pop("guardrail", None)

    return module


def load_guardrail(folder: str):
    return _load(folder, "guardrail.py")


def load_agent(folder: str):
    return _load(folder, "agent.py")


@pytest.fixture
def ai_tool_call_message():
    # Builds the AIMessage a model would return when it requests one or
    # more tool calls, so node functions can be exercised without a model.
    from langchain_core.messages import AIMessage

    def _make(*calls):
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": name,
                    "args": args,
                    "id": f"call-{index}",
                }
                for index, (name, args) in enumerate(calls)
            ],
        )

    return _make
