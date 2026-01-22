# Open-Source Credits & Acknowledgements

SHAIL is built on the work of many open-source projects and communities. This section acknowledges those contributions and clarifies what is open-source versus proprietary in SHAIL.

---

## Open-Source Foundation

SHAIL's architecture and many of its capabilities depend on open-source software. We are grateful to the developers and maintainers who make this possible.

---

## Core Frameworks and Libraries

### FastAPI
**License:** MIT  
**Purpose in SHAIL:** Web framework for API services  
**Acknowledgement:** FastAPI provides the foundation for SHAIL's REST API. We use it for its excellent async support and automatic documentation generation.

### Uvicorn
**License:** BSD  
**Purpose in SHAIL:** ASGI server  
**Acknowledgement:** Uvicorn serves SHAIL's FastAPI applications with high performance.

### Pydantic
**License:** MIT  
**Purpose in SHAIL:** Data validation and settings management  
**Acknowledgement:** Pydantic ensures type safety and validation throughout SHAIL's API layer.

### LangChain
**License:** MIT  
**Purpose in SHAIL:** LLM orchestration and agent patterns  
**Acknowledgement:** LangChain provides the abstractions that structure SHAIL's agent architecture and tool integration patterns.

### FastMCP
**License:** Apache-2.0  
**Purpose in SHAIL:** MCP server implementation  
**Acknowledgement:** FastMCP enables SHAIL's universal tool integration layer. We use it to build MCP-compliant tool servers.

### Redis
**License:** BSD  
**Purpose in SHAIL:** Task queue and coordination  
**Acknowledgement:** Redis powers SHAIL's asynchronous task processing. We use the open-source Redis server.

### SQLite
**License:** Public Domain  
**Purpose in SHAIL:** Local database storage  
**Acknowledgement:** SQLite provides zero-configuration database storage for SHAIL's local data.

### ChromaDB
**License:** Apache-2.0  
**Purpose in SHAIL:** Vector database for RAG (when used)  
**Acknowledgement:** ChromaDB provides lightweight vector storage for SHAIL's memory system.

### pgvector
**License:** PostgreSQL License (similar to MIT/BSD)  
**Purpose in SHAIL:** Vector extension for PostgreSQL  
**Acknowledgement:** pgvector enables PostgreSQL to store and query vector embeddings for SHAIL's RAG system.

---

## Desktop Control Libraries

### PyAutoGUI
**License:** BSD  
**Purpose in SHAIL:** Mouse and keyboard automation  
**Acknowledgement:** PyAutoGUI enables SHAIL to interact with desktop applications through mouse and keyboard control.

### pynput
**License:** LGPL  
**Purpose in SHAIL:** Input device control  
**Acknowledgement:** pynput provides additional desktop control capabilities, especially on macOS.

### PyObjC
**License:** MIT  
**Purpose in SHAIL:** macOS AppKit integration  
**Acknowledgement:** PyObjC enables SHAIL to access native macOS APIs for window management.

---

## Data Processing

### NumPy
**License:** BSD  
**Purpose in SHAIL:** Numerical computing  
**Acknowledgement:** NumPy provides the foundation for numerical operations used by SHAIL's tool integrations.

### Pillow (PIL)
**License:** HPND (Historical Permission Notice and Disclaimer)  
**Purpose in SHAIL:** Image processing  
**Acknowledgement:** Pillow enables SHAIL to process images for vision features and screen analysis.

---

## Utilities

### python-dotenv
**License:** BSD  
**Purpose in SHAIL:** Environment variable management  
**Acknowledgement:** python-dotenv simplifies configuration management in SHAIL.

### requests
**License:** Apache-2.0  
**Purpose in SHAIL:** HTTP client  
**Acknowledgement:** requests provides simple HTTP client functionality for API integrations.

### aiohttp
**License:** Apache-2.0  
**Purpose in SHAIL:** Async HTTP client  
**Acknowledgement:** aiohttp enables asynchronous HTTP requests in SHAIL's async architecture.

### httpx
**License:** BSD  
**Purpose in SHAIL:** Async HTTP client  
**Acknowledgement:** httpx provides modern async HTTP client capabilities.

---

## Voice and Audio (When Enabled)

### LiveKit
**License:** Apache-2.0  
**Purpose in SHAIL:** Real-time communication platform  
**Acknowledgement:** LiveKit provides the infrastructure for SHAIL's voice interaction features (when enabled).

### OpenAI Whisper
**License:** MIT  
**Purpose in SHAIL:** Speech recognition (when used)  
**Acknowledgement:** Whisper provides high-quality, open-source speech recognition capabilities.

---

## AI Models and Services

### Google Gemini API
**Category:** Proprietary Service  
**Purpose in SHAIL:** LLM and embeddings  
**Note:** Google Gemini is a proprietary API service. SHAIL uses it but does not claim ownership or modification of the model itself.

### Google Cloud Speech-to-Text / Text-to-Speech
**Category:** Proprietary Service  
**Purpose in SHAIL:** Voice features (when enabled)  
**Note:** These are proprietary Google Cloud services. SHAIL integrates with them but does not claim ownership.

---

## What SHAIL Adds

SHAIL's value is in:
- **Orchestration logic:** How agents coordinate, how tasks are decomposed, how tools are selected
- **Integration architecture:** The MCP-based system that connects diverse tools
- **Memory system:** The RAG implementation that maintains context
- **Safety workflows:** The approval and permission systems
- **Agent patterns:** The multi-agent architecture and routing logic

These are SHAIL's contributions, built on top of open-source foundations.

---

## License Compatibility

SHAIL's use of open-source libraries is compatible with their respective licenses:
- **MIT/BSD licenses:** Permissive, allow commercial use
- **Apache-2.0:** Permissive, requires attribution
- **LGPL:** Requires derivative works to be LGPL (pynput is used as a library, not modified)

SHAIL does not modify most open-source libraries; it uses them as dependencies. Where modifications are made, they will be documented and contributed back where appropriate.

---

## Contributing Back

SHAIL benefits from open-source software, and we aim to contribute back:
- Bug reports and fixes to upstream projects
- Documentation improvements
- Feature contributions where relevant
- Open-sourcing SHAIL components where appropriate

---

## Transparency Statement

SHAIL is transparent about its dependencies. All open-source libraries are listed in `requirements.txt` files with their versions. This documentation provides context for why each is used.

We do not claim ownership of open-source tools. We use them responsibly, credit them appropriately, and contribute back when possible.

---

## Questions About Licensing

If you have questions about SHAIL's use of open-source software or licensing, please contact the SHAIL team. We are committed to responsible open-source usage and compliance.

---

*This list reflects SHAIL's current dependencies. As SHAIL evolves, dependencies may change. Check `requirements.txt` files in the codebase for the most current list.*
