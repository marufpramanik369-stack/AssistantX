"""
automation
==========
Desktop/OS automation package for AssistantX: application launching,
browser control, file/folder operations, system control (power/volume/
brightness), keyboard/mouse simulation, clipboard access, screenshots,
calculation, YouTube, music playback, and desktop notifications.

Every module here is designed to degrade gracefully when its optional
third-party dependency (pyautogui, pyperclip, plyer, etc.) isn't
installed — functions raise a clear, module-specific *Error exception
rather than crashing at import time, so core/command_router.py can
catch these and phrase a natural "I can't do that right now" response
via brain/response_generator.py instead of the whole app failing.
"""

from __future__ import annotations

from automation.apps import AppLaunchError, close_app, list_known_apps, open_app, resolve_app_command
from automation.browser import BrowserError, is_url_like, open_site, open_url, search, smart_open
from automation.calculator import CalculationError, convert_units, evaluate_expression, format_result
from automation.clipboard import ClipboardError, copy_text, has_text, paste_text
from automation.files import (
    FileOperationError,
    FileSearchResult,
    copy_file,
    create_file,
    delete_file,
    file_exists,
    get_file_info,
    move_file,
    read_text_file,
    rename_file,
    search_files,
)
from automation.folders import (
    FolderOperationError,
    create_folder,
    delete_folder,
    get_well_known_folder,
    list_folder_contents,
    open_folder,
)
from automation.keyboard import KeyboardAutomationError
from automation.keyboard import copy as kb_copy
from automation.keyboard import paste as kb_paste
from automation.keyboard import press_hotkey, press_key, type_text
from automation.mouse import MouseAutomationError, click, double_click, drag_to, move_to, right_click, scroll
from automation.music import MusicControlError
from automation.music import next_track as music_next
from automation.music import pause as music_pause
from automation.music import play as music_play
from automation.music import previous_track as music_previous
from automation.notifications import NotificationError, notify, notify_error, notify_reminder
from automation.screenshot import ScreenshotError, capture_active_window, capture_fullscreen, capture_region
from automation.system import (
    SystemControlError,
    adjust_brightness,
    adjust_volume,
    lock_screen,
    mute,
    restart,
    set_brightness,
    set_volume,
    shutdown,
    sleep,
    unmute,
)
from automation.youtube import YouTubeError, open_search as youtube_search
from automation.youtube import play_top_result as youtube_play

__all__ = [
    # apps
    "AppLaunchError", "open_app", "close_app", "list_known_apps", "resolve_app_command",
    # browser
    "BrowserError", "open_url", "open_site", "search", "smart_open", "is_url_like",
    # files
    "FileOperationError", "FileSearchResult", "create_file", "delete_file", "rename_file",
    "move_file", "copy_file", "search_files", "read_text_file", "file_exists", "get_file_info",
    # folders
    "FolderOperationError", "create_folder", "delete_folder", "open_folder",
    "list_folder_contents", "get_well_known_folder",
    # system
    "SystemControlError", "shutdown", "restart", "sleep", "lock_screen",
    "set_volume", "adjust_volume", "mute", "unmute", "set_brightness", "adjust_brightness",
    # keyboard
    "KeyboardAutomationError", "type_text", "press_key", "press_hotkey", "kb_copy", "kb_paste",
    # mouse
    "MouseAutomationError", "move_to", "click", "double_click", "right_click", "drag_to", "scroll",
    # clipboard
    "ClipboardError", "copy_text", "paste_text", "has_text",
    # screenshot
    "ScreenshotError", "capture_fullscreen", "capture_region", "capture_active_window",
    # calculator
    "CalculationError", "evaluate_expression", "format_result", "convert_units",
    # youtube
    "YouTubeError", "youtube_search", "youtube_play",
    # music
    "MusicControlError", "music_play", "music_pause", "music_next", "music_previous",
    # notifications
    "NotificationError", "notify", "notify_reminder", "notify_error",
]
