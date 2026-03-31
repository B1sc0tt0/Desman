# freshservice_server.py
# Freshservice MCP Server for llama3.2:3b (and larger models)
# Compatible with mcphost + Ollama
import os
import httpx
from fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("Freshservice Agent")

API_KEY  = os.getenv('FRESHSERVICE_API_KEY')
DOMAIN   = os.getenv('FRESHSERVICE_DOMAIN')
BASE_URL = f'https://{DOMAIN}/api/v2'

# Default requester for changes and problems (set in .env)
DEFAULT_REQUESTER_EMAIL = os.getenv('REQUESTER_EMAIL', '')


def get_client() -> httpx.Client:
    return httpx.Client(
        auth=(API_KEY, 'X'),
        headers={'Content-Type': 'application/json'},
        timeout=30.0
    )


def resolve_user(client, user_id):
    """Resolve a user_id to name and email (tries requesters, then agents)."""
    if not user_id:
        return {'name': 'Unknown', 'email': ''}
    try:
        r = client.get(f'{BASE_URL}/requesters/{user_id}')
        if r.status_code == 200:
            u = r.json().get('requester', {})
            return {'name': f"{u.get('first_name','')} {u.get('last_name','')}".strip(), 'email': u.get('primary_email', '')}
    except Exception:
        pass
    try:
        r = client.get(f'{BASE_URL}/agents/{user_id}')
        if r.status_code == 200:
            u = r.json().get('agent', {})
            return {'name': f"{u.get('first_name','')} {u.get('last_name','')}".strip(), 'email': u.get('email', '')}
    except Exception:
        pass
    return {'name': f'ID {user_id}', 'email': ''}


# ════════════════════════════════════════════════
#  TICKET MANAGEMENT
# ════════════════════════════════════════════════

@mcp.tool()
def create_ticket(subject: str, description: str, priority: int = 2) -> dict:
    """Creates a new ticket when a user reports an issue or needs something.
    Use for individual user requests: broken printer, forgotten password, software install.
    Do NOT use for Problems or Change Requests.

    Args:
        subject: Short description e.g. "Printer not working"
        description: Full text of the issue, e.g. "The printer on floor 2 stopped working"
        priority: 1=Low 2=Medium 3=High 4=Urgent (default 2)
    """
    # Extended parameters for larger models: requester_email, source, tags, due_by, group_id, responder_id
    payload = {
        'subject': subject,
        'description': description,
        'priority': priority,
        'status': 2,
        'email': DEFAULT_REQUESTER_EMAIL,
        'source': 2
    }
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/tickets', json=payload)
        resp.raise_for_status()
        ticket = resp.json()['ticket']
        tid = ticket.get('display_id') or ticket.get('id')
        return {'success': True, 'ticket_id': tid, 'message': f'Ticket #{tid} created'}


@mcp.tool()
def list_tickets(status: str = 'open') -> dict:
    """Lists tickets by status. Status must be a string, not an array.

    Args:
        status: "open" or "pending" or "resolved" or "closed" (not an array!)
    """
    # Extended parameters for larger models: page, per_page, priority
    status_map = {'open': 2, 'pending': 3, 'resolved': 4, 'closed': 5}
    if isinstance(status, list):
        status = status[0] if status else 'open'
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 10, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        s_code = status_map.get(str(status).lower())
        if s_code:
            tickets = [t for t in tickets if t['status'] == s_code]
        return {
            'count': len(tickets),
            'tickets': [{'id': t.get('display_id') or t.get('id'), 'subject': t.get('subject', ''), 'status': t.get('status'), 'priority': t.get('priority'), 'created': t.get('created_at', '')} for t in tickets]
        }


@mcp.tool()
def get_ticket_by_id(ticket_id: str) -> dict:
    """Gets details of a single ticket by ID.

    Args:
        ticket_id: Ticket number e.g. 33
    """
    try:
        display_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 100, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        match = [t for t in tickets if t.get('display_id') == display_id or t.get('id') == display_id]
        if not match:
            return {'success': False, 'message': f'Ticket #{display_id} not found'}
        t = match[0]
        return {'success': True, 'ticket': {'id': t.get('display_id') or t.get('id'), 'subject': t.get('subject', ''), 'description': t.get('description_text', ''), 'status': t.get('status'), 'priority': t.get('priority'), 'created': t.get('created_at', ''), 'updated': t.get('updated_at', '')}}


@mcp.tool()
def update_ticket(ticket_id: str, status: str = None, note: str = None) -> dict:
    """Updates status or adds an internal note to a ticket.
    ONLY for status changes (open/pending/resolved/closed) and internal agent notes.
    NOT for replies to the requester - use reply_to_ticket instead!
    NOT for escalation - use promote_to_major_incident instead!

    Args:
        ticket_id: Ticket number e.g. 35
        status: open, pending, resolved, closed (optional)
        note: Internal note/comment (optional)
    """
    # Extended parameters for larger models: priority, subject, description, tags
    status_map = {'open': 2, 'pending': 3, 'resolved': 4, 'closed': 5}
    try:
        display_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}

    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 100, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        match = [t for t in tickets if t.get('display_id') == display_id or t.get('id') == display_id]
        if not match:
            return {'success': False, 'message': f'Ticket #{display_id} not found'}
        internal_id = match[0].get('id')

        payload = {}
        if status:
            s_code = status_map.get(status.lower())
            if s_code:
                payload['status'] = s_code
        if payload:
            client.put(f'{BASE_URL}/tickets/{internal_id}', json=payload).raise_for_status()
        if note:
            client.post(f'{BASE_URL}/tickets/{internal_id}/notes', json={'body': note, 'private': False}).raise_for_status()
        return {'success': True, 'ticket_id': display_id, 'message': f'Ticket #{display_id} updated'}


@mcp.tool()
def reply_to_ticket(ticket_id: str, message: str) -> dict:
    """Sends a reply directly to the requester of a ticket (public, via email).
    Use when someone says: "reply", "respond", "write to the user", "inform the requester".
    Do NOT use update_ticket for replies!

    Args:
        ticket_id: Ticket number e.g. 35
        message: Reply text to send to the requester
    """
    try:
        display_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 100, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        match = [t for t in tickets if t.get('display_id') == display_id or t.get('id') == display_id]
        if not match:
            return {'success': False, 'message': f'Ticket #{display_id} not found'}
        internal_id = match[0].get('id')
        resp = client.post(f'{BASE_URL}/tickets/{internal_id}/reply', json={'body': message})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'ticket_id': display_id, 'message': f'Reply sent to requester of ticket #{display_id}'}


