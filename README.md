# Desman

Local, private, open-source AI agent. Connects on-device LLMs (via Ollama) to business applications via MCP servers. No cloud subscription required. No data leaves your machine unless you opt in to a cloud model.

> *The desman is a semi-aquatic mammal — an odd evolutionary mashup that connects things that don't normally connect.*

---

## What it does

Desman gives you a chat interface to your helpdesk and ITSM tools, powered by an AI model running on your own hardware — or optionally through a cloud API.

Ask questions like:
- *"Show me all open tickets assigned to the networking team"*
- *"Create a ticket for a printer issue in the Berlin office"*
- *"List all assets in the London site"*
- *"Search the knowledge base for VPN setup instructions"*

The agent automatically picks the right tool, calls it, and streams the answer back to you.

**Current integrations**
- **Freshdesk** — tickets, contacts, accounts, groups, ticket fields, knowledge base (24 tools)
- **Freshservice** — tickets, changes, problems, assets, knowledge base, requesters (33 tools)

**UI features**
- Chat panel with real-time streaming and inline tool-call indicators
- CSV import — bulk-create Freshdesk tickets or Freshservice assets from a spreadsheet
- Live tool activity feed (sidebar)
- Model selector — pick your model at runtime; local and cloud models shown together
- MCP server status indicators with per-server enable/disable toggles
- Settings panel — configure API keys, YAML config, and explore MCP tool details in the browser

---

## Model options

Desman supports two types of models. You can use either, or both at the same time.

