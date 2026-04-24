"""
Demo prep workflow — three-worker pipeline for pre-sales intelligence.

Flow:
  1. Intent detection — conservative keyword matching
  2. Worker 1 (Company Research)  — websearch_search tools
  3. Worker 2 (RAG Retrieval)     — rag_list_collections + rag_query tools
  4. Worker 3 (Synthesis)         — no tools, reasoning only

Progress markers yielded:
  *[Researching company...]*
  *[Retrieving relevant vertical content...]*
  *[Synthesising demo prep brief...]*

Graceful degradation:
  - websearch server disabled/absent → skip Worker 1, use user message as context
  - RAG empty or absent            → skip Worker 2, note in brief
  - Never crashes — Worker 3 always produces some output
"""
from __future__ import annotations

from typing import Generator

# ── Intent detection ──────────────────────────────────────────────────────────

# Compound phrases that indicate an operational (non-demo-prep) query — these veto
# detection.  Use specific phrases rather than single words so that "prepare a
# discovery for HANOS and Freshservice — incident management" is not blocked.
_OPERATIONAL = (
    "open ticket",
    "create ticket",
    "list ticket",
    "update ticket",
    "delete ticket",
    "create asset",
    "list asset",
    "update asset",
    "delete asset",
    "create contact",
    "list contact",
    "update contact",
    "open items",
    "knowledge base article",
    "kb article",
    "create change",
    "list change",
    "create problem",
    "list problem",
    "create service request",
    "list service request",
)

# Trigger phrases that indicate a demo / research intent
_TRIGGERS = (
    "prepare",
    "demo prep",
    "demo at",
    "demo for",
    "demo script",
    "demo plan",
    "need a demo",
    "discovery call",
    "discovery prep",
    "discovery question",
    "questions to ask",
    "questions for",
    "research",
    "who is",
    "tell me about",
    "brief on",
    "prep for",
)

# Context words that indicate a company / industry target is present
_CONTEXT_WORDS = (
    " ag",
    " gmbh",
    " inc",
    " ltd",
    " corp",
    "company",
    "manufacturer",
    "bank",
    "retailer",
    "hospital",
    "university",
    "startup",
    "enterprise",
    "insurer",
    "telecom",
    "pharma",
    "chemical",
    "retailer",
    "industry",
    "customer",
    "prospect",
    "account",
    "group",          # e.g. "Siemens Group"
    "holding",
)


def is_demo_prep_intent(message: str) -> bool:
    """
    Return True when the message looks like a demo prep / discovery prep request.

    Conservative by design: both a trigger keyword AND either a company/industry
    context word OR an explicit demo/discovery keyword must be present.
    Falls through to the normal agent loop for any ambiguous case.
    """
    msg = message.lower()

    # Veto: operational queries (ticket management, asset lookups, etc.)
    if any(op in msg for op in _OPERATIONAL):
        return False

    # Must have an explicit trigger
    if not any(t in msg for t in _TRIGGERS):
        return False

    # Trigger is enough when the message explicitly mentions a demo or discovery
    if "demo" in msg or "discovery" in msg:
        return True

    # Otherwise require a company / industry context word
    return any(c in msg for c in _CONTEXT_WORDS)


# Keywords that signal discovery intent (questions-focused output)
_DISCOVERY_SIGNALS = (
    "discovery call",
    "discovery prep",
    "discovery question",
    "discovery meeting",
    "discovery session",
    "prepare for discovery",
    "prep for discovery",
    "questions for",
    "questions to ask",
)


def get_prep_type(message: str) -> str:
    """
    Return 'discovery' if the message is asking for discovery call preparation,
    'demo' otherwise.
    """
    msg = message.lower()
    if any(s in msg for s in _DISCOVERY_SIGNALS):
        return "discovery"
    return "demo"


# ── Worker system prompts ─────────────────────────────────────────────────────

_W1_SYSTEM = (
    "You are a business research assistant. "
    "Given a company name and brief description, search the web and extract structured context. "
    "Cover: industry, estimated size, geography, key products or services, "
    "likely operational pain points, and technology maturity signals. "
    "Also search for recent organisational changes — leadership appointments or departures, "
    "restructuring, acquisitions, layoffs, or strategic pivots announced in the past 12 months. "
    "Also search for investor relations news — earnings announcements, guidance updates, "
    "analyst day presentations, press releases, or major capital allocation decisions. "
    "Use the search tool to gather accurate, current information. "
    "Return your findings as clear prose — you will be summarised by a downstream agent."
)

