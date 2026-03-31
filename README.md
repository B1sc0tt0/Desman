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
- **Freshservice** — tickets, changes, problems, assets, service catalog, journeys, knowledge base (47 tools)
- **RAG** — local document knowledge base (ChromaDB + Ollama embeddings, 6 tools)

**UI features**
- Chat panel with real-time streaming and inline tool-call indicators
- Model name badge shown on each assistant message and in the activity feed
- CSV import — bulk-create Freshdesk tickets or Freshservice assets from a spreadsheet
- RAG panel — upload PDF, DOCX, TXT, or MD files; browse collections; delete documents
- Live tool activity feed (sidebar)
- Model selector — pick your model at runtime; local and cloud models shown together
- MCP server status indicators (FRESHDESK, FRESHSERVICE, RAG) with per-server enable/disable toggles
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

### Step 3 — Install optional RAG dependencies

If you want to use the local knowledge base (RAG), install the extra packages:

```bash
uv pip install -e ".[rag]"
```

Then pull the embedding model (one-time, ~270 MB):

```bash
ollama pull nomic-embed-text
```

> RAG is **disabled by default** (`enabled: false` in `config.local.yaml`). Skip this step entirely if you don't plan to use the knowledge base. To enable it, set `enabled: true` under the `rag` entry in `mcp_servers` and restart Desman.

---

### Step 4 — Add your Freshdesk / Freshservice credentials

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

### Step 5 — Configure Desman

```bash
cp config/config.example.yaml config/config.local.yaml
```

Open `config/config.local.yaml` and review it. The defaults work out of the box, but you may want to:
- Change `system_prompt` to match your team's context (e.g. "You are an IT support assistant for Acme Corp…")
- Set `default_model` to the model you plan to use most
- Enable or disable individual MCP servers under `mcp_servers`

> `config.local.yaml` is also gitignored — safe to put real values in here.

---

### Step 6 — Pull an Ollama model

Download at least one local model before starting. This is a one-time download per model.

```bash
ollama pull llama3.2:3b      # Small and fast — good for low-memory machines
ollama pull llama3.1:8b      # Better quality — recommended for 16 GB machines
```

> You can skip this step if you plan to use only cloud models (HuggingFace, Anthropic, or OpenAI). Add your API key in the UI after starting Desman.

---

### Step 7 — Start Desman

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
│   ├── freshdesk/
│   │   ├── freshdesk_server.py
│   │   └── .env
│   └── rag/
│       ├── rag_server.py    Local RAG (ChromaDB + Ollama embeddings)
│       ├── chroma_db/       Persisted vector store (auto-created)
│       └── data/            Uploaded documents (auto-created)
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

- **3B models are unreliable for multi-step tool chains** — RAG requires two sequential tool calls (`rag_list_collections` → `rag_query`); 3B models frequently skip the first step or narrate tool calls as prose instead of invoking them. Use `llama3.1:8b` or larger (or a cloud model) for any RAG workflow.
- **Complex ticket field creation needs 8B+** — `freshdesk_create_ticket_field` with `nested_field` type requires constructing JSON in `choices_json` and `dependent_fields_json`. 3B models struggle to assemble these correctly. For simple text/dropdown fields, 3B is fine.
- **Smaller models struggle with multi-step tasks generally** — 7B models handle most single-tool requests well. For workflows that combine RAG lookup + action tool (e.g. "look up the customer profile then create a ticket"), use 8B+ or a cloud model.
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
- Freshdesk (24 tools) + Freshservice (47 tools) + local RAG knowledge base (6 tools)

**Recent additions (v0.1.x)**
- **RAG knowledge base** — upload PDF, DOCX, TXT, or MD files via the UI; query with semantic search backed by ChromaDB and Ollama embeddings (`nomic-embed-text`); fully local, no cloud dependency
- **Freshservice service catalog** — create and update service catalog items (fixed: correct hyphenated API endpoint `service-catalog/items`; `visibility` parameter controls draft vs published)
- **Freshservice journeys** — create onboarding/offboarding requests, list active journeys, get journey activities, cancel requests
- **Freshservice service requests** — create requests from catalog items, list requests, approve requests
- **Freshdesk ticket fields** — full field creation: customer visibility (`displayed_to_customers`, `customers_can_edit`), structured dropdown choices, dependent/nested fields, section mappings
- HuggingFace model reliability: Gemma and other HF-hosted models now correctly produce a prose answer after tool results instead of re-invoking tools or looping
- Null argument guard: HuggingFace API responses with `null` tool arguments no longer crash the agent
- Model name badge: the active model is shown inline on each assistant message and in the tool activity feed

**v0.2 considerations**
- Setup wizard — configure credentials and MCP servers entirely through the UI
- Per-server system prompt overrides
- Multi-user support
- AD / SSO integration
