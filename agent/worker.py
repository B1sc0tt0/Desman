"""
WorkerAgent — executes a delegated task using a domain-scoped tool set.

Each worker is responsible for one domain:
  - freshdesk:    customer support (freshdesk_* tools only)
  - freshservice: internal IT / ITSM (freshservice_* tools only)
  - rag:          knowledge base retrieval (rag_* tools only, no hallucination)

Workers receive a role-specific system prompt built from the config role string.
They run the existing agent loop, reusing all provider and tool-call logic,
but restricted to their scoped tool list so they cannot accidentally cross domains.

Workers are designed to be composed by the orchestration runner — they are not
called directly from the HTTP layer.
"""
from __future__ import annotations

from typing import Generator

from .loop import run as agent_loop_run


def _build_model_string(provider: str, model: str) -> str:
    """Return the model_string expected by providers.chat()."""
    return model if provider == "ollama" else f"{provider}:{model}"


class WorkerAgent:
    """
    Executes a tool-using task for a specific domain (Freshdesk, Freshservice, RAG).

    Takes a worker config block from config.yaml (under agents.workers.<name>)
    and the pre-filtered, domain-scoped tool list. Internally it runs the
    existing agent loop — all provider routing, tool call handling, retry logic,
    and streaming is reused unchanged.

    Produces the same token stream as direct mode (text chunks, *[Calling tool:…]*,
    *[Tool result:…]*) so the HTTP layer does not need to handle it differently.
    """

    def __init__(
        self,
        worker_name:    str,
        worker_cfg:     dict,
        scoped_tools:   list[dict],
        cfg:            dict,
        external_apis:  dict,
        session_manager,
    ):
        """
        Args:
            worker_name:    Identifier (e.g. "freshdesk", "freshservice", "rag").
            worker_cfg:     Worker config block from config.yaml agents.workers.<name>.
            scoped_tools:   Pre-filtered tool list — only this worker's domain.
            cfg:            Full Desman config dict.
            external_apis:  External API keys dict.
            session_manager: Active MCP SessionManager (used for tool dispatch).
        """
        self.name         = worker_name
        self._provider    = worker_cfg.get("provider", "ollama")
        self._model       = worker_cfg.get("model", cfg["agent"].get("default_model", ""))
        self._temperature = float(worker_cfg.get("temperature", cfg["agent"].get("temperature", 0.3)))
        self._role        = worker_cfg.get("role", "")
        self._tools       = scoped_tools
        self._cfg         = cfg
        self._ext         = external_apis
        self._sm          = session_manager

    @property
    def model_string(self) -> str:
        """Provider-prefixed model string for use with providers.chat()."""
        return _build_model_string(self._provider, self._model)

    def run(
        self,
        task:    str,
        history: list[dict] | None = None,
        context: str = "",
    ) -> Generator[str, None, None]:
        """
        Execute the delegated task and yield response tokens.

        Args:
            task:    The delegated task description from the orchestrator.
            history: Conversation history. Typically empty for worker calls
                     (the orchestrator provides intent restatement instead).
            context: Additional context to prepend — typically RAG output
                     collected before the worker was invoked.

        Yields:
            str tokens identical to agent.loop.run() output:
            text chunks, *[Calling tool: …]* markers, *[Tool result: …]* markers.
        """
        user_message = task
        if context:
            user_message = (
                f"Relevant context from the knowledge base:\n{context}\n\n"
                f"Task:\n{task}"
            )

        system_prompt = self._role if self._role else (
            "You are a helpful assistant. Use the available tools to complete the task."
        )

        yield from agent_loop_run(
            user_message=user_message,
            history=history or [],
            model=self.model_string,
            cfg=self._cfg,
            session_manager=self._sm,
            disabled_servers=None,          # workers use tools_override instead
            external_apis=self._ext,
            system_prompt=system_prompt,    # role-specific prompt from config
            tools_override=self._tools,     # pre-filtered, domain-scoped tool set
        )
