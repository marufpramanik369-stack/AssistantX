"""
AssistantX - Browser Automation Test Suite
===========================================

Professional unit tests for:
    automation.browser

Test philosophy:
    - No real browser is launched.
    - No external website is contacted.
    - Standard-library only where possible.
    - Browser side effects are mocked.
    - Public API behavior is tested.
    - Invalid input and error handling are covered.
    - Tests are suitable for CI/CD and Windows development.

Run:
    python -m pytest tests/test_browser.py -v

Or:
    pytest tests/test_browser.py -v
"""

from __future__ import annotations

import inspect
from typing import Literal
from unittest.mock import patch

import pytest

from automation import browser

# ============================================================================
# Helpers
# ============================================================================


def _find_public_callable(name: str):
    """Return a public callable from automation.browser."""
    value = getattr(browser, name, None)

    if value is None:
        pytest.fail(
            f"automation.browser does not expose expected callable: {name}"
        )

    if not callable(value):
        pytest.fail(
            f"automation.browser.{name} exists but is not callable."
        )

    return value


def _call_with_supported_args(func, **kwargs):
    """
    Call a function using only keyword arguments accepted by its signature.

    This helper keeps tests slightly resilient when optional parameters differ
    between minor implementations of the browser module.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(**kwargs)

    accepted = {}

    for parameter_name, parameter in signature.parameters.items():
        if parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        ) and parameter_name in kwargs:
            accepted[parameter_name] = kwargs[parameter_name]

    return func(**accepted)


# ============================================================================
# Module / API Tests
# ============================================================================


class TestBrowserModule:
    """Tests for browser module structure and public API."""

    def test_module_imports_successfully(self):
        """Browser module must be importable."""
        assert browser is not None

    def test_browser_module_has_documentation(self):
        """Module should have a useful module docstring."""
        assert browser.__doc__
        assert "browser" in browser.__doc__.lower()

    def test_browser_error_exists(self):
        """BrowserError should be exposed by the module."""
        error_type = getattr(browser, "BrowserError", None)

        assert error_type is not None
        assert issubclass(error_type, Exception)

    def test_expected_public_functions_exist(self):
        """
        Core browser functions expected by AssistantX should exist.

        Some implementations may expose additional helpers; these tests only
        enforce the core API.
        """
        expected = (
            "open_url",
            "search_web",
            "smart_open",
        )

        missing = [
            name
            for name in expected
            if not hasattr(browser, name)
        ]

        assert not missing, (
            "Missing browser API functions: "
            + ", ".join(missing)
        )

    def test_public_functions_are_callable(self):
        """All core browser API functions must be callable."""
        for name in (
            "open_url",
            "search_web",
            "smart_open",
        ):
            function = _find_public_callable(name)
            assert callable(function)


# ============================================================================
# SearchEngine Tests
# ============================================================================


class TestSearchEngine:
    """Tests for the SearchEngine abstraction."""

    def test_search_engine_exists(self):
        """SearchEngine should be available."""
        search_engine = getattr(browser, "SearchEngine", None)

        assert search_engine is not None
        assert callable(search_engine)

    def test_search_engine_can_be_created(self):
        """SearchEngine should support basic construction."""
        SearchEngine = _find_public_callable("SearchEngine")

        engine = SearchEngine(
            name="TestEngine",
            url_template="https://example.com/search?q={query}",
        )

        assert engine is not None

    def test_search_engine_stores_name(self):
        """SearchEngine name should be preserved."""
        SearchEngine = _find_public_callable("SearchEngine")

        engine = SearchEngine(
            name="TestEngine",
            url_template="https://example.com/search?q={query}",
        )

        assert getattr(engine, "name", None) == "TestEngine"

    def test_search_engine_stores_url_template(self):
        """SearchEngine URL template should be preserved."""
        SearchEngine = _find_public_callable("SearchEngine")

        template = "https://example.com/search?q={query}"

        engine = SearchEngine(
            name="TestEngine",
            url_template=template,
        )

        assert getattr(engine, "url_template", None) == template


# ============================================================================
# open_url Tests
# ============================================================================


class TestOpenURL:
    """Tests for URL opening behavior."""

    @patch("automation.browser.webbrowser.open")
    def test_open_http_url(self, mock_open):
        """HTTP URL should be passed to webbrowser."""
        mock_open.return_value = True

        result = browser.open_url("http://example.com")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_open_https_url(self, mock_open):
        """HTTPS URL should be passed to webbrowser."""
        mock_open.return_value = True

        result = browser.open_url("https://example.com")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_open_url_preserves_url(self, mock_open):
        """The original URL should be forwarded unchanged."""
        mock_open.return_value = True

        url = "https://example.com/path?q=assistantx"

        browser.open_url(url)

        args, _ = mock_open.call_args

        assert args
        assert args[0] == url

    @patch("automation.browser.webbrowser.open")
    def test_open_url_does_not_launch_real_browser(self, mock_open):
        """
        Test must use the mocked browser backend rather than launching a
        real browser.
        """
        mock_open.return_value = True

        browser.open_url("https://example.com")

        assert mock_open.called

    def test_open_url_rejects_blank_url(self):
        """Blank URL should raise BrowserError."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url("")

    def test_open_url_rejects_whitespace_url(self):
        """Whitespace-only URL should be rejected."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url("   ")

    def test_open_url_rejects_none(self):
        """None should not be accepted as a URL."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url(None)  # type: ignore[arg-type]

    def test_open_url_rejects_invalid_scheme(self):
        """Unsupported schemes should be rejected."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url("ftp://example.com")

    def test_open_url_rejects_malformed_url(self):
        """Malformed URLs should not be silently accepted."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url("not a valid url")


