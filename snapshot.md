# PROJECT SNAPSHOT
**Last updated:** 2026-10-07 (calendar Urd, lessons, encrypted backup)

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

1. **Domain Category (Router Output):** `business`, `career`, `web_development`, `education`, `general`, `social_media`, `content_creation`, `reminders`, `calendar`
2. **Internal Agent ID (Orchestrator/Planner Key):** `business_agent`, `career_agent`, `webdeveloper_agent`, `education_agent`, `general_agent`, `socialmediamanager_agent`, `contentcreator_agent`, `reminder_agent`, `calendar_agent`
3. **Python Module (File Path):** `business_agent.py`, `career_agent.py`, `webdeveloper_agent.py`, `education_agent.py`, `general_agent.py`, `socialmediamanager_agent.py`, `contentcreator_agent.py`, `reminder_agent.py`, `calendar_agent.py`
4. **Python Class:** `BusinessAgent`, `CareerAgent`, `WebDeveloperAgent`, `EducationAgent`, `GeneralAgent`, `SocialMediaManagerAgent`, `ContentCreatorAgent`, `ReminderAgent`, `CalendarAgent`

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
* **`services.calendar_service.CalendarService`**
  `add(person, kind, title, start, end=None, location="", details=None) -> CalendarEvent`, `update(id, **fields)`, `cancel(id) -> bool`, `get(id)`, `between(start, end, person=None, kind=None)`, `upcoming(days=14, person=None)`; `CalendarEvent.short`, `.icon`, `.to_dict()`
* **`services.notification_service.NotificationService`**
  `notify(title: str, message: str) -> bool` (channels: WindowsToastChannel, TelegramChannel)
* **`core.scheduler.Scheduler`**
  `check_once(now=None) -> int`, `run_forever(stop: Optional[threading.Event] = None)`
* **`core.events.event_bus`** (singleton `EventBus`)
  `publish(type, source, message, **data) -> Optional[Event]` (never raises), `subscribe() -> queue.Queue`, `unsubscribe(q)`, `recent(after_id=0, limit=200) -> list[Event]`
  Event types: `core.starting|online|offline|failed`, `query.received|queued|completed`, `agent.selected`, `memory.lookup|synced`, `websearch.query|results|failed`, `reminder.created|delivered|cancelled`, `calendar.created|updated|cancelled`, `lesson.added|removed`, `backup.started|completed|failed`, `sports.updated|leagues`, `weather.updated`, `security.rejected`
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

## ✅ Desktop Interface "Yggdrasil" (step 1 of 3)
Locations: `ui/` (index.html, app.css, js/app.js, api.js, tree.js, runes.js, effects.js, calendar.js, assets/yggdrasil.ico|png), `clients/desktop.py`, `services/ui_settings.py`, `services/system_monitor.py`, `scripts/install_desktop.ps1`. Full design: project doc `claude/yggdrasil-ui-design.md`.
System display name Yggdrasil, orchestrator Oden (names in `data/ui/settings.json`). Core serves static UI at `/app` (public, no data) + token-protected endpoints: `/agents`, `/settings` (GET/PATCH, pydantic-validated), `/history`, `/system` (nvidia-smi), `/memory/stats`, `/reminders/upcoming` (person mapped by name in category/text), `/documents/folders`, `PUT /documents` (raw body, txt/md/pdf/docx ≤25 MB, safe folder/filename, triggers vector sync), `/assets/background` (GET/PUT/DELETE, magic-byte check), `/people/photos`, `/people/{id}/photo`. Security headers incl. strict CSP. Events enriched: `query.received` has `text`, `query.completed` has `channel`, `text`, `reply` (Telegram conversations show live in the log).
Desktop app: pywebview window (WebView2), token only via JS bridge (`get_token`), `open_url` allowlist, close = hide, pystray tray icon, global hotkey via RegisterHotKey (no keyboard hook), single instance on 127.0.0.1:47832 (second launch sends SHOW), `--hidden` at login (task "Yggdrasil Desktop", 40 s delay), desktop shortcut with icon.
UI: tree variant 2 with cached branches, rune ring, blaster bolts crown→agent / root→wells, wells Mimer/Urd/Hvergelmer, family nodes (rolling 7 days from reminders + calendar), Urd calendar (see Family Calendar below), log with history paging + Telegram messages + steps toggle + search, chat via `/chat` (channel `ui`), file drop → Oden asks folder, background image + 7 sliders, sound levels per category + master mute (persisted). Weather, sports ticker, mail, Slack and Hvergelmer checks are placeholders/hidden until their steps.
Status: Verified live on Windows by the user (window, tray, hotkey, UI).

