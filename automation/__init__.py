"""
automation
==========
AssistantX desktop and OS automation package.

This package provides a unified public API for:

- Application launching and closing
- Web browser automation
- File and folder operations
- System controls
- Keyboard and mouse automation
- Clipboard access
- Screenshots
- Calculator and unit conversion
- YouTube automation
- Music playback
- Desktop notifications

Architecture
------------
Each automation module is independently responsible for its own
optional dependencies and errors. Importing this package should remain
safe even when optional third-party packages are not installed.

Higher-level modules such as:

    core.command_router
    brain.decision_engine
    brain.response_generator

can use these public functions without needing to know the internal
implementation of each automation module.
"""

from __future__ import annotations

# ============================================================================
# Apps
# ============================================================================
from automation.apps import (
    AppAlias,
    AppAutomationError,
    AppCloseError,
    AppInfo,
    AppLaunchError,
    AppNotFoundError,
    AppResolution,
    AppValidationError,
    close_app,
    find_apps,
    get_app_info,
    get_platform_name,
    is_app_available,
    list_known_apps,
    open_app,
    register_app,
    resolve_app,
    resolve_app_command,
    safe_close_app,
    safe_open_app,
    unregister_app,
)
from automation.apps import (
    diagnostics as apps_diagnostics,
)

# ============================================================================
# Browser
# ============================================================================
from automation.browser import (
    BrowserBackendError,
    BrowserError,
    BrowserInfo,
    BrowserValidationError,
    SearchEngine,
    SearchEngineError,
    build_search_url,
    get_browser_info,
    get_search_engine,
    is_url_like,
    list_search_engines,
    normalize_url,
    open_site,
    open_url,
    register_search_engine,
    register_site,
    safe_open_site,
    safe_open_url,
    safe_search,
    safe_smart_open,
    search,
    smart_open,
)
from automation.browser import (
    diagnostics as browser_diagnostics,
)
from automation.browser import (
    is_available as browser_is_available,
)

# ============================================================================
# Calculator
# ============================================================================
from automation.calculator import (
    CalculationError,
    CalculationResult,
    ConversionResult,
    IncompatibleUnitError,
    UnitConversionError,
    UnitDefinition,
    UnsupportedUnitError,
    calculate,
    convert,
    convert_units,
    evaluate_expression,
    format_result,
    list_units,
)

# ============================================================================
# Clipboard
# ============================================================================
from automation.clipboard import (
    ClipboardBackendError,
    ClipboardError,
    ClipboardInfo,
    ClipboardReadError,
    ClipboardValidationError,
    ClipboardWriteError,
    clear_clipboard,
    copy_text,
    get_clipboard_info,
    get_preview,
    get_text_length,
    has_text,
    paste_text,
    safe_copy_text,
    safe_paste_text,
)

# ============================================================================
# Files
# ============================================================================
from automation.files import (
    FileAlreadyExistsError,
    FileInfo,
    FileNotFoundError,
    FileOperationError,
    FileReadError,
    FileSafetyError,
    FileSearchResult,
    FileValidationError,
    FileWriteError,
    append_text_file,
    copy_file,
    create_file,
    delete_file,
    file_exists,
    get_file_info,
    is_directory,
    is_file,
    move_file,
    read_text_file,
    rename_file,
    safe_copy_file,
    safe_create_file,
    safe_delete_file,
    safe_move_file,
    safe_read_text_file,
    safe_rename_file,
    safe_write_text_file,
    search_file_paths,
    search_files,
    write_text_file,
)

# ============================================================================
# Folders
# ============================================================================
from automation.folders import (
    FolderEntry,
    FolderInfo,
    FolderNotFoundError,
    FolderOperationError,
    FolderSafetyError,
    FolderValidationError,
    create_folder,
    delete_folder,
    folder_exists,
    get_folder_info,
    get_folder_size,
    get_well_known_folder,
    list_folder_contents,
    list_folder_contents_dict,
    move_folder,
    normalize_path,
    open_folder,
    rename_folder,
    safe_create_folder,
    safe_delete_folder,
    safe_move_folder,
    safe_open_folder,
    search_folders,
)

