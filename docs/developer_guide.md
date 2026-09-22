# AssistantX Developer Guide

Welcome to the AssistantX Developer Guide.

This document explains how to set up the development environment, understand the project structure, follow coding conventions, add new features, work with the database, implement AI/voice/automation modules, write tests, and prepare AssistantX for production builds.

---

## 1. Purpose

AssistantX is designed as a modular Windows desktop AI assistant.

The project follows a clean, layered architecture so that individual systems can be developed, tested, replaced, or extended without unnecessarily affecting the rest of the application.

The primary development goals are:

- Maintainable code
- Modular architecture
- Clear separation of responsibilities
- Testable components
- Safe database operations
- Replaceable AI providers
- Extensible voice and automation systems
- Professional desktop application structure
- Easy future plugin integration

---

# 2. Development Environment

## 2.1 Recommended Environment

Recommended development environment:

- OS: Windows 10/11
- Python: 3.11+
- IDE: VS Code
- Database: SQLite
- Version Control: Git
- Package Manager: pip
- Virtual Environment: `venv`

---

## 2.2 Clone or Create the Project

The project root should contain:

```text
AssistantX/
├── main.py
├── launcher.py
├── setup.py
├── build_exe.py
├── requirements.txt
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
│
├── assets/
│
├── config/
├── core/
├── brain/
├── ai/
├── voice/
├── automation/
├── dashboard/
│
├── database/
│   └── sqlite/
│
├── docs/
│
└── tests/
