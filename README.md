# Desman

```
        ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋
       ≋                                                  ≋
      ≋            D · E · S · M · A · N                  ≋
       ≋       local AI · connects the unconnected       ≋
        ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋

  ┌─ your machine ─────────────────────────────────────────────┐
  │                                                            │
  │  ┌────────────┐  ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋  ┌─────────────┐ │
  │  │   OLLAMA   │ ≋          .-.          ≋ │ MCP SERVERS │ │
  │  │            │≋≋         (o·o)══════════▶│             │ │
  │  │  llama3    │ ≋≋         ) (          ≋ │◉ freshdesk  │ │
  │  │  qwen2.5   │  ≋≋      /_|_\        ≋≋  │◉ freshsvc   │ │
  │  │  + more    │   ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋ ≋  │◉ your app   │ │
  │  └────────────┘                           └─────────────┘ │
  │                                                            │
  │           no cloud  ·  no lock-in  ·  no leaks            │
  └────────────────────────────────────────────────────────────┘
```

Local, private, open-source AI agent. Connects on-device LLMs (via Ollama) to business applications via MCP servers. No cloud subscription. No vendor lock-in. No data leaves the machine.

> *The desman is a semi-aquatic mammal — an odd evolutionary mashup that connects things that don't normally connect.*

---

## What it does

Desman gives teams a chat interface to their helpdesk and ITSM tools, powered entirely by a local LLM.

**Current integrations**
- **Freshdesk** — tickets, contacts, accounts, groups, ticket fields, knowledge base (24 tools)
- **Freshservice** — tickets, changes, problems, assets, knowledge base, requesters (33 tools)

**UI features**
- Chat panel with real-time streaming and inline tool-call indicators
- CSV import — bulk-create Freshdesk tickets or Freshservice assets row-by-row with drift detection
- Live tool activity feed (sidebar)
- Model selector — auto-detects all locally available Ollama models; user picks at runtime
- MCP server status indicators with per-server enable/disable toggles
- Inline YAML config editor

---

## Project structure

```
desman/
├── agent/                   Core logic
│   ├── config.py            YAML config loader and validator
│   ├── loop.py              Agent loop: Ollama → tool dispatch → stream
│   ├── mcp_client.py        SessionManager, MCPRegistry, FastMCP wiring
│   └── ollama_client.py     Model availability filter
├── config/
│   ├── config.example.yaml  Annotated template — copy to config.local.yaml
│   └── config.local.yaml    Your live config (gitignored — never commit)
├── mcp_servers/             One subfolder per connected application
│   ├── freshservice/
│   │   ├── freshservice_server.py
│   │   └── .env             App credentials (gitignored — never commit)
│   └── freshdesk/
│       ├── freshdesk_server.py
│       └── .env
├── ui/
│   ├── app_fastapi.py       FastAPI backend (current)
│   ├── app.py               Legacy Gradio UI (kept for reference)
│   └── static/
│       ├── index.html       Single-file frontend (all CSS + JS embedded)
│       └── desman-logo.png
├── examples/                Example CSV files for import
├── scripts/                 Dev utilities
├── dist/                    UI release snapshot (see dist/README.md)
├── pyproject.toml
└── README.md
```

---

## Setup

### 1. Install prerequisites

You'll need **Ollama**, **Python 3.11+**, and **uv** (fast Python package manager).

**macOS**
```bash
brew install ollama
brew install uv
```

**Windows** (run in PowerShell or Windows Terminal)
```powershell
winget install Ollama.Ollama
pip install uv
```

**Linux**
```bash
curl -fsSL https://ollama.com/install.sh | sh
pip install uv
```

### 2. Install Python dependencies

```bash
cd desman
uv venv && source .venv/bin/activate   # macOS / Linux
# uv venv && .venv\Scripts\activate    # Windows
uv pip install -e .
```

### 3. Configure MCP servers

Copy the credential templates and fill in your API keys:

```bash
cp mcp_servers/freshservice/.env.example mcp_servers/freshservice/.env
# Edit .env: set FRESHSERVICE_API_KEY, FRESHSERVICE_DOMAIN, REQUESTER_EMAIL

cp mcp_servers/freshdesk/.env.example mcp_servers/freshdesk/.env
# Edit .env: set FRESHDESK_API_KEY, FRESHDESK_DOMAIN
```

### 4. Configure Desman

```bash
cp config/config.example.yaml config/config.local.yaml
# Edit config.local.yaml:
#   - Set system_prompt
#   - Enable/disable mcp_servers entries
#   - Optionally set default_model (can also be changed at runtime in the UI)
```

### 5. Pull at least one Ollama model

```bash
ollama pull llama3.2:3b      # Recommended for Pi / constrained hardware
ollama pull llama3.1:8b      # Recommended for 16 GB machines
```

### 6. Run

```bash
python ui/app_fastapi.py
# → http://127.0.0.1:7860
```

---

## Adding a new application

1. Create `mcp_servers/<appname>/`
2. Add the MCP server script and a `.env` with credentials
3. Add an entry to `config.local.yaml` under `mcp_servers`
4. Restart Desman

No code changes required.

---

## Hardware targets

| Device | RAM | Recommended model |
|---|---|---|
| Raspberry Pi 5 | 8 GB | llama3.2:3b only |
| MacBook Air M1 | 16 GB | llama3.1:8b |
| Mac Mini M4 | 24–32 GB | llama3.1:8b or larger |

---

## Known limitations

- **Smaller models struggle with tool routing** — llama3.2:3b, llama3.1:8b, and Qwen2.5:7b work but need an explicit, minimal system prompt. More capable models (13B+) are significantly more reliable.
- **Single user, single machine** — no auth, no multi-tenancy.
- **Restart required** — config changes take effect on next `python ui/app_fastapi.py`.

---

## Roadmap

**v0.1 (current)**
- Local Ollama inference, no cloud backend
- FastAPI + single-file HTML/JS UI
- System prompt configurable via YAML; model selected at runtime
- MCP servers as self-contained subfolders
- CSV bulk import with drift detection
- Freshdesk (24 tools) + Freshservice (33 tools)

**v0.2 considerations**
- Setup wizard — select applications, enter credentials via UI
- Per-server system prompt overrides
- Multi-user support
- AD / SSO integration
