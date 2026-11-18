"""
AssistantX Dashboard - Main Entry Point
========================================

Enables running dashboard as a Python package:
    python -m dashboard

This module provides the entry point for launching the dashboard
application directly from the package.

Example
-------
>>> # Run from anywhere in the project
>>> python -m dashboard

Version: 1.0.0
"""

if __name__ == "__main__":
    from dashboard.app import main
    exit(main())
    