## ✅ Weather (SMHI)
Locations: `services/weather_service.py` (`WeatherService`, `summarize`), `ui/js/weather.js` (`WeatherWidget`, SVG icons), thread `weather` in Jarvis Core, `GET /weather`.
Source: SMHI SNOW1gv1 point forecast `opendata-download-metfcst.smhi.se/api/category/snow1g/version/1/geotype/point/lon/{lon}/lat/{lat}/data.json` (PMP3gv2 was shut down 2026-03-31). Items: `time` (end of interval), `intervalParametersStartTime`, `data` with `air_temperature`, `wind_speed`, `wind_speed_of_gust`, `wind_from_direction`, `precipitation_amount_mean/max`, `probability_of_precipitation`, `symbol_code` 1–27 (9999 = missing). Hourly ~3 days, then 6/12 h.
Summary: now (temp, wind-chill feels-like when ≤10° and wind ≥2 m/s, text, icon with night moon 20–06, wind m/s + compass, gusts); rain alert next 12 h (≥0.2 mm/h: start/end/total, kind rain/snow/sleet/thunder, badge "regn 17:00" / "regn nu"); hours strip 24 h labelled by interval start; 5 days (min/max, most common daytime symbol, note Blåsigt ≥10 m/s / "x mm" from hourly part / Regn). Refresh 30 min (retry 5 min on failure), fixed host, 15 s timeout, 3 MB cap, values range-checked. Event `weather.updated`.
Place: `settings.weather` {name "Gunnilse", lat 57.82, lon 12.08} (validated to the Nordic region).
UI: header button (icon, temp, orange rain badge) → panel "VÄDER · GUNNILSE" with now, alert, hours, days (temperature range bars), source line.
Status: Implemented, tested with a mocked SNOW1gv1 response (summary, alert, API, UI); real response shape verified via SMHI; pending live verification.

## ✅ Sports Ticker
Locations: `services/sports_service.py` (`SportsService`, `CATALOG`), `agents/sports_agent.py` (`SportsAgent`, id `sports_agent`, label Oden), `ui/js/sports.js` (`SportsTicker`), thread `sports` in Jarvis Core.
Providers: ESPN `site.api.espn.com/apis/site/v2/sports/<sport>/<league>/scoreboard` – no date ranges (a range gives HTTP 400): the plain call returns the current/next game day plus `leagues[0].calendar` (game days); then `?dates=YYYYMMDD` for the latest played round (≤3 game days) and the next 2 game days (non-day calendars, e.g. NFL: yesterday + day before). TheSportsDB free key `123` (eventspastleague → latest round r; eventsround r, r+1, r+2; keep finished/live games and the next game day). CATALOG has 38 leagues with `group` (Sverige incl. SHL 4419, HockeyAllsvenskan 5162, SDHL 5158, Damallsvenskan 5209, Svenska Cupen 4756, Div 1 S/N 4845/4674; Fotboll: eng.1/2/fa, esp.1, ita.1, ger.1, fra.1, ned.1, por.1, sco.1, den.1, nor.1, usa.1; Europa & landslag: CL, EL, ECL, Nations League, VM, VM-kval, EM; Hockey: NHL, Liiga 4931, KHL 4920, DEL 4925, National League 4934; Övrigt: NBA, WNBA, NFL, MLB). Unified `Game{id, league, start UTC, state pre|in|post, status (Swedish: Slut / Slut (ÖT) / Slut (str) / 63'), home/away Team{name, short, score, winner, logo}, url}`. SHL short names from a built-in map.
Refresh every 10 min, every 1 min while a game is live, `wake()` after a league change; event `sports.updated` only when data changed. Network: fixed API hosts and logo hosts, 10 s timeout, JSON ≤4 MB, logos ≤512 kB with magic-byte check, cached in `data/cache/logos/<sha1>.<ext>`; failed logos not retried in the session. API: `GET /sports` (token), `GET /sports/logo/{file}` (public, strict filename regex). CSP img-src now `'self' data: blob:` only. Desktop link allowlist + `www.shl.se`.
Leagues: `settings.sports.leagues` (default `["shl","allsvenskan"]`, ≤30 = `MAX_LEAGUES`); also `GET /sports/catalog`, `PUT /sports/leagues` (validated against CATALOG) for the menu. SportsAgent (no LLM) handles "lägg till X i resultaten", "ta bort X från resultaten", "vilka ligor …"; Orchestrator Step 0 routes them before lessons and the Router; `JarvisCore.set_sports_leagues` saves, publishes `sports.leagues` and wakes the refresher.
UI: bottom bar (hidden when no leagues), 2–4 games per page by width, rotates every 6.5 s, pauses on hover, pager dots; after a league's last page it moves to the next league with games; league menu (scrollable): "Visas" (click = jump, rotation continues; ✕ = remove; game count) and "Lägg till" grouped by `group`; click bar → expanded panel with league tabs and cards with logos; click card → ESPN/shl.se via the desktop bridge.
Status: Implemented, tested with mocked ESPN/TheSportsDB responses (parsing, statuses, logo cache, API, SportsAgent, Playwright UI); real endpoints unreachable from the build sandbox – pending live verification.

