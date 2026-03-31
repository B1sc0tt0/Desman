# Freshdesk MCP Server

Connects Desman to Freshdesk (customer support) via the Freshdesk v2 REST API.

## Setup

```bash
cp .env.example .env
# Edit .env: set FRESHDESK_API_KEY, FRESHDESK_DOMAIN
```

No separate venv needed — this server runs inside Desman's venv.
All dependencies are handled by the root `pyproject.toml`.

## Available tools (24)

### Tickets
| Tool | Description |
|---|---|
| `create_ticket` | Create a new support ticket |
| `list_tickets` | List tickets by status |
| `get_ticket` | Get full ticket details |
| `update_ticket` | Update status, priority, or add a note |
| `delete_ticket` | Delete a ticket |
| `search_tickets` | Full-text ticket search |
| `reply_to_ticket` | Add a reply to a ticket |
| `get_ticket_conversations` | Get conversation thread for a ticket |

### Contacts & Accounts
| Tool | Description |
|---|---|
| `get_contact_by_email` | Look up a contact by email |
| `create_contact` | Create a new contact |
| `create_account` | Create a new company account |
| `link_contact_to_account` | Associate a contact with an account |

### Groups
| Tool | Description |
|---|---|
| `list_groups` | List all agent groups |
| `get_group` | Get details of a group by name |
| `create_group` | Create a new agent group |
| `update_group` | Rename or update a group |
| `add_me_to_group` | Add the current agent to a group |

### Ticket Fields
| Tool | Description |
|---|---|
| `list_ticket_fields` | List all ticket fields |
| `create_ticket_field` | Create a custom ticket field (see below) |

### Ticket Forms
| Tool | Description |
|---|---|
| `list_ticket_forms` | List ticket forms |
| `create_ticket_form` | Create a new ticket form |

### Knowledge Base
| Tool | Description |
|---|---|
| `list_kb_folders` | List KB folders |
| `search_knowledge_base` | Search KB articles |
| `create_kb_article` | Create a new KB article |

## Ticket field creation

`create_ticket_field` supports all Freshdesk custom field types and visibility options.

**Visibility** — by default fields are hidden from customers (agent-only). Use these parameters to make a field visible in the customer portal:
- `displayed_to_customers=true` — show the field
- `customers_can_edit=true` — allow customers to fill it in

**Field types:**
| Type | Notes |
|---|---|
| `custom_text` | Single-line text |
| `custom_paragraph` | Multi-line text |
| `custom_dropdown` | Dropdown — provide `choices` or `choices_json` |
| `custom_checkbox` | Boolean checkbox |
| `custom_date` | Date picker |
| `custom_number` | Integer |
| `custom_decimal` | Decimal number |
| `custom_url` | URL input |
| `nested_field` | 3-level cascading dropdown — requires `choices_json` + `dependent_fields_json` |

**Simple dropdown example:**
```
choices="Refund,Faulty Product,Item Not Delivered"
```

**Structured dropdown with positions (choices_json):**
```json
[{"value":"Refund","position":1},{"value":"Faulty Product","position":2}]
```

**Nested/dependent field (choices_json + dependent_fields_json):**
```json
// choices_json — full 3-level hierarchy
[{"value":"HDFC","position":1,"choices":[{"value":"Chennai","position":1,"choices":[{"value":"Porur","position":1}]}]}]

// dependent_fields_json — labels for levels 2 and 3
[{"label":"District","label_for_customers":"District","level":2},{"label":"Branch","label_for_customers":"Branch","level":3}]
```

## Model guidance

- **3B models** — reliable for list/get operations and simple field creation (text, checkbox, basic dropdown with `choices=`).
- **7B–8B models** — recommended for `nested_field` creation; constructing `choices_json` and `dependent_fields_json` JSON inline requires reliable structured output.
- **Visibility parameters** — always specify `displayed_to_customers` and `customers_can_edit` explicitly; the default is agent-only (hidden from customers).

Source: https://github.com/B1sc0tt0/Freshdesk-MCP-Server-Client
