"""
Orchestration runner — coordinates OrchestratorAgent with WorkerAgent(s).

Full orchestration flow per request:
  1. Call OrchestratorAgent to get a JSON routing decision.
  2. Emit a *[Orchestration trace: {...}]* marker (picked up by app_fastapi).
  3. If rag_first=True or delegate includes RAG, call the RAG worker first
     and collect its text output as grounding context.
  4. Call the appropriate domain worker(s) with the task and any RAG context.
  5. Yield all tokens from the worker(s) back to the caller.

Graceful fallback:
  On OrchestratorError (parse failure, schema violation, provider error),
  emits a fallback trace event and immediately re-runs in direct mode using
  the default config model. The user always gets a response — never an error.

This module is called from app_fastapi._chat_generator() when mode=orchestrated.
It is transparent to the HTTP layer: it yields the same token format as direct mode.
"""
from __future__ import annotations

import json
import logging
from typing import Generator

from .mcp_client import SessionManager
from .orchestrator import OrchestratorAgent, OrchestratorError
from .tool_scope import filter_tools_by_pattern
from .worker import WorkerAgent

logger = logging.getLogger(__name__)


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_worker(
    name:           str,
    cfg:            dict,
    external_apis:  dict,
    session_manager: SessionManager,
) -> WorkerAgent | None:
    """
    Construct a WorkerAgent for the named worker, or None if not configured.

    Reads the worker's config block from cfg["agents"]["workers"][name] and
    filters the full tool list down to the worker's declared tool pattern.
    """
    workers = cfg.get("agents", {}).get("workers", {})
    worker_cfg = workers.get(name)
    if not worker_cfg:
        logger.warning(f"[ORCH] Worker '{name}' is not configured in agents.workers — skipping.")
        return None

    all_tools    = session_manager.all_tools()
    pattern      = worker_cfg.get("tools", "")
    scoped_tools = filter_tools_by_pattern(all_tools, pattern)

    return WorkerAgent(
        worker_name=name,
        worker_cfg=worker_cfg,
        scoped_tools=scoped_tools,
        cfg=cfg,
        external_apis=external_apis,
        session_manager=session_manager,
    )


def _collect_text(generator: Generator[str, None, None]) -> str:
    """
    Drain a token generator and return only the text content.
    Tool-call markers (*[Calling tool: …]* etc.) are discarded since we only
    need the natural-language RAG answer to provide as context.
    """
    parts = []
    for token in generator:
        if not (token.startswith("*[Calling tool:") or token.startswith("*[Tool result:")):
            parts.append(token)
    return "".join(parts).strip()


# ── Public entry point ────────────────────────────────────────────────────────

def run_orchestrated(
    user_message:    str,
    history:         list[dict],
    cfg:             dict,
    session_manager: SessionManager,
    external_apis:   dict,
    disabled_servers: list[str] | None = None,
) -> Generator[str, None, None]:
    """
    Full orchestration flow: route → (optional RAG prefetch) → worker(s) → response.

    Yields the same token strings as agent.loop.run():
      - "*[Orchestration trace: {...}]*\\n"  — routing decision (new marker type)
      - "*[Calling tool: <name>…]*\\n"        — tool invocation (from workers)
      - "*[Tool result: <json>]*\\n"          — tool result (from workers)
      - plain text chunks                    — final assistant response

    Args:
        user_message:    The raw user input string.
        history:         Prior conversation history (list of role/content dicts).
        cfg:             Full Desman config dict.
        session_manager: Active MCP SessionManager.
        external_apis:   External API keys dict.
        disabled_servers: Servers to exclude from tool lists (honoured per worker).
    """

    # ── Step 1: Route ─────────────────────────────────────────────────────────
    orchestrator = OrchestratorAgent(cfg, external_apis)

    yield "*[Agent phase: routing]*\n"
    try:
        routing = orchestrator.route(user_message)
    except OrchestratorError as exc:
        # Emit a fallback trace so the UI can show what happened
        fallback_trace = json.dumps({"fallback": True, "reason": str(exc)})
        yield f"*[Orchestration trace: {fallback_trace}]*\n"

        logger.warning(f"[ORCH] Orchestrator failed — falling back to direct mode. Reason: {exc}")

        # Fall back to direct mode using the default config model
        from .loop import run as direct_run
        yield from direct_run(
            user_message=user_message,
            history=history,
            model=cfg["agent"].get("default_model", ""),
            cfg=cfg,
            session_manager=session_manager,
            disabled_servers=disabled_servers,
            external_apis=external_apis,
        )
        return

    # ── Step 2: Emit trace ────────────────────────────────────────────────────
    yield f"*[Orchestration trace: {json.dumps(routing)}]*\n"

    delegate       = routing.get("delegate_to", "freshservice")
    rag_first      = routing.get("rag_first", False)
    worker_context = routing.get("context", "")

    # ── Step 3: Parse delegates ───────────────────────────────────────────────
    # "freshdesk+rag" → domain_delegates=["freshdesk"], rag_involved=True
    parts             = [p.strip() for p in delegate.split("+")]
    rag_involved      = "rag" in parts
    domain_delegates  = [p for p in parts if p != "rag"]

    # ── Step 4: RAG prefetch (if needed) ─────────────────────────────────────
    if (rag_first or rag_involved) and domain_delegates:
        yield "*[Agent phase: retrieving context]*\n"
        # Only collect RAG context when there are also domain workers to call.
        # If delegate is pure "rag", the RAG worker is called directly below.
        rag_worker = _build_worker("rag", cfg, external_apis, session_manager)
        if rag_worker:
            rag_context = _collect_text(rag_worker.run(task=user_message, history=[]))
            if rag_context:
                worker_context = f"{worker_context}\n\n{rag_context}".strip() if worker_context else rag_context

    # ── Step 5: Dispatch to worker(s) ─────────────────────────────────────────
    if not domain_delegates:
        # Pure RAG query — call RAG worker directly and stream its output
        rag_worker = _build_worker("rag", cfg, external_apis, session_manager)
        if rag_worker:
            yield from rag_worker.run(task=user_message, history=history, context=worker_context)
        else:
            yield "(RAG worker is not configured in agents.workers.rag — check config.local.yaml)\n"
        return

    for worker_name in domain_delegates:
        yield f"*[Agent phase: {worker_name}]*\n"
        worker = _build_worker(worker_name, cfg, external_apis, session_manager)
        if worker:
            yield from worker.run(
                task=user_message,
                history=history,
                context=worker_context,
            )
        else:
            yield (
                f"(Worker '{worker_name}' is not configured in agents.workers — "
                f"add it to config.local.yaml under agents.workers.{worker_name})\n"
            )