# ============================================================================
# Keyboard
# ============================================================================
from automation.keyboard import (
    KeyboardAutomationError,
    KeyboardBackendError,
    KeyboardValidationError,
    enter,
    escape,
    hold_key,
    new_tab,
    press_hotkey,
    press_key,
    redo,
    refresh,
    save,
    select_all,
    switch_window,
    type_text,
    undo,
)
from automation.keyboard import (
    copy as kb_copy,
)
from automation.keyboard import (
    cut as kb_cut,
)
from automation.keyboard import (
    find as kb_find,
)
from automation.keyboard import (
    paste as kb_paste,
)

# ============================================================================
# Mouse
# ============================================================================
from automation.mouse import (
    MouseAutomationError,
    MouseBackendError,
    MouseValidationError,
    Point,
    click,
    double_click,
    drag_to,
    get_position,
    get_screen_size,
    move_relative,
    move_to,
    right_click,
    safe_click,
    safe_double_click,
    safe_move_to,
    safe_right_click,
    safe_scroll,
    scroll,
    scroll_horizontal,
)

# ============================================================================
# Music
# ============================================================================
from automation.music import (
    MusicBackendError,
    MusicControlError,
    MusicValidationError,
    SpotifyController,
    SpotifyDevice,
    SpotifyError,
    SpotifyTrack,
    music_diagnostics,
    next_music_track,
    pause_music,
    play_music,
    previous_music_track,
    resume_music,
    safe_next_music_track,
    safe_pause_music,
    safe_play_music,
    safe_previous_music_track,
    safe_resume_music,
    search_and_play,
    spotify,
    volume_down,
    volume_mute,
    volume_up,
)

# Backward-compatible aliases
music_play = play_music
music_pause = pause_music
music_next = next_music_track
music_previous = previous_music_track


# ============================================================================
# Notifications
# ============================================================================

from automation.notifications import (
    NotificationBackendError,
    NotificationError,
    NotificationRequest,
    NotificationValidationError,
    notify,
    notify_download_completed,
    notify_error,
    notify_info,
    notify_reminder,
    notify_success,
    notify_system_event,
    notify_task_completed,
    notify_update_available,
    notify_warning,
    safe_notify,
)

# ============================================================================
# Screenshots
# ============================================================================
from automation.screenshot import (
    Region,
    ScreenshotBackendError,
    ScreenshotError,
    ScreenshotInfo,
    ScreenshotSaveError,
    ScreenshotValidationError,
    capture_active_window,
    capture_fullscreen,
    capture_region,
    delete_screenshot,
    get_screen_size,
    get_screenshot_directory,
    list_screenshots,
    safe_capture_active_window,
    safe_capture_fullscreen,
    safe_capture_region,
    screenshot,
    screenshot_active_window,
    screenshot_region,
)

# ============================================================================
# System
# ============================================================================
from automation.system import (
    SystemControlError,
    SystemOperationError,
    SystemValidationError,
    adjust_brightness,
    adjust_volume,
    get_brightness,
    get_volume,
    lock_screen,
    mute,
    restart,
    safe_adjust_brightness,
    safe_adjust_volume,
    safe_lock_screen,
    safe_mute,
    safe_restart,
    safe_set_brightness,
    safe_set_volume,
    safe_shutdown,
    safe_sleep,
    safe_unmute,
    set_brightness,
    set_volume,
    shutdown,
    sleep,
    unmute,
)
from automation.system import (
    diagnostics as system_diagnostics,
)

# ============================================================================
# YouTube
# ============================================================================
from automation.youtube import (
    YouTubeError,
    YouTubeSearchResult,
    open_video,
)
from automation.youtube import (
    build_search_url as youtube_build_search_url,
)
from automation.youtube import (
    build_watch_url as youtube_build_watch_url,
)
from automation.youtube import (
    diagnostics as youtube_diagnostics,
)
from automation.youtube import (
    open_search as youtube_search,
)
from automation.youtube import (
    pause as youtube_pause,
)
from automation.youtube import (
    play_top_result as youtube_play,
)
from automation.youtube import (
    safe_open_search as safe_youtube_search,
)
from automation.youtube import (
    safe_play_top_result as safe_youtube_play,
)

