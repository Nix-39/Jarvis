# PROJECT SNAPSHOT
**Last updated:** 2026-10-06 (Jarvis Core + Telegram)

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
| Web search | SearXNG in Docker, 127.0.0.1:8888 only |
| Jarvis Core API | FastAPI/uvicorn, 127.0.0.1:8765 only, bearer token |
| Single-instance lock | localhost port 47831 (bound, never listening) |
| Chat context | num_ctx 16384 (OLLAMA_NUM_CTX) |
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
8. **Untrusted External Content:** Everything fetched from the web is injected as clearly labeled untrusted data and must never be followed as instructions. Only a rewritten, privacy-safe query leaves the machine; personal matters are never searched.
9. **Single Memory Owner:** Exactly one long-running process (Jarvis Core) owns the Orchestrator, ChromaDB and reminder delivery, guarded by a localhost port lock. All user channels (terminal, Telegram, future desktop UI and mobile app) are thin clients of the core. Queries are serialized.
10. **Observability via Events:** Components publish small events on the in-process EventBus (`core/events.py`). Publishing never raises and never blocks; the event feed is exposed only through the authenticated local API.

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

1. **Domain Category (Router Output):** `business`, `career`, `web_development`, `education`, `general`, `social_media`, `content_creation`, `reminders`
2. **Internal Agent ID (Orchestrator/Planner Key):** `business_agent`, `career_agent`, `webdeveloper_agent`, `education_agent`, `general_agent`, `socialmediamanager_agent`, `contentcreator_agent`, `reminder_agent`
3. **Python Module (File Path):** `business_agent.py`, `career_agent.py`, `webdeveloper_agent.py`, `education_agent.py`, `general_agent.py`, `socialmediamanager_agent.py`, `contentcreator_agent.py`, `reminder_agent.py`
4. **Python Class:** `BusinessAgent`, `CareerAgent`, `WebDeveloperAgent`, `EducationAgent`, `GeneralAgent`, `SocialMediaManagerAgent`, `ContentCreatorAgent`, `ReminderAgent`

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
* **`services.web_search_service.WebSearchService`**
  `build_context(user_message: str) -> str`
  `decide(user_message: str) -> tuple[bool, str]`
  `search(query: str) -> list[WebResult]`, `is_available() -> bool`
* **`core.clock`**
  `current_datetime_text() -> str`, `format_datetime_sv(moment: datetime) -> str`
* **`services.reminder_service.ReminderService`**
  `add(text, due, recurrence="none", category="") -> Reminder`, `get(id)`, `list_upcoming(limit=25)`
  `cancel(id) -> bool`, `due(now=None) -> list[Reminder]`, `mark_fired(reminder, now=None) -> Optional[datetime]`, `categories() -> list[str]`
* **`services.notification_service.NotificationService`**
  `notify(title: str, message: str) -> bool` (channels: WindowsToastChannel, TelegramChannel)
* **`core.scheduler.Scheduler`**
  `check_once(now=None) -> int`, `run_forever(stop: Optional[threading.Event] = None)`
* **`core.events.event_bus`** (singleton `EventBus`)
  `publish(type, source, message, **data) -> Optional[Event]` (never raises), `subscribe() -> queue.Queue`, `unsubscribe(q)`, `recent(after_id=0, limit=200) -> list[Event]`
  Event types: `core.starting|online|offline|failed`, `query.received|queued|completed`, `agent.selected`, `memory.lookup|synced`, `websearch.query|results|failed`, `reminder.created|delivered`, `security.rejected`
* **`core.single_instance`**
  `acquire_lock() -> Optional[socket]`, `lock_is_held() -> bool`
* **`core.jarvis_core.JarvisCore`**
  `start_scheduler()`, `start_brain(orchestrator=None)`, `ask(message, channel="terminal") -> PlannerResult`, `status() -> dict`, `status_text() -> str`, `stop()`
