"""
AssistantX - Python Package Setup
=================================

Professional setuptools configuration for AssistantX.

This file provides:
- Package metadata
- Dependency management
- Optional feature extras
- Console entry point
- Package/resource discovery
- Python version validation
- Development and build extras

Recommended installation:

    pip install -e .

Optional features:

    pip install -e ".[ai]"
    pip install -e ".[voice]"
    pip install -e ".[voice-pyaudio]"
    pip install -e ".[automation]"
    pip install -e ".[services]"
    pip install -e ".[database]"
    pip install -e ".[dev]"
    pip install -e ".[build]"
    pip install -e ".[all]"

Author: AssistantX Team
License: MIT
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from setuptools import find_packages, setup

# ============================================================================
# PROJECT PATHS
# ============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent

README_FILE = PROJECT_ROOT / "README.md"
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

PACKAGE_NAME = "assistantx"
DISPLAY_NAME = "AssistantX"

VERSION = "1.0.0"
MINIMUM_PYTHON = (3, 10)


# ============================================================================
# PYTHON VERSION VALIDATION
# ============================================================================


def validate_python_version() -> None:
    """
    Ensure AssistantX is running on a supported Python version.

    Raises:
        RuntimeError: If the installed Python version is unsupported.
    """

    current_version = sys.version_info[:2]

    if current_version < MINIMUM_PYTHON:
        required = ".".join(map(str, MINIMUM_PYTHON))
        current = ".".join(map(str, current_version))

        raise RuntimeError(
            f"{DISPLAY_NAME} requires Python {required} or newer. "
            f"Current Python version: {current}"
        )


# ============================================================================
# FILE HELPERS
# ============================================================================


def read_file(path: Path) -> str:
    """
    Read a UTF-8 text file safely.

    Args:
        path: File path.

    Returns:
        File contents, or an empty string if the file does not exist.
    """

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8")


def read_long_description() -> str:
    """
    Load the project README for PyPI/package metadata.
    """

    content = read_file(README_FILE)

    if content:
        return content

    return (
        "AssistantX - A modular desktop AI assistant "
        "with AI, voice, automation, services and dashboard support."
    )


# ============================================================================
# VERSION HELPERS
# ============================================================================


def validate_version(version: str) -> None:
    """
    Validate the project version.

    The version follows a standard semantic-style format such as:

        1.0.0
        1.2.3
        2.0.0rc1
        2.0.0.post1
    """

    pattern = re.compile(
        r"^\d+\.\d+\.\d+"
        r"(?:[a-zA-Z]+\d*)?"
        r"(?:\.\d+)?$"
    )

    if not pattern.match(version):
        raise RuntimeError(
            f"Invalid AssistantX version: {version!r}"
        )


# ============================================================================
# REQUIREMENTS
# ============================================================================


def read_requirements() -> list[str]:
    """
    Read dependencies from requirements.txt.

    The following lines are ignored:

    - Empty lines
    - Comments
    - Editable installs
    - Local file references
    - Requirement files
    """

    if not REQUIREMENTS_FILE.exists():
        return []

    dependencies: list[str] = []

    for raw_line in REQUIREMENTS_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        if line.startswith(("-r ", "--requirement ")):
            continue

        if line.startswith(("-e ", "--editable ")):
            continue

        if line.startswith((".", "/", "\\")):
            continue

        dependencies.append(line)

    return dependencies


# ============================================================================
# CORE DEPENDENCIES
# ============================================================================
#
# Keep runtime dependencies here if you do NOT want setup.py to depend
# entirely on requirements.txt.
#
# Currently requirements.txt is used as the main dependency source.
#


INSTALL_REQUIRES = read_requirements()


# ============================================================================
# OPTIONAL DEPENDENCIES
# ============================================================================
#
# IMPORTANT:
# PyAudio is intentionally NOT part of the normal voice extra.
#
# PyAudio may require native C/C++ build tools depending on the Python
# version and available wheels.
#
# Therefore:
#
#     pip install -e ".[voice]"
#
# does not force PyAudio.
#
# If PyAudio is specifically required:
#
#     pip install -e ".[voice-pyaudio]"
#
# ============================================================================


EXTRAS_REQUIRE = {
    # ------------------------------------------------------------------------
    # AI PROVIDERS
    # ------------------------------------------------------------------------
    "ai": [
        "google-genai>=1.0.0,<2.0.0",
        "ollama>=0.4.0,<1.0.0",
        "openai>=1.50.0,<2.0.0",
    ],

    # ------------------------------------------------------------------------
    # VOICE
    # ------------------------------------------------------------------------
    "voice": [
        "SpeechRecognition>=3.10.0,<4.0.0",
        "pyttsx3>=2.90,<3.0.0",
        "sounddevice>=0.5.0,<1.0.0",
        "soundfile>=0.12.0,<1.0.0",
    ],

    # ------------------------------------------------------------------------
    # PYAUDIO - OPTIONAL NATIVE DEPENDENCY
    # ------------------------------------------------------------------------
    "voice-pyaudio": [
        "PyAudio>=0.2.14,<1.0.0",
    ],

    # ------------------------------------------------------------------------
    # DESKTOP AUTOMATION
    # ------------------------------------------------------------------------
    "automation": [
        "PyAutoGUI>=0.9.54,<1.0.0",
        "pyperclip>=1.9.0,<2.0.0",
        "Pillow>=10.4.0,<13.0.0",
        "plyer>=2.1.0,<3.0.0",
    ],

    # ------------------------------------------------------------------------
    # WEB / ONLINE SERVICES
    # ------------------------------------------------------------------------
    "services": [
        "requests>=2.32.0,<3.0.0",
        "httpx>=0.27.0,<1.0.0",
        "beautifulsoup4>=4.12.0,<5.0.0",
        "wikipedia>=1.4.0,<2.0.0",
    ],

    # ------------------------------------------------------------------------
    # DATABASE
    # ------------------------------------------------------------------------
    "database": [
        "SQLAlchemy>=2.0.0,<3.0.0",
        "pydantic>=2.8.0,<3.0.0",
    ],

    # ------------------------------------------------------------------------
    # SCHEDULER / ASYNC
    # ------------------------------------------------------------------------
    "scheduler": [
        "APScheduler>=3.10.0,<4.0.0",
        "anyio>=4.4.0,<5.0.0",
    ],

    # ------------------------------------------------------------------------
    # SCIENTIFIC / EMBEDDINGS
    # ------------------------------------------------------------------------
    "ml": [
        "numpy>=1.26.0,<3.0.0",
        "scikit-learn>=1.4.0,<2.0.0",
    ],

    # ------------------------------------------------------------------------
    # DEVELOPMENT
    # ------------------------------------------------------------------------
    "dev": [
        "pytest>=8.3.0,<9.0.0",
        "pytest-cov>=5.0.0,<7.0.0",
        "ruff>=0.6.0,<1.0.0",
        "mypy>=1.11.0,<2.0.0",
    ],

    # ------------------------------------------------------------------------
    # BUILD / PACKAGING
    # ------------------------------------------------------------------------
    "build": [
        "pyinstaller>=6.10.0,<7.0.0",
        "build>=1.2.0,<2.0.0",
        "wheel>=0.44.0,<1.0.0",
        "setuptools>=70.0.0,<81.0.0",
    ],
}


# ============================================================================
# "ALL" EXTRA
# ============================================================================


def build_all_extra() -> list[str]:
    """
    Combine all optional extras into one dependency list.

    Duplicate dependencies are removed while preserving order.
    """

    combined: list[str] = []

    for dependencies in EXTRAS_REQUIRE.values():
        for dependency in dependencies:
            if dependency not in combined:
                combined.append(dependency)

    return combined


EXTRAS_REQUIRE["all"] = build_all_extra()


# ============================================================================
# PACKAGE DATA
# ============================================================================


PACKAGE_DATA = {
    PACKAGE_NAME: [
        # Configuration / resources
        "resources/**/*",

        # Language files
        "resources/languages/**/*",

        # Prompt templates
        "resources/prompts/**/*",

        # Templates
        "resources/templates/**/*",

        # Fonts
        "assets/fonts/**/*",

        # Themes
        "assets/themes/**/*",

        # Images
        "assets/images/**/*",

        # Sounds
        "assets/sounds/**/*",

        # Icons
        "assets/icons/**/*",
    ]
}


# ============================================================================
# EXCLUDED DIRECTORIES
# ============================================================================


EXCLUDED_PACKAGES = [
    "tests",
    "tests.*",
    "docs",
    "docs.*",
    "scripts",
    "scripts.*",
]


# ============================================================================
# PROJECT URLS
# ============================================================================


PROJECT_URLS = {
    "Homepage": "https://github.com/YOUR_USERNAME/AssistantX",
    "Repository": "https://github.com/YOUR_USERNAME/AssistantX",
    "Issues": "https://github.com/YOUR_USERNAME/AssistantX/issues",
    "Documentation": "https://github.com/YOUR_USERNAME/AssistantX/tree/main/docs",
}


# ============================================================================
# CLASSIFIERS
# ============================================================================


CLASSIFIERS = [
    # Development status
    "Development Status :: 4 - Beta",

    # Audience
    "Intended Audience :: End Users/Desktop",

    # License
    "License :: OSI Approved :: MIT License",

    # Programming language
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",

    # Operating systems
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX",
    "Operating System :: MacOS",

    # Topics
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Desktop Environment",
    "Topic :: Software Development :: Libraries",
]


# ============================================================================
# KEYWORDS
# ============================================================================


KEYWORDS = [
    "ai",
    "assistant",
    "desktop-assistant",
    "artificial-intelligence",
    "automation",
    "voice-assistant",
    "gemini",
    "ollama",
    "local-ai",
    "productivity",
    "python",
]


# ============================================================================
# VALIDATION
# ============================================================================


validate_python_version()
validate_version(VERSION)


# ============================================================================
# SETUP
# ============================================================================


setup(
    # ------------------------------------------------------------------------
    # Basic metadata
    # ------------------------------------------------------------------------
    name=PACKAGE_NAME,
    version=VERSION,
    description=(
        "AssistantX - A modular desktop AI assistant "
        "with voice, automation and local/cloud AI support."
    ),
    long_description=read_long_description(),
    long_description_content_type="text/markdown",

    # ------------------------------------------------------------------------
    # Author
    # ------------------------------------------------------------------------
    author="AssistantX Team",
    author_email="",

    # ------------------------------------------------------------------------
    # License
    # ------------------------------------------------------------------------
    license="MIT",

    # ------------------------------------------------------------------------
    # Project URLs
    # ------------------------------------------------------------------------
    url=PROJECT_URLS["Homepage"],
    project_urls=PROJECT_URLS,

    # ------------------------------------------------------------------------
    # Package discovery
    # ------------------------------------------------------------------------
    packages=find_packages(
        exclude=EXCLUDED_PACKAGES,
    ),

    include_package_data=True,
    package_data=PACKAGE_DATA,

    # ------------------------------------------------------------------------
    # Python requirement
    # ------------------------------------------------------------------------
    python_requires=">=3.10",

    # ------------------------------------------------------------------------
    # Runtime dependencies
    # ------------------------------------------------------------------------
    install_requires=INSTALL_REQUIRES,

    # ------------------------------------------------------------------------
    # Optional dependencies
    # ------------------------------------------------------------------------
    extras_require=EXTRAS_REQUIRE,

    # ------------------------------------------------------------------------
    # Console command
    # ------------------------------------------------------------------------
    entry_points={
        "console_scripts": [
            "assistantx=main:main",
        ],
    },

    # ------------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------------
    classifiers=CLASSIFIERS,
    keywords=KEYWORDS,

    # ------------------------------------------------------------------------
    # Zip safety
    # ------------------------------------------------------------------------
    zip_safe=False,
)

