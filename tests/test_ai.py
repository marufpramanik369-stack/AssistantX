"""
AssistantX - AI Provider Tests
================================

Unit tests for the AssistantX AI layer.

Coverage:
    - ChatMessage
    - CompletionResult
    - AIProviderBase contract
    - Provider success/failure handling
    - Provider fallback behavior
    - Streaming behavior
    - Provider factory
    - Invalid provider handling
    - Conversation message validation

These tests are intentionally network-free. External AI providers such as
Gemini, Ollama, or local models should be mocked during unit testing.

Run:
    python -m pytest tests/test_ai.py -v

Run with coverage:
    python -m pytest tests/test_ai.py --cov=ai --cov-report=term-missing
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import Any, Final
from unittest.mock import MagicMock, patch

import pytest

import ai.provider

# ============================================================================
# Test Constants
# ============================================================================

TEST_PROVIDER: Final[str] = "test"
TEST_MODEL: Final[str] = "test-model"
TEST_PROMPT: Final[str] = "Hello AssistantX"
TEST_RESPONSE: Final[str] = "Hello! How can I help you?"
TEST_ERROR: Final[str] = "Test provider error"


# ============================================================================
# Mock Provider
# ============================================================================

class MockAIProvider(ai.provider.AIProviderBase):
    """
    Deterministic mock AI provider used for isolated unit tests.

    This provider never accesses the network, filesystem, external APIs,
    or any other external service. It is intentionally lightweight so
    provider behavior can be tested independently from real AI backends.
    """

    name = TEST_PROVIDER
    provider_name = TEST_PROVIDER
    model = TEST_MODEL
    model_name = TEST_MODEL
    default_model = TEST_MODEL

    def __init__(
        self,
        *,
        response: str = TEST_RESPONSE,
        should_fail: bool = False,
        error_message: str = TEST_ERROR,
        **_kwargs: Any,
    ) -> None:
        """Initialize the mock provider."""
        super().__init__(model=TEST_MODEL, **_kwargs)

        self.response = response
        self.should_fail = should_fail
        self.error_message = error_message
        self.generate_calls = 0

    def _call_api(
        self,
        _messages: Sequence[ai.provider.ChatMessage | Mapping[str, Any]],
        **_kwargs: Any,
    ) -> ai.provider.CompletionResult:
        """Generate a deterministic mock completion for base provider logic."""
        self.generate_calls += 1

        if self.should_fail:
            raise RuntimeError(self.error_message)

        return ai.provider.CompletionResult(
            text=self.response,
            provider=self.name,
            model=self.model,
            latency_seconds=0.01,
            tokens_used=10,
            finish_reason="stop",
            success=True,
        )

    def _generate(
        self,
        messages: list[ai.provider.ChatMessage],
        **kwargs: Any,
    ) -> ai.provider.CompletionResult:
        """Alias for backward compatibility with tests expecting _generate."""
        return self._call_api(messages, **kwargs)

    def is_available(self) -> bool:
        """Report whether the mock provider is available."""
        return True


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def provider() -> MockAIProvider:
    """Return a healthy mock AI provider."""
    return MockAIProvider()


@pytest.fixture
def failing_provider() -> MockAIProvider:
    """Return a provider that always fails."""
    return MockAIProvider(
        should_fail=True,
        error_message=TEST_ERROR,
    )


@pytest.fixture
def user_message() -> ai.provider.ChatMessage:
    """Return a standard user message."""
    return ai.provider.ChatMessage(
        role=ai.provider.Role.USER,
        content=TEST_PROMPT,
    )


# ============================================================================
# ChatMessage Tests
# ============================================================================


class TestChatMessage:
    """Tests for ChatMessage."""

    def test_create_user_message(self) -> None:
        """A user message should preserve role and content."""
        message = ai.provider.ChatMessage(
            role=ai.provider.Role.USER,
            content=TEST_PROMPT,
        )

        assert message.role == ai.provider.Role.USER
        assert message.content == TEST_PROMPT

    def test_create_assistant_message(self) -> None:
        """An assistant message should preserve its role."""
        message = ai.provider.ChatMessage(
            role=ai.provider.Role.ASSISTANT,
            content=TEST_RESPONSE,
        )

        assert message.role == ai.provider.Role.ASSISTANT
        assert message.content == TEST_RESPONSE

    def test_create_system_message(self) -> None:
        """A system message should be supported."""
        message = ai.provider.ChatMessage(
            role=ai.provider.Role.SYSTEM,
            content="You are AssistantX.",
        )

        assert message.role == ai.provider.Role.SYSTEM

    def test_message_content_is_string(self) -> None:
        """Message content should be textual."""
        message = ai.provider.ChatMessage(
            role=ai.provider.Role.USER,
            content=TEST_PROMPT,
        )

        assert isinstance(message.content, str)
        assert message.content

    def test_message_has_timestamp(self) -> None:
        """Messages should expose a timestamp."""
        message = ai.provider.ChatMessage(
            role=ai.provider.Role.USER,
            content=TEST_PROMPT,
        )

        assert message.timestamp is not None


# ============================================================================
# CompletionResult Tests
# ============================================================================


class TestCompletionResult:
    """Tests for CompletionResult."""

    def test_successful_result(self) -> None:
        """A successful completion should report ok=True."""
        result = ai.provider.CompletionResult(
            text=TEST_RESPONSE,
            provider=TEST_PROVIDER,
            model=TEST_MODEL,
            tokens_used=10,
            finish_reason="stop",
        )

        assert result.ok is True
        assert result.text == TEST_RESPONSE
        assert result.provider == TEST_PROVIDER
        assert result.model == TEST_MODEL

    def test_failed_result(self) -> None:
        """A result containing an error should report ok=False."""
        result = ai.provider.CompletionResult(
            text="",
            provider=TEST_PROVIDER,
            model=TEST_MODEL,
            error=TEST_ERROR,
        )

        assert result.ok is False
        assert result.error == TEST_ERROR

    def test_result_token_count(self) -> None:
        """Token usage should be preserved."""
        result = ai.provider.CompletionResult(
            text=TEST_RESPONSE,
            provider=TEST_PROVIDER,
            model=TEST_MODEL,
            tokens_used=42,
        )

        assert result.tokens_used == 42

    def test_finish_reason_is_preserved(self) -> None:
        """The provider finish reason should be preserved."""
        result = ai.provider.CompletionResult(
            text=TEST_RESPONSE,
            provider=TEST_PROVIDER,
            model=TEST_MODEL,
            finish_reason="stop",
        )

        assert result.finish_reason == "stop"


# ============================================================================
# Provider Tests
# ============================================================================


class TestAIProvider:
    """Tests for the common AI provider contract."""

    def test_provider_can_generate(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """A healthy provider should generate a response."""
        result = provider.generate(
            [user_message],
        )

        assert isinstance(result, ai.provider.CompletionResult)
        assert result.ok is True
        assert result.text == TEST_RESPONSE

    def test_provider_name_is_preserved(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Provider metadata should be available in the result."""
        result = provider.generate(
            [user_message],
        )

        assert result.provider == TEST_PROVIDER

    def test_model_name_is_preserved(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Model metadata should be available in the result."""
        result = provider.generate(
            [user_message],
        )

        assert result.model == TEST_MODEL

    def test_provider_records_generation(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """The mock provider should receive the generation request."""
        provider.generate([user_message])

        assert provider.generate_calls == 1

    def test_multiple_requests(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Multiple generation requests should be handled independently."""
        provider.generate([user_message])
        provider.generate([user_message])
        provider.generate([user_message])

        assert provider.generate_calls == 3


# ============================================================================
# Failure & Error Handling
# ============================================================================


class TestAIProviderErrors:
    """Tests for provider error behavior."""

    def test_provider_failure_returns_unsuccessful_result(
        self,
        failing_provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Provider failures should be normalized by the base provider."""
        result = failing_provider.generate(
            [user_message],
        )

        assert isinstance(result, ai.provider.CompletionResult)
        assert result.ok is False

    def test_provider_failure_contains_error(
        self,
        failing_provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """A failed completion should contain an error message."""
        result = failing_provider.generate(
            [user_message],
        )

        assert result.error is not None
        assert TEST_ERROR in str(result.error)

    def test_failed_result_has_no_successful_text(
        self,
        failing_provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """A failed generation should not be treated as successful output."""
        result = failing_provider.generate(
            [user_message],
        )

        assert result.ok is False


# ============================================================================
# Streaming Tests
# ============================================================================


class TestAIStreaming:
    """Tests for provider streaming behavior."""

    def test_default_stream_returns_completion(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """
        The base provider stream implementation should yield the generated
        completion when no specialized streaming implementation exists.
        """
        chunks = list(
            provider.stream(
                [user_message],
            )
        )

        assert chunks
        assert isinstance(chunks[0], ai.provider.CompletionResult)
        assert chunks[0].text == TEST_RESPONSE

    def test_stream_preserves_provider_metadata(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Streaming fallback should preserve provider metadata."""
        chunks = list(
            provider.stream(
                [user_message],
            )
        )

        result = chunks[0]

        assert result.provider == TEST_PROVIDER
        assert result.model == TEST_MODEL


# ============================================================================
# Prompt / Message Handling
# ============================================================================


class TestMessageHandling:
    """Tests for message collections passed to providers."""

    def test_multiple_messages(
        self,
        provider: MockAIProvider,
    ) -> None:
        """Providers should accept conversation history."""
        messages = [
            ai.provider.ChatMessage(
                role=ai.provider.Role.SYSTEM,
                content="You are AssistantX.",
            ),
            ai.provider.ChatMessage(
                role=ai.provider.Role.USER,
                content="Hello.",
            ),
            ai.provider.ChatMessage(
                role=ai.provider.Role.ASSISTANT,
                content="Hello! How can I help?",
            ),
            ai.provider.ChatMessage(
                role=ai.provider.Role.USER,
                content="Tell me about yourself.",
            ),
        ]

        result = provider.generate(messages)

        assert result.ok is True

    def test_empty_message_collection(
        self,
        provider: MockAIProvider,
    ) -> None:
        """
        Provider behavior with empty input should remain deterministic.

        Validation, if required by the real provider contract, should be
        implemented in AIProviderBase and asserted here accordingly.
        """
        result = provider.generate([])

        assert isinstance(result, ai.provider.CompletionResult)


# ============================================================================
# Factory Tests
# ============================================================================

class TestProviderFactory:
    """Production-grade unit test suite for AI provider factory resolution."""

    @pytest.mark.parametrize(
        ("provider_name", "loader_target"),
        [
            ("gemini", "ai.provider._load_gemini_provider"),
            ("ollama", "ai.provider._load_ollama_provider"),
            ("local", "ai.provider._load_local_provider"),
        ],
    )
    def test_factory_resolves_supported_backends(
        self, provider_name: str, loader_target: str
    ) -> None:
        """Verify that registered backends initialize correctly using lazy loaders."""
        mock_instance = MagicMock(spec=ai.provider.AIProviderBase)
        mock_provider_cls = MagicMock(return_value=mock_instance)

        with patch(loader_target, return_value=mock_provider_cls):
            provider = ai.provider.get_provider(provider_name)

            assert provider is mock_instance
            mock_provider_cls.assert_called_once()

    def test_unknown_provider_raises_factory_error(self) -> None:
        """Verify that asking for an unsupported provider raises a strict ProviderValidationError."""
        with pytest.raises(ai.provider.ProviderValidationError):
            ai.provider.get_provider("unsupported-provider")


# ============================================================================
# Fallback Chain Tests
# ============================================================================


class TestProviderFallback:
    """Tests for AI provider fallback selection."""

    def test_fallback_chain_returns_candidates(self) -> None:
        """Fallback resolution should produce available providers."""
        with patch(
            "ai.provider.get_provider",
        ) as mock_get_provider:
            mock_get_provider.side_effect = [
                MockAIProvider(),
                MockAIProvider(),
            ]

            providers = ai.provider.get_fallback_chain("gemini")

            assert providers

    def test_preferred_provider_is_attempted_first(self) -> None:
        """The preferred provider should be the first fallback candidate."""
        with patch(
            "ai.provider.get_provider",
        ) as mock_get_provider:
            mock_get_provider.return_value = MockAIProvider()

            providers = ai.provider.get_fallback_chain("gemini")

            assert providers
            first = providers[0]

            assert isinstance(first, MockAIProvider)


# ============================================================================
# Latency / Timing Tests
# ============================================================================


class TestProviderTiming:
    """Tests for provider timing metadata."""

    def test_latency_is_recorded(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Successful generation should record non-negative latency."""
        result = provider.generate(
            [user_message],
        )

        assert result.latency_seconds is not None
        assert result.latency_seconds >= 0

    def test_generation_completes_quickly(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """
        The mock provider should complete without unnecessary delay.

        This protects the unit test from accidentally introducing real
        network/API calls.
        """
        started = time.perf_counter()

        provider.generate(
            [user_message],
        )

        elapsed = time.perf_counter() - started

        assert elapsed < 2.0


# ============================================================================
# Regression Tests
# ============================================================================


class TestAIRegression:
    """Regression tests for important AI-layer guarantees."""

    def test_response_text_is_not_empty(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Successful AI responses should contain text."""
        result = provider.generate(
            [user_message],
        )

        assert result.ok is True
        assert result.text.strip()

    def test_provider_result_is_typed(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """Provider output should use the shared CompletionResult type."""
        result = provider.generate(
            [user_message],
        )

        assert type(result) is ai.provider.CompletionResult

    def test_provider_does_not_require_network(
        self,
        provider: MockAIProvider,
        user_message: ai.provider.ChatMessage,
    ) -> None:
        """The test provider must work entirely offline."""
        result = provider.generate(
            [user_message],
        )

        assert result.ok is True
        assert result.text.strip()