* **`core.api`** (local HTTP API, 127.0.0.1:8765, `Authorization: Bearer <data/api_token.txt>`)
  `GET /health` (no token), `GET /status`, `POST /chat {message, channel}` -> `{reply, agent, seconds, success}`, `GET /events/recent?after_id&limit`, `GET /events/stream?after_id` (SSE)
* **`services.telegram_service.TelegramService`**
  `run(stop)`, `poll_once() -> list`, `handle_update(update)`, `send_text(text, chat_id=None) -> bool`, `setup_mode`
* **Pending-confirmation convention:** an agent awaiting a yes/no stores `<agent_id>.pending` (dict with `created`) in MemoryService state; the Orchestrator routes short replies back to it for 15 minutes.
* **`core.router.Router`**
  `classify_intent(user_input: str) -> str`
* **`core.planner.Planner`**
  `run(target_agent: str, user_message: str) -> PlannerResult`
* **`core.orchestrator.JarvisOrchestrator`**
  `process_query(user_message: str, channel: str = "terminal") -> PlannerResult`
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
- No inbound ports: every local service binds 127.0.0.1 only; phone access uses outbound Telegram long polling. Local API requires a bearer token and checks the Host header.

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
jarvis.bat          (terminal client for Jarvis Core, uses .venv automatically)
scripts/            (install_core.ps1 = autostart task "Jarvis Core", restart_core.ps1, check_autostart.ps1)
docker/searxng/     (docker-compose.yml, config/settings.yml, .env secret - gitignored)
requirements.txt
README.md
SNAPSHOT.md

agents/
    __init__.py
    reminder_agent.py
    business_agent.py
    career_agent.py
    contentcreator_agent.py
    education_agent.py
    general_agent.py
    socialmediamanager_agent.py
    webdeveloper_agent.py

clients/
    __init__.py
    terminal.py     (thin client: /chat + live events)

core/
    __init__.py
    api.py          (local FastAPI app)
    clock.py
    config.py
    events.py       (EventBus)
    jarvis_core.py  (always-running background process)
    logger.py
    orchestrator.py (+ standalone debug chat, refuses while core runs)
    planner.py
    router.py
    scheduler.py    (thread in the core; standalone for troubleshooting)
    single_instance.py

data/               (gitignored)
    api_token.txt   (local API token, auto-generated)
    reminder_categories.txt
    documents/      (personal documents, category subfolders)
    jarvis_memory.db
    vector_store/   (ChromaDB)

logs/
    jarvis_core.log       (Jarvis Core)
    jarvis.log            (debug chat)
    jarvis_scheduler.log  (standalone scheduler only)

prompts/
    router.txt
    reminder_agent.txt
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
    notification_service.py
    ollama_service.py
    prompt_loader.py
    reminder_service.py
    telegram_service.py
    vector_service.py
    web_search_service.py

templates/
```

---

# Current Architecture

```
                     Terminal (jarvis.bat)      Telegram (phone)      Desktop UI (planned)
                               └───────────────────────┼───────────────────────┘
                                                        ▼
                         Jarvis Core (background process, local API on 127.0.0.1, live event feed)
                                            │
                                            ▼
                                   Jarvis Orchestrator
                                            │
                        ┌───────────────────┤
                        ▼                   ▼
                     Router              Planner
                    (intent)       (timeouts, retries)
                                            │
      ┌──────────┬──────────┬──────────┬────┴─────┬──────────┬──────────┬──────────┐
      ▼          ▼          ▼          ▼          ▼          ▼          ▼          ▼
  Business    Career     WebDev    Education   General    Social     Content   Reminder
      └──────────┴──────────┴──────────┴────┬─────┴──────────┴──────────┴──────────┘
                                            ▼
                                        Services
      ┌────────────────────────┬────────────┴─────────────┬────────────────────────┐
      ▼                        ▼                          ▼                        ▼
   Ollama                   Memory                     Vector                  WebSearch
(chat+embed)               (SQLite)                  (ChromaDB)                (SearXNG)

                  Reminder ◄── Scheduler (thread in Core) ──► Notification
                    (SQLite)                            (Windows, Telegram)
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

