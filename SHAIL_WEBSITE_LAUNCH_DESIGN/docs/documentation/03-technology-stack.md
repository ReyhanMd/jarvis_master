# Technology Stack

This section documents all technologies used in SHAIL, organized by category. For each technology, we explain what it is, why it's used, and what role it plays in SHAIL.

---

## AI Models

### Google Gemini
**Category:** Large Language Model (LLM)  
**Purpose in SHAIL:** Primary reasoning engine for the Master Planner and agents  
**Reason for Selection:** Strong performance on reasoning tasks, reliable API, cost-effective for orchestration workloads  
**Role:** Powers task decomposition, agent selection, tool parameter generation, and natural language understanding

### Gemini Embeddings (text-embedding-004)
**Category:** Embedding Model  
**Purpose in SHAIL:** Generates vector embeddings for RAG memory system  
**Reason for Selection:** Consistent with Gemini ecosystem, high-quality embeddings for semantic search  
**Role:** Converts text (tool usage, project context, user intents) into vectors for similarity search

---

## APIs and Services

### Google Cloud Speech-to-Text
**Category:** Speech Recognition API  
**Purpose in SHAIL:** Converts voice input to text  
**Reason for Selection:** High accuracy, reliable API, integrates with Google ecosystem  
**Role:** Enables voice interaction with SHAIL (when voice features are enabled)

### Google Cloud Text-to-Speech
**Category:** Text-to-Speech API  
**Purpose in SHAIL:** Converts text responses to speech  
**Reason for Selection:** Natural-sounding voices, reliable API  
**Role:** Enables voice responses from SHAIL (when voice features are enabled)

---

## Infrastructure

### Redis
**Category:** In-Memory Data Store / Task Queue  
**Purpose in SHAIL:** Task queuing and coordination between services  
**Reason for Selection:** Fast, reliable, widely used for async task processing  
**Role:** Queues tasks from API to worker processes, enables asynchronous execution

### SQLite
**Category:** Embedded Database  
**Purpose in SHAIL:** Local storage for audit logs, task history, and structured data  
**Reason for Selection:** Zero-configuration, file-based, sufficient for local storage needs  
**Role:** Stores task execution history, approval logs, and other structured records

### PostgreSQL (with pgvector)
**Category:** Relational Database with Vector Extension  
**Purpose in SHAIL:** Vector store for RAG memory (when pgvector is configured)  
**Reason for Selection:** Robust database with native vector support, production-ready  
**Role:** Stores and queries vector embeddings for semantic search in RAG system

### ChromaDB
**Category:** Vector Database  
**Purpose in SHAIL:** Alternative vector store for RAG memory (fallback option)  
**Reason for Selection:** Lightweight, easy to set up, good for development and smaller deployments  
**Role:** Stores vector embeddings when PostgreSQL is not available

---

## Orchestration and Automation

### Model Context Protocol (MCP)
**Category:** Protocol / Standard  
**Purpose in SHAIL:** Universal adapter layer for tool integration  
**Reason for Selection:** Standard protocol for LLM-tool integration, enables consistent tool discovery and execution  
**Role:** All tools register via MCP, providing unified interface for agents to discover and use tools

### FastMCP
**Category:** MCP Implementation Library  
**Purpose in SHAIL:** Python library for building MCP servers and clients  
**Reason for Selection:** Well-maintained, Pythonic API, simplifies MCP integration  
**Role:** Provides the MCP server implementation that SHAIL uses to expose tools

### LangChain
**Category:** LLM Orchestration Framework  
**Purpose in SHAIL:** Provides abstractions for LLM interactions, tool calling, and agent patterns  
**Reason for Selection:** Mature framework, good abstractions, active development  
**Role:** Structures agent logic, LLM calls, and tool integration patterns

### LangChain Google GenAI
**Category:** LangChain Integration  
**Purpose in SHAIL:** Connects LangChain to Google Gemini API  
**Reason for Selection:** Official integration, maintained by LangChain team  
**Role:** Enables LangChain agents to use Google Gemini models

---

## Web Framework and API

### FastAPI
**Category:** Web Framework  
**Purpose in SHAIL:** REST API for SHAIL services  
**Reason for Selection:** Modern, fast, automatic API documentation, async support  
**Role:** Provides HTTP endpoints for task submission, status checking, and approval workflows

### Uvicorn
**Category:** ASGI Server  
**Purpose in SHAIL:** Runs FastAPI applications  
**Reason for Selection:** High performance, async support, standard for FastAPI  
**Role:** Serves the SHAIL API services

