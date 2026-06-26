# Jarvis Master / Shail

This repository contains the `jarvis_master` codebase which powers the Shail application, its backend services, native integrations, and browser extensions.

## Repository Structure

- `apps/`: Core application services, UI, and scripts (Python/Next.js).
- `shail/`: Python backend, Langgraph logic, vector store (Chroma), and agent reasoning systems.
- `shail-extension/`: A browser extension (built with WXT) for screen and API capture, bridging web context to the Jarvis ecosystem.
- `native/`: macOS and cross-platform native binaries (e.g., MemoryWatchdog) for deeper system integration.
- `scripts/`: Assorted shell and Python scripts for setup, health checks, deduplication, testing, and lifecycle management.

## Capabilities

- **Browser & API Capture:** Extracts conversations and page context to enrich AI intelligence.
- **RAG & Vector Memory:** Robust persistence layer (ChromaDB & SQLite) for memory and active capture retrieval.
- **Agent Reasoning:** Leveraging Langgraph and specialized tools to analyze user context and assist intelligently.
- **Native Watchdogs:** Telemetry and memory management integrated on the system level.

## Getting Started

Check out the scripts in the root directory for setup, such as `setup_permissions.sh`, `start_shail.sh`, or `setup_langgraph.sh`.

## Data Upgrade Features
Current capabilities implemented on the DATA-UPGRADE-BRANCH branch include various memory enhancements, pipeline status components, native integrations, and advanced extraction logic for various AI web endpoints.
