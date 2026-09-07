"""
brain
=====
The "understanding + decision" package for AssistantX.

Pipeline overview:

    raw text
        │
        ▼
    brain.classifier.classify()        -> Intent
        │
        ▼
    brain.context_manager               (anaphora, pending state)
        │
        ▼
    brain.decision_engine.process()     -> Decision (execute/clarify/confirm/chat)
        │
        ├── if EXECUTE ──► core.command_router (outside this package)
        │
        ▼
    brain.response_generator.generate() -> Response (final user-facing text)

brain.prompt_engine is used internally by response_generator for the
CHAT path, gathering memory context and talking to ai.conversation.
"""

from __future__ import annotations

from brain.classifier import IntentClassifier, Rule, classifier
from brain.context_manager import ContextManager, ContextSnapshot, context_manager
from brain.decision_engine import Decision, DecisionAction, DecisionEngine, decision_engine
from brain.intent import Entity, Intent, SubIntent, general_chat_intent, unknown_intent
from brain.prompt_engine import PromptEngine, PromptPlan, prompt_engine
from brain.response_generator import ExecutionOutcome, Response, ResponseGenerator, response_generator

__all__ = [
    # intent
    "Intent",
    "Entity",
    "SubIntent",
    "unknown_intent",
    "general_chat_intent",
    # classifier
    "IntentClassifier",
    "Rule",
    "classifier",
    # context
    "ContextManager",
    "ContextSnapshot",
    "context_manager",
    # decision engine
    "DecisionEngine",
    "Decision",
    "DecisionAction",
    "decision_engine",
    # prompt engine
    "PromptEngine",
    "PromptPlan",
    "prompt_engine",
    # response generator
    "ResponseGenerator",
    "Response",
    "ExecutionOutcome",
    "response_generator",
]
