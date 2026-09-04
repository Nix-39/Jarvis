# PROJECT SNAPSHOT
**Last updated:** 2026-08-01

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
| Local LLM | llama3.1:8b |
| Ollama | http://localhost:11434 |
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
- Centralized logging with correlation IDs.
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

.env
.gitignore
requirements.txt
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

data/
    jarvis_memory.db (planned SQLite database)

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
    ollama_service.py
    prompt_loader.py

templates/
```

---

# Current Architecture

```
                               User
                                │
                                ▼
                       Jarvis Orchestrator
                                │
                                ▼
                             Router
                                │
                                ▼
                             Planner
                                │
     ┌──────────┬──────────┬────┴─────┬──────────┬──────────┬──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼          ▼          ▼
 Business   Career   WebDeveloper Education   General  SocialMedia  ContentCreator
   Agent      Agent      Agent        Agent      Agent      Manager        Agent
     │          │          │            │          │            │            │
     └──────────┴──────────┴────────────┴──────────┴────────────┴────────────┘
                                │
                                ▼
                             Services
                    ┌───────────┴───────────┐
                    ▼                       ▼
            PromptLoader             OllamaService
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

First-generation core architecture & complete agent layer finalized and verified.

Completed in this phase:
- Synchronized Router category outputs and Orchestrator mapping.
- Standardized API signatures (`PromptLoader.load()`, `OllamaService.chat()`).
- Established 4-tier naming standards across categories, agent IDs, files, and class names.
- Successfully verified full end-to-end pipeline via `python -m core.orchestrator`.

---

# Planned Infrastructure Services

```
services/

ollama_service.py (verified)
prompt_loader.py (verified)

memory_service.py (NEXT STEP - SQLite for session retention & conversation memory)
vector_service.py (planned - Local VectorDB/ChromaDB for custom files/RAG)
slack_service.py (planned - Slack integration for mobile connection)
social_media_analytics_service.py (planned - Competitor analytics/data export fetcher)
voice_service.py (planned)
speech_to_text_service.py (planned)
text_to_speech_service.py (planned)
api_service.py (planned)
notification_service.py (planned)
```

---

# Next Milestone: MemoryService

**Location:** `services/memory_service.py`
**Database Location:** `data/jarvis_memory.db` (configured via `Config.DATA_DIR`)

**Planned Responsibilities:**
- Persistent SQLite database initialization and connection handling.
- Session creation and session management.
- Conversation history logging (User request + Agent response + metadata).
- User preferences and state key-value storage.
- Thread-safe database operations.

**Explicit Out-of-Scope (Reserved for `VectorService`):**
- Vector embeddings.
- Semantic search.
- Unstructured document retrieval / RAG.

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