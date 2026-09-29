# Jarvis — Local-First Agent Operating System

A modular, security-first AI operating system that runs entirely on local hardware. Built for personal use, business automation and as a software architecture portfolio project.

Jarvis coordinates eight specialized AI agents behind a single orchestrator, with both short-term and long-term memory, using local models via [Ollama](https://ollama.com). Nothing leaves the machine. The architecture is built first and functionality is added incrementally on top of it, with every component verified before the next one starts.

## What Jarvis does

Jarvis is designed to become a "second brain": an assistant that remembers, finds old information by meaning, and eventually reminds and acts on its own.

- **Routes requests** to the right specialist agent (business, career, web development, education, social media, content creation, reminders, general).
- **Reminders with confirmation:** "påminn mig på fredag kl 10 om att ringa banken" → Jarvis proposes, you confirm or correct, and an always-on background scheduler notifies you when it is time (Windows notification, Telegram). One-off and recurring (daily, weekdays, weekly, monthly), with categories.
- **Short-term memory:** each agent sees the latest turns of its own conversation.
- **Long-term memory:** semantic search across *all* past conversations, across all agents, so something mentioned weeks ago to one agent can be found by another.
- **Live web information:** when a question needs current facts (news, prices, competitors, regulations), Jarvis searches the web through a private, self-hosted SearXNG instance and cites its sources. It knows today's date and time.
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

                  Reminder ◄── Scheduler (own process) ──► Notification
                    (SQLite)                            (Windows, Telegram)
```

**Separation of concerns:**

- **Router:** intent classification only. Outputs a validated domain category.
- **Orchestrator:** the single entry point. Owns the mapping from categories to agents and creates the shared services.
- **Planner:** executes agent steps thread-safely with timeouts and retries via the `Agent` protocol (`handle`).
- **Agents:** domain logic only. They never talk to external systems directly.
- **Services:** infrastructure only (LLM calls, prompts, memory, vector search, web search, reminders, notifications). WebSearch talks to SearXNG running in Docker; the Scheduler is a separate background process that delivers reminders.

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

## Web search design

- **Jarvis decides when to search.** A quick model step judges whether a question needs current information and writes a short search query. Only that rewritten query leaves the machine, never the raw message, so personal details are stripped. Personal matters are never searched. Prefix a message with `sök:` to force a search.
- **Private search engine:** SearXNG runs in Docker, bound to `127.0.0.1` only, with all Linux capabilities dropped except three and no privilege escalation.
- **Reads the best pages:** top results plus the main text of the top 2 pages (`WEB_FETCH_PAGES`).
- **Security:** web content is labeled as untrusted in the prompt (prompt-injection defense); page fetching blocks localhost, private and link-local addresses on every redirect hop (SSRF protection), with timeouts, a size cap and a content-type allowlist.
- **Fail-soft:** if SearXNG is down, Jarvis still answers and says its information may be outdated.

## Reminders & scheduler

- **ReminderAgent** turns natural language into a structured proposal and always asks for confirmation. "ja" saves, "nej" discards, anything else ("kl 11 istället") corrects. The model never writes to the database; only validated Python code does.
- **Background scheduler** (`core/scheduler.py`) runs as its own process without a window, started at login by Windows Task Scheduler with normal user rights. It checks for due reminders every 30 seconds, delivers reminders missed while the computer was off (marked as late), and a port lock prevents two schedulers from running.
- **Notifications as channels** (`NotificationService`): Windows toast and Telegram today, a future Jarvis mobile app plugs in as another channel. Notification text is passed to PowerShell via environment variables and XML-escaped, never interpolated into a command.
- **Categories** live in `data/reminder_categories.txt` (private). Reminders store a reserved `calendar_event_id` for the upcoming Google Calendar integration.

## Tech stack

| Component | Details |
|---|---|
| Language | Python 3.13 |
| Chat model | `qwen3:8b` via Ollama (configurable) |
| Embedding model | `qwen3-embedding:0.6b` via Ollama (multilingual, incl. Swedish) |
| Short-term memory | SQLite, WAL mode, one connection per thread |
| Long-term memory | ChromaDB (persistent, telemetry disabled) |
| Documents | `pypdf`, `python-docx` |
| Web search | SearXNG (self-hosted, Docker), `httpx`, `lxml` |
| Config/secrets | `.env` (never committed) + `core/config.py` |
| Logging | Centralized rotating file logs, plan IDs for tracing |
| Hardware (dev) | AMD Ryzen 9 3900X · 32 GB RAM · NVIDIA RTX 3060 12 GB |

## Project structure

```
jarvis/
├── jarvis.bat              # Start the chat (uses .venv automatically)
├── scripts/install_scheduler.ps1  # Autostart the background scheduler at login
├── docker/searxng/         # Private search engine (docker-compose + settings)
├── .env.example            # Configuration template (copy to .env)
├── requirements.txt
│
├── agents/                 # Domain-specific logic, one file per agent
├── core/
│   ├── clock.py            # Current date/time for prompts
│   ├── config.py           # Settings and paths (self-creating folders)
│   ├── logger.py
│   ├── orchestrator.py     # Entry point + interactive chat
│   ├── planner.py
│   ├── router.py
│   └── scheduler.py        # Background process: delivers reminders
├── prompts/                # Static system prompts, one per agent + router
├── services/
│   ├── ollama_service.py   # chat() + embed()
│   ├── prompt_loader.py
│   ├── memory_service.py   # Short-term memory (SQLite)
│   ├── notification_service.py  # Windows toast + Telegram channels
│   ├── reminder_service.py # Reminders (SQLite, recurrence)
│   ├── vector_service.py   # Long-term memory + documents (ChromaDB)
│   └── web_search_service.py  # Live web information via SearXNG
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
4. Start the private search engine (requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)). Create `docker/searxng/.env` with a random secret, then start it:
   ```powershell
   cd docker\searxng
   ..\..\.venv\Scripts\python -c "import secrets; print('SEARXNG_SECRET=' + secrets.token_hex(32))" | Out-File -Encoding ascii .env
   docker compose up -d
   cd ..\..
   ```