## ✅ Encrypted Backup
Location: `services/backup_service.py` (`BackupService`), thread `backup` in Jarvis Core, API `GET /backup/status`, `POST /backup/run`, Hvergelmer panel (status + "Kör backup nu"), `/status` line on Telegram.
Config (.env): `BACKUP_DIR` (folder on another disk, empty = off), `BACKUP_PASSPHRASE` (≥12 chars, secret), `BACKUP_TIME` 03:00, `BACKUP_KEEP` 14. Refuses a target inside data/; warns when on the same drive as Jarvis.
Content: data/ except vector_store (derived), -wal/-shm/-journal/.tmp/.part; every `*.db` via SQLite backup API + `serialize()`; empty folders kept. Format `.ygg`: header `YGGBAK1\n` | salt 16 | scrypt log2N=16,r=8,p=1 | nonce prefix 7; chunks of ≤1 MiB tar.gz sealed with AES-256-GCM (nonce = prefix|counter|final flag, AAD = header) – streamed, nothing unencrypted on disk. Written as `.ygg.part`, fsynced, fully decrypted/verified (entry count), then renamed; prune to newest N.
Schedule: first backup right away when none exists; then daily at BACKUP_TIME, or immediately after a missed night; retry 1 h after a failure; failure notification (toast/Telegram) at most every 12 h. Events `backup.started|completed|failed`.
CLI: `python -m services.backup_service status|run|verify <file>|restore <file> <empty dir>` (restore verifies first, extracts with tarfile `filter="data"`, never into live data/). Requires package `cryptography`.
Status: Implemented, tested (round-trip, wrong passphrase, tampering, truncation, pruning, failure path, API, UI); pending live verification.
Decision: no PIN lock – family risk is low and constant code entry would get in the way; the coming password vault gets its own master password.

## ✅ Lessons ("lärdomar") – the user teaches Oden
Locations: `services/lessons_service.py` (`LessonBook`, singleton `lesson_book`), `agents/lessons_agent.py` (`LessonsAgent`, agent id `lessons_agent`, display name = Oden).
Lessons live one per line in `data/lessons.md` (`- [scope] text`, hand-editable, re-read on mtime change, max 60 × 300 chars). Scopes: alla (all agents except router), oden (router), kalender, påminnelser, allmänt, utbildning, karriär, business, webb, sociala medier, content. `lesson_book.block_for(agent_id)` is appended after `{self.system_prompt}` in every agent prompt and in the router prompt ("follow unless they conflict with the System Instructions"). Fail-soft.
LessonsAgent uses no LLM: fixed regexes for "lär dig: …", "vad har du lärt dig?", "glöm lärdom N"; scope from a prefix (`[kalender]`, `kalender:`) or simple hints, correctable with "bara kalendern"/"gäller alla"; confirmation via `lessons_agent.pending`. Orchestrator Step 0 routes these commands (and scope corrections while a lesson is pending) to LessonsAgent before the pending-reply check and the Router. Events `lesson.added|removed`.
Status: Implemented, tested (service, agent, end-to-end through the API with fake Ollama, prompt injection verified); pending live verification.

