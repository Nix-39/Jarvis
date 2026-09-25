# PROJECT SNAPSHOT
**Last updated:** 2026-09-25

---

# Project

**Jarvis - Local-First Agent Operating System**

A modular, security-first, local AI operating system built for personal use, business automation, and as a professional GitHub portfolio project.

Jarvis is designed to evolve into a Local-First AI Operating System capable of coordinating multiple specialized AI agents, persistent memory, external tools, business automation, voice interaction, mobile connectivity, analytics, and future multi-agent collaboration while maintaining a modular, security-first architecture.

The project is intentionally built for long-term scalability from the beginning rather than rapid prototyping.

---

# User & Business Context

## Owner

Robin, commonly called "Nix" (the origin of the business names).

### Background

- Recently graduated IT Security Developer / Cyber Security Specialist (IT-säkerhetsutvecklare) from a Higher Vocational Education (Yrkeshögskola).
- Currently seeking employment within Cyber Security or IT Support.
- Building Jarvis both as a personal AI operating system and as a professional portfolio project.
- Long-term goal is to demonstrate software architecture, AI orchestration, security engineering, automation, and maintainability.

---

# Business 1 — VerkstadsFlow

Website

https://www.verkstadsflow.se

Description

- Swedish web agency specialized in automotive workshops.
- Builds modern WordPress websites.
- Current production stack uses WordPress and Elementor.
- Integrates AI assistants into customer websites.
- Focus on automation, lead generation, performance, and maintainability.

Primary supporting agent

- BusinessAgent

---

# Business 2 — Nix Studio

Description

Independent creative studio.

Current goals

- Build the Nix Studio website.
- Sell custom hand-tufted rugs.
- Build a recognizable premium creative brand.

Primary supporting agents

- BusinessAgent
- ContentCreatorAgent
- SocialMediaManagerAgent

---

# Business 3 — The AI Duck

Description

Educational cybersecurity and AI brand.

Purpose

- Create educational content about cybersecurity.
- Explain online tracking and privacy.
- Explain AI technologies.
- Build authority within cybersecurity.
- Grow through YouTube, Instagram, Facebook and affiliate marketing.

Primary supporting agents

- ContentCreatorAgent
- SocialMediaManagerAgent
- EducationAgent

---

# Personal Brand

Purpose

- Professional portfolio.
- Technical blog.
- Cybersecurity expertise.
- Software architecture.
- Creative projects.

---

# Future Business Areas

- Affiliate Marketing
- YouTube
- Instagram
- Facebook
- TikTok
- Digital Products
- Courses
- Multiple online income streams

Dedicated agents and services will gradually automate these areas.

---

# Hardware & Environment

| Component | Specification |
|-----------|---------------|
| CPU | AMD Ryzen 9 3900X |
| RAM | 32 GB |
| GPU | NVIDIA RTX 3060 12 GB |
| Local LLM (chat) | qwen3:8b (thinking off by default) |
| Embedding model | qwen3-embedding:0.6b |
| Ollama | http://localhost:11434 |
| Vector DB | ChromaDB (local, telemetry off) |
| Python | 3.13.x |

Development language

Python

Conversation language

Swedish

Code language

English

Comments

English

Docstrings

English

Logs

English

---

# Architecture Philosophy

Build the final architecture from the beginning while implementing functionality incrementally.

Verified infrastructure should remain stable unless a clear architectural improvement exists.

---

# Core Architecture Decisions (ADR)

1. **Static Prompts vs. Application Logic:** Prompt files (`prompts/*.txt`) contain static system instructions and rules only. Dynamic runtime data (e.g., user requests, history context) is structured and injected by Python code.
2. **Router Scope:** Router performs intent classification only and outputs validated **Domain Categories**. Router contains no business logic, agent instantiation, or orchestrator mapping.
3. **Orchestrator Scope:** Orchestrator acts as the sole system entry point and owns the explicit mapping between **Domain Categories** and **Internal Agent IDs**.
4. **Planner Scope:** Planner works exclusively with **Internal Agent IDs** and coordinates thread-safe execution, timeouts, and retries using the `Agent` protocol interface (`handle`).
5. **Separation of Concerns:** Core performs orchestration only. Agents contain domain-specific business logic only. Services handle infrastructure and external integrations only. Core and Agents never communicate directly with external systems.
6. **Memory Source of Truth:** SQLite (MemoryService) is the single source of truth for conversations. The ChromaDB vector index (VectorService) is derived data, kept in sync by a self-healing sync and always rebuildable.
7. **Fail-Soft Optional Features:** Long-term memory must never break an agent reply. On failure, agents answer without background context.

