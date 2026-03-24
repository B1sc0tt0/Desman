# Freshservice MCP Server

MCP server exposing Freshservice ITSM operations as tools for the Desman agent. Connects via the Freshservice REST API using an API key.

---

## Setup

### 1. Add credentials

Copy the template and fill in your API key:

```bash
cp mcp_servers/freshservice/.env.example mcp_servers/freshservice/.env
```

Edit `mcp_servers/freshservice/.env`:

```
FRESHSERVICE_API_KEY=your_api_key_here
FRESHSERVICE_DOMAIN=yourcompany.freshservice.com
REQUESTER_EMAIL=you@yourcompany.com
```

**Getting your API key:** Freshservice → Profile Settings → API Key (bottom right). The domain is the subdomain of your Freshservice portal — e.g. if your portal is at `acme.freshservice.com`, set `FRESHSERVICE_DOMAIN=acme.freshservice.com`. `REQUESTER_EMAIL` is used as the default requester when creating Changes and Problems.

### 2. Register in Desman config

In `config/config.local.yaml`, ensure this entry exists under `mcp_servers`:

```yaml
mcp_servers:
  - name: "freshservice"
    folder: "freshservice"
    script: "freshservice_server.py"
    enabled: true
```

### 3. Restart Desman

```bash
python ui/app_fastapi.py
```

No separate venv needed. All dependencies (`fastmcp`, `httpx`, `python-dotenv`) are in the root `pyproject.toml`.

---

## Tools (33)

### Tickets

| Tool | Description |
|---|---|
| `create_ticket` | Create a new ticket with subject, description, and priority |
| `list_tickets` | List tickets filtered by status (`open`, `pending`, `resolved`, `closed`) |
| `get_ticket_by_id` | Retrieve a ticket and its full details by ID |
| `update_ticket` | Update status or add an internal note to a ticket |
| `reply_to_ticket` | Send a public reply to the requester of a ticket |
| `get_ticket_activities` | Fetch the full activity log for a ticket |
| `delete_ticket` | Permanently delete a ticket by ID |
| `search_tickets` | Full-text search across tickets by keyword |
| `promote_to_major_incident` | Get instructions for promoting a ticket to a Major Incident |

### Requesters

| Tool | Description |
|---|---|
| `get_requester_by_email` | Look up a requester by email address |

### Changes

| Tool | Description |
|---|---|
| `create_change` | Create a Change Request with subject, description, planned start/end, and type |
| `list_changes` | List all Change Requests (paginated) |
| `update_change` | Update a Change Request status or add a note |
| `close_change` | Close a Change Request with a closing note |
| `delete_change` | Permanently delete a Change Request |
| `create_change_note` | Add a note to an existing Change Request |

### Problems

| Tool | Description |
|---|---|
| `list_problems` | List all Problems (paginated) |
| `get_problem_by_id` | Retrieve a Problem and its details by ID |
| `create_problem` | Create a new Problem with subject, description, and due date |
| `update_problem` | Update a Problem status or add a note |
| `close_problem` | Close a Problem with a closing note |
| `add_problem_note` | Add a note to an existing Problem |

### Assets

| Tool | Description |
|---|---|
| `list_assets` | List all assets, with optional filter by name, tag, or asset type |
| `list_asset_types` | List all asset types (e.g. Laptop, Monitor, Hardware) |
| `get_asset_type_fields` | Return the field schema for a given asset type |
| `get_asset_by_id` | Retrieve full details of a single asset by ID |
| `create_asset` | Create a new asset by name, type, state, product, and tag |
| `update_asset` | Update an asset's name, tag, description, or assigned user |
| `delete_asset` | Permanently delete an asset by ID |
| `assign_asset_to_me` | Assign an asset to the default requester configured in `.env` |

### Knowledge Base

| Tool | Description |
|---|---|
| `search_knowledge_base` | Search KB articles by keyword |
| `list_solution_folders` | List all KB categories and their folders with IDs |
| `create_solution_article` | Create a new KB article in a specified folder |

---

## Tool naming in Desman

Desman prefixes all tool names with the server name to avoid routing collisions. In the agent loop and activity feed, these tools appear as:

```
freshservice_create_ticket
freshservice_list_changes
freshservice_create_asset
... etc
```

---

## Permissions required

The API key must belong to an **agent** account (not a requester). For full tool access, the agent should have:

- Ticket management permissions (view, create, update, delete)
- Change and Problem management
- Asset management (CMDB read/write)
- Knowledge base read/write
- Requester lookup

Admin-level API keys have all permissions by default.
