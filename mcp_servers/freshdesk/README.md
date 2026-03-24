# Freshdesk MCP Server

MCP server exposing Freshdesk helpdesk operations as tools for the Desman agent. Connects via the Freshdesk REST API using an API key.

---

## Setup

### 1. Add credentials

Copy the template and fill in your API key:

```bash
cp mcp_servers/freshdesk/.env.example mcp_servers/freshdesk/.env
```

Edit `mcp_servers/freshdesk/.env`:

```
FRESHDESK_API_KEY=your_api_key_here
FRESHDESK_DOMAIN=yourcompany.freshdesk.com
```

**Getting your API key:** Freshdesk → Profile Settings → API Key (bottom right). The domain is the subdomain of your Freshdesk portal — e.g. if your portal is at `acme.freshdesk.com`, set `FRESHDESK_DOMAIN=acme.freshdesk.com`.

### 2. Register in Desman config

In `config/config.local.yaml`, ensure this entry exists under `mcp_servers`:

```yaml
mcp_servers:
  - name: "freshdesk"
    folder: "freshdesk"
    script: "freshdesk_server.py"
    enabled: true
```

### 3. Restart Desman

```bash
python ui/app_fastapi.py
```

No separate venv needed. All dependencies (`fastmcp`, `httpx`, `python-dotenv`) are in the root `pyproject.toml`.

---

## Tools (24)

### Tickets

| Tool | Description |
|---|---|
| `create_ticket` | Create a new ticket with subject, description, type, priority, status, group, and assignee |
| `list_tickets` | List tickets filtered by status (`open`, `pending`, `resolved`, `closed`) |
| `get_ticket` | Retrieve a ticket and its full details by ID |
| `update_ticket` | Update status, priority, or add an internal note to a ticket |
| `delete_ticket` | Permanently delete a ticket by ID |
| `search_tickets` | Full-text search across tickets |
| `reply_to_ticket` | Send a public reply to a ticket |
| `get_ticket_conversations` | Fetch the full conversation thread for a ticket |

### Contacts

| Tool | Description |
|---|---|
| `get_contact_by_email` | Look up a contact by email address |
| `create_contact` | Create a new contact with name, email, and optional phone |

### Accounts

| Tool | Description |
|---|---|
| `create_account` | Create a company account by name |
| `link_contact_to_account` | Associate a contact (by email) with an account (by name) |

### Knowledge Base

| Tool | Description |
|---|---|
| `search_knowledge_base` | Search KB articles by keyword |
| `list_kb_folders` | List all KB folders and their IDs |
| `create_kb_article` | Create a new KB article in a named folder |

### Groups

| Tool | Description |
|---|---|
| `list_groups` | List all agent groups |
| `get_group` | Get a group by name |
| `add_me_to_group` | Add the authenticated agent to a group by name |
| `create_group` | Create a new agent group |
| `update_group` | Rename or update a group's description |

### Ticket Forms & Fields

| Tool | Description |
|---|---|
| `list_ticket_forms` | List all ticket forms |
| `create_ticket_form` | Create a new ticket form |
| `list_ticket_fields` | List all ticket fields and their metadata |
| `create_ticket_field` | Create a new custom ticket field (text, dropdown, checkbox, etc.) |

---

## Tool naming in Desman

Desman prefixes all tool names with the server name to avoid routing collisions. In the agent loop and activity feed, these tools appear as:

```
freshdesk_create_ticket
freshdesk_list_tickets
freshdesk_search_knowledge_base
... etc
```

---

## Permissions required

The API key must belong to an **agent** account (not a contact). For full tool access, the agent should have:

- Ticket management permissions (view, create, update, delete)
- Contact and account management
- Knowledge base read/write
- Group management (for group tools)

Admin-level API keys have all permissions by default.