Dependency direction

```
Core
    ↓
Services
    ↓
External Systems
```

```
Agents
    ↓
Services
    ↓
External Systems
```

---

# 4-Tier System Hierarchy & Naming Standard

Jarvis strictly enforces a 4-tier naming hierarchy to maintain zero ambiguity across components:

1. **Domain Category (Router Output):** `business`, `career`, `web_development`, `education`, `general`, `social_media`, `content_creation`
2. **Internal Agent ID (Orchestrator/Planner Key):** `business_agent`, `career_agent`, `webdeveloper_agent`, `education_agent`, `general_agent`, `socialmediamanager_agent`, `contentcreator_agent`
3. **Python Module (File Path):** `business_agent.py`, `career_agent.py`, `webdeveloper_agent.py`, `education_agent.py`, `general_agent.py`, `socialmediamanager_agent.py`, `contentcreator_agent.py`
4. **Python Class:** `BusinessAgent`, `CareerAgent`, `WebDeveloperAgent`, `EducationAgent`, `GeneralAgent`, `SocialMediaManagerAgent`, `ContentCreatorAgent`

---

# Verified Public APIs

To prevent API hallucination, all components must strictly interface with these verified public signatures:

* **`services.prompt_loader.PromptLoader`**
  `load(filename: str) -> str`
* **`services.ollama_service.OllamaService`**
  `chat(prompt: str) -> str`
  `embed(texts: List[str]) -> List[List[float]]`
* **`services.memory_service.MemoryService`**
  `create_session(session_id: str = "default") -> str`
  `get_session(session_id: str = "default") -> Optional[dict]`
  `save_message(session_id, role, content, agent_id=None, context=None, metadata=None) -> int`
  `get_session_messages(session_id="default", agent_id=None, context=None, limit=None) -> list[Message]`
  `get_messages_after(after_id: int = 0, limit=None) -> list[Message]`
  `get_message_ids() -> set[int]`, `count_messages(max_id=None) -> int`
  `set_state(key: str, value: Any) -> None`, `get_state(key: str, default=None) -> Any`
* **`services.vector_service.VectorService`**
  `build_context(query: str, exclude_message_ids=(), top_k=3) -> str`
  `search_conversations(query, top_k=3, exclude_message_ids=()) -> list[SearchHit]`
  `search_documents(query, top_k=3, category=None) -> list[SearchHit]`
  `sync_all(time_budget=None, blocking=True) -> dict[str, int]`
  `rebuild_index() -> dict[str, int]`, `stats() -> dict`
* **`core.router.Router`**
  `classify_intent(user_input: str) -> str`
* **`core.planner.Planner`**
  `run(target_agent: str, user_message: str) -> PlannerResult`
* **`core.orchestrator.JarvisOrchestrator`**
  `process_query(user_message: str) -> PlannerResult`
* **`Agent Protocol Interface`**
  `handle(action: str, payload: Dict[str, Any]) -> str`

---

# Security Baseline

- Zero Trust mindset.
- Security designed from day one.
- No hardcoded credentials.
- Secrets stored in `.env`.
- Static configuration belongs in `config.py`.
- Centralized logging with plan IDs for tracing.
- Local-first privacy: no telemetry, private runtime data in `data/` is gitignored.
- Fail-Fast validation.
- Least Privilege.
- Traceability.

---

# Coding Standards

- Python follows PEP 8.
- Lowercase package names only.
- Every package contains `__init__.py`.
- Code, comments, docstrings and logs are written in English.
- Swedish is used during development discussions only.

---

# Development Workflow

- Build incrementally.
- Verify every completed component before continuing.
- Do NOT redesign verified infrastructure without architectural benefit.
- Prioritize maintainability over shortcuts.
- Infrastructure first.
- Functionality second.
- Keep verified components stable.

---

# AI Collaboration Rules