## ✅ Jarvis Core, Local API & Event Feed
Locations: `core/jarvis_core.py`, `core/api.py`, `core/events.py`, `core/single_instance.py`, `scripts/install_core.ps1`
One always-running process (pythonw, Task Scheduler task "Jarvis Core" at logon + 20 s delay, RunLevel Limited, restart on failure; replaces the old "Jarvis Scheduler" task). Startup: single-instance lock → scheduler thread (reminders work immediately) → local API → background startup: wait for Ollama (up to 5 min) → Orchestrator (memory sync) → Telegram thread → "🟢 Jarvis är online". Queries from all channels serialized by a lock (`query.queued` event when waiting). API: 127.0.0.1:8765, bearer token (`data/api_token.txt`, constant-time compare), TrustedHost (127.0.0.1/localhost), no CORS, no docs/OpenAPI, SSE stream with heartbeat that ends cleanly on shutdown. uvicorn warnings go to `logs/jarvis_core.log`; httpx INFO logging silenced (Telegram URLs contain the token).
Status: Implemented, tested with fake Ollama (end-to-end: API, SSE, terminal client, lock refusal, graceful Ctrl+C); pending live verification.

## ✅ Telegram Two-Way Chat
Location: `services/telegram_service.py`
Long polling (getUpdates, outbound HTTPS only). Answers only `TELEGRAM_CHAT_ID`; others ignored, logged and published as `security.rejected`. Setup mode (token, no chat id): a private /start gets its chat id back, nothing is executed. Messages older than 10 min (sent while offline) are not executed - the user is asked to resend. Offset saved in MemoryService state `telegram.offset` before handling (at-most-once). Typing indicator, replies split at 4000 chars, plain text, `/status`, `/hjalp`. Token never logged.
Status: Implemented, tested with mocked Telegram API; pending live verification.

## ✅ Terminal Client & Launcher
`jarvis.bat` → `clients/terminal.py`: thin client of Jarvis Core (`Du >`, `/status`, `exit`; live dimmed "› ..." event lines while waiting, `--quiet` hides them). Waits while the core starts; explains how to start it if it is not running. `python -m core.orchestrator` remains as a standalone debug chat and refuses to run while the core holds the lock (two ChromaDB writers could corrupt the index).
Status: Implemented; pending live verification.

## ✅ SearXNG (Docker)
Location: `docker/searxng/`
Self-hosted private metasearch. Bound to 127.0.0.1:8888 only, cap_drop ALL (+CHOWN/SETGID/SETUID), no-new-privileges, limiter off (private), JSON format on, secret in gitignored .env. Docker Desktop starts at sign-in; container restart unless-stopped.
Status: Verified.

## ✅ WebSearchService + date awareness
Location: `services/web_search_service.py`, `core/clock.py`
Every agent prompt gets the current local date/time. Before answering, an LLM decision step judges whether current information is needed and rewrites a short privacy-safe query (bias: search when unsure; never personal matters; `sök:` forces). SearXNG top 5 results + main text of top 2 pages (lxml extraction). Web content labeled untrusted. SSRF protection (public IPs only, every redirect re-checked), timeouts, 2 MB cap, content-type allowlist. Fail-soft. OLLAMA_NUM_CTX=16384 so long prompts are not silently truncated. CLI: `python -m services.web_search_service "fråga"`.
Status: Implemented, tested with fake SearXNG/pages; pending live verification.

