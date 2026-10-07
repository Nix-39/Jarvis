# Jarvis — Local-First Agent Operating System

A modular, security-first AI operating system that runs entirely on local hardware. Built for personal use, business automation and as a software architecture portfolio project.

Jarvis coordinates eight specialized AI agents behind a single orchestrator, with both short-term and long-term memory, using local models via [Ollama](https://ollama.com). Nothing leaves the machine. The architecture is built first and functionality is added incrementally on top of it, with every component verified before the next one starts.

## What Jarvis does

Jarvis is designed to become a "second brain": an assistant that remembers, finds old information by meaning, and eventually reminds and acts on its own.

- **Routes requests** to the right specialist agent (business, career, web development, education, social media, content creation, reminders, calendar, general).
- **Reminders with confirmation:** "påminn mig på fredag kl 10 om att ringa banken" → Jarvis proposes, you confirm or correct, and an always-on background scheduler notifies you when it is time (Windows notification, Telegram). One-off and recurring (daily, weekdays, weekly, monthly), with categories.
- **Family calendar (Urd):** "Natta jobbar 9–19:15 på fredag", "jag dömer H4 Floda–Gunnilse på lördag kl 15, samling 14:15, Flodala, jag är AD1, HD är Anders Andersson" → Jarvis shows the booking card, you confirm, and it lands in the calendar. Ordinary bookings, work shifts and referee matches (football/floorball with division, role, venue and the whole referee crew). Ask "hur jobbar Natta på fredag?" and get a direct answer.
- **Always running, reachable from the phone:** Jarvis Core runs in the background from login. Chat with it in a terminal at the computer, or from anywhere through a private Telegram bot (no open ports).
- **Short-term memory:** each agent sees the latest turns of its own conversation.
- **Long-term memory:** semantic search across *all* past conversations, across all agents, so something mentioned weeks ago to one agent can be found by another.
- **Live web information:** when a question needs current facts (news, prices, competitors, regulations), Jarvis searches the web through a private, self-hosted SearXNG instance and cites its sources. It knows today's date and time.
- **Personal knowledge base:** drop documents (`.txt`, `.md`, `.pdf`, `.docx`) into category folders and the agents use relevant passages when answering.
- **Business support** for [VerkstadsFlow](https://www.verkstadsflow.se), a web agency for automotive workshops.

## Architecture

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
  Business    Career     WebDev    Education   General    Social     Content   Reminder + Calendar
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

**Separation of concerns:**

- **Jarvis Core:** the one always-running process. Owns the Orchestrator, the reminder scheduler, the Telegram bot and the local API. Clients (terminal, phone, future desktop UI) never load models or memory themselves.
- **Router:** intent classification only. Outputs a validated domain category.
- **Orchestrator:** the single entry point. Owns the mapping from categories to agents and creates the shared services.
- **Planner:** executes agent steps thread-safely with timeouts and retries via the `Agent` protocol (`handle`).
- **Agents:** domain logic only. They never talk to external systems directly.
- **Services:** infrastructure only (LLM calls, prompts, memory, vector search, web search, reminders, notifications, Telegram). WebSearch talks to SearXNG running in Docker.

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

## Jarvis Core, Telegram & the event feed

- **One owner of memory.** ChromaDB must not be written by two processes at once, so exactly one process, Jarvis Core (`core/jarvis_core.py`), owns the Orchestrator. A localhost port lock guarantees a single instance. Questions from all channels are answered one at a time, in arrival order.
- **Autostart without a window:** Windows Task Scheduler starts the core at login with normal user rights. At startup it waits for Ollama, so the order in which programs start does not matter. Reminders run from the first second, even before the AI models are ready.
- **Local API** (`core/api.py`, FastAPI): bound to `127.0.0.1` only, so it is not reachable from the network. Every endpoint except `/health` needs a bearer token that is generated on first start (`data/api_token.txt`, private), so other programs and web pages on the same computer cannot use it. Host-header check against DNS rebinding, no CORS, no public API docs.
- **Telegram bot** (`services/telegram_service.py`): long polling over outgoing HTTPS, so no port is opened on the computer or router. Only the owner's chat id is answered; others are ignored and logged. Messages sent while the computer was off are not executed (an old "remind me in 10 minutes" would be wrong); Jarvis asks you to resend them. The bot token is never logged. `/status` shows how Jarvis is doing.
- **Event feed** (`core/events.py`): components publish small events ("Kategori 'business' → business_agent", "Söker på webben: …", "Påminnelse skickad"). The terminal shows them live while you wait, and they are streamed via `/events/stream` (Server-Sent Events) for the upcoming visual desktop interface that shows the second brain at work.

## Desktop interface – Yggdrasil

The visual face of the system: **Yggdrasil**, the world tree, with **Oden** as the orchestrator that hands out work.

- **Live brain map:** the seven agents sit above the tree. When Oden routes a question, three glowing bolts fly from the crown to the agent and back with the answer; memory lookups and reminders travel down the roots to the three wells: **Mimer** (memory), **Urd** (calendar) and **Hvergelmer** (security).
- **Log and chat** on the right: everything Oden and the agents say and do, including questions from Telegram, with search (Ctrl+F) and history.
- **Family column:** one node per family member with their next seven days; click a booking for its full details. **Urd** opens the calendar: a day view with one column per family member ("Idag"), a week view and a month view with week numbers, person filters, and a detail card for every booking (referee matches show division, teams, venue, assembly time and the whole crew).
- **Drop a document** anywhere on the window and Oden asks which folder it belongs in, saves it and learns it.
- **Always available:** own window with icon, system tray, starts hidden at login, global hotkey **Ctrl+Alt+J**. Background image, sound levels and names are personal settings in `data/ui/`.

Security: the interface is a web page served by the core on `127.0.0.1` and shown in its own window (WebView2). The static files contain no data; every personal endpoint needs the API token, which only the desktop app hands to the page through its JavaScript bridge, so other programs and web pages on the computer cannot use it. Strict Content-Security-Policy, uploads validated by type, size and path (no path traversal), the hotkey uses Windows' `RegisterHotKey` (no keyboard hook), and external links open only for an allowlist of sites.

## Reminders & scheduler

- **ReminderAgent** turns natural language into a structured proposal and always asks for confirmation. "ja" saves, "nej" discards, anything else ("kl 11 istället") corrects. The model never writes to the database; only validated Python code does.
- **Scheduler** (`core/scheduler.py`) runs as a thread inside Jarvis Core. It checks for due reminders every 30 seconds and delivers reminders missed while the computer was off (marked as late).
- **Notifications as channels** (`NotificationService`): Windows toast and Telegram today, a future Jarvis mobile app plugs in as another channel. Notification text is passed to PowerShell via environment variables and XML-escaped, never interpolated into a command.
- **Categories** live in `data/reminder_categories.txt` (private). Reminders store a reserved `calendar_event_id` for the upcoming Google Calendar integration.

## Weather

The weather at home in the header (icon, temperature and a badge such as "regn 17:00"); click it for the weather now (feels-like, wind), a rain alert for the next 12 hours, an hourly strip and five days.

- **Source:** SMHI's open point forecast **SNOW1gv1** (the API that replaced PMP3gv2 in 2026), no key. Fetched by Jarvis Core every 30 minutes; the interface only reads the cached summary.
- **Place:** `weather` in `data/ui/settings.json` (`name`, `lat`, `lon`), default Gunnilse, Göteborg.

## Sports ticker

A results bar along the bottom of Yggdrasil: each league's latest round of results and its next games, 2–4 at a time, with a LIVE badge while a game is on. When a league has been shown it moves on to the next. The league menu (bottom left, scrollable) jumps to a league and adds or removes leagues; rotation continues afterwards. Click the bar for all games with team logos; click a game to open it on ESPN (or shl.se).

- **Sources:** ESPN's public scoreboard JSON for most leagues (Allsvenskan, Premier League, Champions League, NHL, NBA ...; game days are read from the league calendar since the endpoint has no date ranges) and TheSportsDB's free API for SHL, HockeyAllsvenskan, SDHL, Damallsvenskan, Liiga, KHL and more. 38 leagues are built in, up to 30 can be shown. Both sit behind one `Game` model, so a provider can be swapped without touching the interface.
- **Choose leagues by talking to Oden:** "lägg till Premier League i resultaten", "ta bort NHL från resultaten", "vilka ligor finns?". Recognised by fixed patterns (no model), stored in `data/ui/settings.json`. Default: SHL and Allsvenskan.
- **Privacy and safety:** only Jarvis Core talks to the internet – fixed hosts, timeouts and size limits; it refreshes every 10 minutes (every minute while a game is live) and caches the team logos locally (checked by magic bytes), so the interface itself makes no external requests.

## Encrypted backup

Every night (03:00, or as soon as the computer is on after a missed night) Jarvis Core backs up `data/` to a folder on another disk:

- **What:** the memory database, calendar, reminders, lessons, settings, photos and documents. The vector index is skipped (it is rebuilt from the database and documents). SQLite is copied with its own backup API, so the copy is consistent while Jarvis runs.
- **How:** the tar.gz stream goes straight through **AES-256-GCM** in 1 MiB chunks – nothing unencrypted touches the disk. The key comes from `BACKUP_PASSPHRASE` via **scrypt** with a new random salt per backup. Every chunk is authenticated and the last one is marked final, so a wrong passphrase, a changed file or a truncated file is detected.
- **Checked:** each backup is decrypted and read through before it gets its final name; the newest 14 are kept. A failure is shown in Hvergelmer and sent as a Windows/Telegram notification.
- **Restore** (never touches the live data folder):
  ```
  python -m services.backup_service verify  D:\YggdrasilBackup\yggdrasil-20261008-030000.ygg
  python -m services.backup_service restore D:\YggdrasilBackup\yggdrasil-20261008-030000.ygg C:\restore
  ```
  Unpacking refuses absolute paths, `..` and links outside the target folder.

Keep a copy of the passphrase outside the computer – without it no backup can be opened.

## Teaching Oden – lessons

You can teach Oden in plain Swedish instead of changing code:

```
Oden, lär dig: när jag säger match menar jag ett domaruppdrag   -> Oden shows the lesson and where it applies
bara kalendern                                                  -> limit it to the calendar ("gäller alla" for everywhere)
ja                                                              -> saved
vad har du lärt dig?                                            -> numbered list
glöm lärdom 2                                                   -> removed after "ja"
```

- Lessons are stored one per line in `data/lessons.md` (private) and can be edited by hand; `[kalender]`, `[oden]`, `[business]` ... limits a lesson to one agent (`oden` = how requests are routed), no scope means all agents.
- They are added to the prompts of the agents they apply to, below the system instructions. Nothing changes in the code.
- The commands are recognised by fixed patterns in Python (`LessonsAgent`, no language model), and everything is confirmed first, so web pages, documents or the model itself can never add lessons.

## Calendar – Urd

- **CalendarService** (`services/calendar_service.py`) stores bookings per family member in SQLite (`calendar_events`): kind `event`, `work` or `match`, start/end in UTC, location and validated details. Each event has `source` and `external_id` reserved for Google Calendar sync.
- **Referee matches** store sport (fotboll/innebandy), division, home and away team, own role, assembly time and the crew (`HD`, `AD1`, `AD2` ...). They are shown as `⚽ H4 (AD) Floda - Gunnilse` in lists and in full in the detail card:
  ```
  ⚽ H4 AD Floda - Gunnilse
  Flodala
  HD: Anders Andersson
  AD1: Robin Boqvist
  AD2: Johan Johansson
  ```
- **CalendarAgent** also sees reminders (they show in the same calendar) and can list and remove them.
- **CalendarAgent** works like ReminderAgent: the model only produces a structured proposal, you confirm with "ja", and validated Python code writes to the database. It can add, list and remove bookings. Your own name in the referee crew comes from `full_name` for the first person in `data/ui/settings.json`.
- **Several days and recurring bookings:** trips, courses and cups are all-day bookings shown as one banner across the days ("Rydboholm Cup mån–sön"), and bookings can repeat weekly, every other week (also pinned to even/odd weeks: "Julian är hos oss tor–sön varannan jämn vecka resten av året") or monthly. Single days of a series can be removed ("Julian är inte här vecka 44") and extra days added. The model only describes the request; Python computes every date and week number.
- Night shifts (22:00–06:30) roll over to the next day automatically; matches get a default length (football 120 min, floorball 90 min).

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
| Local API | FastAPI + uvicorn (127.0.0.1 only, bearer token, Server-Sent Events) |
| Desktop interface | HTML/CSS/vanilla JS modules + Canvas/SVG, pywebview (WebView2), pystray |
| Phone access | Telegram Bot API (long polling, no open ports) |
| Config/secrets | `.env` (never committed) + `core/config.py` |
| Logging | Centralized rotating file logs, plan IDs for tracing |
| Hardware (dev) | AMD Ryzen 9 3900X · 32 GB RAM · NVIDIA RTX 3060 12 GB |

## Project structure

```
jarvis/
├── jarvis.bat              # Chat with Jarvis in a terminal (uses .venv automatically)
├── scripts/
│   ├── install_core.ps1    # Autostart Jarvis Core at login (no window)
│   ├── restart_core.ps1    # Restart (or -Stop) Jarvis Core, e.g. after editing .env
│   ├── install_desktop.ps1 # Desktop shortcut + tray app at login
│   └── check_autostart.ps1 # Verify that everything starts and runs
├── docker/searxng/         # Private search engine (docker-compose + settings)
├── ui/                     # Desktop interface (HTML/CSS/JS modules, icon) served by the core
├── .env.example            # Configuration template (copy to .env)
├── requirements.txt
│
├── agents/                 # Domain-specific logic, one file per agent
├── clients/
│   ├── desktop.py          # Desktop app: window, tray icon, global hotkey
│   └── terminal.py         # Thin terminal client for Jarvis Core
├── core/
│   ├── api.py              # Local API (127.0.0.1, token, event stream)
│   ├── clock.py            # Current date/time for prompts
│   ├── config.py           # Settings and paths (self-creating folders)
│   ├── events.py           # Live event feed (what Jarvis is doing)
│   ├── jarvis_core.py      # The always-running background process
│   ├── logger.py
│   ├── orchestrator.py     # Routing pipeline (+ standalone debug chat)
│   ├── planner.py
│   ├── router.py
│   ├── scheduler.py        # Delivers reminders (thread in the core)
│   └── single_instance.py  # Lock: only one process owns the memory
├── prompts/                # Static system prompts, one per agent + router
├── services/
│   ├── ollama_service.py   # chat() + embed()
│   ├── prompt_loader.py
│   ├── memory_service.py   # Short-term memory (SQLite)
│   ├── backup_service.py   # Encrypted nightly backup of data/ (AES-256-GCM)
│   ├── sports_service.py   # Sports results (ESPN + TheSportsDB), logo cache
│   ├── weather_service.py  # Weather from SMHI open data (SNOW1gv1)
│   ├── calendar_service.py # Family calendar Urd (SQLite: bookings, shifts, matches)
│   ├── lessons_service.py  # The user's lessons for Oden (data/lessons.md)
│   ├── notification_service.py  # Windows toast + Telegram channels
│   ├── reminder_service.py # Reminders (SQLite, recurrence)
│   ├── system_monitor.py   # GPU load / VRAM for the interface
│   ├── ui_settings.py      # Interface settings, people, images (data/ui/)
│   ├── telegram_service.py # Two-way chat with the phone
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
5. *(Optional)* Connect your phone via Telegram:
   1. In Telegram, talk to **@BotFather**, send `/newbot` and follow the steps. Put the token you get in `.env` as `TELEGRAM_BOT_TOKEN`.
   2. Start Jarvis Core (next step), send `/start` to your new bot, and it replies with your chat id. Put it in `.env` as `TELEGRAM_CHAT_ID` and restart the core with `.\scripts\restart_core.ps1`.
6. Start Jarvis Core automatically at every login (normal user rights, no window):
   ```powershell
   .\scripts\install_core.ps1
   .\scripts\check_autostart.ps1   # everything should be green
   ```
   Test notifications with `.venv\Scripts\python -m core.scheduler --test-notification`. To watch the core's log live instead, run `.\scripts\restart_core.ps1 -Stop` and then `.venv\Scripts\python -m core.jarvis_core`.
7. Chat with Jarvis: double-click `jarvis.bat`, or run it from a terminal:
   ```powershell
   .\jarvis
   ```
   No venv activation is needed. Type your message after `Du >`, `/status` shows how Jarvis is doing, and `exit` quits. Add `--quiet` to hide the live "what Jarvis is doing" lines. Logs are in `logs/jarvis_core.log`.
8. Install the desktop interface (desktop shortcut, tray icon at login, Ctrl+Alt+J):
   ```powershell
   .\scripts\install_desktop.ps1
   ```

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
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | empty | Private Telegram bot: chat and notifications on the phone (optional) |
| `TELEGRAM_MAX_MESSAGE_AGE_MINUTES` | `10` | Older Telegram messages (sent while Jarvis was off) are not executed |
| `TELEGRAM_STARTUP_MESSAGE` | `true` | Send "Jarvis är online" to Telegram when the core starts |
| `JARVIS_API_PORT` | `8765` | Local API port (always bound to 127.0.0.1) |
| `OLLAMA_STARTUP_WAIT_SECONDS` | `300` | How long the core waits for Ollama at login |
| `DESKTOP_HOTKEY` | `ctrl+alt+j` | Global hotkey that brings up the Yggdrasil window |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `BACKUP_DIR` | *(empty)* | Folder on another disk for the encrypted backup (empty = off) |
| `BACKUP_PASSPHRASE` | *(empty)* | Secret, ≥ 12 characters – keep a copy outside the computer |
| `BACKUP_TIME` / `BACKUP_KEEP` | `03:00` / `14` | Nightly time and number of backups kept |

## Status

| Component | Status |
|---|---|
| Config, Logger, PromptLoader, OllamaService | ✅ Verified |
| Router, Planner, Orchestrator | ✅ Verified & tested |
| 7 specialist agents (+ ReminderAgent, CalendarAgent) | ✅ Verified |
| MemoryService (short-term memory) | ✅ Verified |
| VectorService (long-term memory + documents) | ✅ Verified |
| Terminal chat (`jarvis.bat`) | ✅ Verified |
| SearXNG (self-hosted, hardened) | ✅ Verified |
| WebSearchService (live web information) + date awareness | ✅ Implemented |
| ReminderAgent + scheduler + notifications | ✅ Verified |
| Jarvis Core (always running) + local API + event feed | ✅ Implemented |
| Telegram two-way chat (mobile access) | ✅ Implemented |
| Desktop interface "Yggdrasil" (brain map, log/chat, family column, tray, hotkey) | ✅ Verified |
| Family calendar Urd (bookings, work shifts, referee matches, day/week/month views) | ✅ Implemented |
| Lessons – teach Oden in plain Swedish (data/lessons.md) | ✅ Implemented |
| Encrypted nightly backup of data/ (AES-256-GCM, verified, restore CLI) | ✅ Implemented |
| Sports results ticker (ESPN + TheSportsDB, leagues chosen via Oden) | ✅ Implemented |
| Weather (SMHI SNOW1gv1: now, rain alert, hours, 5 days) | ✅ Implemented |
| Hvergelmer security checks, Gmail, Slack, morning briefing | 📋 Planned |
| Google Calendar (family calendars, categories) | 📋 Planned |
| Own Jarvis mobile app (API + Tailscale) | 📋 Planned |
| Voice (local speech-to-text, text-to-speech, "Hej Jarvis" wake word) | 📋 Planned |
| Social media analytics | 📋 Planned |

## Design principles

- **Local-first and private:** all models run locally, telemetry is disabled, and private data in `data/` is never committed.
- **Zero Trust:** no hardcoded credentials, secrets only in `.env`, and registry lookups validated before execution.
- **Fail-fast validation, fail-soft features:** invalid input is rejected early, and optional features degrade gracefully instead of crashing a reply.
- **Infrastructure first, functionality second:** verified components stay stable unless there is a clear architectural reason to change them.
- **Strict 4-tier naming standard** across domain categories, agent IDs, modules and classes.

## License

TBD