Assume verified components are production-ready unless explicitly stated otherwise.

Mandatory rules

- **Dual-LLM Workflow:** Robin uses two parallel LLMs for input at every step. Always cross-examine, review, and combine suggestions into a single, cohesive, production-ready solution.
- **API Consistency Check:** Verify existing public APIs, class names, and method signatures before proposing or generating code.
- **Explicit Code Trigger:** Never output full code files prematurely. Discuss, review, and await an explicit user request (e.g., *"ge mig nu koden för xx.py"*) before generating code.
- Always generate COMPLETE files when requested. Never generate partial snippets unless explicitly asked.
- Never tell Robin to insert code manually.
- Always specify the exact file path.
- Keep responses compact, structured, and free of cosmetic refactoring.
- Communicate in Swedish during development discussions.
- Write all Python code, docstrings, comments, and log messages in English.

---

# Project Structure

```
C:\jarvis

.env                (gitignored)
.env.example
.gitignore
jarvis.bat          (launcher, uses .venv automatically)
requirements.txt
README.md
SNAPSHOT.md

agents/
    __init__.py
    business_agent.py
    career_agent.py
    contentcreator_agent.py
    education_agent.py
    general_agent.py
    socialmediamanager_agent.py
    webdeveloper_agent.py

core/
    __init__.py
    config.py
    logger.py
    orchestrator.py
    planner.py
    router.py

data/               (gitignored)
    documents/      (personal documents, category subfolders)
    jarvis_memory.db
    vector_store/   (ChromaDB)

logs/
    jarvis.log

prompts/
    router.txt
    business_agent.txt
    career_agent.txt
    contentcreator_agent.txt
    education_agent.txt
    general_agent.txt
    socialmediamanager_agent.txt
    webdeveloper_agent.txt

services/
    __init__.py
    memory_service.py
    ollama_service.py
    prompt_loader.py
    vector_service.py

templates/
```

---

# Current Architecture

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

---

# Completed Components

## ✅ Config
Location: `core/config.py`
Responsibilities: Load `.env`, central paths (`PROMPTS_DIR`, `DATA_DIR`, `LOGS_DIR`), self-healing directory creation.
Status: Verified.

## ✅ Logger
Location: `core/logger.py`
Responsibilities: Central logging, console output, rotating log files, configurable levels.
Status: Verified.

## ✅ OllamaService
Location: `services/ollama_service.py`
Responsibilities: Generic local LLM communication via `.chat(prompt: str)`.
Status: Verified.

## ✅ PromptLoader
Location: `services/prompt_loader.py`
Responsibilities: Central prompt file management via `.load(filename: str)`.
Status: Verified.

## ✅ Router
Location: `core/router.py`
Responsibilities: Intent classification. Uses `PromptLoader.load("router.txt")` and `OllamaService.chat()`. Returns validated Domain Categories.
Status: Verified & Tested.

## ✅ Planner
Location: `core/planner.py`
Responsibilities: Execution planning, thread-safe step coordination, retries, timeouts, telemetry, immutable `PlannerResult`.
Status: Verified & Tested.

## ✅ Orchestrator
Location: `core/orchestrator.py`
Responsibilities: Entry point for Jarvis execution pipeline. Coordinates Router → Category Mapping → Planner → Agent execution. Validates registry lookups (Zero Trust). Supports Dependency Injection.
Status: Verified & Tested (`python -m core.orchestrator`).

## ✅ MemoryService
Location: `services/memory_service.py`
Responsibilities: Short-term memory. SQLite (WAL, one connection per thread), sessions, conversation history, prefixed key-value state (e.g. `business_agent.active_client`). One continuous session ("default"). Agents read their last 8 messages as context.
Status: Verified.

## ✅ VectorService
Location: `services/vector_service.py`
Responsibilities: Long-term memory. ChromaDB with `qwen3-embedding:0.6b`. Semantic search over all conversations (all agents) and personal documents in `data/documents/` (txt, md, pdf, docx; category = subfolder). Self-healing sync (new/deleted messages, new/changed/deleted files), automatic re-index on embedding model change, fail-soft. Retrieval: top 3 messages + top 3 chunks, relevance cutoff `VECTOR_MAX_DISTANCE` (0.55), short-term window excluded. CLI: `python -m services.vector_service [--search TEXT | --rebuild | --stats]`.
Status: Verified (live test: relevant doc distance ~0.27, unrelated ~0.8).