# ============================================================================
# Package Diagnostics
# ============================================================================


def diagnostics() -> dict[str, object]:
    """
    Return a combined health/diagnostic report for the automation layer.

    This is useful for:
        - AssistantX startup checks
        - Settings/About page
        - Debugging
        - Developer diagnostics
    """
    return {
        "apps": apps_diagnostics(),
        "browser": browser_diagnostics(),
        "system": system_diagnostics(),
        "youtube": youtube_diagnostics(),
    }


# ============================================================================
# Package Metadata
# ============================================================================

PACKAGE_NAME = "automation"
PACKAGE_DESCRIPTION = "AssistantX desktop and OS automation layer"


# ============================================================================
# Public API
# ============================================================================

__all__ = [

    # ------------------------------------------------------------------------
    # Apps
    # ------------------------------------------------------------------------
    "AppAlias",
    "AppAutomationError",
    "AppCloseError",
    "AppInfo",
    "AppLaunchError",
    "AppNotFoundError",
    "AppResolution",
    "AppValidationError",
    "open_app",
    "close_app",
    "safe_open_app",
    "safe_close_app",
    "resolve_app",
    "resolve_app_command",
    "list_known_apps",
    "find_apps",
    "get_app_info",
    "is_app_available",
    "register_app",
    "unregister_app",
    "get_platform_name",

    # ------------------------------------------------------------------------
    # Browser
    # ------------------------------------------------------------------------
    "BrowserError",
    "BrowserBackendError",
    "BrowserValidationError",
    "BrowserInfo",
    "SearchEngine",
    "SearchEngineError",
    "open_url",
    "open_site",
    "search",
    "smart_open",
    "safe_open_url",
    "safe_open_site",
    "safe_search",
    "safe_smart_open",
    "is_url_like",
    "normalize_url",
    "build_search_url",
    "get_browser_info",
    "browser_is_available",
    "get_search_engine",
    "list_search_engines",
    "register_search_engine",
    "register_site",

    # ------------------------------------------------------------------------
    # Calculator
    # ------------------------------------------------------------------------
    "CalculationError",
    "CalculationResult",
    "ConversionResult",
    "UnitDefinition",
    "UnitConversionError",
    "UnsupportedUnitError",
    "IncompatibleUnitError",
    "evaluate_expression",
    "calculate",
    "format_result",
    "convert_units",
    "convert",
    "list_units",

    # ------------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------------
    "ClipboardError",
    "ClipboardBackendError",
    "ClipboardValidationError",
    "ClipboardReadError",
    "ClipboardWriteError",
    "ClipboardInfo",
    "copy_text",
    "paste_text",
    "clear_clipboard",
    "has_text",
    "get_text_length",
    "get_preview",
    "get_clipboard_info",
    "safe_copy_text",
    "safe_paste_text",

    # ------------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------------
    "FileOperationError",
    "FileValidationError",
    "FileNotFoundError",
    "FileAlreadyExistsError",
    "FileSafetyError",
    "FileReadError",
    "FileWriteError",
    "FileSearchResult",
    "FileInfo",
    "create_file",
    "delete_file",
    "rename_file",
    "move_file",
    "copy_file",
    "search_files",
    "search_file_paths",
    "read_text_file",
    "write_text_file",
    "append_text_file",
    "file_exists",
    "is_file",
    "is_directory",
    "get_file_info",
    "safe_create_file",
    "safe_delete_file",
    "safe_rename_file",
    "safe_move_file",
    "safe_copy_file",
    "safe_read_text_file",
    "safe_write_text_file",

    # ------------------------------------------------------------------------
    # Folders
    # ------------------------------------------------------------------------
    "FolderOperationError",
    "FolderValidationError",
    "FolderSafetyError",
    "FolderNotFoundError",
    "FolderEntry",
    "FolderInfo",
    "create_folder",
    "delete_folder",
    "open_folder",
    "list_folder_contents",
    "list_folder_contents_dict",
    "get_folder_info",
    "get_folder_size",
    "get_well_known_folder",
    "folder_exists",
    "normalize_path",
    "rename_folder",
    "move_folder",
    "search_folders",
    "safe_create_folder",
    "safe_delete_folder",
    "safe_open_folder",
    "safe_move_folder",

    # ------------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------------
    "KeyboardAutomationError",
    "KeyboardBackendError",
    "KeyboardValidationError",
    "type_text",
    "press_key",
    "press_hotkey",
    "hold_key",
    "kb_copy",
    "kb_paste",
    "kb_cut",
    "kb_find",
    "undo",
    "redo",
    "select_all",
    "save",
    "find",
    "switch_window",
    "new_tab",
    "refresh",
    "enter",
    "escape",

    # ------------------------------------------------------------------------
    # Mouse
    # ------------------------------------------------------------------------
    "MouseAutomationError",
    "MouseBackendError",
    "MouseValidationError",
    "Point",
    "get_position",
    "get_screen_size",
    "move_to",
    "move_relative",
    "click",
    "double_click",
    "right_click",
    "drag_to",
    "scroll",
    "scroll_horizontal",
    "safe_move_to",
    "safe_click",
    "safe_double_click",
    "safe_right_click",
    "safe_scroll",

    # ------------------------------------------------------------------------
    # Music
    # ------------------------------------------------------------------------
    "MusicControlError",
    "MusicBackendError",
    "MusicValidationError",
    "SpotifyError",
    "SpotifyTrack",
    "SpotifyDevice",
    "SpotifyController",
    "spotify",
    "play_music",
    "pause_music",
    "resume_music",
    "next_music_track",
    "previous_music_track",
    "search_and_play",
    "volume_up",
    "volume_down",
    "volume_mute",
    "safe_play_music",
    "safe_pause_music",
    "safe_resume_music",
    "safe_next_music_track",
    "safe_previous_music_track",

    # Backward compatibility
    "music_play",
    "music_pause",
    "music_next",
    "music_previous",

    # ------------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------------
    "NotificationError",
    "NotificationBackendError",
    "NotificationValidationError",
    "NotificationRequest",
    "notify",
    "safe_notify",
    "notify_info",
    "notify_success",
    "notify_warning",
    "notify_error",
    "notify_reminder",
    "notify_task_completed",
    "notify_download_completed",
    "notify_update_available",
    "notify_system_event",

    # ------------------------------------------------------------------------
    # Screenshots
    # ------------------------------------------------------------------------
    "ScreenshotError",
    "ScreenshotBackendError",
    "ScreenshotValidationError",
    "ScreenshotSaveError",
    "ScreenshotInfo",
    "Region",
    "capture_fullscreen",
    "capture_region",
    "capture_active_window",
    "screenshot",
    "screenshot_region",
    "screenshot_active_window",
    "safe_capture_fullscreen",
    "safe_capture_region",
    "safe_capture_active_window",
    "get_screenshot_directory",
    "list_screenshots",
    "delete_screenshot",
    "get_screen_size",

    # ------------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------------
    "SystemControlError",
    "SystemOperationError",
    "SystemValidationError",
    "shutdown",
    "restart",
    "sleep",
    "lock_screen",
    "set_volume",
    "adjust_volume",
    "mute",
    "unmute",
    "set_brightness",
    "adjust_brightness",
    "get_volume",
    "get_brightness",
    "safe_shutdown",
    "safe_restart",
    "safe_sleep",
    "safe_lock_screen",
    "safe_set_volume",
    "safe_adjust_volume",
    "safe_mute",
    "safe_unmute",
    "safe_set_brightness",
    "safe_adjust_brightness",

    # ------------------------------------------------------------------------
    # YouTube
    # ------------------------------------------------------------------------
    "YouTubeError",
    "YouTubeSearchResult",
    "youtube_search",
    "youtube_play",
    "youtube_build_search_url",
    "youtube_build_watch_url",
    "open_video",
    "youtube_pause",
    "safe_youtube_search",
    "safe_youtube_play",

    # ------------------------------------------------------------------------
    # Package
    # ------------------------------------------------------------------------
    "PACKAGE_NAME",
    "PACKAGE_DESCRIPTION",
    "diagnostics",
]
