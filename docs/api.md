# AssistantX API Documentation

> **AssistantX** — Modular Windows AI Assistant  
> API reference and developer integration guide.

---

## Table of Contents

- [1. Overview](#1-overview)
- [2. Architecture](#2-architecture)
- [3. Core API](#3-core-api)
  - [3.1 Assistant](#31-assistant)
  - [3.2 History](#32-history)
  - [3.3 Memory](#33-memory)
  - [3.4 Scheduler](#34-scheduler)
- [4. Database API](#4-database-api)
  - [4.1 DatabaseManager](#41-databasemanager)
  - [4.2 Conversations](#42-conversations)
  - [4.3 Messages](#43-messages)
  - [4.4 Memories](#44-memories)
  - [4.5 Tasks](#45-tasks)
  - [4.6 Settings](#46-settings)
  - [4.7 Commands](#47-commands)
  - [4.8 Profile](#48-profile)
  - [4.9 Cache](#49-cache)
- [5. AI API](#5-ai-api)
- [6. Voice API](#6-voice-api)
- [7. Automation API](#7-automation-api)
- [8. Configuration API](#8-configuration-api)
- [9. Error Handling](#9-error-handling)
- [10. Development Guidelines](#10-development-guidelines)
- [11. Versioning](#11-versioning)

---

# 1. Overview

AssistantX uses a modular architecture where each major feature is isolated into its own package.

The main API layers are:

```text
Application
    │
    ├── Core
    │   ├── Assistant
    │   ├── History
    │   ├── Memory
    │   └── Scheduler
    │
    ├── AI
    │   ├── Provider
    │   ├── Gemini
    │   └── Ollama
    │
    ├── Voice
    │   ├── Input
    │   └── Output
    │
    ├── Automation
    │   ├── System
    │   ├── Browser
    │   └── Applications
    │
    ├── Database
    │   └── SQLite
    │
    └── Dashboard
        └── Desktop UI