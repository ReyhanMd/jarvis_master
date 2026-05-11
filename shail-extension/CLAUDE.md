# SHAIL — Project Context for Claude Code

## What This Project Is
SHAIL is a local-first AI orchestration and memory system. 
Chrome Extension (WXT/TypeScript) + FastAPI backend (Python) + ChromaDB + SQLite.
65-70% built. Do NOT redesign architecture. Evolve incrementally.

## The #1 Priority Right Now
Sprint 1: Canonical session continuity. 
Build `session-buffer.ts`. Eliminate `turns.slice(-maxTurns)` sliding window.
Everything downstream depends on this being correct first.

## What You Must Never Touch
- `observeWithStability` — do not modify
- `importance.ts` — do not modify  
- `LangGraphExecutor` and all agents — they must stay ignorant of memory storage
- `FastMCP` layer — do not touch
- WAL-mode SQLite setup — already correct

## Repository Structure
[let /init fill this in from your actual repo]

## Active Sprint
SPRINT 1 — Canonical Session Buffer
See: SHAIL_Implementation_Execution_Plan_v3.md Sprint 1 section for full details.