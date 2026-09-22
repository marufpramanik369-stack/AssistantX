"""
AssistantX Brain Package
=========================

The intelligence, understanding and decision-making layer of AssistantX.

Pipeline
--------

    User Input
        │
        ▼
    classifier
        │
        ▼
    Intent
        │
        ▼
    context_manager
        │
        ├── pending action
        ├── clarification
        └── anaphora resolution
        │
        ▼
    decision_engine
        │
        ├── EXECUTE
        ├── ASK_CLARIFICATION
        ├── ASK_CONFIRMATION
        ├── CHAT
        └── CANCELLED
        │
        ▼
    core.command_router
        │
        ▼
    response_generator
        │
        ▼
    User Response

Architecture
------------

The ``brain`` package is intentionally separated from:

    - UI / dashboard
    - automation
    - database
    - voice
    - external services

This keeps the AssistantX decision layer modular and allows future
AI providers, plugins and automation modules to be added without
coupling them directly to the UI.

Main Components
---------------

``intent``
    Data structures representing user intent and entities.

``classifier``
    Fast, deterministic, dependency-free intent classification.

``context_manager``
    Maintains short-term conversational state, pending actions,
    clarifications and entity references.

``decision_engine``
    Converts an Intent + Context into an actionable Decision.

``prompt_engine``
    Builds contextual prompts for conversational AI responses.

``response_generator``
    Converts decisions and execution outcomes into user-facing
    responses.

Usage
-----

Simple classification::

    from brain import classifier

    intent = classifier.classify("open chrome")

Decision processing::

    from brain import decision_engine

    decision = decision_engine.process(intent)

Convenience imports::

    from brain import (
        Intent,
        Entity,
        IntentClassifier,
        Decision,
        DecisionAction,
    )

Notes
-----

This module should contain package-level exports only.

Business logic belongs inside the individual brain modules.
"""


from __future__ import annotations

# ============================================================================
# Package Metadata
# ============================================================================

__title__ = "AssistantX Brain"
__description__ = (
    "Understanding, intent classification, context and decision layer "
    "for AssistantX."
)
__version__ = "1.0.0"
__author__ = "AssistantX"
__license__ = "MIT"


# ============================================================================
# Intent Layer
# ============================================================================

# ============================================================================
# Classifier Layer
# ============================================================================
from brain.classifier import (
    IntentClassifier,
    Rule,
    classifier,
    classify,
)

# ============================================================================
# Context Layer
# ============================================================================
from brain.context_manager import (
    ContextManager,
    ContextSnapshot,
    context_manager,
)

# ============================================================================
# Decision Layer
# ============================================================================
from brain.decision_engine import (
    Decision,
    DecisionAction,
    DecisionEngine,
    decision_engine,
)
from brain.intent import (
    Entity,
    Intent,
    SubIntent,
    general_chat_intent,
    unknown_intent,
)

# ============================================================================
# Prompt Layer
# ============================================================================
from brain.prompt_engine import (
    PromptEngine,
    PromptPlan,
    prompt_engine,
)

# ============================================================================
# Response Layer
# ============================================================================
from brain.response_generator import (
    ExecutionOutcome,
    Response,
    ResponseGenerator,
    response_generator,
)

# ============================================================================
# Public API
# ============================================================================

__all__ = [

    # ------------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------------
    "ContextManager",
    "ContextSnapshot",
    "Decision",
    "DecisionAction",
    # ------------------------------------------------------------------------
    # Decision Engine
    # ------------------------------------------------------------------------
    "DecisionEngine",
    "Entity",
    "ExecutionOutcome",
    # ------------------------------------------------------------------------
    # Intent
    # ------------------------------------------------------------------------
    "Intent",
    # ------------------------------------------------------------------------
    # Classifier
    # ------------------------------------------------------------------------
    "IntentClassifier",
    # ------------------------------------------------------------------------
    # Prompt Engine
    # ------------------------------------------------------------------------
    "PromptEngine",
    "PromptPlan",
    "Response",
    # ------------------------------------------------------------------------
    # Response Generator
    # ------------------------------------------------------------------------
    "ResponseGenerator",
    "Rule",
    "SubIntent",
    "__author__",
    "__description__",
    "__license__",
    # ------------------------------------------------------------------------
    # Package metadata
    # ------------------------------------------------------------------------
    "__title__",
    "__version__",
    "classifier",
    "classify",
    "context_manager",
    "decision_engine",
    "general_chat_intent",
    "prompt_engine",
    "response_generator",
    "unknown_intent",
]


# ============================================================================
# Package Diagnostics
# ============================================================================


def diagnostics() -> dict[str, object]:
    """
    Return a lightweight diagnostic snapshot of the brain package.

    This function intentionally avoids executing AI requests or
    automation commands.

    Returns
    -------
    dict
        Package and component availability information.
    """

    components = {
        "intent": Intent is not None,
        "classifier": classifier is not None,
        "context_manager": context_manager is not None,
        "decision_engine": decision_engine is not None,
        "prompt_engine": prompt_engine is not None,
        "response_generator": response_generator is not None,
    }

    return {
        "package": __title__,
        "version": __version__,
        "status": (
            "healthy"
            if all(components.values())
            else "degraded"
        ),
        "components": components,
    }


# ============================================================================
# Convenience Pipeline
# ============================================================================


def understand(text: str) -> Intent:
    """
    Convert raw user input into an Intent.

    This is a lightweight convenience API around the global classifier.

    Example
    -------

        intent = understand("open chrome")
    """

    return classifier.classify(text)


# ============================================================================
# Module Initialization
# ============================================================================


__all__.append("diagnostics")
__all__.append("understand")
