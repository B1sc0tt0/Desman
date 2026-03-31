# freshdesk_server.py
import os
import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Freshdesk Server")

API_KEY  = os.getenv('FRESHDESK_API_KEY')
DOMAIN   = os.getenv('FRESHDESK_DOMAIN')
BASE_URL = f'https://{DOMAIN}/api/v2'

def get_client() -> httpx.Client:
    return httpx.Client(
        auth=(API_KEY, 'X'),
        headers={'Content-Type': 'application/json'},
        timeout=30.0
    )


# ════════════════════════════════════════════════
#  TICKET MANAGEMENT
# ════════════════════════════════════════════════

@mcp.tool()
def create_ticket(
    subject: str,
    description: str,
    email: str,
    priority: int = 2,
    status: int = 2,
    type: str = None,
    name: str = None,
    phone: str = None,
    tags: str | None = None,
    cc_emails: str | None = None,
) -> dict:
    """Creates a support ticket for a customer.

    Args:
        subject: Short summary of the issue
        description: Full description of the issue
        email: Requester email e.g. john@company.com
        priority: 1=Low 2=Medium 3=High 4=Urgent (default 2)
        status: 2=Open 3=Pending 4=Resolved 5=Closed (default 2)
        type: Ticket type e.g. "Problem", "Incident", "Question", "Feature Request"
        name: Requester full name (optional)
        phone: Requester phone number (optional)
        tags: List of tag strings e.g. ["login", "urgent"] (optional)
        cc_emails: List of emails to CC on the ticket (optional)
    """
    # Normalise status — model sometimes passes the integer as a string
    if isinstance(status, str):
        status_map = {'open': 2, 'pending': 3, 'resolved': 4, 'closed': 5}
        status = status_map.get(status.lower(), int(status)) if status.isdigit() is False else int(status)

    payload: dict = {
        'subject': subject,
        'description': description,
        'priority': priority,
        'status': status,
        'email': email,
        'source': 2,  # Portal
    }
    if type:
        payload['type'] = type
    if name:
        payload['name'] = name
    if phone:
        payload['phone'] = phone
    if tags:
        payload['tags'] = tags if isinstance(tags, list) else [t.strip() for t in str(tags).split(',')]
    if cc_emails:
        payload['cc_emails'] = cc_emails if isinstance(cc_emails, list) else [cc_emails]

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/tickets', json=payload)
        # If the only error is an invalid `type` value, retry without it so the
        # ticket is still created rather than failing and prompting the model to
        # translate or guess a valid type value.
        # If a field-level validation error is returned, strip the offending optional
        # fields and retry once so the ticket is still created rather than failing
        # and causing the model to retry or translate values.
        _OPTIONAL_FIELDS = ('type', 'cc_emails', 'tags', 'name', 'phone')
        if not resp.is_success:
            try:
                err_body = resp.json()
                err_text = resp.text.lower()
                bad_fields = set()
                for err in err_body.get('errors', []):
                    f = err.get('field', '')
                    if f in _OPTIONAL_FIELDS:
                        bad_fields.add(f)
                # Fallback: scan raw text for field names
                if not bad_fields:
                    for f in _OPTIONAL_FIELDS:
                        if f'"{ f}"' in err_text or f"'{f}'" in err_text:
                            bad_fields.add(f)
            except Exception:
                bad_fields = set()
            if bad_fields:
                retry_payload = {k: v for k, v in payload.items() if k not in bad_fields}
                resp = client.post(f'{BASE_URL}/tickets', json=retry_payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        ticket = resp.json()
        tid = ticket.get('id')
        return {'success': True, 'ticket_id': tid, 'message': f'Ticket #{tid} created'}


@mcp.tool()
def list_tickets(status: str = 'open') -> dict:
    """Use when the user asks to list, show, or count tickets by their status.
    Do NOT use for keyword or subject searches — use search_tickets instead.

    Args:
        status: open, pending, resolved, or closed (default open)
    """
    status_map = {'open': 2, 'pending': 3, 'resolved': 4, 'closed': 5}
    if isinstance(status, list):
        status = status[0] if status else 'open'
    s_code = status_map.get(str(status).lower())
    if not s_code:
        return {'success': False, 'message': f'Invalid status "{status}". Use: open, pending, resolved, closed'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/search/tickets', params={'query': f'"status:{s_code}"', 'page': 1})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        data = resp.json()
        results = data.get('results', [])
        return {
            'count': data.get('total', len(results)),
            'status': status,
            'tickets': [{'id': t.get('id'), 'subject': t.get('subject', ''), 'status': t.get('status'), 'priority': t.get('priority'), 'created': t.get('created_at', '')} for t in results]
        }


@mcp.tool()
def get_ticket(ticket_id: str) -> dict:
    """Retrieves details of a single ticket.

    Args:
        ticket_id: Ticket number e.g. 33
    """
    try:
        tid = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets/{tid}')
        if not resp.is_success:
            return {'success': False, 'message': f'Ticket #{tid} not found (HTTP {resp.status_code})'}
        t = resp.json()
        return {
            'success': True,
            'ticket': {
                'id': t.get('id'),
                'subject': t.get('subject', ''),
                'description': t.get('description_text', ''),
                'status': t.get('status'),
                'priority': t.get('priority'),
                'requester_id': t.get('requester_id'),
                'responder_id': t.get('responder_id'),
                'created': t.get('created_at', ''),
                'updated': t.get('updated_at', ''),
            }
        }


@mcp.tool()
def update_ticket(ticket_id: str, status: str = None, priority: int = None, note: str = None) -> dict:
    """Updates a ticket status/priority or adds an internal note.
    For replies to the customer use reply_to_ticket instead.

    Args:
        ticket_id: Ticket number e.g. 35
        status: open, pending, resolved, closed (optional)
        priority: 1=Low 2=Medium 3=High 4=Urgent (optional)
        note: Internal note visible only to agents (optional)
    """
    status_map = {'open': 2, 'pending': 3, 'resolved': 4, 'closed': 5}
    try:
        tid = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        payload = {}
        if status:
            s_code = status_map.get(status.lower())
            if s_code:
                payload['status'] = s_code
        if priority:
            payload['priority'] = priority
        if payload:
            r = client.put(f'{BASE_URL}/tickets/{tid}', json=payload)
            if not r.is_success:
                return {'success': False, 'message': f'API error {r.status_code}: {r.text}'}
        if note:
            r = client.post(f'{BASE_URL}/tickets/{tid}/notes', json={'body': note, 'private': True})
            if not r.is_success:
                return {'success': False, 'message': f'API error {r.status_code}: {r.text}'}
        return {'success': True, 'ticket_id': tid, 'message': f'Ticket #{tid} updated'}


@mcp.tool()
def delete_ticket(ticket_id: str) -> dict:
    """Permanently deletes a ticket.

    Args:
        ticket_id: Ticket number e.g. 33
    """
    try:
        tid = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.delete(f'{BASE_URL}/tickets/{tid}')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'message': f'Ticket #{tid} deleted'}


@mcp.tool()
def search_tickets(query: str) -> dict:
    """Use when the user asks to find, search, or look up tickets by a word or topic.
    Do NOT use to filter by status — use list_tickets instead.

    Args:
        query: Keyword to search in subject/description e.g. VPN, password reset
    """
    if not query or not query.strip():
        return {'success': False, 'message': 'Search term required'}
    with get_client() as client:
        # Try Freshdesk search API first
        resp = client.get(f'{BASE_URL}/search/tickets', params={'query': f'"{query.strip()}"'})
        if resp.is_success:
            data = resp.json()
            results = data.get('results', [])
            return {
                'count': data.get('total', len(results)),
                'query': query,
                'tickets': [{'id': t.get('id'), 'subject': t.get('subject', ''), 'status': t.get('status'), 'priority': t.get('priority')} for t in results]
            }
        # Fallback: local filter
        resp2 = client.get(f'{BASE_URL}/tickets', params={'per_page': 30, 'page': 1})
        if not resp2.is_success:
            return {'success': False, 'message': f'API error {resp2.status_code}: {resp2.text}'}
        tickets = resp2.json()
        if not isinstance(tickets, list):
            tickets = tickets.get('tickets', [])
        q = query.strip().lower()
        filtered = [t for t in tickets if q in t.get('subject', '').lower()]
        return {'count': len(filtered), 'query': query, 'tickets': [{'id': t.get('id'), 'subject': t.get('subject', ''), 'status': t.get('status'), 'priority': t.get('priority')} for t in filtered]}


@mcp.tool()
def reply_to_ticket(ticket_id: str, message: str) -> dict:
    """Sends a public reply to the customer via email.
    Use when asked to "reply", "write to the customer", "notify the requester".
    For internal notes use update_ticket with the note parameter.

    Args:
        ticket_id: Ticket number e.g. 35
        message: Reply text for the customer
    """
    try:
        tid = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/tickets/{tid}/reply', json={'body': message})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'ticket_id': tid, 'message': f'Reply sent to customer of ticket #{tid}'}


@mcp.tool()
def get_ticket_conversations(ticket_id: str) -> dict:
    """Shows all conversations (replies and notes) on a ticket.

    Args:
        ticket_id: Ticket number e.g. 35
    """
    try:
        tid = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets/{tid}/conversations')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        conversations = resp.json()
        if not isinstance(conversations, list):
            conversations = []
        return {
            'ticket_id': tid,
            'count': len(conversations),
            'conversations': [
                {
                    'id': c.get('id'),
                    'type': 'note' if c.get('private') else 'reply',
                    'body_text': c.get('body_text', ''),
                    'created': c.get('created_at', ''),
                    'from_email': c.get('from_email', ''),
                }
                for c in conversations
            ]
        }


# ════════════════════════════════════════════════
#  CONTACTS
# ════════════════════════════════════════════════

@mcp.tool()
def get_contact_by_email(email: str) -> dict:
    """Looks up a customer contact by email address.

    Args:
        email: Email address e.g. john@company.com
    """
    if not email or '@' not in email:
        return {'success': False, 'message': 'Invalid email address'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/contacts', params={'email': email.strip().lower()})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        contacts = resp.json()
        if not isinstance(contacts, list):
            contacts = []
        if not contacts:
            return {'success': False, 'message': f'No contact found with email "{email}"'}
        c = contacts[0]
        return {
            'success': True,
            'contact_id': c.get('id'),
            'name': c.get('name', ''),
            'email': c.get('email', ''),
            'phone': c.get('phone', ''),
            'company_id': c.get('company_id'),
        }


@mcp.tool()
def create_contact(name: str, email: str, phone: str = None) -> dict:
    """Creates a new customer contact.

    Args:
        name: Full name e.g. John Doe
        email: Email address e.g. john@company.com
        phone: Phone number (optional)
    """
    if not email or '@' not in email:
        return {'success': False, 'message': 'Invalid email address'}
    payload = {'name': name, 'email': email.strip().lower()}
    if phone:
        payload['phone'] = phone
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/contacts', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        c = resp.json()
        return {'success': True, 'contact_id': c.get('id'), 'message': f'Contact "{name}" created'}


# ════════════════════════════════════════════════
#  ACCOUNTS
# ════════════════════════════════════════════════

@mcp.tool()
def create_account(name: str) -> dict:
    """Creates a new company account.

    Args:
        name: Company name e.g. Acme Corp
    """
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/companies', json={'name': name})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        c = resp.json()
        return {'success': True, 'account_id': c.get('id'), 'message': f'Account "{name}" created'}


@mcp.tool()
def link_contact_to_account(contact_email: str, account_name: str) -> dict:
    """Links a contact to a company account. Looks up both by email and name.

    Args:
        contact_email: Contact's email address e.g. john@company.com
        account_name: Exact company name e.g. Acme Corp
    """
    with get_client() as client:
        # Resolve contact
        cr = client.get(f'{BASE_URL}/contacts', params={'email': contact_email.strip().lower()})
        if not cr.is_success or not cr.json():
            return {'success': False, 'message': f'Contact not found: {contact_email}'}
        contacts = cr.json()
        if not isinstance(contacts, list) or not contacts:
            return {'success': False, 'message': f'Contact not found: {contact_email}'}
        contact_id = contacts[0].get('id')

        # Resolve account by name autocomplete
        ar = client.get(f'{BASE_URL}/companies/autocomplete', params={'name': account_name.strip()})
        if not ar.is_success:
            return {'success': False, 'message': f'Account lookup failed: {ar.status_code}'}
        companies = ar.json().get('companies', [])
        if not companies:
            return {'success': False, 'message': f'Account not found: {account_name}'}
        company_id = companies[0].get('id')

        # Link
        lr = client.put(f'{BASE_URL}/contacts/{contact_id}', json={'company_id': company_id})
        if not lr.is_success:
            return {'success': False, 'message': f'API error {lr.status_code}: {lr.text}'}
        return {'success': True, 'message': f'Contact {contact_email} linked to account "{account_name}"'}


# ════════════════════════════════════════════════
#  KNOWLEDGE BASE
# ════════════════════════════════════════════════

@mcp.tool()
def search_knowledge_base(query: str) -> dict:
    """Searches the knowledge base for articles.

    Args:
        query: Search term e.g. VPN or password reset
    """
    if not query or not query.strip():
        return {'success': False, 'message': 'Search term required'}
    import re
    def strip_html(text):
        return re.sub(r'<[^>]+>', ' ', text or '')
    query_lower = query.strip().lower()
    all_articles = []
    with get_client() as client:
        categories_resp = client.get(f'{BASE_URL}/solutions/categories')
        if not categories_resp.is_success:
            return {'success': False, 'message': f'Could not load categories (HTTP {categories_resp.status_code})'}
        categories = categories_resp.json()
        if not isinstance(categories, list):
            categories = []
        for category in categories:
            folders_resp = client.get(f'{BASE_URL}/solutions/categories/{category["id"]}/folders')
            if not folders_resp.is_success:
                continue
            folders = folders_resp.json()
            if not isinstance(folders, list):
                folders = []
            for folder in folders:
                articles_resp = client.get(f'{BASE_URL}/solutions/folders/{folder["id"]}/articles')
                if not articles_resp.is_success:
                    continue
                articles = articles_resp.json()
                if not isinstance(articles, list):
                    articles = []
                all_articles.extend(articles)
        filtered = [
            a for a in all_articles
            if query_lower in a.get('title', '').lower()
            or query_lower in strip_html(a.get('description', '')).lower()
        ]
        if not filtered:
            return {'count': 0, 'message': f'No articles found for "{query}"', 'articles': []}
        return {
            'count': len(filtered),
            'articles': [{'id': a.get('id'), 'title': a.get('title', ''), 'summary': strip_html(a.get('description', ''))[:300]} for a in filtered]
        }


@mcp.tool()
def list_kb_folders() -> dict:
    """Lists the full structure of the knowledge base: all categories and their folders with IDs.
    Use when the user asks about the knowledge base structure, available folders, or categories.
    Always call this before create_kb_article to confirm where to publish.
    """
    with get_client() as client:
        cats_resp = client.get(f'{BASE_URL}/solutions/categories')
        if not cats_resp.is_success:
            return {'success': False, 'message': f'API error {cats_resp.status_code}: {cats_resp.text}'}
        categories = cats_resp.json()
        if not isinstance(categories, list):
            categories = []
        result = []
        for cat in categories:
            folders_resp = client.get(f'{BASE_URL}/solutions/categories/{cat["id"]}/folders')
            if not folders_resp.is_success:
                continue
            folders = folders_resp.json()
            if not isinstance(folders, list):
                folders = []
            result.append({
                'category': cat.get('name', ''),
                'folders': [{'id': f.get('id'), 'name': f.get('name', '')} for f in folders]
            })
        return {'categories': result}


@mcp.tool()
def create_kb_article(title: str = '', content: str = '', folder_name: str = '') -> dict:
    """Creates and publishes a knowledge base article.
    If title, content, or folder_name are missing, returns available folders and asks the user to provide all three.

    Args:
        title: Article title e.g. How to reset your password
        content: Article body text (plain text or HTML)
        folder_name: Folder name e.g. Technischer Service
    """
    with get_client() as client:
        # Step 1: missing info — return folder list and prompt user
        if not title.strip() or not content.strip() or not folder_name.strip():
            cats_resp = client.get(f'{BASE_URL}/solutions/categories')
            categories = cats_resp.json() if cats_resp.is_success and isinstance(cats_resp.json(), list) else []
            folders = []
            for cat in categories:
                fr = client.get(f'{BASE_URL}/solutions/categories/{cat["id"]}/folders')
                if fr.is_success and isinstance(fr.json(), list):
                    for f in fr.json():
                        folders.append({'folder': f.get('name', ''), 'category': cat.get('name', '')})
            return {
                'action_required': 'Please provide the article title, content, and choose a folder from the list below.',
                'available_folders': folders
            }

        # Step 2: all params present — resolve folder and publish
        cats_resp = client.get(f'{BASE_URL}/solutions/categories')
        folder_id = None
        for cat in (cats_resp.json() if cats_resp.is_success and isinstance(cats_resp.json(), list) else []):
            fr = client.get(f'{BASE_URL}/solutions/categories/{cat["id"]}/folders')
            if not fr.is_success:
                continue
            for f in (fr.json() if isinstance(fr.json(), list) else []):
                if f.get('name', '').lower() == folder_name.strip().lower():
                    folder_id = f.get('id')
                    break
            if folder_id:
                break
        if not folder_id:
            all_folders = []
            for cat in (cats_resp.json() if cats_resp.is_success and isinstance(cats_resp.json(), list) else []):
                fr2 = client.get(f'{BASE_URL}/solutions/categories/{cat["id"]}/folders')
                if fr2.is_success and isinstance(fr2.json(), list):
                    all_folders.extend([f.get('name') for f in fr2.json()])
            return {'success': False, 'message': f'Folder "{folder_name}" not found.', 'available_folders': all_folders}
        resp = client.post(f'{BASE_URL}/solutions/folders/{folder_id}/articles', json={'title': title, 'description': content, 'status': 2})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        a = resp.json()
        return {'success': True, 'article_id': a.get('id'), 'message': f'Article "{title}" published in "{folder_name}"'}


# ════════════════════════════════════════════════
#  GROUPS
# ════════════════════════════════════════════════

@mcp.tool()
def list_groups() -> dict:
    """Lists ALL agent groups. Use this when no specific group name is mentioned."""
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/groups')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        groups = resp.json()
        if not isinstance(groups, list):
            groups = []
        return {'count': len(groups), 'groups': [{'id': g.get('id'), 'name': g.get('name', ''), 'description': g.get('description', '')} for g in groups]}


@mcp.tool()
def add_me_to_group(group_name: str) -> dict:
    """Adds you (the current API user) to an agent group.

    Args:
        group_name: Group name e.g. "VIP Support"
    """
    with get_client() as client:
        # Get current agent from API key
        me_resp = client.get(f'{BASE_URL}/agents/me')
        if not me_resp.is_success:
            return {'success': False, 'message': f'Could not identify current agent (HTTP {me_resp.status_code})'}
        my_id = me_resp.json().get('id')

        # Resolve group name to ID and get current agent_ids
        groups_resp = client.get(f'{BASE_URL}/groups')
        if not groups_resp.is_success:
            return {'success': False, 'message': f'API error {groups_resp.status_code}: {groups_resp.text}'}
        groups = groups_resp.json() if isinstance(groups_resp.json(), list) else []
        match = [g for g in groups if g.get('name', '').lower() == group_name.strip().lower()]
        if not match:
            available = [g['name'] for g in groups]
            return {'success': False, 'message': f'Group "{group_name}" not found. Available: {available}'}
        group_id = match[0]['id']

        # Fetch current agent_ids and append
        grp_resp = client.get(f'{BASE_URL}/groups/{group_id}')
        current_ids = grp_resp.json().get('agent_ids', []) if grp_resp.is_success else []
        if my_id in current_ids:
            return {'success': True, 'message': f'You are already a member of "{group_name}"'}
        updated_ids = current_ids + [my_id]

        resp = client.put(f'{BASE_URL}/groups/{group_id}', json={'agent_ids': updated_ids})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'message': f'You have been added to "{group_name}"'}


@mcp.tool()
def get_group(group_name: str) -> dict:
    """Gets details of ONE specific group by name. Only use when a specific group name is mentioned.

    Args:
        group_name: Group name e.g. "VIP Support"
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/groups')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        groups = resp.json() if isinstance(resp.json(), list) else []
        match = [g for g in groups if g.get('name', '').lower() == group_name.strip().lower()]
        if not match:
            available = [g['name'] for g in groups]
            return {'success': False, 'message': f'Group "{group_name}" not found. Available: {available}'}
        g = match[0]
        return {'success': True, 'group': {'id': g.get('id'), 'name': g.get('name', ''), 'description': g.get('description', ''), 'agent_ids': g.get('agent_ids', [])}}


@mcp.tool()
def create_group(name: str, description: str = None) -> dict:
    """Creates a new agent group.

    Args:
        name: Group name e.g. "Billing Support"
        description: Group description (optional)
    """
    payload: dict = {'name': name}
    if description:
        payload['description'] = description
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/groups', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        g = resp.json()
        return {'success': True, 'group_id': g.get('id'), 'message': f'Group "{name}" created'}


@mcp.tool()
def update_group(group_name: str, new_name: str | None = None, description: str | None = None) -> dict:
    """Updates an agent group's name or description. Looks up the group by name.

    Args:
        group_name: Current group name e.g. "VIP Support"
        new_name: New name (optional)
        description: New description (optional)
    """
    import json as _json

    def _clean(val):
        """Strip JSON wrapping and reject null-like strings."""
        if not val or str(val).strip().lower() in ('null', 'none', ''):
            return None
        s = str(val).strip()
        try:
            parsed = _json.loads(s)
            if isinstance(parsed, dict):
                return next(iter(parsed.values()), None)
        except (ValueError, TypeError):
            pass
        return s

    clean_name = _clean(new_name)
    clean_desc = _clean(description)

    payload = {}
    if clean_name:
        payload['name'] = clean_name
    if clean_desc:
        payload['description'] = clean_desc
    if not payload:
        return {'success': False, 'message': 'Nothing to update — provide at least one of: new_name, description'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/groups')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        groups = resp.json() if isinstance(resp.json(), list) else []
        match = [g for g in groups if g.get('name', '').lower() == group_name.strip().lower()]
        if not match:
            available = [g['name'] for g in groups]
            return {'success': False, 'message': f'Group "{group_name}" not found. Available: {available}'}
        group_id = match[0]['id']
        resp2 = client.put(f'{BASE_URL}/groups/{group_id}', json=payload)
        if not resp2.is_success:
            return {'success': False, 'message': f'API error {resp2.status_code}: {resp2.text}'}
        return {'success': True, 'group_id': group_id, 'message': f'Group "{group_name}" updated'}


# ════════════════════════════════════════════════
#  TICKET FORMS
# ════════════════════════════════════════════════

@mcp.tool()
def list_ticket_forms() -> dict:
    """Lists all ticket forms in Freshdesk. Always call this before creating a form."""
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/ticket-forms')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        forms = resp.json()
        if not isinstance(forms, list):
            forms = []
        return {
            'count': len(forms),
            'forms': [{'id': f.get('id'), 'name': f.get('name', ''), 'title': f.get('title', ''), 'default': f.get('default', False), 'description': f.get('description', '')} for f in forms]
        }


@mcp.tool()
def create_ticket_form(title: str, description: str = '') -> dict:
    """Creates a new ticket form. Freshdesk automatically adds the required base fields
    (requester, subject, description, company). After creating, always tell the user
    which fields were included and that additional fields can be added via the Freshdesk portal.
    Do not attempt any further tool calls after this succeeds.

    Args:
        title: Form title e.g. "Hardware Request"
        description: Short description shown to customers e.g. "Request new hardware equipment"
    """
    payload: dict = {'title': title}
    if description:
        payload['description'] = description
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/ticket-forms', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        f = resp.json()
        included = [field['name'] for field in f.get('fields', [])]
        return {
            'success': True,
            'form_id': f.get('id'),
            'form_name': f.get('name', ''),
            'message': f'Form "{title}" created successfully.',
            'included_fields': included,
            'note': 'Additional fields can be added to this form via the Freshdesk portal under Admin → Ticket Forms.'
        }


# ════════════════════════════════════════════════
#  TICKET FIELDS
# ════════════════════════════════════════════════

@mcp.tool()
def list_ticket_fields() -> dict:
    """Lists all ticket fields (default and custom) in Freshdesk."""
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/ticket_fields')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        fields = resp.json()
        if not isinstance(fields, list):
            fields = []
        return {
            'count': len(fields),
            'fields': [{'id': f.get('id'), 'name': f.get('name', ''), 'label': f.get('label', ''), 'type': f.get('field_type', ''), 'required': f.get('required_for_closure', False)} for f in fields]
        }


@mcp.tool()
def create_ticket_field(
    label: str,
    field_type: str,
    displayed_to_customers: bool = False,
    customers_can_edit: bool = False,
    label_for_customers: str | None = None,
    choices: str | None = None,
    choices_json: str | None = None,
    dependent_fields_json: str | None = None,
    section_mappings_json: str | None = None,
    position: int | None = None,
) -> dict:
    """Creates a new custom ticket field.

    By default fields are hidden from customers (displayed_to_customers=false).
    Set displayed_to_customers=true and customers_can_edit=true to expose the field
    in the customer portal.

    Supported field types:
      custom_text, custom_dropdown, custom_checkbox, custom_date,
      custom_number, custom_paragraph, custom_decimal, custom_url,
      nested_field (3-level dependent/cascading dropdown)

    For custom_dropdown:
      - Use choices="North,South,East,West" for simple comma-separated values, OR
      - Use choices_json for structured choices with positions:
        '[{"value":"Refund","position":1},{"value":"Faulty Product","position":2}]'

    For nested_field (dependent/cascading dropdown):
      - choices_json must contain the full nested hierarchy.
      - dependent_fields_json defines the labels for levels 2 and 3:
        '[{"label":"District","label_for_customers":"District","level":2},
          {"label":"Branch","label_for_customers":"Branch","level":3}]'

    For section_mappings (place field in a specific form section):
      - section_mappings_json: '[{"position":3,"section_id":1}]'

    Args:
        label: Internal label e.g. "Issue Type"
        field_type: One of the supported types listed above
        displayed_to_customers: Show this field to customers in the portal (default false)
        customers_can_edit: Allow customers to edit this field (default false)
        label_for_customers: Customer-facing label (defaults to label if not set)
        choices: Simple comma-separated values for custom_dropdown e.g. "North,South,East,West"
        choices_json: JSON array of choice objects — use for dropdowns with positions or nested_field hierarchies
        dependent_fields_json: JSON array defining level-2 and level-3 labels for nested_field
        section_mappings_json: JSON array to place the field in a specific form section
        position: Display position of the field (optional)
    """
    import json as _json

    valid_types = [
        'custom_text', 'custom_dropdown', 'custom_checkbox', 'custom_date',
        'custom_number', 'custom_paragraph', 'custom_decimal', 'custom_url',
        'nested_field',
    ]
    if field_type not in valid_types:
        return {'success': False, 'message': f'Invalid field_type "{field_type}". Valid types: {valid_types}'}
    if field_type in ('custom_dropdown', 'nested_field') and not choices and not choices_json:
        return {'success': False, 'message': f'choices or choices_json is required for {field_type}'}
    if field_type == 'nested_field' and not dependent_fields_json:
        return {'success': False, 'message': 'dependent_fields_json is required for nested_field — define labels for levels 2 and 3'}

    payload: dict = {
        'label': label,
        'label_for_customers': label_for_customers or label,
        'type': field_type,
        'displayed_to_customers': displayed_to_customers,
        'customers_can_edit': customers_can_edit,
    }

    if position is not None:
        payload['position'] = position

    # Build choices
    if choices_json:
        try:
            payload['choices'] = _json.loads(choices_json)
        except _json.JSONDecodeError as e:
            return {'success': False, 'message': f'choices_json is not valid JSON: {e}'}
    elif choices:
        payload['choices'] = [{'value': c.strip(), 'position': i + 1} for i, c in enumerate(choices.split(',')) if c.strip()]

    # Dependent field level labels (nested_field only)
    if dependent_fields_json:
        try:
            payload['dependent_fields'] = _json.loads(dependent_fields_json)
        except _json.JSONDecodeError as e:
            return {'success': False, 'message': f'dependent_fields_json is not valid JSON: {e}'}

    # Section mappings
    if section_mappings_json:
        try:
            payload['section_mappings'] = _json.loads(section_mappings_json)
        except _json.JSONDecodeError as e:
            return {'success': False, 'message': f'section_mappings_json is not valid JSON: {e}'}

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/admin/ticket_fields', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        f = resp.json()
        visibility = 'visible to customers' if displayed_to_customers else 'agent-only (hidden from customers)'
        return {
            'success': True,
            'field_id': f.get('id'),
            'label': f.get('label'),
            'type': f.get('field_type'),
            'visibility': visibility,
            'message': f'Ticket field "{label}" created. Visibility: {visibility}.',
        }


# ── Start server ──────────────────────────────
if __name__ == '__main__':
    mcp.run(transport='stdio')
