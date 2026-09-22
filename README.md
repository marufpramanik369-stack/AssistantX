# AssistantX

<p align="center">
  <strong>AssistantX</strong>
</p>

<p align="center">
  A modular, extensible and intelligent desktop AI assistant built with Python.
</p>

<p align="center">
  <em>AI • Voice • Automation • Memory • Services • Productivity</em>
</p>

<p align="center">

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=for-the-badge)](#platform-support)
[![Status](https://img.shields.io/badge/Status-Active%20Development-orange?style=for-the-badge)](#project-status)

</p>

---

## Overview

**AssistantX** is a modular desktop AI assistant designed to combine conversational AI, voice interaction, desktop automation, memory, web services, and a modern graphical interface into a single application.

The project is designed with a layered architecture so that AI providers, automation modules, services, voice systems, database components, and UI components can evolve independently.

AssistantX can work with cloud AI providers as well as local AI backends, making it possible to run the assistant with minimal or no recurring AI API cost when using supported local models.

---

## Features

### AI & Conversation

- Multiple AI provider support
- Google Gemini integration
- Ollama local AI integration
- Local AI provider architecture
- Conversation history
- Context management
- Prompt engineering
- Intent classification
- Decision engine
- Response generation
- Configurable AI temperature
- Configurable model selection
- Provider fallback architecture

### Voice Assistant

- Speech recognition
- Text-to-speech
- Wake-word support
- Voice command processing
- Multiple language support
- Noise filtering architecture
- Automatic voice responses

### Desktop Automation

AssistantX is designed to interact with the local computer through modular automation components.

Supported automation areas include:

- Application launching
- Application closing
- Browser control
- File operations
- Folder operations
- Keyboard automation
- Mouse automation
- Clipboard management
- Screenshots
- System controls
- Media controls
- YouTube integration
- Desktop notifications
- Calculator and unit conversion

### Web & External Services

The service layer is designed to support:

- Web search
- Weather information
- News
- Wikipedia
- Translation
- Email
- Reminders
- Application update checking

External services can be enabled or disabled independently through configuration.

### Memory & Data

AssistantX includes architecture for:

- Conversation history
- Long-term memory
- User profile
- Application settings
- Scheduled tasks
- Command storage
- SQLite database
- JSON-based local data
- Runtime cache

### Modern Dashboard

The dashboard architecture supports:

- Dark theme
- Light theme
- Animated interface
- Chat interface
- Sidebar
- Message bubbles
- Typing indicators
- Splash screen
- Profile section
- Settings
- Dialogs
- Particle effects
- UI transitions
- Custom widgets

### Plugin System

AssistantX includes a plugin architecture intended to support:

- Custom commands
- Extensions
- Third-party plugins
- Modular feature loading
- Future community extensions

---

# Architecture

AssistantX follows a modular layered architecture.

```text
                         ┌─────────────────────┐
                         │       User          │
                         └──────────┬──────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │      Dashboard / Voice      │
                     └──────────────┬──────────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │        Core Assistant       │
                     └──────────────┬──────────────┘
                                    │
                     ┌──────────────▼──────────────┐
                     │            Brain            │
                     │ Intent • Context • Decision │
                     └──────────────┬──────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼────────┐   ┌────────▼────────┐   ┌──────▼───────┐
      │   AI Providers │   │    Services     │   │ Automation   │
      └───────┬────────┘   └────────┬────────┘   └──────┬───────┘
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                         ┌──────────▼──────────┐
                         │ Operating System / │
                         │ Internet / Database│
                         └─────────────────────┘

                         