_W2_SYSTEM = (
    "You are a knowledge base retrieval specialist. "
    "Given company research, query the RAG knowledge base and extract structured content "
    "for use in demo and discovery preparation. "
    "Always call rag_list_collections first to discover the real collection names — "
    "never assume or invent collection names. "
    "Pick the collections that best match the company's industry and query them. "
    "For every result, extract and return VERBATIM: "
    "(1) the exact discovery questions as written in the knowledge base, "
    "(2) the process area and activity they belong to, "
    "(3) the features mentioned, "
    "(4) the pain points described in the manual vs automated process fields. "
    "Label each item with its actual collection name. "
    "Do not paraphrase — copy the discovery questions and features exactly as found."
)

_DEFAULT_DEMO_PREP_PROMPT = """\
You are a senior solution engineer preparing a live Freshdesk/Freshservice demo for a prospect.
You have company research (web search) and knowledge base content (Freshworks vertical playbooks).
Output a DEMO PREPARATION GUIDE — concrete, specific, assertive. No hedging language ("may", "could", "might").
Name the company in every section. State facts and recommendations as confident assertions.

## Company Snapshot
2-3 sentences: industry, size, geography.
Include one specific fact (a number, initiative, or known challenge) that shows you did your homework.

## Pain Points to Address
3-4 pain points grounded in the company research and knowledge base.
State each as a confident assertion — not a hypothesis. Write in the company's voice.
For each:
- **Pain:** "[Company] struggles with X" — name the specific operational challenge based on the research
- **How Freshdesk/Freshservice solves it:** State the specific capability and exactly how it eliminates the pain.
  Format: "[Feature name] does X, which means [company] no longer has to Y."

## Demo Environment — What to Prepare Before the Demo
Concrete setup for the demo environment so it feels real for this specific company.
Use their actual industry context, org structure, and product lines in every name.

**Freshdesk**
- Groups: exact names to create (e.g. "B2B Wholesale Support", "B2C Online Returns") — match their business units
- Custom ticket fields: exact field names and types (e.g. "Order ID [text]", "Product Category [dropdown: Food/Accessories/Toys]", "Retailer Region [dropdown]")
- SLA policies: exact tier names, response and resolution times, and which customer segment each applies to
- Sample contacts / companies: 2-3 fictitious but realistic names matching their actual customer base
- Canned responses: exact titles and a one-line description of the content for each
- Automation rules: exact rule logic (e.g. "If ticket source = email AND group = B2B → assign to B2B Wholesale Support, set priority = High")

**Freshservice** (include only if clearly relevant to this company's profile)
- Departments / groups: names reflecting their org structure
- Service catalog items: exact item names realistic for their environment
- Asset types or custom fields: relevant to their infrastructure
- Sample incidents or service requests: exact scenario title and what to walk through

## Demo Flow
Narrative structure — not a feature tour. Every step must reference the prepared demo environment above.

**Act 1 — Opening hook (2 min)**
Write the exact sentence to open with. It must cite a specific fact from the research.
Then: one sentence on what this demo will prove for them specifically.

**Act 2 — Core scenarios (15 min)**
2-3 scenarios, each directly mapped to a pain point. For each:
- **What to show:** exact screen or workflow (e.g. "Open the pre-created ticket from 'PetCare GmbH', show the Order ID field populated, trigger the B2B SLA timer")
- **Value statement:** "[Company] currently does X manually / loses time on X. Freshdesk's Y means they get Z instead." State this as a fact.
- **Wow moment:** the single thing that should make them lean forward — name it explicitly

**Act 3 — Proof (3 min)**
One relevant metric, retail industry case study reference, or integration highlight.
Do not invent numbers. If none are available from the research, state that and suggest a relevant integration instead.

## Likely Objections and Responses
2-3 objections realistic for this company (pricing, GDPR, existing tools, complexity).
For each: the objection verbatim as they might say it, and a direct confident response.

## Things to Avoid
1-2 topics or angles that are irrelevant or could backfire specifically for this account.

Never hallucinate. If research is insufficient for a section, say so explicitly.\
"""

