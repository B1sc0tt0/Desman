"""
Gradio UI entrypoint — compatible with Gradio 6.x.
SessionManager is held as a module-level global (not gr.State) because
Gradio 6 deepcopies all State values, which breaks async objects.
Run from project root: python ui/app.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import gradio as gr

from agent.config import load_config, ConfigError, get_curated_models, get_mcp_server_configs
from agent.ollama_client import filter_to_available
from agent.mcp_client import SessionManager
from agent.loop import run

# Module-level globals — initialised once, never copied by Gradio
_session_manager: SessionManager | None = None
_cfg: dict | None = None
_model_map: dict | None = None


def build_app() -> gr.Blocks:
    global _session_manager, _cfg, _model_map

    # ── Config ────────────────────────────────────────────────────────────────
    try:
        _cfg = load_config()
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)

    # ── Models ────────────────────────────────────────────────────────────────
    curated = get_curated_models(_cfg)
    try:
        available = filter_to_available(curated, _cfg["ollama"]["base_url"])
    except RuntimeError as e:
        print(f"[OLLAMA ERROR] {e}")
        sys.exit(1)

    if not available:
        pulled = [m["ollama_model"] for m in curated]
        print(
            "[ERROR] None of the configured models are available locally.\n"
            f"Pull at least one: {', '.join(pulled)}\n"
            f"Example: ollama pull {pulled[0]}"
        )
        sys.exit(1)

    _model_map = {m["display_name"]: m["ollama_model"] for m in available}
    display_names = list(_model_map.keys())

    configured_default = _cfg["agent"].get("default_model")
    default_display = display_names[0]
    for entry in available:
        if entry["ollama_model"] == configured_default:
            default_display = entry["display_name"]
            break

    # ── MCP servers ───────────────────────────────────────────────────────────
    mcp_configs = get_mcp_server_configs(_cfg)
    _session_manager = SessionManager()
    if mcp_configs:
        print("[MCP] Connecting to MCP servers...")
        try:
            _session_manager.start(mcp_configs)
        except Exception as e:
            print(f"[MCP] WARNING: {e}")
            print("[MCP] Continuing without tool support.")
    else:
        print("[MCP] No MCP servers configured. Running in plain chat mode.")

    # ── UI ────────────────────────────────────────────────────────────────────
    with gr.Blocks(title="Desman") as app:
        gr.Markdown("## Desman")

        with gr.Row():
            model_picker = gr.Dropdown(
                choices=display_names,
                value=default_display,
                label="Model",
                scale=1,
                interactive=True,
            )

        # Gradio 6: use type="messages" with dict format {"role": ..., "content": ...}
        chatbot = gr.Chatbot(height=500)

        with gr.Row():
            user_input = gr.Textbox(
                placeholder="Type your message and press Enter...",
                show_label=False,
                scale=8,
            )
            send_btn = gr.Button("Send", variant="primary", scale=1)

        def respond(message: str, history: list, display_name: str):
            if not message.strip():
                yield "", history
                return

            ollama_model = _model_map[display_name]
            history = history or []

            # Gradio 6 messages format: list of {"role": "user"|"assistant", "content": str}
            history = history + [
                {"role": "user", "content": message},
                {"role": "assistant", "content": ""},
            ]

            # Build loop history from all but the last assistant placeholder
            # Gradio 6 stores content as list of blocks [{'text': '...', 'type': 'text'}]
            # Ollama requires content as plain string — extract text here
            def extract_content(msg: dict) -> str:
                c = msg.get("content", "")
                if isinstance(c, list):
                    return " ".join(block.get("text", "") for block in c if isinstance(block, dict))
                return str(c) if c else ""

            loop_history = [
                {"role": msg["role"], "content": extract_content(msg)}
                for msg in history[:-2]
            ]

            full = ""
            for token in run(message, loop_history, ollama_model, _cfg, _session_manager):
                full += token
                history[-1]["content"] = full
                yield "", history

        send_btn.click(
            respond,
            inputs=[user_input, chatbot, model_picker],
            outputs=[user_input, chatbot],
        )
        user_input.submit(
            respond,
            inputs=[user_input, chatbot, model_picker],
            outputs=[user_input, chatbot],
        )

    return app


if __name__ == "__main__":
    app = build_app()
    app.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
    )
