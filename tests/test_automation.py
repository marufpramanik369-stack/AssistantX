"""
AssistantX - Automation Test Suite
====================================

Unit tests for the AssistantX automation layer.

Covered modules:
    - apps
    - browser
    - files
    - folders
    - keyboard
    - mouse
    - clipboard
    - calculator
    - youtube
    - screenshot
    - notifications
    - music

Design goals:
    - No destructive system operations
    - No real browser launching
    - No real keyboard/mouse input
    - No external network dependency
    - Temporary filesystem isolation
    - Mock-based third-party integrations

Run:
    python -m pytest tests/test_automation.py -v

Run a specific test class:
    python -m pytest tests/test_automation.py::TestCalculator -v
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ============================================================================
# Imports
# ============================================================================
from automation import (
    browser,
    calculator,
    clipboard,
    files,
    folders,
    keyboard,
    mouse,
    music,
    notifications,
    screenshot,
    youtube,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """
    Create an isolated temporary workspace.

    No real user files should be touched by filesystem tests.
    """
    workspace = tmp_path / "assistantx_test_workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


@pytest.fixture
def sample_file(temp_workspace: Path) -> Path:
    """Create a small sample text file."""
    path = temp_workspace / "sample.txt"
    path.write_text(
        "AssistantX automation test file.",
        encoding="utf-8",
    )
    return path


# ============================================================================
# Browser Tests
# ============================================================================


class TestBrowser:
    """Tests for automation.browser."""

    def test_build_search_url(self) -> None:
        """Search URL generation should encode the query correctly."""
        url = browser.build_search_url("AssistantX Python")

        assert isinstance(url, str)
        assert url.startswith(("http://", "https://"))
        assert "AssistantX" in url

    def test_search_url_contains_encoded_query(self) -> None:
        """Special characters should be safely encoded."""
        url = browser.build_search_url(
            "python automation & AI"
        )

        assert isinstance(url, str)
        assert "python" in url.lower()

    def test_open_url_uses_webbrowser(self) -> None:
        """open_url should delegate to the standard browser backend."""
        with patch.object(
            browser.webbrowser,
            "open",
            return_value=True,
        ) as mock_open:
            result = browser.open_url(
                "https://example.com",
            )

        assert result is True
        mock_open.assert_called_once()

    def test_open_url_rejects_invalid_url(self) -> None:
        """Invalid URLs should not be opened."""
        with pytest.raises(browser.BrowserError):
            browser.open_url(
                "not-a-valid-url",
            )

    def test_search_uses_browser_backend(self) -> None:
        """Search should eventually open a generated search URL."""
        with patch.object(
            browser,
            "open_url",
            return_value=True,
        ) as mock_open:
            result = browser.search(
                "AssistantX",
            )

        assert result is True
        mock_open.assert_called_once()

    def test_smart_open_http_url(self) -> None:
        """smart_open should recognize a direct HTTP URL."""
        with patch.object(
            browser,
            "open_url",
            return_value=True,
        ) as mock_open:
            result = browser.smart_open(
                "https://example.com",
            )

        assert result is True
        mock_open.assert_called_once()

    def test_smart_open_domain(self) -> None:
        """smart_open should recognize domain-like input."""
        with patch.object(
            browser,
            "open_url",
            return_value=True,
        ) as mock_open:
            result = browser.smart_open(
                "example.com",
            )

        assert result is True
        mock_open.assert_called_once()


# ============================================================================
# Calculator Tests
# ============================================================================


class TestCalculator:
    """Tests for automation.calculator."""

    def test_addition(self) -> None:
        """Basic addition should work."""
        result = calculator.evaluate_expression(
            "2 + 3",
        )

        assert result == 5

    def test_subtraction(self) -> None:
        """Basic subtraction should work."""
        result = calculator.evaluate_expression(
            "10 - 4",
        )

        assert result == 6

    def test_multiplication(self) -> None:
        """Basic multiplication should work."""
        result = calculator.evaluate_expression(
            "6 * 7",
        )

        assert result == 42

    def test_division(self) -> None:
        """Basic division should work."""
        result = calculator.evaluate_expression(
            "20 / 4",
        )

        assert result == 5

    def test_floor_division(self) -> None:
        """Floor division should be supported."""
        result = calculator.evaluate_expression(
            "17 // 5",
        )

        assert result == 3

    def test_modulo(self) -> None:
        """Modulo should be supported."""
        result = calculator.evaluate_expression(
            "17 % 5",
        )

        assert result == 2

    def test_power(self) -> None:
        """Power operation should be supported."""
        result = calculator.evaluate_expression(
            "2 ** 4",
        )

        assert result == 16

    def test_parentheses(self) -> None:
        """Parentheses should preserve mathematical precedence."""
        result = calculator.evaluate_expression(
            "(2 + 3) * 4",
        )

        assert result == 20

    def test_division_by_zero_is_rejected(self) -> None:
        """Division by zero should raise the module-specific error."""
        with pytest.raises(calculator.CalculationError):
            calculator.evaluate_expression(
                "10 / 0",
            )

    def test_unsafe_expression_is_rejected(self) -> None:
        """Unsafe Python expressions must never be evaluated."""
        with pytest.raises(calculator.CalculationError):
            calculator.evaluate_expression(
                "__import__('os').system('echo unsafe')",
            )

    def test_unsafe_function_call_is_rejected(self) -> None:
        """Function calls should not be accepted by the arithmetic parser."""
        with pytest.raises(calculator.CalculationError):
            calculator.evaluate_expression(
                "open('test.txt')",
            )

    def test_format_result(self) -> None:
        """Result formatter should return readable text."""
        result = calculator.format_result(42)

        assert isinstance(result, str)
        assert "42" in result


# ============================================================================
# File Operation Tests
# ============================================================================


class TestFiles:
    """Tests for automation.files."""

    def test_create_file(
        self,
        temp_workspace: Path,
    ) -> None:
        """File creation should work inside the temporary workspace."""
        target = temp_workspace / "created.txt"

        # Adjust this call if the project's final API uses a different
        # parameter name for file content.
        result = files.create_file(
            target,
            content="Hello AssistantX",
        )

        assert target.exists()
        assert target.is_file()

        if result is not None:
            assert Path(result) == target

    def test_read_created_file(
        self,
        sample_file: Path,
    ) -> None:
        """The sample file should contain the expected content."""
        assert sample_file.read_text(
            encoding="utf-8",
        ) == "AssistantX automation test file."

    def test_rename_file(
        self,
        sample_file: Path,
    ) -> None:
        """Renaming should affect only the temporary test file."""
        target = sample_file.with_name(
            "renamed.txt",
        )

        files.rename_file(
            sample_file,
            target,
        )

        assert not sample_file.exists()
        assert target.exists()

    def test_copy_file(
        self,
        sample_file: Path,
        temp_workspace: Path,
    ) -> None:
        """Copying should preserve the source."""
        target = temp_workspace / "copy.txt"

        files.copy_file(
            sample_file,
            target,
        )

        assert sample_file.exists()
        assert target.exists()
        assert target.read_text(
            encoding="utf-8",
        ) == sample_file.read_text(
            encoding="utf-8",
        )

    def test_move_file(
        self,
        sample_file: Path,
        temp_workspace: Path,
    ) -> None:
        """Moving should relocate the file."""
        destination_dir = temp_workspace / "destination"
        destination_dir.mkdir()

        target = destination_dir / sample_file.name

        files.move_file(
            sample_file,
            destination_dir,
        )

        assert not sample_file.exists()
        assert target.exists()

    def test_delete_file(
        self,
        sample_file: Path,
    ) -> None:
        """Deletion should work on a controlled temporary file."""
        files.delete_file(
            sample_file,
        )

        assert not sample_file.exists()

    def test_search_finds_file(
        self,
        sample_file: Path,
    ) -> None:
        """File search should be able to find a known test file."""
        results = files.search_files(
            "sample.txt",
            roots=(sample_file.parent,),
        )

        assert results is not None

        paths = [
            Path(item.path)
            for item in results
        ]

        assert sample_file in paths


# ============================================================================
# Folder Tests
# ============================================================================


class TestFolders:
    """Tests for automation.folders."""

    def test_create_folder(
        self,
        temp_workspace: Path,
    ) -> None:
        """Folder creation should work in the isolated workspace."""
        folder_name = "test_folder"

        result = folders.create_folder(
            folder_name,
            parent_dir=temp_workspace,
        )

        target = temp_workspace / folder_name

        assert target.exists()
        assert target.is_dir()

        if result is not None:
            assert Path(result) == target

    def test_create_nested_folder(
        self,
        temp_workspace: Path,
    ) -> None:
        """Nested directories should be supported."""
        parent = temp_workspace / "parent"
        parent.mkdir()

        folders.create_folder(
            "child",
            parent_dir=parent,
        )

        assert (parent / "child").is_dir()

    def test_delete_folder(
        self,
        temp_workspace: Path,
    ) -> None:
        """Folder deletion should affect only the temporary directory."""
        target = temp_workspace / "remove_me"
        target.mkdir()

        folders.delete_folder(
            target,
        )

        assert not target.exists()


# ============================================================================
# Keyboard Tests
# ============================================================================


class TestKeyboard:
    """Tests for automation.keyboard."""

    def test_backend_availability_returns_bool(self) -> None:
        """Availability check should always return a boolean."""
        result = keyboard.is_available()

        assert isinstance(result, bool)

    def test_get_backend_failure_is_clear(self) -> None:
        """Missing backend should produce the module-specific error."""
        with patch.object(
            keyboard,
            "pyautogui",
            None,
        ), pytest.raises(keyboard.KeyboardAutomationError):
            keyboard._get_backend()

    def test_press_delegates_to_backend(self) -> None:
        """press should delegate to pyautogui."""
        fake_backend = MagicMock()

        with patch.object(
            keyboard,
            "_get_backend",
            return_value=fake_backend,
        ):
            keyboard.press("enter")

        fake_backend.press.assert_called_once_with("enter")

    def test_write_delegates_to_backend(self) -> None:
        """Text typing should delegate to the backend."""
        fake_backend = MagicMock()

        with patch.object(
            keyboard,
            "_get_backend",
            return_value=fake_backend,
        ):
            keyboard.write_text("AssistantX")

        fake_backend.write.assert_called_once()


# ============================================================================
# Mouse Tests
# ============================================================================


class TestMouse:
    """Tests for automation.mouse."""

    def test_point_dataclass(self) -> None:
        """Point should preserve x/y coordinates."""
        point = mouse.Point(
            x=100,
            y=200,
        )

        assert point.x == 100
        assert point.y == 200

    def test_point_as_tuple(self) -> None:
        """Point should convert to a coordinate tuple."""
        point = mouse.Point(
            x=100,
            y=200,
        )

        assert point.as_tuple() == (100, 200)

    def test_backend_availability_returns_bool(self) -> None:
        """Availability check should return a boolean."""
        assert isinstance(
            mouse.is_available(),
            bool,
        )

    def test_move_to_delegates_to_backend(self) -> None:
        """Mouse movement should use the configured backend."""
        fake_backend = MagicMock()

        with patch.object(
            mouse,
            "_get_backend",
            return_value=fake_backend,
        ):
            mouse.move_to(
                100,
                200,
            )

        fake_backend.moveTo.assert_called_once()


# ============================================================================
# Clipboard Tests
# ============================================================================


class TestClipboard:
    """Tests for automation.clipboard."""

    def test_availability_returns_bool(self) -> None:
        """Clipboard availability should be boolean."""
        assert isinstance(
            clipboard.is_available(),
            bool,
        )

    def test_copy_text_uses_pyperclip_when_available(self) -> None:
        """copy_text should use pyperclip when available."""
        fake_pyperclip = MagicMock()

        with patch.object(
            clipboard,
            "pyperclip",
            fake_pyperclip,
        ):
            clipboard.copy_text(
                "AssistantX",
            )

        fake_pyperclip.copy.assert_called_once_with(
            "AssistantX",
        )

    def test_paste_text_uses_pyperclip(self) -> None:
        """paste_text should return clipboard text."""
        fake_pyperclip = MagicMock()
        fake_pyperclip.paste.return_value = "AssistantX"

        with patch.object(
            clipboard,
            "pyperclip",
            fake_pyperclip,
        ):
            result = clipboard.paste_text()

        assert result == "AssistantX"


# ============================================================================
# YouTube Tests
# ============================================================================


class TestYouTube:
    """Tests for automation.youtube."""

    def test_build_search_url(self) -> None:
        """YouTube search URL should contain the query."""
        url = youtube.build_search_url(
            "lofi music",
        )

        assert url.startswith(
            "https://www.youtube.com/results",
        )
        assert "lofi" in url

    def test_build_watch_url(self) -> None:
        """YouTube watch URL should contain the video ID."""
        video_id = "dQw4w9WgXcQ"

        url = youtube.build_watch_url(
            video_id,
        )

        assert url == (
            "https://www.youtube.com/watch?v="
            + video_id
        )

    def test_build_watch_url_rejects_invalid_id(self) -> None:
        """Invalid YouTube IDs should not silently create URLs."""
        with pytest.raises(ValueError):
            youtube.build_watch_url(
                "invalid",
            )


# ============================================================================
# Screenshot Tests
# ============================================================================


class TestScreenshot:
    """Tests for automation.screenshot."""

    def test_region_as_tuple(self) -> None:
        """Region should convert to the expected tuple."""
        region = screenshot.Region(
            left=10,
            top=20,
            width=300,
            height=200,
        )

        assert region.as_tuple() == (
            10,
            20,
            300,
            200,
        )

    def test_region_values_are_preserved(self) -> None:
        """Region coordinates should remain unchanged."""
        region = screenshot.Region(
            left=1,
            top=2,
            width=100,
            height=50,
        )

        assert region.left == 1
        assert region.top == 2
        assert region.width == 100
        assert region.height == 50

    def test_screenshot_backend_failure_is_handled(self) -> None:
        """Unavailable screenshot backend should raise ScreenshotError."""
        with patch.object(
            screenshot,
            "pyautogui",
            None,
        ), pytest.raises(
            screenshot.ScreenshotError,
        ):
            screenshot._get_backend()


# ============================================================================
# Notification Tests
# ============================================================================


class TestNotifications:
    """Tests for automation.notifications."""

    def test_notification_request_defaults(self) -> None:
        """NotificationRequest should provide sensible defaults."""
        request = notifications.NotificationRequest(
            title="AssistantX",
            message="Test notification",
        )

        assert request.title == "AssistantX"
        assert request.message == "Test notification"
        assert request.timeout_seconds > 0

    def test_custom_notification_timeout(self) -> None:
        """Custom timeout should be preserved."""
        request = notifications.NotificationRequest(
            title="Test",
            message="Hello",
            timeout_seconds=5,
        )

        assert request.timeout_seconds == 5


# ============================================================================
# Music Tests
# ============================================================================


class TestMusic:
    """Tests for automation.music."""

    def test_backend_availability_returns_bool(self) -> None:
        """Music backend availability should be boolean."""
        assert isinstance(
            music.is_available(),
            bool,
        )

    def test_play_pause_uses_media_key_backend(self) -> None:
        """Play/pause should delegate to the keyboard backend."""
        fake_backend = MagicMock()

        with patch.object(
            music,
            "pyautogui",
            fake_backend,
        ):
            music.play_pause()

        fake_backend.press.assert_called_once()


# ============================================================================
# Cross-Module Safety Tests
# ============================================================================


class TestAutomationSafety:
    """General safety/regression tests."""

    def test_browser_does_not_open_invalid_input(self) -> None:
        """Invalid browser input should fail before backend invocation."""
        with patch.object(
            browser.webbrowser,
            "open",
        ) as mock_open, pytest.raises(browser.BrowserError):
            browser.open_url(
                "this is definitely not a URL",
            )

        mock_open.assert_not_called()

    def test_calculator_does_not_execute_python(self) -> None:
        """Calculator must remain an arithmetic evaluator."""
        malicious_expressions = (
            "__import__('os')",
            "eval('2+2')",
            "exec('print(1)')",
            "open('file.txt')",
        )

        for expression in malicious_expressions:
            with pytest.raises(
                calculator.CalculationError,
            ):
                calculator.evaluate_expression(
                    expression,
                )

    def test_file_tests_use_temporary_paths(
        self,
        temp_workspace: Path,
    ) -> None:
        """The test workspace must live under pytest's temporary directory."""
        assert temp_workspace.exists()
        assert temp_workspace.is_dir()
        assert "pytest" in str(
            temp_workspace,
        ).lower()


# ============================================================================
# Serialization / Data Integrity Tests
# ============================================================================


class TestAutomationDataIntegrity:
    """Tests for data structures exposed by automation modules."""

    def test_region_is_serializable(self) -> None:
        """Region values should be easily serializable."""
        region = screenshot.Region(
            left=0,
            top=0,
            width=1920,
            height=1080,
        )

        payload = {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        }

        encoded = json.dumps(payload)
        decoded = json.loads(encoded)

        assert decoded["width"] == 1920
        assert decoded["height"] == 1080

    def test_point_is_serializable(self) -> None:
        """Mouse coordinates should be JSON-compatible."""
        point = mouse.Point(
            x=500,
            y=300,
        )

        payload = {
            "x": point.x,
            "y": point.y,
        }

        encoded = json.dumps(payload)
        decoded = json.loads(encoded)

        assert decoded == {
            "x": 500,
            "y": 300,
        }
