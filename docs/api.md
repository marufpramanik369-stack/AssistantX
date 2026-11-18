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

## 1. Overview

AssistantX uses a modular architecture where each major feature is isolated into its own package.

## 2. Architecture

AssistantX is built as a modular system, with each major capability isolated into a separate package or layer. This separation helps keep the application maintainable, testable, and extensible as new features are introduced.

## 3. Core API

### 3.1 Assistant

Documentation for the central assistant runtime and orchestration interface.

### 3.2 History

Documentation for conversation history storage and retrieval APIs.

### 3.3 Memory

Documentation for short- and long-term memory management APIs.

### 3.4 Scheduler

Documentation for task scheduling and background execution APIs.

## 4. Database API

### 4.1 DatabaseManager

Database lifecycle and connection management API.

### 4.2 Conversations

Conversation record access and management API.

### 4.3 Messages

Message storage and query API.

### 4.4 Memories

Persistent memory records API.

### 4.5 Tasks

Task persistence and execution status API.

### 4.6 Settings

Application settings and configuration storage API.

### 4.7 Commands

Command metadata and execution history API.

### 4.8 Profile

User profile and preference API.

### 4.9 Cache

Temporary cache and performance data API.

## 5. AI API

AI provider, model, and inference integration details.

## 6. Voice API

Speech input and output integration details.

## 7. Automation API

System, browser, and app automation APIs.

## 8. Configuration API

Runtime configuration and device setup APIs.

## 9. Error Handling

Common failure modes and error response conventions.

## 10. Development Guidelines

Implementation standards and contributor guidance.

## 11. Versioning

API version compatibility and release tracking guidelines.

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