_DEFAULT_DISCOVERY_PREP_PROMPT = """\
You are a senior solution engineer preparing for a first discovery call with a specific prospect.
You have two inputs:
  (A) Company research — facts from web search about this prospect
  (B) Knowledge base content — verbatim discovery questions, process areas, features, and
      pain points extracted from Freshworks CX/EX vertical playbooks for this industry

Output a DISCOVERY PREPARATION GUIDE.

CRITICAL RULE: The discovery questions MUST be grounded in the knowledge base content in input (B).
Do not invent questions. Take verbatim KB questions and adapt them to this company's specific context
(industry, size, geography, known challenges). If KB returned no content, flag it as a gap.

## Company Snapshot
2-3 sentences: industry, size, geography.
One specific fact from the research you can reference naturally in the call.

## Pain Points (Research-Grounded)
3-4 pain points inferred from the company research. State each as an assertion, not a guess.
For each:
- **Pain:** "[Company] faces X" — the specific operational challenge based on what the research reveals
- **Signal:** the research fact that points to this pain (e.g. "They operate 6,000+ SKUs across B2B and B2C channels")
- **Angle:** which Freshdesk or Freshservice capability is most relevant — state it as a confident recommendation

## Primary Hypothesis
One sentence: the most likely core problem Freshdesk or Freshservice solves for them.
State it as a going-in assertion, not a question — the call confirms or refines it.

## Discovery Questions
Group by process area from the knowledge base. Label each [CX] or [EX].
[CX] = customer experience / Freshdesk   [EX] = employee and IT experience / Freshservice

For each question, lead with a research-backed statement that sets context, then ask the question:
**[CX/EX] Research context:** "[One sentence from the research that makes this question relevant to them specifically.]"
**Question:** <KB question adapted to reference this company>
→ *Probing for:* what you want to learn
→ *KB source:* the process area this comes from

Target 8-12 questions across 3-5 process areas.
If the knowledge base was sparse, name which areas are missing.

## Context to Reference Naturally
2-3 specific facts from the research, written as ready-to-use conversation starters.
Example: "I noticed you distribute to 100+ countries with a 6,000 SKU catalogue — how does your support team handle product enquiries at that volume?"

## Watch-outs
1-2 sensitivities, existing tool investments, or information gaps that could affect the call.

Do not invent questions. If the knowledge base was sparse, say which areas are not covered.\
"""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _agent_loop_run(*args, **kwargs):
    """Lazy wrapper around agent.loop.run to avoid circular import at module level."""
    from .loop import run  # noqa: PLC0415
    return run(*args, **kwargs)


def _collect_text(generator: Generator[str, None, None]) -> str:
    """Drain a generator and return only the natural-language text.
    Tool-call progress markers are discarded — we only need the model's prose output.
    """
    parts = []
    for token in generator:
        if not (
            token.startswith("*[Calling tool:")
            or token.startswith("*[Tool result:")
            or token.startswith("*[Agent reached")
        ):
            parts.append(token)
    return "".join(parts).strip()


def _w1_task(user_message: str) -> str:
    return (
        f"Research the following company or prospect and return structured findings:\n\n"
        f"{user_message}\n\n"
        "Use multiple web searches to find:\n"
        "1. Core profile — industry, size, geography, key products/services, "
        "operational pain points, technology maturity signals.\n"
        "2. Recent organisational changes — search '[company] leadership change OR restructuring "
        "OR acquisition OR layoffs OR reorg 2024 2025'. Report any executive appointments or "
        "departures, org restructuring, M&A activity, or strategic pivots.\n"
        "3. Investor relations news — search '[company] earnings OR investor relations OR "
        "annual report OR press release 2024 2025'. Report earnings results, guidance, "
        "analyst day highlights, or major strategic announcements.\n"
        "Be specific and factual. If a search returns no relevant results for a section, say so."
    )


def _w2_task(user_message: str, company_context: str) -> str:
    return (
        "Company research summary:\n"
        f"{company_context}\n\n"
        "Original request:\n"
        f"{user_message}\n\n"
        "Query the RAG knowledge base and extract content for this company's industry:\n"
        "1. Call rag_list_collections to see ALL available collections. "
        "Use the actual collection names returned — do NOT assume names like 'cx_verticals' or 'ex_processes'.\n"
        "2. From the returned list, pick the 1-2 collections whose names best match the company's industry "
        "(e.g. if the company is a retailer, pick a collection with 'Retail' in the name; "
        "for manufacturing pick 'Manufacturing'; for IT/employee topics pick collections with 'IT', "
        "'Service', 'Incident', or 'Employee' in the name). "
        "Query each chosen collection using the company's industry as the search term "
        "(e.g. 'retail', 'manufacturing', 'banking'). "
        "Also try an IT/employee-experience collection using terms like 'IT service', 'incident', "
        "'employee onboarding', 'asset management'.\n\n"
        "For every result, return VERBATIM:\n"
        "- The exact discovery questions as written (do not paraphrase)\n"
        "- The process area / activity they belong to\n"
        "- The features listed\n"
        "- The manual process and automated process pain points\n"
        "Label each block with its source collection name."
    )


