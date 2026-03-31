# Freshservice MCP Server

Connects Desman to Freshservice (ITSM) via the Freshservice v2 REST API.

## Setup

```bash
cp .env.example .env
# Edit .env: set FRESHSERVICE_API_KEY, FRESHSERVICE_DOMAIN, REQUESTER_EMAIL
```

No separate venv needed — this server runs inside Desman's venv.
All dependencies are handled by the root `pyproject.toml`.

## Available tools (47)

### Tickets
| Tool | Description |
|---|---|
| `create_ticket` | Create a new incident ticket |
| `list_tickets` | List tickets by status |
| `get_ticket_by_id` | Get full ticket details |
| `update_ticket` | Update status or add a note |
| `reply_to_ticket` | Add a reply to a ticket |
| `get_ticket_activities` | Get audit trail for a ticket |
| `delete_ticket` | Delete a ticket |
| `search_tickets` | Full-text ticket search |

### Changes
| Tool | Description |
|---|---|
| `create_change` | Create a change request |
| `list_changes` | List change requests |
| `update_change` | Update status or add a note |
| `close_change` | Close a change with a note |
| `delete_change` | Delete a change |
| `create_change_note` | Add a note to a change |

### Problems
| Tool | Description |
|---|---|
| `list_problems` | List problems |
| `get_problem_by_id` | Get full problem details |
| `create_problem` | Create a new problem record |
| `update_problem` | Update status or add a note |
| `close_problem` | Close a problem with a note |
| `add_problem_note` | Add a note to a problem |

### Assets
| Tool | Description |
|---|---|
| `list_assets` | List assets, optionally filtered |
| `list_asset_types` | List all asset type categories |
| `get_asset_type_fields` | Get custom fields for an asset type |
| `get_asset_by_id` | Get full asset details |
| `create_asset` | Create a new asset |
| `update_asset` | Update asset fields |
| `delete_asset` | Delete an asset |
| `assign_asset_to_me` | Assign an asset to the requester |

### Service Catalog
| Tool | Description |
|---|---|
| `list_service_catalog_categories` | List all catalog categories |
| `list_service_catalog_items` | List catalog items, optionally filtered |
| `get_service_catalog_item` | Get full item details and custom fields |
| `create_service_catalog_item` | Create a new catalog item (visibility: 1=draft, 2=published) |
| `update_service_catalog_item` | Update an existing catalog item |
| `create_service_request` | Place a service request from a catalog item |
| `list_service_requests` | List service requests |
| `approve_service_request` | Approve a pending service request |

### Journeys (Onboarding / Offboarding)
| Tool | Description |
|---|---|
| `list_active_journeys` | List active onboarding and offboarding requests |
| `get_journey_by_id` | Get details of a journey request |
| `get_journey_activities` | Get activity log for a journey |
| `create_onboarding_request` | Start an onboarding journey for a new employee |
| `create_offboarding_request` | Start an offboarding journey |
| `cancel_journey_request` | Cancel an active journey request |

### Knowledge Base
| Tool | Description |
|---|---|
| `search_knowledge_base` | Search solution articles |
| `list_solution_folders` | List KB folders |
| `create_solution_article` | Create a new KB article |

### Requesters
| Tool | Description |
|---|---|
| `get_requester_by_email` | Look up a requester by email address |
| `promote_to_major_incident` | Promote a ticket to a major incident |

## Model guidance

- **3B models (Llama 3.2 3B)** — reliable for single-tool requests: list, get, create ticket/change. Avoid complex multi-step flows.
- **7B–8B models** — recommended for service catalog and journey workflows which involve two sequential tool calls (list categories → create item).
- **service catalog item creation** — requires `category_id` from `list_service_catalog_categories`. Prompt the model to call that first.

Source: https://github.com/B1sc0tt0/Freshservice-MCP-Server-Client