### Pydantic
**Category:** Data Validation Library  
**Purpose in SHAIL:** Type validation and settings management  
**Reason for Selection:** Strong typing, automatic validation, integrates with FastAPI  
**Role:** Validates API requests, manages configuration, ensures type safety

---

## Desktop Control

### PyAutoGUI
**Category:** Desktop Automation Library  
**Purpose in SHAIL:** Mouse and keyboard control, screen interaction  
**Reason for Selection:** Cross-platform, reliable, well-documented  
**Role:** Enables SHAIL to control mouse, keyboard, and interact with desktop applications

### pynput
**Category:** Input Control Library  
**Purpose in SHAIL:** Alternative/additional mouse and keyboard control  
**Reason for Selection:** Low-level control, good for macOS integration  
**Role:** Provides additional desktop control capabilities, especially on macOS

### PyObjC
**Category:** Python-Objective-C Bridge  
**Purpose in SHAIL:** macOS AppKit integration for window management  
**Reason for Selection:** Native macOS API access, required for advanced window control  
**Role:** Enables SHAIL to detect, move, resize, and manage macOS application windows

---

## Data Processing

### NumPy
**Category:** Numerical Computing Library  
**Purpose in SHAIL:** Numerical operations (used by dependencies and potential engineering tool integrations)  
**Reason for Selection:** Standard library for numerical computing in Python  
**Role:** Supports mathematical operations in tool integrations and data processing

### Pillow (PIL)
**Category:** Image Processing Library  
**Purpose in SHAIL:** Image manipulation and processing  
**Reason for Selection:** Standard Python image library, widely used  
**Role:** Processes images for vision features and screen capture analysis

---

## Utilities

### python-dotenv
**Category:** Configuration Management  
**Purpose in SHAIL:** Loads environment variables from .env files  
**Reason for Selection:** Simple, standard way to manage configuration  
**Role:** Manages API keys and configuration without hardcoding

### requests
**Category:** HTTP Client Library  
**Purpose in SHAIL:** HTTP requests to external APIs  
**Reason for Selection:** Standard Python HTTP library, simple API  
**Role:** Makes API calls to external services

### aiohttp / httpx
**Category:** Async HTTP Client Libraries  
**Purpose in SHAIL:** Asynchronous HTTP requests  
**Reason for Selection:** Async support for non-blocking API calls  
**Role:** Enables concurrent API requests in async contexts

---

## Voice and Audio (Optional Features)

### LiveKit
**Category:** Real-Time Communication Platform  
**Purpose in SHAIL:** Voice interaction infrastructure (when voice features are enabled)  
**Reason for Selection:** Production-ready real-time audio/video platform  
**Role:** Handles real-time voice streaming and processing

### LiveKit Agents
**Category:** LiveKit Integration  
**Purpose in SHAIL:** Agent framework for LiveKit voice interactions  
**Reason for Selection:** Official framework for building voice agents with LiveKit  
**Role:** Structures voice agent logic and audio processing

### OpenAI Whisper
**Category:** Speech Recognition Model  
**Purpose in SHAIL:** Alternative/local speech recognition (when configured)  
**Reason for Selection:** Open-source, can run locally, high accuracy  
**Role:** Provides local speech-to-text capabilities

---

## Development and Testing

### pytest
**Category:** Testing Framework  
**Purpose in SHAIL:** Unit and integration testing  
**Reason for Selection:** Standard Python testing framework  
**Role:** Enables automated testing of SHAIL components

---

## Notes on Technology Selection

**Open Standards First**
SHAIL prioritizes open standards (like MCP) and well-documented protocols. This enables integration with diverse tools and reduces vendor lock-in.

**Python Ecosystem**
SHAIL is built primarily in Python, leveraging the rich ecosystem of libraries for AI, web development, and system integration.

**Modularity**
Technologies are chosen to enable modularity. Components can be swapped (e.g., ChromaDB vs PostgreSQL for vectors) without changing core architecture.

**Production Readiness**
Technologies are selected for reliability and production use, not just prototyping. This includes proper error handling, logging, and monitoring capabilities.

---

## Version Information

Specific versions are managed through `requirements.txt` files in the SHAIL codebase. This documentation reflects the general technology choices; exact versions may vary by installation.

---

*This stack evolves as SHAIL develops. New tools and integrations are added through the MCP layer, maintaining architectural consistency.*