def _w3_task(user_message: str, company_context: str, rag_context: str) -> str:
    parts = [f"Original request:\n{user_message}"]

    if company_context:
        parts.append(f"Company research:\n{company_context}")
    else:
        parts.append("Company research: not available — base the brief on the original request only.")

    if rag_context:
        parts.append(f"Knowledge base content:\n{rag_context}")
    else:
        parts.append(
            "Knowledge base content: not available — no RAG collections were found or queried. "
            "Draw on general Freshdesk/Freshservice product knowledge for the brief."
        )

    parts.append("Using the above, produce the demo prep brief.")
    return "\n\n".join(parts)


# ── Public entry point ────────────────────────────────────────────────────────

def run_demo_prep(
    user_message: str,
    history: list[dict],
    model: str,
    cfg: dict,
    session_manager,
    external_apis: dict,
) -> Generator[str, None, None]:
    """
    Run the three-worker demo prep pipeline and yield response tokens.

    Yields the same token format as agent.loop.run():
      - progress indicators: *[Researching company...]* etc.
      - model size warning if a 3B model is selected
      - plain text chunks (the final brief from Worker 3)
    """

    # ── Model size warning ────────────────────────────────────────────────────
    if "3b" in model.lower():
        yield (
            "*Demo prep works best with 8B or larger models. "
            "Proceeding with 3B but results may be less reliable.*\n\n"
        )

    # ── Resolve available tools ───────────────────────────────────────────────
    all_tools: list[dict] = session_manager.all_tools() if session_manager else []

    websearch_tools = [
        t for t in all_tools
        if t["function"]["name"] == "websearch_search"
    ]
    rag_tools = [
        t for t in all_tools
        if t["function"]["name"] in ("rag_list_collections", "rag_query")
    ]

    company_context = ""
    rag_context = ""

    # ── Worker 1: Company Research ────────────────────────────────────────────
    if websearch_tools:
        yield "*[Researching company...]*\n"
        company_context = _collect_text(
            _agent_loop_run(
                user_message=_w1_task(user_message),
                history=[],
                model=model,
                cfg=cfg,
                session_manager=session_manager,
                disabled_servers=None,
                external_apis=external_apis,
                system_prompt=_W1_SYSTEM,
                tools_override=websearch_tools,
            )
        )
        if not company_context:
            # Model produced nothing useful — fall back to user's original message
            company_context = user_message
    else:
        yield "*[Web search server is not enabled — using the context you provided.]*\n"
        company_context = user_message

    # ── Worker 2: RAG Retrieval ───────────────────────────────────────────────
    if rag_tools:
        yield "*[Retrieving relevant vertical content...]*\n"
        rag_context = _collect_text(
            _agent_loop_run(
                user_message=_w2_task(user_message, company_context),
                history=[],
                model=model,
                cfg=cfg,
                session_manager=session_manager,
                disabled_servers=None,
                external_apis=external_apis,
                system_prompt=_W2_SYSTEM,
                tools_override=rag_tools,
            )
        )
    else:
        yield "*[RAG server not available — brief will rely on research only.]*\n"

    # ── Worker 3: Synthesis ───────────────────────────────────────────────────
    prep_type = get_prep_type(user_message)
    if prep_type == "discovery":
        yield "*[Synthesising discovery preparation...]*\n"
        synthesis_prompt = (
            cfg.get("agent", {}).get("discovery_prep_prompt") or _DEFAULT_DISCOVERY_PREP_PROMPT
        ).strip()
    else:
        yield "*[Synthesising demo preparation...]*\n"
        synthesis_prompt = (
            cfg.get("agent", {}).get("demo_prep_prompt") or _DEFAULT_DEMO_PREP_PROMPT
        ).strip()

    yield from _agent_loop_run(
        user_message=_w3_task(user_message, company_context, rag_context),
        history=[],
        model=model,
        cfg=cfg,
        session_manager=session_manager,
        disabled_servers=None,
        external_apis=external_apis,
        system_prompt=synthesis_prompt,
        tools_override=[],   # reasoning-only — no tool access
    )
