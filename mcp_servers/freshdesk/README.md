# Freshdesk MCP Server

Copy `freshdesk_server.py` into this folder and fill in your credentials.

## Setup

```bash
# Copy and fill in credentials
cp .env.example .env
# Edit .env: set FRESHDESK_API_KEY, FRESHDESK_DOMAIN
```

No separate venv needed — this server runs inside Desman's venv.
All dependencies are handled by the root `pyproject.toml`.

Source: https://github.com/B1sc0tt0/Freshdesk-MCP-Server-Client