## ✅ Reminders, Scheduler & Notifications
Locations: `agents/reminder_agent.py`, `prompts/reminder_agent.txt`, `services/reminder_service.py`, `services/notification_service.py`, `core/scheduler.py`, `scripts/install_scheduler.ps1`
ReminderAgent: natural language → JSON proposal → confirmation (ja / nej / correction); create, list, cancel; one-off + daily/weekdays/weekly/monthly; categories from `data/reminder_categories.txt`. Router category `reminders`. Orchestrator routes short replies to an agent with a fresh pending proposal.
Scheduler: separate always-on process (pythonw, Task Scheduler at logon, RunLevel Limited), poll 30s, late delivery of missed reminders, recurring skip to next future time, port lock (single instance), own log `logs/jarvis_scheduler.log`.
Notifications: channel design (Windows toast via PowerShell with env-var input, Telegram outbound). Reminders reserve `calendar_event_id` for CalendarService.
Status: Implemented, tested with fake LLM/notifications; pending live verification.

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
| Terminal client + jarvis.bat | 🔧 Pending live test |
| Jarvis Core + local API + EventBus | 🔧 Pending live test |
| Telegram two-way chat | 🔧 Pending live test |
| Autostart chain (Ollama, Docker/SearXNG, Jarvis task) | ✅ (re-check after install_core.ps1) |
| SearXNG (Docker, hardened) | ✅ |
| WebSearchService + date awareness | ✅ |
| ReminderAgent + scheduler + notifications | ✅ |
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

Jarvis Core: Jarvis is always running in the background from login and reachable from the terminal and the phone (Telegram). The event feed that the visual interface will build on is in place.

Completed in this phase:
- Web search (SearXNG) + date awareness; reminders with confirmation, scheduler and notifications.
- `.gitattributes` line-ending normalization; autostart chain verified (`scripts/check_autostart.ps1`).
- Jarvis Core (single memory owner) with local API, EventBus and Telegram two-way chat; terminal client.

---

# Planned Infrastructure Services

```
services/

ollama_service.py (verified)
prompt_loader.py (verified)

memory_service.py (verified - short-term memory, SQLite)
vector_service.py (verified - long-term memory + documents, ChromaDB)
web_search_service.py (verified - live web info via self-hosted SearXNG)
reminder_service.py (implemented - reminders, recurrence)
notification_service.py (implemented - Windows toast + Telegram channels)
telegram_service.py (implemented - two-way Telegram chat = mobile access)
calendar_service.py (planned - Google Calendar, family calendars per category)
core/api.py (implemented - local API; later exposed to the own mobile app over Tailscale)
slack_service.py (planned - Slack integration for mobile connection)
social_media_analytics_service.py (planned - Competitor analytics/data export fetcher)
voice_service.py (planned)
speech_to_text_service.py (planned)
text_to_speech_service.py (planned)
```

---

# Roadmap (agreed order)

1. **Visual desktop interface (NEXT):** web UI served by Jarvis Core on 127.0.0.1, shown in its own app window; desktop icon; tray icon (Jarvis keeps running in the background when the window closes); global hotkey (e.g. Ctrl+Alt+J) to bring it up; chat window for typing (quiet hours when the family sleeps); sound on/off toggle; live "second brain" map of the Orchestrator and agents driven by `/events/stream` (which agent works, web searches, memory lookups, reminders).
2. **Voice:** local speech-to-text and text-to-speech, wake word "Hej Jarvis" (both hotkey and wake word wake Jarvis); respects the sound toggle.
3. **CalendarService (Google Calendar):** start with the current Google account, move to a new private account later. One calendar per category (each child, family, Robin's work, wife's work, VerkstadsFlow), shared with the wife (iPhone via Google account in iOS Calendar) and shown on an Android tablet as family display. Jarvis picks the calendar from the category ("lägg in BVC-tid för ..."), always with confirmation.
4. Later: Cal.com booking for VerkstadsFlow (on top of Google Calendar); own mobile app (Jarvis Core API over Tailscale, PWA or .NET MAUI) as another chat/notification channel; social media analytics.
5. **Computer hardening (after the setup is complete):** review open ports (`netstat -abno`) and close what is not needed; stricter Windows Firewall rules (block inbound by default, verify Docker/SearXNG and Jarvis stay on 127.0.0.1); review autostart programs; consider BitLocker (with the recovery key stored safely). Constraint: family members use the computer with automatic login and no separate accounts, so measures must not add logins.

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