## ✅ Interactive Chat & Launcher
`python -m core.orchestrator` runs an interactive chat (`Du >`, `exit` to quit, `--verbose` for console logs). `jarvis.bat` starts it with the project venv, no activation needed.
Status: Verified.

## ✅ Specialist Agents (7 Agents)
Locations:
- `agents/business_agent.py` (`BusinessAgent`)
- `agents/career_agent.py` (`CareerAgent`)
- `agents/webdeveloper_agent.py` (`WebDeveloperAgent`)
- `agents/education_agent.py` (`EducationAgent`)
- `agents/general_agent.py` (`GeneralAgent`)
- `agents/socialmediamanager_agent.py` (`SocialMediaManagerAgent`)
- `agents/contentcreator_agent.py` (`ContentCreatorAgent`)
Status: All 7 agents verified.

---

# Verification Status

| Component | Status |
|-----------|--------|
| Config | ✅ |
| Logger | ✅ |
| PromptLoader | ✅ |
| OllamaService | ✅ |
| Router | ✅ |
| Planner | ✅ |
| BusinessAgent | ✅ |
| CareerAgent | ✅ |
| WebDeveloperAgent | ✅ |
| EducationAgent | ✅ |
| GeneralAgent | ✅ |
| SocialMediaManagerAgent | ✅ |
| ContentCreatorAgent | ✅ |
| Orchestrator | ✅ |
| MemoryService (short-term memory) | ✅ |
| VectorService (long-term memory + documents) | ✅ |
| Interactive chat + jarvis.bat | ✅ |
| Full pipeline (`python -m core.orchestrator`) | ✅ |
| Logging & Audit Trail | ✅ |
| Intent classification | ✅ |
| Category-to-Agent Mapping | ✅ |
| Planner execution | ✅ |
| Retry & Timeout | ✅ |
| Package imports & Name consistency | ✅ |
| End-to-end pipeline integration | ✅ |

Known Issues: None.

---

# Current Milestone

Memory layer complete: short-term and long-term memory verified end-to-end. Jarvis is usable day-to-day via the interactive chat.

Completed in this phase:
- MemoryService wired into Orchestrator and all 7 agents (shared instance via DI).
- VectorService: long-term memory over all conversations + personal documents.
- Switched chat model to qwen3:8b (thinking off by default via `OLLAMA_THINK`); agent timeout raised to 120s (`AGENT_TIMEOUT_SECONDS`) after timeouts caused duplicate retries.
- Interactive chat mode and `jarvis.bat` launcher; `.env.example` added.
- Test data removed from the memory database.

---

# Planned Infrastructure Services

```
services/

ollama_service.py (verified)
prompt_loader.py (verified)

memory_service.py (verified - short-term memory, SQLite)
vector_service.py (verified - long-term memory + documents, ChromaDB)
scheduler_service.py (NEXT STEP - reminders and background tasks)
slack_service.py (planned - Slack integration for mobile connection)
social_media_analytics_service.py (planned - Competitor analytics/data export fetcher)
voice_service.py (planned)
speech_to_text_service.py (planned)
text_to_speech_service.py (planned)
api_service.py (planned)
notification_service.py (planned)
```

---

# Next Milestone: Scheduler & Reminders

Goal: the "remind me and do things for me" part of the second-brain vision.

Not yet designed. Open questions to settle before code:
- How reminders are created (natural language via agents, e.g. "påminn mig på fredag om X").
- Where reminders are stored (MemoryService/SQLite as source of truth).
- How they are delivered (Windows notification first, mobile later via notification_service).
- How the scheduler runs (background thread in the chat process vs. a separate always-on process).
- Background upkeep: the scheduler can also call `VectorService.sync_all()`.

---

# Non-Goals

Jarvis is NOT intended to become
- A generic ChatGPT clone.
- A prompt collection.
- A monolithic AI assistant.

Jarvis IS intended to become
- A structured AI operating system.
- A modular orchestration platform.
- A local-first AI environment.
- A professional software architecture portfolio.
- A scalable foundation for future automation and AI services.

---

End of snapshot.