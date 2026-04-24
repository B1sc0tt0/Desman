# Web Search MCP Server

Provides web search via [DuckDuckGo](https://duckduckgo.com) — **no API key required**.

Used by the demo prep workflow to research companies and prospects before a discovery call.

## Setup

No credentials needed. Enable in `config.local.yaml`:

```yaml
mcp_servers:
  - name: "websearch"
    folder: "websearch"
    script: "websearch_server.py"
    enabled: true
```

No separate venv needed — this server runs inside Desman's venv.
All dependencies are handled by the root `pyproject.toml` (`ddgs` package).

## Available tools

| Tool | Description |
|---|---|
| `search` | Search the web using DuckDuckGo. Returns title, URL, and snippet for each result. |

## Usage

The `search` tool is used automatically by the demo prep workflow. You can also invoke it
directly in the chat:

> *"Search for Clariant AG specialty chemicals"*

## Notes

- **No API key required** — Uses the `ddgs` package (DuckDuckGo), free and anonymous.
- Results are capped at 10 regardless of `max_results`.
- If DuckDuckGo rate-limits the request, the server waits 2 s and retries once.
- Internet access is required. If Desman runs on an air-gapped machine, disable this server.
