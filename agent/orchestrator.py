"""
OrchestratorAgent — analyses the user request and produces a JSON routing decision.

The orchestrator's single responsibility is intent classification and routing.
It NEVER calls MCP tools directly. Its sole output is a structured JSON object
that tells the orchestration runner which worker agent(s) to invoke.

Routing schema:
    {
        "intent":      "<one-sentence restatement of the user task>",
        "delegate_to": "freshdesk | freshservice | rag | freshdesk+rag | freshservice+rag",
        "rag_first":   true | false,
        "context":     "<any additional context or clarification for the worker>"
    }

On parse failure the caller (orchestration.py) catches OrchestratorError and
falls back to direct mode automatically. The orchestrator never crashes the app.

Configuration (in config.local.yaml under agents.orchestrator):
    provider:    ollama | anthropic | openai | huggingface
    model:       model identifier (e.g. "meta-llama/Llama-3.3-70B-Instruct")
    temperature: float (default 0.1 — low temperature for deterministic routing)
    role:        optional free-text description prepended to the system prompt
"""
from __future__ import annotations

import json
import logging
import re

from .providers import chat as provider_chat

logger = logging.getLogger(__name__)

# ── Routing schema ────────────────────────────────────────────────────────────

_ROUTING_SCHEMA: dict[str, type] = {
    "intent":      str,
    "delegate_to": str,
    "rag_first":   bool,
    "context":     str,
}

_VALID_DELEGATES = frozenset({
    "freshdesk",
    "freshservice",
    "rag",
    "freshdesk+rag",
    "freshservice+rag",
})

# ── System prompt ─────────────────────────────────────────────────────────────

_ROUTING_INSTRUCTIONS = """
You are an intent router for an IT support agent. Your only job is to analyse
the user's request and output a JSON routing decision.

You MUST respond with ONLY valid JSON matching this exact schema.
No explanation. No prose. No markdown fences. Just the JSON object:

{
  "intent":      "<one-sentence restatement of the user task>",
  "delegate_to": "<one of: freshdesk | freshservice | rag | freshdesk+rag | freshservice+rag>",
  "rag_first":   <true or false>,
  "context":     "<additional context or clarification for the worker, or empty string>"
}

Routing rules:
  freshdesk           → customer support tickets, contacts, knowledge base articles, portal, groups
  freshservice        → internal IT tickets, assets, changes, problems, service requests, onboarding/offboarding
  rag                 → policy lookup, SLA retrieval, procedure docs — no live data needed
  freshdesk+rag       → customer support that needs both live ticket data AND internal policies/KB
  freshservice+rag    → IT request that needs both live ITSM data AND policy/SLA/procedure context
  rag_first: true     → the knowledge base must be checked BEFORE querying live data
  rag_first: false    → live data is self-sufficient, or RAG is not involved

Output ONLY the JSON object. Nothing else.
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_model_string(provider: str, model: str) -> str:
    """Return the model_string expected by providers.chat()."""
    return model if provider == "ollama" else f"{provider}:{model}"


def _extract_json(text: str) -> dict | None:
    """
    Attempt to extract a JSON object from the model's text output.

    Handles:
      - Clean JSON output
      - Markdown code-fenced JSON (```json ... ```)
      - Reasoning-model <think>...</think> wrappers
      - JSON embedded inside prose (first JSON object found)
    """
    text = text.strip()
    # Strip <think>...</think> blocks (qwen3, o1-style reasoning models)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # Strip optional markdown fences
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()

    # Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Search for the first embedded JSON object
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _validate_routing(obj: dict) -> bool:
    """Return True only if the routing decision has all required keys and valid values."""
    for key, expected_type in _ROUTING_SCHEMA.items():
        if key not in obj:
            logger.debug(f"[ORCH] Missing key in routing: '{key}'")
            return False
        if not isinstance(obj[key], expected_type):
            logger.debug(f"[ORCH] Wrong type for '{key}': expected {expected_type}, got {type(obj[key])}")
            return False
    if obj["delegate_to"] not in _VALID_DELEGATES:
        logger.debug(f"[ORCH] Unknown delegate_to value: '{obj['delegate_to']}'")
        return False
    return True


# ── OrchestratorAgent ─────────────────────────────────────────────────────────

class OrchestratorAgent:
    """
    Routes a user request to the appropriate worker agent(s).

    Uses the provider and model defined under agents.orchestrator in config.
    Produces a routing decision dict. Raises OrchestratorError if the model
    output cannot be parsed or validated — the caller should catch this and
    fall back to direct mode.

    The orchestrator is intentionally stateless: each call to route() is
    independent and creates no history between requests.
    """

    def __init__(self, cfg: dict, external_apis: dict):
        """
        Args:
            cfg:           Full Desman config dict (from load_config()).
            external_apis: External API keys dict (from load_external_apis()).
        """
        self._cfg = cfg
        self._ext = external_apis

        orch = cfg.get("agents", {}).get("orchestrator", {})
        self._provider    = orch.get("provider", "ollama")
        self._model       = orch.get("model", cfg["agent"].get("default_model", ""))
        self._temperature = float(orch.get("temperature", 0.1))
        self._role        = orch.get("role", "")

    def route(self, user_message: str) -> dict:
        """
        Analyse the user message and return a routing decision dict.

        Returns:
            dict with keys: intent, delegate_to, rag_first, context

        Raises:
            OrchestratorError: If the LLM output cannot be parsed or fails schema validation.
        """
        system_prompt = _ROUTING_INSTRUCTIONS
        if self._role:
            system_prompt = f"{self._role}\n\n{_ROUTING_INSTRUCTIONS}"

        model_string = _build_model_string(self._provider, self._model)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": str(user_message)},
        ]

        try:
            result = provider_chat(
                model_string=model_string,
                messages=messages,
                tools=[],                   # orchestrator never uses tools
                temperature=self._temperature,
                cfg=self._cfg,
                external_apis=self._ext,
            )
        except Exception as e:
            raise OrchestratorError(f"Provider call failed: {e}") from e

        raw = result.text.strip()

        if not raw:
            raise OrchestratorError("Orchestrator returned an empty response.")

        obj = _extract_json(raw)
        if obj is None:
            raise OrchestratorError(
                f"Orchestrator output is not valid JSON.\nRaw: {raw[:300]}"
            )
        if not _validate_routing(obj):
            raise OrchestratorError(
                f"Orchestrator routing schema is invalid.\nParsed: {obj}"
            )

        logger.info(f"[ORCH] Routing decision: {obj}")
        return obj


class OrchestratorError(Exception):
    """Raised when the orchestrator cannot produce a valid routing decision."""
    pass