@mcp.tool()
def get_ticket_activities(ticket_id: str) -> dict:
    """Shows the activity log of a ticket - everything that has happened so far.

    Args:
        ticket_id: Ticket number e.g. 35
    """
    try:
        display_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 100, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        match = [t for t in tickets if t.get('display_id') == display_id or t.get('id') == display_id]
        if not match:
            return {'success': False, 'message': f'Ticket #{display_id} not found'}
        internal_id = match[0].get('id')
        resp = client.get(f'{BASE_URL}/tickets/{internal_id}/activities')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        activities = resp.json().get('activities', [])
        return {
            'ticket_id': display_id,
            'count': len(activities),
            'activities': [{'actor': a.get('actor', {}).get('name', 'System'), 'content': a.get('content', ''), 'created': a.get('created_at', '')} for a in activities]
        }


@mcp.tool()
def delete_ticket(ticket_id: str) -> dict:
    """Permanently deletes a ticket. Use with caution!

    Args:
        ticket_id: Ticket number e.g. 33
    """
    try:
        display_id = int(ticket_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {ticket_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 100, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        match = [t for t in tickets if t.get('display_id') == display_id or t.get('id') == display_id]
        if not match:
            return {'success': False, 'message': f'Ticket #{display_id} not found'}
        internal_id = match[0].get('id')
        client.delete(f'{BASE_URL}/tickets/{internal_id}').raise_for_status()
        return {'success': True, 'message': f'Ticket #{display_id} deleted'}


@mcp.tool()
def search_tickets(query: str) -> dict:
    """Searches tickets by keyword in subject or description.

    Args:
        query: Search term e.g. "VPN" or "printer"
    """
    if not query or not query.strip():
        return {'success': False, 'message': 'Search term is required'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'per_page': 10, 'page': 1})
        resp.raise_for_status()
        tickets = resp.json().get('tickets', [])
        q = query.strip().lower()
        filtered = [t for t in tickets if q in t.get('subject', '').lower() or q in t.get('description', '').lower()]
        return {'count': len(filtered), 'query': query, 'tickets': [{'id': t.get('display_id') or t.get('id'), 'subject': t.get('subject', ''), 'status': t.get('status'), 'priority': t.get('priority')} for t in filtered]}


# ════════════════════════════════════════════════
#  CHANGE MANAGEMENT
# ════════════════════════════════════════════════

@mcp.tool()
def get_requester_by_email(email: str) -> dict:
    """Looks up a requester by email address.

    Args:
        email: Email address e.g. john@company.com
    """
    if not email or '@' not in email:
        return {'success': False, 'message': 'Invalid email address'}
    with get_client() as client:
        # Attempt 1: direct API filter
        resp = client.get(f'{BASE_URL}/requesters', params={'email': email.strip().lower()})
        resp.raise_for_status()
        requesters = resp.json().get('requesters', [])
        # Attempt 2: load all and filter locally
        if not requesters:
            resp2 = client.get(f'{BASE_URL}/requesters', params={'per_page': 100, 'page': 1})
            resp2.raise_for_status()
            all_requesters = resp2.json().get('requesters', [])
            requesters = [r for r in all_requesters if r.get('primary_email', '').lower() == email.strip().lower()]
        # Attempt 3: search agents
        if not requesters:
            resp3 = client.get(f'{BASE_URL}/agents', params={'email': email.strip().lower()})
            resp3.raise_for_status()
            agents = resp3.json().get('agents', [])
            if agents:
                a = agents[0]
                return {'success': True, 'requester_id': a.get('id'), 'name': f"{a.get('first_name','')} {a.get('last_name','')}".strip(), 'email': a.get('email', '')}
        if not requesters:
            return {'success': False, 'message': f'No requester found with email "{email}"'}
        r = requesters[0]
        return {'success': True, 'requester_id': r.get('id'), 'name': f"{r.get('first_name','')} {r.get('last_name','')}".strip(), 'email': r.get('primary_email', '')}


@mcp.tool()
def create_change(subject: str, description: str, planned_start: str, planned_end: str, change_type: str = 'standard') -> dict:
    """Creates a Change Request. Requester is loaded automatically from .env.
    If planned_start or planned_end are missing, ask the user for them!

    Args:
        subject: Subject e.g. "Firewall Update"
        description: Description e.g. "Updating firewall to version 2.4"
        planned_start: Planned start e.g. "03/10/2026 08:00 AM" or "2026-03-10T08:00:00Z"
        planned_end: Planned end e.g. "03/10/2026 10:00 AM" or "2026-03-10T10:00:00Z"
        change_type: minor, standard (default), major, emergency
    """
    # Extended parameters for larger models: priority, impact, risk
    type_map = {'minor': 1, 'standard': 2, 'major': 3, 'emergency': 4}
    if isinstance(change_type, list):
        change_type = change_type[0] if change_type else 'standard'

    if not planned_start or not planned_end:
        return {'success': False, 'message': 'Please provide start and end date, e.g. "03/10/2026 08:00 AM to 10:00 AM"'}

    # Parse various date formats to ISO 8601
    from datetime import datetime
    def parse_date(s):
        s = s.strip()
        formats = [
            '%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M',
            '%d.%m.%Y %H:%M Uhr', '%d.%m.%Y %H:%M',
            '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M'
        ]
        for fmt in formats:
            try:
                return datetime.strptime(s, fmt).strftime('%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                continue
        return s  # Return as-is if already ISO format

    requester_result = get_requester_by_email(DEFAULT_REQUESTER_EMAIL)
    if not requester_result.get('success'):
        return {'success': False, 'message': f'Default requester not found. Please set REQUESTER_EMAIL in .env. Error: {requester_result.get("message")}'}

    with get_client() as client:
        payload = {
            'subject': subject,
            'description': description,
            'requester_id': requester_result['requester_id'],
            'priority': 1,
            'impact': 1,
            'status': 1,
            'risk': 1,
            'change_type': type_map.get(str(change_type).lower(), 2),
            'planned_start_date': parse_date(planned_start),
            'planned_end_date': parse_date(planned_end),
        }
        resp = client.post(f'{BASE_URL}/changes', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        cid = resp.json().get('change', {}).get('id', 'Unknown')
        return {'success': True, 'change_id': cid, 'message': f'Change #{cid} created ({change_type})'}


@mcp.tool()
def list_changes(page: int = 1) -> dict:
    """Lists all Change Requests.

    Args:
        page: Page number (default 1)
    """
    # Extended parameters for larger models: per_page, query
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/changes', params={'page': page, 'per_page': 10})
        resp.raise_for_status()
        changes = resp.json().get('changes', [])
        return {'count': len(changes), 'changes': [{'id': c.get('id'), 'subject': c.get('subject', ''), 'status': c.get('status'), 'priority': c.get('priority'), 'change_type': c.get('change_type'), 'planned_start': c.get('planned_start_date', '')} for c in changes]}


@mcp.tool()
def update_change(change_id: str, status: str = None, note: str = None) -> dict:
    """Updates a Change Request status or adds a note.

    Args:
        change_id: Change ID e.g. 5
        status: open, planning, awaiting_approval, pending_release, pending_review, closed (optional)
        note: Note to add (optional)
    """
    # Extended parameters for larger models: priority, impact, risk, change_type, planned_start_date
    status_map = {'open': 1, 'planning': 2, 'awaiting_approval': 3, 'pending_release': 4, 'pending_review': 5, 'closed': 6}
    try:
        cid = int(change_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {change_id}'}
    payload = {}
    if status:
        s_code = status_map.get(status.lower())
        if s_code:
            payload['status'] = s_code
    with get_client() as client:
        if payload:
            client.put(f'{BASE_URL}/changes/{cid}', json=payload).raise_for_status()
        if note:
            client.post(f'{BASE_URL}/changes/{cid}/notes', json={'body': note, 'private': False}).raise_for_status()
        return {'success': True, 'change_id': cid, 'message': f'Change #{cid} updated'}


@mcp.tool()
def close_change(change_id: str, note: str) -> dict:
    """Closes a Change Request.

    Args:
        change_id: Change ID e.g. 5
        note: Result description e.g. "Successfully deployed"
    """
    try:
        cid = int(change_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {change_id}'}
    with get_client() as client:
        client.put(f'{BASE_URL}/changes/{cid}', json={'status': 6, 'change_result_explanation': note}).raise_for_status()
        return {'success': True, 'change_id': cid, 'message': f'Change #{cid} closed'}


@mcp.tool()
def delete_change(change_id: str) -> dict:
    """Deletes a Change Request. Use with caution!

    Args:
        change_id: Change ID e.g. 5
    """
    try:
        cid = int(change_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {change_id}'}
    with get_client() as client:
        client.delete(f'{BASE_URL}/changes/{cid}').raise_for_status()
        return {'success': True, 'message': f'Change #{cid} deleted'}


@mcp.tool()
def create_change_note(change_id: str, note: str) -> dict:
    """Adds a note to a CHANGE REQUEST (not to tickets!).
    Only use when a Change is explicitly mentioned.

    Args:
        change_id: Change ID e.g. 5
        note: Note content
    """
    try:
        cid = int(change_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {change_id}'}
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/changes/{cid}/notes', json={'body': note, 'private': False})
        resp.raise_for_status()
        return {'success': True, 'change_id': cid, 'message': f'Note added to Change #{cid}'}


# ════════════════════════════════════════════════
#  PROBLEM MANAGEMENT
# ════════════════════════════════════════════════

@mcp.tool()
def promote_to_major_incident(ticket_id: str) -> dict:
    """Provides instructions for promoting a ticket to a Major Incident.
    Note: Freshservice API does not support this action - it must be done manually in the UI.

    Args:
        ticket_id: Ticket ID e.g. 35
    """
    return {
        'success': False,
        'manual_action_required': True,
        'message': (
            f'Promoting to Major Incident is not possible via API (Freshservice limitation). '
            f'Please do it manually in the browser: '
            f'https://{DOMAIN}/a/tickets/{ticket_id} -> click "Promote to Major Incident"'
        )
    }


@mcp.tool()
def list_problems(page: int = 1) -> dict:
    """Lists all Problems.

    Args:
        page: Page number (default 1)
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/problems', params={'page': page, 'per_page': 10})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        problems = resp.json().get('problems', [])
        return {'count': len(problems), 'problems': [{'id': p.get('id'), 'subject': p.get('subject', ''), 'status': p.get('status'), 'priority': p.get('priority'), 'due_by': p.get('due_by', '')} for p in problems]}


@mcp.tool()
def get_problem_by_id(problem_id: str) -> dict:
    """Gets details of a single Problem.

    Args:
        problem_id: Problem ID e.g. 3
    """
    try:
        pid = int(problem_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {problem_id}'}
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/problems/{pid}')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        p = resp.json().get('problem', {})
        return {'success': True, 'problem': {'id': p.get('id'), 'subject': p.get('subject', ''), 'description': p.get('description_text', ''), 'status': p.get('status'), 'priority': p.get('priority'), 'due_by': p.get('due_by', ''), 'created': p.get('created_at', '')}}


@mcp.tool()
def create_problem(subject: str, description: str, due_by: str) -> dict:
    """Creates a new Problem. Requester is loaded automatically from .env.
    If due_by is missing, ask the user for it!

    Args:
        subject: Subject e.g. "Network outage on 3rd floor"
        description: Description e.g. "No network access since 09:00"
        due_by: Due date e.g. "03/10/2026 05:00 PM" or "2026-03-10T17:00:00Z"
    """
    if not due_by:
        return {'success': False, 'message': 'Please provide a due date, e.g. "03/10/2026 05:00 PM"'}
    from datetime import datetime
    due_parsed = due_by.strip()
    for fmt in ('%m/%d/%Y %I:%M %p', '%m/%d/%Y %H:%M', '%d.%m.%Y %H:%M Uhr', '%d.%m.%Y %H:%M', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            due_parsed = datetime.strptime(due_parsed, fmt).strftime('%Y-%m-%dT%H:%M:%SZ')
            break
        except ValueError:
            continue
    requester_result = get_requester_by_email(DEFAULT_REQUESTER_EMAIL)
    if not requester_result.get('success'):
        return {'success': False, 'message': 'Default requester not found. Please set REQUESTER_EMAIL in .env.'}
    with get_client() as client:
        payload = {
            'subject': subject,
            'description': description,
            'requester_id': requester_result['requester_id'],
            'priority': 1,
            'impact': 1,
            'status': 1,
            'due_by': due_parsed,
        }
        resp = client.post(f'{BASE_URL}/problems', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        pid = resp.json().get('problem', {}).get('id', 'Unknown')
        return {'success': True, 'problem_id': pid, 'message': f'Problem #{pid} created (due: {due_by})'}


@mcp.tool()
def update_problem(problem_id: str, status: str = None, note: str = None) -> dict:
    """Updates a Problem status or adds a note.

    Args:
        problem_id: Problem ID e.g. 3
        status: open, change_requested, closed (optional)
        note: Note to add (optional)
    """
    status_map = {'open': 1, 'change_requested': 2, 'closed': 3}
    try:
        pid = int(problem_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {problem_id}'}
    with get_client() as client:
        if status:
            s_code = status_map.get(status.lower())
            if s_code:
                resp = client.put(f'{BASE_URL}/problems/{pid}', json={'status': s_code})
                if not resp.is_success:
                    return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        if note:
            resp = client.post(f'{BASE_URL}/problems/{pid}/notes', json={'body': note, 'private': False})
            if not resp.is_success:
                return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'problem_id': pid, 'message': f'Problem #{pid} updated'}


@mcp.tool()
def close_problem(problem_id: str, note: str) -> dict:
    """Closes a Problem.

    Args:
        problem_id: Problem ID e.g. 3
        note: Resolution note e.g. "Root cause found and fixed"
    """
    try:
        pid = int(problem_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {problem_id}'}
    with get_client() as client:
        resp = client.put(f'{BASE_URL}/problems/{pid}', json={'status': 3})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        client.post(f'{BASE_URL}/problems/{pid}/notes', json={'body': note, 'private': False})
        return {'success': True, 'problem_id': pid, 'message': f'Problem #{pid} closed'}


@mcp.tool()
def add_problem_note(problem_id: str, note: str) -> dict:
    """Adds a note to a Problem.

    Args:
        problem_id: Problem ID e.g. 3
        note: Note content
    """
    try:
        pid = int(problem_id)
    except (ValueError, TypeError):
        return {'success': False, 'message': f'Invalid ID: {problem_id}'}
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/problems/{pid}/notes', json={'body': note, 'private': False})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'problem_id': pid, 'message': f'Note added to Problem #{pid}'}


# ════════════════════════════════════════════════
#  ASSET MANAGEMENT
# ════════════════════════════════════════════════

@mcp.tool()
def list_assets(search: str = None, asset_type_id: str = None) -> dict:
    """Lists all assets. Optionally filter by name, asset tag, or asset type.

    Args:
        search: Search term e.g. "Laptop" or "ASSET-001" (optional)
        asset_type_id: Filter by asset type ID (optional, ignored if not numeric)
    """
    with get_client() as client:
        params = {'per_page': 100, 'page': 1}
        try:
            if asset_type_id:
                params['asset_type_id'] = int(asset_type_id)
        except (ValueError, TypeError):
            pass
        resp = client.get(f'{BASE_URL}/assets', params=params)
        resp.raise_for_status()
        assets = resp.json().get('assets', [])
        if search:
            s = search.strip().lower()
            assets = [a for a in assets if s in a.get('name', '').lower() or s in a.get('asset_tag', '').lower()]
        result = []
        for a in assets:
            user = resolve_user(client, a.get('user_id'))
            manager = resolve_user(client, a.get('agent_id'))
            result.append({
                'id': a.get('display_id') or a.get('id'),
                'name': a.get('name', ''),
                'asset_tag': a.get('asset_tag', ''),
                'assigned_to': f"{user['name']} ({user['email']})" if user['email'] else user['name'],
                'managed_by': f"{manager['name']} ({manager['email']})" if manager['email'] else manager['name']
            })
        return {'count': len(result), 'assets': result}


@mcp.tool()
def list_asset_types() -> dict:
    """Lists all asset types available in Freshservice (e.g. Laptop, Hardware, Monitor)."""
    with get_client() as client:
        all_types = []
        page = 1
        while True:
            resp = client.get(f'{BASE_URL}/asset_types', params={'per_page': 100, 'page': page})
            if not resp.is_success:
                return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
            types = resp.json().get('asset_types', [])
            if not types:
                break
            all_types.extend(types)
            page += 1
        return {'count': len(all_types), 'asset_types': [{'id': t.get('id'), 'name': t.get('name', '')} for t in all_types]}


@mcp.tool()
def get_asset_type_fields(asset_type_id: int) -> dict:
    """Returns the fields for a given asset type.

    Args:
        asset_type_id: Asset type ID from list_asset_types
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/asset_types/{asset_type_id}/fields')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        fields = resp.json().get('asset_type_fields', [])
        return {
            'asset_type_id': asset_type_id,
            'count': len(fields),
            'fields': [{'name': f.get('name'), 'label': f.get('label'), 'field_type': f.get('field_type'), 'required': f.get('required', False)} for f in fields]
        }


@mcp.tool()
def get_asset_by_id(id: int) -> dict:
    """Gets full details of a single asset by its ID.

    Args:
        id: Asset ID e.g. 12
    """
    with get_client() as client:
        resp2 = client.get(f'{BASE_URL}/assets/{id}')
        if not resp2.is_success:
            return {'success': False, 'message': f'Asset #{id} not found'}
        asset = resp2.json().get('asset', {})
        user = resolve_user(client, asset.get('user_id'))
        manager = resolve_user(client, asset.get('agent_id'))
        return {
            'success': True,
            'asset': {
                'id': id,
                'name': asset.get('name', ''),
                'asset_tag': asset.get('asset_tag', ''),
                'asset_type_id': asset.get('asset_type_id'),
                'state': asset.get('asset_state', ''),
                'assigned_to': f"{user['name']} ({user['email']})" if user['email'] else user['name'],
                'managed_by': f"{manager['name']} ({manager['email']})" if manager['email'] else manager['name'],
                'created': asset.get('created_at', ''),
                'updated': asset.get('updated_at', ''),
            }
        }


@mcp.tool()
def create_asset(name: str, asset_type_name: str, asset_state: str = 'In Use', product_name: str = None, asset_tag: str = None) -> dict:
    """Creates a new asset.

    Args:
        name: Asset name e.g. "MacBook-Test-01"
        asset_type_name: Asset type name e.g. "Laptop" or "Hardware"
        asset_state: Asset state e.g. "In Use", "In Stock", "Reserved", "Retired" (default "In Use")
        product_name: Product name e.g. "Apple MacBook Air 13" (optional)
        asset_tag: Asset tag e.g. "ASSET-042" (optional)
    """
    with get_client() as client:
        # Resolve type name to ID
        all_types = []
        page = 1
        while True:
            r = client.get(f'{BASE_URL}/asset_types', params={'per_page': 100, 'page': page})
            if not r.is_success:
                return {'success': False, 'message': f'Could not fetch asset types: {r.status_code}'}
            batch = r.json().get('asset_types', [])
            if not batch:
                break
            all_types.extend(batch)
            page += 1
        match = [t for t in all_types if t.get('name', '').lower() == asset_type_name.strip().lower()]
        if not match:
            available = [t['name'] for t in all_types]
            return {'success': False, 'message': f'Asset type "{asset_type_name}" not found. Available: {available}'}
        resolved_id = match[0]['id']

        # Fetch required type_fields for this asset type
        fields_resp = client.get(f'{BASE_URL}/asset_types/{resolved_id}/fields')
        type_fields = {}
        if fields_resp.is_success:
            for section in fields_resp.json().get('asset_type_fields', []):
                for f in section.get('fields', []):
                    fname = f.get('name', '')
                    if not f.get('required') or not fname or fname in ('name', 'asset_type_id'):
                        continue
                    if fname.startswith('asset_state_'):
                        type_fields[fname] = asset_state
                    elif fname.startswith('product_'):
                        # Look up product by name or use first available for this type
                        products_resp = client.get(f'{BASE_URL}/products')
                        products = products_resp.json().get('products', []) if products_resp.is_success else []
                        if product_name:
                            pm = [p for p in products if product_name.lower() in p.get('name', '').lower()]
                            type_fields[fname] = pm[0]['id'] if pm else (products[0]['id'] if products else None)
                        else:
                            # Use first product matching this asset type
                            typed = [p for p in products if p.get('asset_type_id') == resolved_id]
                            type_fields[fname] = typed[0]['id'] if typed else (products[0]['id'] if products else None)

        payload: dict = {'name': name, 'asset_type_id': resolved_id}
        if type_fields:
            payload['type_fields'] = type_fields
        if asset_tag:
            payload['asset_tag'] = asset_tag

        resp = client.post(f'{BASE_URL}/assets', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        asset = resp.json().get('asset', {})
        aid = asset.get('display_id') or asset.get('id')
        return {'success': True, 'asset_id': aid, 'message': f'Asset #{aid} created'}


@mcp.tool()
def update_asset(asset_id: int, name: str = None, asset_tag: str = None, description: str = None, user_email: str = None) -> dict:
    """Updates an asset's name, tag, or description.
    To assign an asset to a user, provide user_email. Assigning without an email is not supported.

    Args:
        asset_id: Asset display ID e.g. 12
        name: New name (optional)
        asset_tag: New asset tag (optional)
        description: New description (optional)
        user_email: Email address to assign the asset e.g. "john@company.com" (optional)
    """
    payload = {}
    if name:
        payload['name'] = name
    if asset_tag:
        payload['asset_tag'] = asset_tag
    if description:
        payload['description'] = description
    with get_client() as client:
        if user_email:
            if '@' not in user_email:
                return {'success': False, 'message': 'user_email must be a valid email address e.g. "john@company.com"'}
            requester = get_requester_by_email(user_email)
            if not requester.get('success'):
                return {'success': False, 'message': f'User not found for email "{user_email}". Provide the exact email address of the user in Freshservice.'}
            payload['user_id'] = requester['requester_id']
        if not payload:
            return {'success': False, 'message': 'Nothing to update — provide at least one of: name, asset_tag, description, user_email'}
        resp2 = client.put(f'{BASE_URL}/assets/{asset_id}', json=payload)
        if not resp2.is_success:
            return {'success': False, 'message': f'API error {resp2.status_code}: {resp2.text}'}
        return {'success': True, 'asset_id': asset_id, 'message': f'Asset #{asset_id} updated'}


@mcp.tool()
def delete_asset(asset_id: int) -> dict:
    """Permanently deletes an asset. Use with caution!

    Args:
        asset_id: Asset display ID e.g. 12
    """
    with get_client() as client:
        resp2 = client.delete(f'{BASE_URL}/assets/{asset_id}')
        if not resp2.is_success:
            return {'success': False, 'message': f'API error {resp2.status_code}: {resp2.text}'}
        return {'success': True, 'message': f'Asset #{asset_id} deleted'}


@mcp.tool()
def assign_asset_to_me(asset_id: int) -> dict:
    """Assigns an asset to yourself (the default requester configured in .env).

    Args:
        asset_id: Asset display ID e.g. 7
    """
    if not DEFAULT_REQUESTER_EMAIL:
        return {'success': False, 'message': 'REQUESTER_EMAIL is not set in .env'}
    requester = get_requester_by_email(DEFAULT_REQUESTER_EMAIL)
    if not requester.get('success'):
        return {'success': False, 'message': f'Could not find requester for {DEFAULT_REQUESTER_EMAIL}'}
    with get_client() as client:
        resp = client.put(f'{BASE_URL}/assets/{asset_id}', json={'user_id': requester['requester_id']})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'asset_id': asset_id, 'message': f'Asset #{asset_id} assigned to {DEFAULT_REQUESTER_EMAIL}'}

# ── UPGRADE NOTE FOR LARGER MODELS ────────────────────────────────────────────
# To support assigning assets to any user by email, update update_asset() as follows:
# 1. Remove the assign_asset_to_me tool above (it becomes redundant)
# 2. In update_asset(), the user_email parameter is already wired to get_requester_by_email()
#    and sets payload['user_id'] — this works for any email, not just the default one.
# 3. Larger models (llama3.1:8b+) can reliably pass a user_email parameter.
#    For 3B models this is unreliable — they hallucinate email addresses.
# ──────────────────────────────────────────────────────────────────────────────


# ════════════════════════════════════════════════
#  KNOWLEDGE BASE
# ════════════════════════════════════════════════

@mcp.tool()
def search_knowledge_base(query: str) -> dict:
    """Searches the knowledge base for articles.

    Args:
        query: Search term e.g. "VPN" or "password reset"
    """
    if not query or not query.strip():
        return {'success': False, 'message': 'Search term is required'}
    import re
    def strip_html(text):
        return re.sub(r'<[^>]+>', ' ', text or '')
    query_lower = query.strip().lower()
    all_articles = []
    with get_client() as client:
        categories = client.get(f'{BASE_URL}/solutions/categories').json().get('categories', [])
        for category in categories:
            folders = client.get(f'{BASE_URL}/solutions/folders', params={'category_id': category['id']}).json().get('folders', [])
            for folder in folders:
                articles = client.get(f'{BASE_URL}/solutions/articles', params={'folder_id': folder['id']}).json().get('articles', [])
                all_articles.extend(articles)
        filtered = [a for a in all_articles if query_lower in a.get('title', '').lower() or query_lower in strip_html(a.get('description', '')).lower()]
        if not filtered:
            return {'count': 0, 'message': f'No articles found for "{query}"', 'articles': []}
        return {'count': len(filtered), 'articles': [{'id': a.get('id'), 'title': a.get('title', ''), 'summary': strip_html(a.get('description', ''))[:300]} for a in filtered]}


@mcp.tool()
def list_solution_folders() -> dict:
    """Lists all knowledge base categories and their folders with IDs.
    Use this before creating an article to find the correct folder_id or folder name.
    """
    with get_client() as client:
        categories = client.get(f'{BASE_URL}/solutions/categories').json().get('categories', [])
        result = []
        for cat in categories:
            folders_resp = client.get(f'{BASE_URL}/solutions/folders', params={'category_id': cat['id']}).json()
            for folder in folders_resp.get('folders', []):
                result.append({
                    'folder_id': folder['id'],
                    'folder_name': folder.get('name', ''),
                    'category_id': cat['id'],
                    'category_name': cat.get('name', ''),
                })
        if not result:
            return {'success': False, 'message': 'No folders found in the knowledge base'}
        return {'success': True, 'count': len(result), 'folders': result}


@mcp.tool()
def create_solution_article(
    title: str,
    description: str,
    folder_name: str | None = None,
    folder_id: str | None = None,
    category_name: str | None = None,
    status: str | None = None,
    article_type: str | None = None,
    tags: str | None = None,
) -> dict:
    """Creates a new knowledge base article in Freshservice Solutions.

    Args:
        title: Article title e.g. "How to reset your VPN password"
        description: Article body — plain text or HTML
        folder_name: Name of the folder to publish into (resolved automatically).
                     Use list_solution_folders to find available folders.
        folder_id: Numeric folder ID — use this instead of folder_name if known
        category_name: Narrows folder lookup when folder_name matches multiple categories
        status: "draft" or "published" (default published). Also accepts "1" or "2".
        article_type: "permanent" or "workaround" (default permanent). Also accepts "1" or "2".
        tags: Comma-separated tags e.g. "vpn,password,remote"
    """
    if not folder_id and not folder_name:
        return {'success': False, 'message': 'Provide either folder_id or folder_name'}

    # Normalise status
    status_map = {'draft': 1, '1': 1, 'published': 2, '2': 2}
    status_int = status_map.get(str(status).lower(), 2) if status is not None else 2

    # Normalise article_type
    type_map = {'permanent': 1, '1': 1, 'workaround': 2, '2': 2}
    type_int = type_map.get(str(article_type).lower(), 1) if article_type is not None else 1

    # Resolve folder_id
    resolved_folder_id = int(folder_id) if folder_id else None
    if not resolved_folder_id:
        with get_client() as client:
            categories = client.get(f'{BASE_URL}/solutions/categories').json().get('categories', [])
            needle = folder_name.strip().lower()
            cat_needle = category_name.strip().lower() if category_name else None
            for cat in categories:
                if cat_needle and cat_needle not in cat.get('name', '').lower():
                    continue
                folders = client.get(f'{BASE_URL}/solutions/folders', params={'category_id': cat['id']}).json().get('folders', [])
                for f in folders:
                    if needle in f.get('name', '').lower():
                        resolved_folder_id = f['id']
                        break
                if resolved_folder_id:
                    break
        if not resolved_folder_id:
            return {'success': False, 'message': f'Folder "{folder_name}" not found. Use list_solution_folders to see available folders.'}

    # Wrap plain text in a paragraph if it doesn't look like HTML
    body = description if description.strip().startswith('<') else f'<p>{description}</p>'

    # Normalise tags — accept comma string or list
    tag_list = None
    if tags:
        if isinstance(tags, list):
            tag_list = [str(t).strip() for t in tags if str(t).strip()]
        else:
            tag_list = [t.strip() for t in str(tags).split(',') if t.strip()]

    payload: dict = {
        'title': title,
        'description': body,
        'folder_id': resolved_folder_id,
        'status': status_int,
    }
    if tag_list:
        payload['tags'] = tag_list

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/solutions/articles', json=payload)
        # Retry without optional fields that the instance may not support
        if not resp.is_success:
            try:
                err_text = resp.text.lower()
                bad = [f for f in ('type', 'tags') if f'"{f}"' in err_text or f"'{f}'" in err_text]
            except Exception:
                bad = []
            if bad:
                retry_payload = {k: v for k, v in payload.items() if k not in bad}
                resp = client.post(f'{BASE_URL}/solutions/articles', json=retry_payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        article = resp.json().get('article', resp.json())
        aid = article.get('id')
        return {'success': True, 'article_id': aid, 'message': f'Article #{aid} created in folder {resolved_folder_id}'}


# ════════════════════════════════════════════════
#  SERVICE CATALOG & SERVICE REQUESTS
# ════════════════════════════════════════════════

@mcp.tool()
def list_service_catalog_categories() -> dict:
    """Lists all service catalog categories.
    Call this first to find a category_id before creating a new service catalog item.
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/service_catalog/categories')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        categories = resp.json().get('service_categories', [])
        return {
            'count': len(categories),
            'categories': [{'id': c.get('id'), 'name': c.get('name', '')} for c in categories],
        }


@mcp.tool()
def create_service_catalog_item(
    name: str,
    category_id: int,
    short_description: str = "",
    description: str = "",
    visibility: int = 1,
    status: int | None = None,
    workspace_id: int = 2,
) -> dict:
    """Creates a new service catalog item in Freshservice.

    Use list_service_catalog_categories to get a valid category_id first.

    Args:
        name: Name of the service catalog item
        category_id: ID of the category to place the item in (from list_service_catalog_categories)
        short_description: Brief one-line description shown in the catalog
        description: Full HTML description of the item
        visibility: 1 = draft (default), 2 = published (visible to requesters)
        status: Alias for visibility — 1 = draft, 2 = published
        workspace_id: Workspace to create the item in (default 2 = IT)
    """
    effective_visibility = int(status) if status is not None else visibility
    service_item: dict = {
        'name': name,
        'category_id': category_id,
        'visibility': effective_visibility,
        'description': description if description else f'<p>{name}</p>',
    }
    if short_description:
        service_item['short_description'] = short_description
    if not short_description and description:
        # Strip HTML tags for short description if not provided
        import re
        service_item['short_description'] = re.sub(r'<[^>]+>', '', description)[:200].strip() or name

    payload = {'service_item': service_item, 'workspace_id': workspace_id}

    # Note: endpoint uses hyphen (service-catalog), not underscore
    with get_client() as client:
        resp = client.post(f'{BASE_URL}/service-catalog/items', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        item = resp.json().get('service_item', {})
        return {
            'success': True,
            'item_id': item.get('display_id'),
            'name': item.get('name'),
            'category_id': item.get('category_id'),
            'visibility': item.get('visibility'),
            'workspace_id': item.get('workspace_id'),
            'message': f'Service catalog item "{name}" created (display_id={item.get("display_id")})',
        }


@mcp.tool()
def update_service_catalog_item(
    item_id: int,
    name: str | None = None,
    description: str | None = None,
    short_description: str | None = None,
    is_active: bool | None = None,
    category_id: int | None = None,
    visibility: int | None = None,
    status: int | None = None,
) -> dict:
    """Updates an existing service catalog item.

    Args:
        item_id: ID of the service catalog item to update
        name: New name (optional)
        description: New description (optional)
        short_description: New short description (optional)
        is_active: Set to false to deactivate, true to reactivate (optional)
        category_id: Move to a different category (optional)
        visibility: 1 = draft, 2 = published (optional)
        status: Alias for visibility — 1 = draft, 2 = published (optional)
    """
    payload: dict = {}
    if name is not None:
        payload['name'] = name
    if description is not None:
        payload['description'] = description
    if short_description is not None:
        payload['short_description'] = short_description
    if is_active is not None:
        payload['is_active'] = is_active
    if category_id is not None:
        payload['category_id'] = category_id
    effective_visibility = int(status) if status is not None else visibility
    if effective_visibility is not None:
        payload['visibility'] = effective_visibility
    if not payload:
        return {'success': False, 'message': 'Nothing to update — provide at least one field'}

    # Note: endpoint uses hyphen (service-catalog), not underscore
    with get_client() as client:
        resp = client.put(f'{BASE_URL}/service-catalog/items/{item_id}', json={'service_item': payload})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'item_id': item_id, 'message': f'Service catalog item #{item_id} updated'}


@mcp.tool()
def list_service_catalog_items(search: str = None, category_id: str = None) -> dict:
    """Lists available items in the Freshservice service catalog.
    Call this first to find the item ID before creating a service request.

    Args:
        search: Filter by name e.g. "Laptop" or "Onboarding" (optional)
        category_id: Filter by category ID (optional)
    """
    with get_client() as client:
        params = {'per_page': 30, 'page': 1}
        if category_id:
            try:
                params['category_id'] = int(category_id)
            except (ValueError, TypeError):
                pass
        resp = client.get(f'{BASE_URL}/service_catalog/items', params=params)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        items = resp.json().get('service_items', [])
        if search:
            s = search.strip().lower()
            items = [i for i in items if s in i.get('name', '').lower() or s in i.get('description', '').lower()]
        return {
            'count': len(items),
            'items': [
                {
                    'id': i.get('id'),
                    'name': i.get('name', ''),
                    'category': i.get('category_name', ''),
                    'description': (i.get('description', '') or '')[:200],
                    'cost': i.get('cost_visibility', ''),
                    'delivery_time': i.get('delivery_time', ''),
                }
                for i in items
            ],
        }


@mcp.tool()
def get_service_catalog_item(item_id: int) -> dict:
    """Gets full details and custom fields of a service catalog item.
    Use this before create_service_request to see what custom_fields are available.

    Args:
        item_id: Service catalog item ID from list_service_catalog_items
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/service_catalog/items/{item_id}')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        item = resp.json().get('service_item', {})
        # Surface custom fields so the agent knows what to fill in
        fields = [
            {
                'name': f.get('name'),
                'label': f.get('label'),
                'field_type': f.get('field_type'),
                'required': f.get('required', False),
            }
            for f in item.get('custom_fields', [])
        ]
        return {
            'success': True,
            'id': item.get('id'),
            'name': item.get('name', ''),
            'category': item.get('category_name', ''),
            'description': item.get('description', ''),
            'custom_fields': fields,
        }


@mcp.tool()
def create_service_request(
    service_item_id: int,
    requested_for_email: str,
    quantity: int = 1,
    custom_fields: str | None = None,
) -> dict:
    """Creates a service request from a service catalog item.

    Use list_service_catalog_items to find the item ID, and
    get_service_catalog_item to see the available custom fields.

    Args:
        service_item_id: ID of the catalog item to request
        requested_for_email: Email of the person the request is for
        quantity: Number of items to request (default 1)
        custom_fields: JSON string of custom field values
                       e.g. '{"laptop_model": "MacBook Air", "department": "IT"}'
    """
    requester = get_requester_by_email(requested_for_email)
    if not requester.get('success'):
        return {'success': False, 'message': f'Requester not found for "{requested_for_email}": {requester.get("message")}'}

    payload: dict = {
        'quantity': quantity,
        'requested_for_id': requester['requester_id'],
    }

    if custom_fields:
        try:
            cf = __import__('json').loads(custom_fields) if isinstance(custom_fields, str) else custom_fields
            if isinstance(cf, dict):
                payload['custom_fields'] = cf
        except Exception:
            return {'success': False, 'message': f'custom_fields is not valid JSON: {custom_fields}'}

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/service_catalog/items/{service_item_id}/place_request', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        sr = resp.json().get('service_request', {})
        sid = sr.get('id') or sr.get('display_id')
        return {
            'success': True,
            'service_request_id': sid,
            'message': f'Service request #{sid} created for {requested_for_email}',
        }


@mcp.tool()
def list_service_requests(page: int = 1) -> dict:
    """Lists service requests (fulfilled items from the service catalog).

    Args:
        page: Page number (default 1)
    """
    with get_client() as client:
        resp = client.get(f'{BASE_URL}/tickets', params={'type': 'Service Request', 'per_page': 20, 'page': page})
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        tickets = resp.json().get('tickets', [])
        return {
            'count': len(tickets),
            'service_requests': [
                {
                    'id': t.get('display_id') or t.get('id'),
                    'subject': t.get('subject', ''),
                    'status': t.get('status'),
                    'priority': t.get('priority'),
                    'created': t.get('created_at', ''),
                }
                for t in tickets
            ],
        }


@mcp.tool()
def approve_service_request(ticket_id: int) -> dict:
    """Approves a pending service request.

    Note: approval behaviour depends on your Freshservice account approval configuration.
    If approval workflows are not configured, this call may return an error.

    Args:
        ticket_id: Service request ticket ID e.g. 42
    """
    with get_client() as client:
        resp = client.put(f'{BASE_URL}/tickets/{ticket_id}/approve')
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'ticket_id': ticket_id, 'message': f'Service request #{ticket_id} approved'}


# ════════════════════════════════════════════════
#  JOURNEYS (EMPLOYEE LIFECYCLE)
# ════════════════════════════════════════════════
# Freshservice Journey API uses three endpoints:
#   /journey_requests       — generic journey requests
#   /onboarding_requests    — employee onboarding
#   /offboarding_requests   — employee offboarding
# Journey templates are configured in the Freshservice UI and
# cannot be listed via API; use list_active_journeys to see past ones.

@mcp.tool()
def list_active_journeys(page: int = 1) -> dict:
    """Lists active and recent employee journeys (onboarding + offboarding).

    Args:
        page: Page number (default 1)
    """
    with get_client() as client:
        results = []
        for endpoint, kind in [
            ('/onboarding_requests', 'onboarding'),
            ('/offboarding_requests', 'offboarding'),
        ]:
            resp = client.get(f'{BASE_URL}{endpoint}', params={'page': page, 'per_page': 20})
            if resp.is_success:
                key = endpoint.lstrip('/').rstrip('s') + 's'  # crude pluralisation
                # key could be 'onboarding_requests' or 'offboarding_requests'
                items = resp.json().get(key, resp.json().get('journey_requests', []))
                for j in items:
                    results.append({
                        'id': j.get('id'),
                        'type': kind,
                        'status': j.get('status', ''),
                        'employee_id': j.get('employee_id') or j.get('requester_id'),
                        'created': j.get('created_at', ''),
                    })
        if results:
            return {'count': len(results), 'journeys': results}
        # Fallback: generic journey_requests endpoint
        resp = client.get(f'{BASE_URL}/journey_requests', params={'page': page, 'per_page': 20, 'filter': 'all'})
        if not resp.is_success:
            return {'success': False, 'message': f'Journey API not available: {resp.status_code}: {resp.text}'}
        items = resp.json().get('journey_requests', [])
        return {
            'count': len(items),
            'journeys': [
                {
                    'id': j.get('id'),
                    'type': j.get('journey_type', ''),
                    'status': j.get('status', ''),
                    'employee_id': j.get('employee_id'),
                    'created': j.get('created_at', ''),
                }
                for j in items
            ],
        }


@mcp.tool()
def get_journey_by_id(journey_id: int, journey_type: str = 'onboarding') -> dict:
    """Gets full details of a specific journey request.

    Args:
        journey_id: Journey request ID
        journey_type: "onboarding", "offboarding", or "journey" (default "onboarding")
    """
    endpoint_map = {
        'onboarding':  f'{BASE_URL}/onboarding_requests/{journey_id}',
        'offboarding': f'{BASE_URL}/offboarding_requests/{journey_id}',
        'journey':     f'{BASE_URL}/journey_requests/{journey_id}',
    }
    url = endpoint_map.get(journey_type.lower(), endpoint_map['onboarding'])
    with get_client() as client:
        resp = client.get(url)
        if not resp.is_success:
            return {'success': False, 'message': f'Journey #{journey_id} not found: {resp.status_code}: {resp.text}'}
        data = resp.json()
        journey = data.get('onboarding_request') or data.get('offboarding_request') or data.get('journey_request') or data
        return {'success': True, 'journey': journey}


@mcp.tool()
def get_journey_activities(journey_id: int, journey_type: str = 'journey') -> dict:
    """Lists tickets and tasks associated with a journey request.

    Args:
        journey_id: Journey request ID
        journey_type: "onboarding", "offboarding", or "journey" (default "journey")
    """
    endpoint_map = {
        'onboarding':  f'{BASE_URL}/onboarding_requests/{journey_id}/tickets',
        'offboarding': f'{BASE_URL}/offboarding_requests/{journey_id}/tickets',
        'journey':     f'{BASE_URL}/journey_requests/{journey_id}/activities',
    }
    url = endpoint_map.get(journey_type.lower(), endpoint_map['journey'])
    with get_client() as client:
        resp = client.get(url)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        data = resp.json()
        items = data.get('tickets') or data.get('activities') or []
        return {'success': True, 'journey_id': journey_id, 'count': len(items), 'items': items}


@mcp.tool()
def create_onboarding_request(
    employee_email: str,
    manager_email: str | None = None,
    department: str | None = None,
    start_date: str | None = None,
    location: str | None = None,
) -> dict:
    """Creates an onboarding journey request for a new employee.

    The onboarding journey is configured in the Freshservice UI — this triggers it
    for a specific employee. The employee must already exist as a requester.

    Args:
        employee_email: Email of the employee being onboarded
        manager_email: Manager's email (optional)
        department: Department name e.g. "Engineering" (optional)
        start_date: Start date e.g. "2026-04-01" (optional)
        location: Office location e.g. "Berlin HQ" (optional)
    """
    employee = get_requester_by_email(employee_email)
    if not employee.get('success'):
        return {'success': False, 'message': f'Employee not found in Freshservice: {employee_email}'}

    payload: dict = {'employee_id': employee['requester_id']}

    if manager_email:
        mgr = get_requester_by_email(manager_email)
        if mgr.get('success'):
            payload['reporting_manager_id'] = mgr['requester_id']

    if department:
        payload['department'] = department
    if start_date:
        payload['start_date'] = start_date
    if location:
        payload['location'] = location

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/onboarding_requests', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        req = resp.json().get('onboarding_request', resp.json())
        rid = req.get('id')
        return {
            'success': True,
            'onboarding_id': rid,
            'message': f'Onboarding request #{rid} created for {employee_email}',
        }


@mcp.tool()
def create_offboarding_request(
    employee_email: str,
    last_working_day: str | None = None,
    manager_email: str | None = None,
    reason: str | None = None,
) -> dict:
    """Creates an offboarding journey request for a departing employee.

    Args:
        employee_email: Email of the employee being offboarded
        last_working_day: Last day e.g. "2026-05-01" (optional)
        manager_email: Manager's email (optional)
        reason: Reason for offboarding e.g. "Resignation", "Retirement" (optional)
    """
    employee = get_requester_by_email(employee_email)
    if not employee.get('success'):
        return {'success': False, 'message': f'Employee not found in Freshservice: {employee_email}'}

    payload: dict = {'employee_id': employee['requester_id']}

    if manager_email:
        mgr = get_requester_by_email(manager_email)
        if mgr.get('success'):
            payload['reporting_manager_id'] = mgr['requester_id']

    if last_working_day:
        payload['last_working_date'] = last_working_day
    if reason:
        payload['separation_cause'] = reason

    with get_client() as client:
        resp = client.post(f'{BASE_URL}/offboarding_requests', json=payload)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        req = resp.json().get('offboarding_request', resp.json())
        rid = req.get('id')
        return {
            'success': True,
            'offboarding_id': rid,
            'message': f'Offboarding request #{rid} created for {employee_email}',
        }


@mcp.tool()
def cancel_journey_request(journey_id: int, journey_type: str = 'onboarding') -> dict:
    """Cancels an active journey request.

    Args:
        journey_id: Journey request ID to cancel
        journey_type: "onboarding", "offboarding", or "journey" (default "onboarding")
    """
    endpoint_map = {
        'onboarding':  f'{BASE_URL}/onboarding_requests/{journey_id}/cancel',
        'offboarding': f'{BASE_URL}/offboarding_requests/{journey_id}/cancel',
        'journey':     f'{BASE_URL}/journey_requests/{journey_id}/cancel',
    }
    url = endpoint_map.get(journey_type.lower(), endpoint_map['onboarding'])
    with get_client() as client:
        resp = client.put(url)
        if not resp.is_success:
            return {'success': False, 'message': f'API error {resp.status_code}: {resp.text}'}
        return {'success': True, 'journey_id': journey_id, 'message': f'Journey #{journey_id} cancelled'}


# ── Start server ──────────────────────────────
if __name__ == '__main__':
    mcp.run(transport='stdio')