5. Start the background scheduler automatically at every login (normal user rights, no window):
   ```powershell
   .\scripts\install_scheduler.ps1
   ```
   Test notifications with `.venv\Scripts\python -m core.scheduler --test-notification`.
6. Start Jarvis: double-click `jarvis.bat`, or run it from a terminal:
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
| `OLLAMA_NUM_CTX` | `16384` | Context window for chat requests |
| `WEB_SEARCH_ENABLED` | `true` | Turn live web search on/off |
| `SEARXNG_URL` | `http://127.0.0.1:8888` | Local SearXNG instance |
| `WEB_MAX_RESULTS` | `5` | Search results used per question |
| `WEB_FETCH_PAGES` | `2` | Top pages read in full (0 = snippets only) |
| `WEB_TIMEOUT_SECONDS` | `8` | Timeout for search and page fetching |
| `SCHEDULER_POLL_SECONDS` | `30` | How often the scheduler checks for due reminders |
| `NOTIFY_WINDOWS` | `true` | Windows toast notifications |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Phone notifications via a private Telegram bot (optional) |
| `LOG_LEVEL` | `INFO` | Log verbosity |

## Status

| Component | Status |
|---|---|
| Config, Logger, PromptLoader, OllamaService | ✅ Verified |
| Router, Planner, Orchestrator | ✅ Verified & tested |
| 7 specialist agents (+ ReminderAgent) | ✅ Verified |
| MemoryService (short-term memory) | ✅ Verified |
| VectorService (long-term memory + documents) | ✅ Verified |
| Interactive chat + `jarvis.bat` launcher | ✅ Verified |
| SearXNG (self-hosted, hardened) | ✅ Verified |
| WebSearchService (live web information) + date awareness | ✅ Implemented |
| ReminderAgent + background scheduler + notifications | ✅ Implemented |
| Telegram two-way chat (mobile access) | 📋 Planned (next) |
| Google Calendar (family calendars, categories) | 📋 Planned |
| Own Jarvis mobile app (API + Tailscale) | 📋 Planned |
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
