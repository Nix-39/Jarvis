# Jarvis — Local-First Agent Operating System

A modular, security-first, local AI operating system built for personal use, business automation, and as a professional software architecture portfolio project.

Jarvis coordinates multiple specialized AI agents behind a single orchestrator, running entirely on local hardware via [Ollama](https://ollama.com). It is designed from day one for long-term scalability rather than rapid prototyping — the architecture is built first, functionality is added incrementally on top of it.

## What Jarvis does

Jarvis routes natural-language requests to the right specialist agent, which handles the request using a local LLM and, going forward, persistent memory and external tools. Planned use cases include:

- Personal productivity and self-directed learning support
- Business automation for [VerkstadsFlow](https://www.verkstadsflow.se) (web agency for automotive workshops)
- Career support (CV, cover letters, job applications)
- Content creation and social media management
- Future: voice interaction, mobile connectivity, analytics, and multi-agent collaboration

## Architecture

\`\`\`
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
\`\`\`

**Separation of concerns:**

- **Router** — intent classification only. Outputs a validated Domain Category. No business logic or agent instantiation.
- **Orchestrator** — sole system entry point. Owns the mapping between Domain Categories and Internal Agent IDs.
- **Planner** — works with Internal Agent IDs only. Coordinates thread-safe execution, timeouts, and retries via the `Agent` protocol (`handle`).
- **Agents** — domain-specific business logic only. Never talk to external systems directly.
- **Services** — infrastructure and external integrations only (LLM calls, prompt loading, and going forward: memory, vector search, notifications, etc.).

## Tech stack

| Component | Details |
|---|---|
| Language | Python 3.13 |
| Local LLM | llama3.1:8b via [Ollama](https://ollama.com) (`http://localhost:11434`) |
| Hardware (dev) | AMD Ryzen 9 3900X · 32 GB RAM · NVIDIA RTX 3060 12 GB |
| Config/secrets | `.env` (never committed) + `core/config.py` |
| Logging | Centralized, rotating file logs with correlation IDs |

## Project structure

\`\`\`
jarvis/
├── .env                    # Local secrets (not committed)
├── requirements.txt
├── README.md
│
├── agents/                 # Domain-specific business logic
│   ├── business_agent.py
│   ├── career_agent.py
│   ├── contentcreator_agent.py
│   ├── education_agent.py
│   ├── general_agent.py
│   ├── socialmediamanager_agent.py
│   └── webdeveloper_agent.py
│
├── core/                   # Orchestration only
│   ├── config.py
│   ├── logger.py
│   ├── orchestrator.py
│   ├── planner.py
│   └── router.py
│
├── data/                   # SQLite database (gitignored)
├── logs/                   # Rotating log files (gitignored)
│
├── prompts/                # Static system prompts, one per agent + router
│
├── services/                # Infrastructure & external integrations
│   ├── ollama_service.py
│   ├── prompt_loader.py
│   └── memory_service.py   # In progress
│
└── templates/
\`\`\`

## Getting started

1. Clone the repo and create a virtual environment:
   \`\`\`bash
   git clone https://github.com/Nix-39/jarvis.git
   cd jarvis
   python -m venv .venv
   source .venv/bin/activate   # or .venv\Scripts\activate on Windows
   \`\`\`
2. Install dependencies:
   \`\`\`bash
   pip install -r requirements.txt
   \`\`\`
3. Copy `.env.example` to `.env` and fill in any required values.
4. Make sure [Ollama](https://ollama.com) is running locally with the `llama3.1:8b` model pulled:
   \`\`\`bash
   ollama pull llama3.1:8b
   \`\`\`
5. Run the full pipeline:
   \`\`\`bash
   python -m core.orchestrator
   \`\`\`

## Status

**Current milestone:** first-generation core architecture and complete agent layer, verified end-to-end.

| Component | Status |
|---|---|
| Config, Logger | ✅ Verified |
| PromptLoader, OllamaService | ✅ Verified |
| Router | ✅ Verified & tested |
| Planner | ✅ Verified & tested |
| Orchestrator | ✅ Verified & tested |
| 7 specialist agents | ✅ Verified |
| Full pipeline (`python -m core.orchestrator`) | ✅ Verified |
| **MemoryService** (SQLite session & conversation memory) | 🔧 In progress |
| VectorService (RAG / semantic search) | 📋 Planned |
| Slack integration | 📋 Planned |
| Voice / speech-to-text / text-to-speech | 📋 Planned |
| Social media analytics service | 📋 Planned |

## Design principles

- **Zero Trust** — no hardcoded credentials, all secrets via `.env`.
- **Fail-fast validation** and least-privilege access throughout.
- **Infrastructure first, functionality second** — verified components stay stable unless there's a clear architectural reason to change them.
- **Strict 4-tier naming standard** across Domain Categories, Internal Agent IDs, Python modules, and class names to keep the codebase unambiguous as it grows.

## License

TBD