## ✅ Family Calendar "Urd"
Locations: `services/calendar_service.py`, `agents/calendar_agent.py`, `prompts/calendar_agent.txt`, `ui/js/calendar.js`; router category `calendar` (prompts/router.txt section 8; REMINDERS narrowed to "påminn mig").
CalendarService: SQLite table `calendar_events` (person, kind event|work|match, title, start_at/end_at UTC, location, details JSON, status, source 'local', external_id reserved for Google sync, all_day, recurrence JSON, skip_dates JSON; columns migrated in place); add/update/cancel/skip/get/between/upcoming/series. All-day bookings span whole days (local midnight → midnight after last day, ≤62 days) and render as banners. Recurrence `{freq weekly|biweekly|monthly, parity ''|even|odd (ISO week), until}` is expanded on read into occurrences (`key` = `<id>@<first day>`); `skip(id, day)` removes one occurrence; extra/moved days are new bookings; events `calendar.created|updated|cancelled`. Match details validated: sport fotboll|innebandy (icons ⚽/🏑), division, home, away, role, gather HH:MM, officials [{role,name}] ≤8. Formats: title `H4 AD Floda - Gunnilse`, short `⚽ H4 (AD) Floda - Gunnilse`.
CalendarAgent (`calendar_agent`, pending key `calendar_agent.pending`): JSON proposal → card → "ja"/"nej"/correction; create (incl. all_day/end_date/repeat), list, cancel (whole booking, series `5`, one occurrence `5@YYYY-MM-DD`, reminder `r4`). Follow-up questions are stored as a `clarify` pending so the answer is routed back. The prompt gets a 42-day date lookup table (date, weekday, ISO week) and Python does all date/parity maths; a cup is one all-day event, not a match. Own crew entry from people[0].full_name (fallback name); crew sorted HD, AD1, AD2. Night shifts roll over to next day; default match length fotboll 120 / innebandy 90 min. Single work-shift question answered directly ("Natta jobbar 09:00–19:15 fredag 9 oktober."). Also sees upcoming reminders (ids `r<id>` in the prompt): lists them and can remove them, since they show in the same family calendar.
API: `GET /calendar/events?start&end` (ISO, ≤400 days), `DELETE /calendar/events/{id}`, `DELETE /reminders/{id}` (ReminderService.cancel publishes `reminder.cancelled`). `/health` returns `ui` (fingerprint of ui/ files); static UI served with `Cache-Control: no-cache`, and an open window reloads itself when the fingerprint changes after a core restart. Chat labels read "Oden · <agent>". `people[].full_name` in `data/ui/settings.json`.
UI: Urd day view (one column per family member, all-day bookings as a strip at the top; "Idag" opens it), week view with stacked banner lanes above the days, month view with ISO weeks and continuous bars; series detail card has "Ta bort bara denna gång" / "Ta bort hela serien"; week header → day, week number → week; every booking clickable → detail card (match full format with crew) with delete (double-click confirm); family column merges reminders + calendar events, items clickable → detail.
Status: Implemented, tested in container (service + agent with fake LLM, end-to-end via API with fake Ollama, Playwright UI day/week/detail); pending live verification.

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
| Telegram two-way chat | ✅ |
| Desktop interface Yggdrasil (window, tray, hotkey, live brain map) | ✅ |
| Family calendar Urd (CalendarService + CalendarAgent + day/week/month UI) | 🔧 Pending live test |
| Lessons (LessonBook + LessonsAgent, data/lessons.md) | 🔧 Pending live test |
| Encrypted backup (BackupService, AES-256-GCM, restore CLI) | 🔧 Pending live test |
| Sports ticker (SportsService, SportsAgent, ticker UI) | 🔧 Pending live test |
| Weather (WeatherService SMHI SNOW1gv1, header + panel) | 🔧 Pending live test |
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
calendar_service.py (implemented - local family calendar Urd; Google Calendar sync planned)
core/api.py (implemented - local API; later exposed to the own mobile app over Tailscale)
slack_service.py (planned - Slack integration for mobile connection)
social_media_analytics_service.py (planned - Competitor analytics/data export fetcher)
voice_service.py (planned)
speech_to_text_service.py (planned)
text_to_speech_service.py (planned)
```

---

# Roadmap (agreed order)

1. **Visual desktop interface – step 1 DONE (verified).** **Urd local calendar, lessons and encrypted backup DONE (pending live test); PIN lock dropped.** Sports ticker and weather (SMHI, Gunnilse) DONE (pending live test). Next: morning briefing from Oden, then Hvergelmer security checks. Original scope: web UI served by Jarvis Core on 127.0.0.1, shown in its own app window; desktop icon; tray icon (Jarvis keeps running in the background when the window closes); global hotkey (e.g. Ctrl+Alt+J) to bring it up; chat window for typing (quiet hours when the family sleeps); sound on/off toggle; live "second brain" map of the Orchestrator and agents driven by `/events/stream` (which agent works, web searches, memory lookups, reminders).
2. **Voice:** local speech-to-text and text-to-speech, wake word "Hej Jarvis" (both hotkey and wake word wake Jarvis); respects the sound toggle.
3. **Google Calendar sync on top of the local Urd calendar:** start with the current Google account, move to a new private account later. One calendar per category (each child, family, Robin's work, wife's work, VerkstadsFlow), shared with the wife (iPhone via Google account in iOS Calendar) and shown on an Android tablet as family display. Jarvis picks the calendar from the category ("lägg in BVC-tid för ..."), always with confirmation.
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