### Local models (no internet required)
Run entirely on your machine via [Ollama](https://ollama.com). Your data never leaves the device.

| Device | RAM | Recommended model |
|---|---|---|
| Raspberry Pi 5 | 8 GB | `llama3.2:3b` |
| MacBook Air M1 | 16 GB | `llama3.1:8b` |
| Mac Mini M4 | 24–32 GB | `llama3.1:8b` or larger |

### Cloud models (internet required)
Configured in the UI under **Settings → External APIs**. Just paste your API key — no config files needed.

| Provider | Models | Notes |
|---|---|---|
| HuggingFace | Llama 3.3 70B, Qwen 2.5 72B, Gemma 27B, Mistral, Mixtral and more | Free tier available at [huggingface.co](https://huggingface.co) |
| Anthropic | Claude Sonnet 4.6, Claude Haiku 4.5, Claude Opus 4.6 | Paid API |
| OpenAI | GPT-4o, GPT-4o Mini, GPT-4 Turbo | Paid API |

---

## Setup

### What you need before starting

- **Python 3.12 or newer** — [python.org/downloads](https://www.python.org/downloads/)
- **Ollama** — runs AI models locally on your machine
- **uv** — a fast Python package installer (replaces pip for this project)
- API keys for Freshdesk and/or Freshservice

> **Not sure if you have Python?** Open a terminal and type `python --version`. If it shows 3.12 or higher, you're good.

---

### Step 1 — Install Ollama and uv

**macOS**
```bash
brew install ollama
brew install uv
```

**Windows** (run in PowerShell)
```powershell
winget install Ollama.Ollama
pip install uv
```

**Linux**
```bash
curl -fsSL https://ollama.com/install.sh | sh
pip install uv
```

---

### Step 2 — Download the project and install dependencies

```bash
cd desman
uv venv && source .venv/bin/activate   # macOS / Linux
# uv venv && .venv\Scripts\activate    # Windows

uv pip install -e .
```

This creates an isolated Python environment and installs everything Desman needs.

---

### Step 3 — Add your Freshdesk / Freshservice credentials

Each integration has a credentials file. Copy the template and fill in your details.

**Freshservice**
```bash
cp mcp_servers/freshservice/.env.example mcp_servers/freshservice/.env
```
Then open `mcp_servers/freshservice/.env` in any text editor and set:
```
FRESHSERVICE_API_KEY=your_api_key_here
FRESHSERVICE_DOMAIN=yourcompany.freshservice.com
REQUESTER_EMAIL=you@yourcompany.com
```

**Freshdesk**
```bash
cp mcp_servers/freshdesk/.env.example mcp_servers/freshdesk/.env
```
Then open `mcp_servers/freshdesk/.env` and set:
```
FRESHDESK_API_KEY=your_api_key_here
FRESHDESK_DOMAIN=yourcompany.freshdesk.com
```

> **Where to find your API key:** In Freshservice or Freshdesk, go to your profile (top-right corner) → Profile Settings → API Key.

> These `.env` files are gitignored — they will never be accidentally committed to version control.

---

### Step 4 — Configure Desman

```bash
cp config/config.example.yaml config/config.local.yaml
```

Open `config/config.local.yaml` and review it. The defaults work out of the box, but you may want to:
- Change `system_prompt` to match your team's context (e.g. "You are an IT support assistant for Acme Corp…")
- Set `default_model` to the model you plan to use most
- Enable or disable individual MCP servers under `mcp_servers`

> `config.local.yaml` is also gitignored — safe to put real values in here.

---

### Step 5 — Pull an Ollama model

Download at least one local model before starting. This is a one-time download per model.

```bash
ollama pull llama3.2:3b      # Small and fast — good for low-memory machines
ollama pull llama3.1:8b      # Better quality — recommended for 16 GB machines
```

> You can skip this step if you plan to use only cloud models (HuggingFace, Anthropic, or OpenAI). Add your API key in the UI after starting Desman.

---

### Step 6 — Start Desman

```bash
python ui/app_fastapi.py
```

Then open your browser at: **http://127.0.0.1:7860**

To stop Desman, press `Ctrl+C` in the terminal.

---

## Using cloud models (HuggingFace, Anthropic, OpenAI)

You don't need to edit any config files for cloud models. Just:

1. Start Desman and open the UI
2. Click **Settings** (top-right gear icon)
3. Go to the **External APIs** tab
4. Paste your API key and toggle the provider on
5. Click **Save & Apply**

Cloud models will appear in the model selector immediately.

**HuggingFace free tier** gives access to Llama 3.3 70B, Qwen 2.5 72B, Gemma 27B, Mistral, Mixtral and others — no credit card required. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) with *"Make calls to Inference Providers"* permission enabled.

---

## Adding a new application

1. Create `mcp_servers/<appname>/`
2. Add the MCP server script and a `.env` file with the app's credentials
3. Add an entry to `config.local.yaml` under `mcp_servers`
4. Restart Desman

No code changes required in Desman itself.

---

## Project structure

```
desman/
├── agent/                   Core logic
│   ├── config.py            YAML config loader and validator
│   ├── loop.py              Agent loop: model → tool dispatch → stream
│   ├── mcp_client.py        MCP session manager
│   └── providers.py         Multi-provider LLM client (Ollama, Anthropic, OpenAI, HuggingFace)
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
│   ├── app_fastapi.py       FastAPI backend
│   └── static/
│       ├── index.html       Single-file frontend (all CSS + JS embedded)
│       └── desman-logo.png
├── dist/                    Prebuilt UI snapshot for releases
├── examples/                Example CSV files for bulk import
├── scripts/                 Dev utilities
├── pyproject.toml
└── README.md
```

---

## Known limitations

- **Smaller models struggle with complex requests** — 3B and 7B models work well for straightforward queries but may need more explicit instructions for multi-step tasks. Models 13B and above are noticeably more reliable.
- **Single user, single machine** — no authentication, no multi-tenancy. Designed for personal or small-team use on a trusted network.
- **Restart required for config changes** — changes to `config.local.yaml` (models list, MCP servers, system prompt) take effect after restarting with `python ui/app_fastapi.py`. API keys and the enabled/disabled toggle for cloud providers can be changed live in the UI without restarting.

---

## Roadmap

**v0.1 (current)**
- Local Ollama inference + cloud APIs (HuggingFace, Anthropic, OpenAI)
- FastAPI backend + single-file HTML/JS UI
- System prompt and model list configurable via YAML; model switchable at runtime
- MCP servers as self-contained subfolders — add a new app without touching Desman code
- CSV bulk import with per-row status and drift detection
- Freshdesk (24 tools) + Freshservice (33 tools)

**v0.2 considerations**
- Setup wizard — configure credentials and MCP servers entirely through the UI
- Per-server system prompt overrides
- Multi-user support
- AD / SSO integration
