# Guarded Agents in Action

This repository is a practical learning project for building AI agents with guardrails.

The goal is to learn agent development and guardrail development together.

We will use LangGraph to build the agents and Claude Sonnet 4 as the language model.

## What We Will Learn

We will build agents step by step.

Each agent will introduce a new agent pattern and a new guardrail concept.

The main guardrail areas are:

1. Input guardrails
2. Action guardrails
3. Financial risk controls
4. Human approval
5. Memory guardrails
6. Retrieval guardrails
7. Plan validation
8. Output guardrails
9. Blast radius controls

## Learning Path

### Agent 01

PII Input Guardrail

Learn:

1. LangGraph State
2. Nodes
3. Edges
4. Input guardrails
5. PII detection
6. PII sanitization

### Agent 02

Financial Action Guardrail

Learn:

1. Tools
2. ReAct
3. Tool calls
4. Action validation
5. Financial limits

### Agent 03

Risk Routing

Learn:

1. Conditional routing
2. Risk levels
3. Low risk actions
4. Medium risk actions
5. High risk actions

### Agent 04

Human Approval

Learn:

1. Human in the loop
2. Pause
3. Approval
4. Resume

### Agent 05

Memory Guardrail

Learn how to stop sensitive information from entering long term memory.

### Agent 06

Retrieval Guardrail

Learn:

1. Retrieval security
2. Access control
3. Indirect prompt injection
4. Document trust

### Agent 07

Plan Guardrail

Learn how to validate an agent plan before allowing it to execute actions.

### Agent 08

Output Guardrail

Learn how to inspect the final response before returning it to the user.

### Agent 09

Blast Radius Guardrail

Learn how to control cumulative agent behavior.

For example, one refund may be safe, but many refunds together may create a large financial risk.

## Overall Architecture

The final system will gradually move toward this architecture:

```text
User
  |
  v
Input Guardrail
  |
  v
Agent
  |
  v
Action Guardrail
  |
  v
Tool
  |
  v
Agent
  |
  v
Output Guardrail
  |
  v
User
```

Other controls such as risk scoring, approval, memory protection, retrieval validation, and blast radius checks will be added as the project grows.

## Main Design Idea

The model can propose an action.

The guardrail decides whether that action is allowed.

The tool performs the action only after validation.

For important financial operations, deterministic rules and human approval should be used instead of trusting the model alone.

## Technology

Python

LangGraph

LangChain

Claude Sonnet 4

Pydantic

## Repository Structure

```text
guarded_agents_in_action/
|
|__ README.md
|__ requirements.txt
|
|__ agents/
    |
    |__ 01_pii_input/
    |   |__ agent.py
    |   |__ guardrail.py
    |   |__ README.md
    |
    |__ 02_financial_action/
    |
    |__ 03_risk_routing/
    |
    |__ 04_human_approval/
    |
    |__ 05_memory_guardrail/
    |
    |__ 06_retrieval_guardrail/
    |
    |__ 07_plan_guardrail/
    |
    |__ 08_output_guardrail/
    |
    |__ 09_blast_radius/
```

## Setup

Install the required packages.

```bash
pip install -r requirements.txt
```

Add the Anthropic API key to the environment.

```text
ANTHROPIC_API_KEY=your_key
```

## Model

The agents use Claude Sonnet 4.

```python
from langchain_anthropic import ChatAnthropic

model = ChatAnthropic(
    model="claude-sonnet-4-20250514"
)
```

## Goal

The goal of this repository is not only to learn LangGraph.

The goal is to learn how to build agents that can operate safely in real systems.

We will especially focus on PII and financial use cases.