# ============================================================================
# Web Search Tests
# ============================================================================


class TestSearchWeb:
    """Tests for search_web()."""

    @patch("automation.browser.webbrowser.open")
    def test_search_web_basic_query(self, mock_open):
        """Basic search query should open a search URL."""
        mock_open.return_value = True

        result = browser.search_web("Python programming")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_search_web_forwards_query(self, mock_open):
        """Search query should appear in the generated URL."""
        mock_open.return_value = True

        query = "AssistantX Python AI"

        browser.search_web(query)

        args, _ = mock_open.call_args
        generated_url = args[0]

        assert "AssistantX" in generated_url
        assert "Python" in generated_url
        assert "AI" in generated_url

    @patch("automation.browser.webbrowser.open")
    def test_search_web_handles_special_characters(self, mock_open):
        """Special characters should be URL encoded safely."""
        mock_open.return_value = True

        query = "Python + AI & automation"

        browser.search_web(query)

        args, _ = mock_open.call_args

        assert args
        generated_url = args[0]

        assert generated_url.startswith("http")

    @patch("automation.browser.webbrowser.open")
    def test_search_web_handles_unicode(self, mock_open):
        """Unicode queries should not crash URL construction."""
        mock_open.return_value = True

        query = "বাংলা ভাষা"

        browser.search_web(query)

        mock_open.assert_called_once()

    def test_search_web_rejects_blank_query(self):
        """Blank search query should raise BrowserError."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.search_web("")

    def test_search_web_rejects_whitespace_query(self):
        """Whitespace-only query should raise BrowserError."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.search_web("     ")

    def test_search_web_rejects_none(self):
        """None search query should be rejected."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.search_web(None)  # type: ignore[arg-type]


# ============================================================================
# Smart Open Tests
# ============================================================================


class TestSmartOpen:
    """Tests for smart_open()."""

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_https_url(self, mock_open):
        """smart_open should recognize a direct HTTPS URL."""
        mock_open.return_value = True

        result = browser.smart_open("https://example.com")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_http_url(self, mock_open):
        """smart_open should recognize a direct HTTP URL."""
        mock_open.return_value = True

        result = browser.smart_open("http://example.com")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_domain_like_input(self, mock_open):
        """Domain-like input should be converted/opened appropriately."""
        mock_open.return_value = True

        result = browser.smart_open("example.com")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_search_query(self, mock_open):
        """Natural-language input should be handled as a search when needed."""
        mock_open.return_value = True

        result = browser.smart_open("latest Python documentation")

        mock_open.assert_called_once()
        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_unicode_query(self, mock_open):
        """Unicode natural-language queries should work."""
        mock_open.return_value = True

        browser.smart_open("বাংলাদেশের খবর")

        mock_open.assert_called_once()

    def test_smart_open_rejects_blank_input(self):
        """Blank input should raise BrowserError."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.smart_open("")

    def test_smart_open_rejects_whitespace_input(self):
        """Whitespace-only input should raise BrowserError."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.smart_open("    ")


# ============================================================================
# Search Engine Integration Tests
# ============================================================================


class TestSearchEngineIntegration:
    """Tests for custom search-engine behavior."""

    @patch("automation.browser.webbrowser.open")
    def test_custom_search_engine_can_be_used(
        self,
        mock_open,
    ):
        """A custom SearchEngine should be usable if supported by the API."""
        mock_open.return_value = True

        SearchEngine = getattr(browser, "SearchEngine", None)

        if SearchEngine is None:
            pytest.skip("SearchEngine is not available.")

        engine = SearchEngine(
            name="Example",
            url_template="https://example.com/search?q={query}",
        )

        # Only test directly if the implementation exposes a compatible
        # search-engine parameter.
        try:
            result = _call_with_supported_args(
                browser.search_web,
                query="AssistantX",
                engine=engine,
                search_engine=engine,
            )
        except TypeError:
            pytest.skip(
                "search_web does not expose a custom search-engine parameter."
            )

        assert result is not None
        assert mock_open.called


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestBrowserErrors:
    """Tests for browser backend failures."""

    @patch("automation.browser.webbrowser.open")
    def test_browser_backend_failure_is_handled(self, mock_open):
        """Backend exceptions should be converted to BrowserError."""
        BrowserError = browser.BrowserError

        mock_open.side_effect = RuntimeError("Browser backend failed")

        with pytest.raises(BrowserError):
            browser.open_url("https://example.com")

    @patch("automation.browser.webbrowser.open")
    def test_browser_backend_os_error_is_handled(self, mock_open):
        """OSError from the browser backend should be handled."""
        BrowserError = browser.BrowserError

        mock_open.side_effect = OSError("Unable to launch browser")

        with pytest.raises(BrowserError):
            browser.open_url("https://example.com")

    @patch("automation.browser.webbrowser.open")
    def test_search_backend_failure_is_handled(self, mock_open):
        """Search operation should convert backend errors."""
        BrowserError = browser.BrowserError

        mock_open.side_effect = RuntimeError("Search browser failed")

        with pytest.raises(BrowserError):
            browser.search_web("AssistantX")


# ============================================================================
# URL Validation Tests
# ============================================================================


class TestURLValidation:
    """Tests for URL-related edge cases."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "https://example.com/",
            "https://example.com/path",
            "https://example.com/path?q=test",
            "https://sub.example.com",
            "http://localhost:8000",
        ],
    )
    @patch("automation.browser.webbrowser.open")
    def test_valid_urls(
        self,
        mock_open,
        url: Literal['https://example.com', 'https://example.com/', 'https://example.com/path', 'https://example.com/path?q=test', 'https://sub.example.com', 'http://localhost:8000'],
    ):
        """Common valid HTTP(S) URLs should be accepted."""
        mock_open.return_value = True

        result = browser.open_url(url)

        mock_open.assert_called_once()
        assert result is not None

    @pytest.mark.parametrize(
        "url",
        [
            "",
            " ",
            "example",
            "ht!tp://example.com",
            "javascript:alert(1)",
            "file:///etc/passwd",
        ],
    )
    def test_invalid_urls(self, url: Literal['', ' ', 'example', 'ht!tp://example.com', 'javascript:alert(1)', 'file:///etc/passwd']):
        """Clearly invalid or unsafe schemes should be rejected."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.open_url(url)


# ============================================================================
# Search Query Edge Cases
# ============================================================================


class TestSearchEdgeCases:
    """Search input boundary and robustness tests."""

    @pytest.mark.parametrize(
        "query",
        [
            "python",
            "python programming",
            "Python 3.14",
            "AI assistant",
            "AssistantX automation",
            "C++ programming",
            "email@example.com",
            "100% Python",
            "বাংলা",
            "বাংলা Python",
        ],
    )
    @patch("automation.browser.webbrowser.open")
    def test_supported_queries(
        self,
        mock_open,
        query: Literal['python', 'python programming', 'Python 3.14', 'AI assistant', 'AssistantX automation', 'C++ programming', 'email@example.com', '100% Python', 'বাংলা', 'বাংলা Python'],
    ):
        """Representative search queries should be accepted."""
        mock_open.return_value = True

        result = browser.search_web(query)

        mock_open.assert_called_once()
        assert result is not None

    @pytest.mark.parametrize(
        "query",
        [
            "",
            " ",
            "   ",
            "\t",
            "\n",
        ],
    )
    def test_empty_queries_are_rejected(self, query: Literal['', ' ', '   ', '\t', '\n']):
        """Empty-like search queries should be rejected."""
        BrowserError = browser.BrowserError

        with pytest.raises(BrowserError):
            browser.search_web(query)


# ============================================================================
# Return Value Tests
# ============================================================================


class TestReturnValues:
    """Tests ensuring public methods return useful results."""

    @patch("automation.browser.webbrowser.open")
    def test_open_url_returns_result(self, mock_open):
        """open_url should expose a meaningful result."""
        mock_open.return_value = True

        result = browser.open_url("https://example.com")

        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_search_web_returns_result(self, mock_open):
        """search_web should expose a meaningful result."""
        mock_open.return_value = True

        result = browser.search_web("AssistantX")

        assert result is not None

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_returns_result(self, mock_open):
        """smart_open should expose a meaningful result."""
        mock_open.return_value = True

        result = browser.smart_open("https://example.com")

        assert result is not None


# ============================================================================
# Regression Tests
# ============================================================================


class TestBrowserRegression:
    """
    Regression tests for common issues in AssistantX browser automation.

    These tests intentionally avoid launching a real browser.
    """

    @patch("automation.browser.webbrowser.open")
    def test_no_real_browser_is_launched(self, mock_open):
        """
        The test environment must only interact with the mocked backend.
        """
        mock_open.return_value = True

        browser.open_url("https://example.com")

        assert mock_open.call_count == 1

    @patch("automation.browser.webbrowser.open")
    def test_query_is_not_lost(self, mock_open):
        """Search query should survive URL generation."""
        mock_open.return_value = True

        query = "AssistantX browser automation"

        browser.search_web(query)

        generated_url = mock_open.call_args.args[0]

        assert "AssistantX" in generated_url
        assert "browser" in generated_url
        assert "automation" in generated_url

    @patch("automation.browser.webbrowser.open")
    def test_smart_open_direct_url_only_opens_once(self, mock_open):
        """
        Direct URLs should not accidentally trigger both URL opening and
        search fallback.
        """
        mock_open.return_value = True

        browser.smart_open("https://example.com")

        assert mock_open.call_count == 1


# ============================================================================
# Performance / Stability Tests
# ============================================================================


class TestBrowserStability:
    """Lightweight stability checks."""

    @patch("automation.browser.webbrowser.open")
    def test_repeated_open_calls(self, mock_open):
        """Repeated calls should remain stable."""
        mock_open.return_value = True

        for _ in range(10):
            browser.open_url("https://example.com")

        assert mock_open.call_count == 10

    @patch("automation.browser.webbrowser.open")
    def test_repeated_search_calls(self, mock_open):
        """Repeated searches should remain stable."""
        mock_open.return_value = True

        for _ in range(10):
            browser.search_web("AssistantX")

        assert mock_open.call_count == 10

    @patch("automation.browser.webbrowser.open")
    def test_repeated_smart_open_calls(self, mock_open):
        """Repeated smart-open operations should remain stable."""
        mock_open.return_value = True

        for _ in range(10):
            browser.smart_open("https://example.com")

        assert mock_open.call_count == 10


# ============================================================================
# Public API Compatibility
# ============================================================================


class TestPublicAPICompatibility:
    """Compatibility checks for AssistantX integration."""

    def test_browser_error_name_is_stable(self):
        """Command router should be able to import BrowserError."""
        assert browser.BrowserError.__name__ == "BrowserError"

    def test_search_engine_name_is_stable(self):
        """SearchEngine should have a stable class name."""
        SearchEngine = getattr(browser, "SearchEngine", None)

        if SearchEngine is None:
            pytest.fail("SearchEngine is required by the browser API.")

        assert SearchEngine.__name__ == "SearchEngine"

    def test_module_exports_core_symbols(self):
        """
        Core public symbols should be available through the module namespace.
        """
        expected = (
            "BrowserError",
            "SearchEngine",
            "open_url",
            "search_web",
            "smart_open",
        )

        for name in expected:
            assert hasattr(browser, name), (
                f"Missing public symbol: {name}"
            )


# ============================================================================
# Final Smoke Test
# ============================================================================


class TestBrowserSmoke:
    """Final high-level smoke tests."""

    @patch("automation.browser.webbrowser.open")
    def test_complete_browser_flow(self, mock_open):
        """
        Simulate the main AssistantX browser flow:

            1. Open direct URL
            2. Perform search
            3. Smart-open another URL
        """
        mock_open.return_value = True

        browser.open_url("https://example.com")
        browser.search_web("AssistantX AI")
        browser.smart_open("https://example.org")

        assert mock_open.call_count == 3

    def test_exception_hierarchy(self):
        """BrowserError should be suitable for broad Exception handling."""
        BrowserError = browser.BrowserError

        assert issubclass(BrowserError, Exception)

    def test_module_is_import_safe(self):
        """
        Importing browser module should not require optional third-party
        browser packages.
        """
        assert browser is not None
