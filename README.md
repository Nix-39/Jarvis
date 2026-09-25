# Jarvis — Local-First Agent Operating System

A modular, security-first AI operating system that runs entirely on local hardware. Built for personal use, business automation and as a software architecture portfolio project.

Jarvis coordinates seven specialized AI agents behind a single orchestrator, with both short-term and long-term memory, using local models via [Ollama](https://ollama.com). Nothing leaves the machine. The architecture is built first and functionality is added incrementally on top of it, with every component verified before the next one starts.

## What Jarvis does

Jarvis is designed to become a "second brain": an assistant that remembers, finds old information by meaning, and eventually reminds and acts on its own.

- **Routes requests** to the right specialist agent (business, career, web development, education, social media, content creation, general).
- **Short-term memory:** each agent sees the latest turns of its own conversation.
- **Long-term memory:** semantic search across *all* past conversations, across all agents, so something mentioned weeks ago to one agent can be found by another.
- **Personal knowledge base:** drop documents (`.txt`, `.md`, `.pdf`, `.docx`) into category folders and the agents use relevant passages when answering.
- **Business support** for [VerkstadsFlow](https://www.verkstadsflow.se), a web agency for automotive workshops.

## Architecture

```
                                       User (chat)
                                            │
                                            ▼
                                   Jarvis Orchestrator
                                            │
                        ┌───────────────────┤
                        ▼                   ▼
                     Router              Planner
                    (intent)       (timeouts, retries)
                                            │
     ┌────────────┬────────────┬────────────┼────────────┬────────────┬────────────┐
     ▼            ▼            ▼            ▼            ▼            ▼            ▼
 Business      Career       WebDev      Education     General    SocialMedia    Content
     └────────────┴────────────┴────────────┼────────────┴────────────┴────────────┘
                                            ▼
                                        Services
      ┌───────────────────────┬─────────────┴─────────────┬───────────────────────┐
      ▼                       ▼                           ▼                       ▼
PromptLoader            OllamaService               MemoryService           VectorService
                       (chat + embed)               (short-term)             (long-term)
                                                       SQLite                 ChromaDB
                                                          │                       ▲
                                                          └───── synced into ─────┘
```

**Separation of concerns:**

- **Router:** intent classification only. Outputs a validated domain category.
- **Orchestrator:** the single entry point. Owns the mapping from categories to agents and creates the shared services.
- **Planner:** executes agent steps thread-safely with timeouts and retries via the `Agent` protocol (`handle`).
- **Agents:** domain logic only. They never talk to external systems directly.
- **Services:** infrastructure only (LLM calls, prompts, memory, vector search).

## Memory design

| | Short-term memory | Long-term memory |
|---|---|---|
| Service | `MemoryService` | `VectorService` |
| Storage | SQLite (`data/jarvis_memory.db`) | ChromaDB (`data/vector_store/`) |
| Scope | Last 8 messages, per agent | All conversations (all agents) + documents |
| Lookup | Chronological | Semantic (embeddings, cosine distance) |

Key decisions:

- **SQLite is the single source of truth.** The vector index is derived data. A self-healing sync indexes new messages, drops deleted ones and re-indexes new or changed documents, so nothing is lost if an embedding call fails.
- **Changing the embedding model triggers an automatic full re-index**, because vectors from different models are not comparable.
- **Fail-soft:** if long-term memory is unavailable, agents still answer, just without background context.
- **Guardrails on retrieval:** at most 3 conversation hits and 3 document hits per request, a relevance cutoff (`VECTOR_MAX_DISTANCE`), and no duplicates of what is already in short-term memory.

## Tech stack

| Component | Details |
|---|---|
| Language | Python 3.13 |
| Chat model | `qwen3:8b` via Ollama (configurable) |
| Embedding model | `qwen3-embedding:0.6b` via Ollama (multilingual, incl. Swedish) |
| Short-term memory | SQLite, WAL mode, one connection per thread |
| Long-term memory | ChromaDB (persistent, telemetry disabled) |
| Documents | `pypdf`, `python-docx` |
| Config/secrets | `.env` (never committed) + `core/config.py` |
| Logging | Centralized rotating file logs, plan IDs for tracing |
| Hardware (dev) | AMD Ryzen 9 3900X · 32 GB RAM · NVIDIA RTX 3060 12 GB |

## Project structure

```
jarvis/
├── jarvis.bat              # Start the chat (uses .venv automatically)
├── .env.example            # Configuration template (copy to .env)
├── requirements.txt
│
├── agents/                 # Domain-specific logic, one file per agent
├── core/
│   ├── config.py           # Settings and paths (self-creating folders)
│   ├── logger.py
│   ├── orchestrator.py     # Entry point + interactive chat
│   ├── planner.py
│   └── router.py
├── prompts/                # Static system prompts, one per agent + router
├── services/
│   ├── ollama_service.py   # chat() + embed()
│   ├── prompt_loader.py
│   ├── memory_service.py   # Short-term memory (SQLite)
│   └── vector_service.py   # Long-term memory + documents (ChromaDB)
│
├── data/                   # Private runtime data (gitignored)
│   ├── documents/          # Your documents, organized in category folders
│   ├── jarvis_memory.db
│   └── vector_store/
└── logs/                   # Rotating log files (gitignored)
```

## Getting started (Windows)

1. Clone the repo and create a virtual environment:
   ```powershell
   git clone https://github.com/Nix-39/jarvis.git
   cd jarvis
   py -3.13 -m venv .venv
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
2. Create your configuration:
   ```powershell
   copy .env.example .env
   ```
3. Install [Ollama](https://ollama.com) and pull the models:
   ```powershell
   ollama pull qwen3:8b
   ollama pull qwen3-embedding:0.6b
   ```
4. Start Jarvis: double-click `jarvis.bat`, or run it from a terminal:
   ```powershell
   .\jarvis
   ```
   No venv activation is needed. Type your message after `Du >`, and type `exit` to quit. Add `--verbose` to see all logs in the terminal.

## Using long-term memory

Put documents in `data/documents/`, organized in subfolders of any depth:

```
data/documents/
├── skola/python/anteckningar.pdf
├── verkstadsflow/kunder/offert_nilsson.docx
└── karriar/cv.docx
```

New, changed and deleted files are picked up automatically. Useful commands:

```powershell
.venv\Scripts\python -m services.vector_service                  # sync + statistics
.venv\Scripts\python -m services.vector_service --search "text"  # test a search, shows distances
.venv\Scripts\python -m services.vector_service --rebuild        # wipe and rebuild the index
```

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_MODEL` | `llama3.1:8b` | Chat model |
| `OLLAMA_EMBED_MODEL` | `qwen3-embedding:0.6b` | Embedding model for long-term memory |
| `OLLAMA_THINK` | `false` | Reasoning mode for models that support it (slower, deeper) |
| `AGENT_TIMEOUT_SECONDS` | `120` | Max time per agent step before the Planner retries |
| `VECTOR_MAX_DISTANCE` | `0.55` | Relevance cutoff for long-term memory (lower = stricter) |
| `LOG_LEVEL` | `INFO` | Log verbosity |

## Status

| Component | Status |
|---|---|
| Config, Logger, PromptLoader, OllamaService | ✅ Verified |
| Router, Planner, Orchestrator | ✅ Verified & tested |
| 7 specialist agents | ✅ Verified |
| MemoryService (short-term memory) | ✅ Verified |
| VectorService (long-term memory + documents) | ✅ Verified |
| Interactive chat + `jarvis.bat` launcher | ✅ Verified |
| Scheduler & reminders | 📋 Planned (next) |
| Notifications / mobile access | 📋 Planned |
| Voice (speech-to-text, text-to-speech) | 📋 Planned |
| Social media analytics | 📋 Planned |

## Design principles

- **Local-first and private:** all models run locally, telemetry is disabled, and private data in `data/` is never committed.
- **Zero Trust:** no hardcoded credentials, secrets only in `.env`, and registry lookups validated before execution.
- **Fail-fast validation, fail-soft features:** invalid input is rejected early, and optional features degrade gracefully instead of crashing a reply.
- **Infrastructure first, functionality second:** verified components stay stable unless there is a clear architectural reason to change them.
- **Strict 4-tier naming standard** across domain categories, agent IDs, modules and classes.

## License

TBD
