"""
FastAPI backend for Desman.

Endpoints:
  GET  /                      — serve index.html
  GET  /api/models            — list available Ollama models
  GET  /api/mcp/status        — MCP server connection status
  GET  /api/config            — read config.local.yaml as text
  POST /api/config            — write config.local.yaml
  POST /api/chat              — SSE stream: chat + tool activity events
  POST /api/csv/preview       — parse CSV, return structured preview
  POST /api/csv/run           — SSE stream: execute CSV config plan via agent
  GET  /api/examples          — list available example CSV files
  GET  /api/examples/{name}   — download an example CSV file

Run from project root:
  python ui/app_fastapi.py
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import sys
import threading
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.config import (
    ConfigError,
    CONFIG_PATH,
    get_curated_models,
    get_mcp_server_configs,
    get_system_prompt,
    load_config,
)
from agent.mcp_client import SessionManager
from agent.ollama_client import filter_to_available, list_local_models

# ── App & globals ─────────────────────────────────────────────────────────────

_cfg: dict | None = None
_session_manager: SessionManager | None = None
_model_map: dict | None = None          # display_name → ollama_model
_mcp_status: dict[str, str] = {}        # server_name → "connected" | "error" | "disabled"

STATIC_DIR    = Path(__file__).parent / "static"
EXAMPLES_DIR  = Path(__file__).parent.parent / "examples"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _cfg, _session_manager, _model_map, _mcp_status

    try:
        _cfg = load_config()
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}")
        sys.exit(1)

    # Models
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
            f"Pull at least one: {', '.join(pulled)}"
        )
        sys.exit(1)

    _model_map = {m["display_name"]: m["ollama_model"] for m in available}

    # MCP servers
    mcp_configs = get_mcp_server_configs(_cfg)
    _session_manager = SessionManager()

    for srv in _cfg.get("mcp_servers", []):
        if srv.get("enabled", True):
            _mcp_status[srv["name"]] = "connecting"
        else:
            _mcp_status[srv["name"]] = "disabled"

    if mcp_configs:
        print("[MCP] Connecting to MCP servers...")
        try:
            _session_manager.start(mcp_configs)
            for srv in mcp_configs:
                _mcp_status[srv["name"]] = "connected"
        except Exception as e:
            print(f"[MCP] WARNING: {e}")
            for name, status in _mcp_status.items():
                if status == "connecting":
                    _mcp_status[name] = "error"
    else:
        print("[MCP] No MCP servers configured.")

    yield


app = FastAPI(title="Desman", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Static ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    html = STATIC_DIR / "index.html"
    if not html.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return html.read_text()


# ── Models ────────────────────────────────────────────────────────────────────

@app.get("/api/models")
async def api_models():
    """Returns available curated models plus any extra local Ollama models."""
    curated = [
        {"display_name": name, "ollama_model": model, "curated": True}
        for name, model in (_model_map or {}).items()
    ]
    # Also expose raw local models not in the curated list
    try:
        all_local = list_local_models(_cfg["ollama"]["base_url"])
        curated_models = {m["ollama_model"] for m in curated}
        extra = [
            {"display_name": m, "ollama_model": m, "curated": False}
            for m in all_local if m not in curated_models
        ]
    except Exception:
        extra = []

    default_model = _cfg["agent"].get("default_model", "")
    default_display = (curated[0]["display_name"] if curated else "")
    for entry in curated:
        if entry["ollama_model"] == default_model:
            default_display = entry["display_name"]
            break

    return {"models": curated + extra, "default": default_display}


# ── MCP status ────────────────────────────────────────────────────────────────

@app.get("/api/mcp/status")
async def api_mcp_status():
    servers = []
    for name, status in _mcp_status.items():
        tool_count = 0
        tools = []
        if _session_manager and _session_manager.registry:
            conn = _session_manager.registry.connections.get(name)
            if conn:
                tool_count = len(conn.tools)
                # Strip server prefix from tool names for display
                prefix = f"{name}_"
                tools = [
                    t['function']['name'][len(prefix):] if t['function']['name'].startswith(prefix) else t['function']['name']
                    for t in conn.tools
                ]
        servers.append({"name": name, "status": status, "tool_count": tool_count, "tools": tools})
    total_tools = sum(s["tool_count"] for s in servers)
    return {"servers": servers, "total_tools": total_tools}


# ── Config ────────────────────────────────────────────────────────────────────

@app.get("/api/config")
async def api_config_get():
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config.local.yaml not found")
    return JSONResponse({"yaml": CONFIG_PATH.read_text()})


class ConfigWriteBody(BaseModel):
    yaml: str


@app.post("/api/config")
async def api_config_post(body: ConfigWriteBody):
    import yaml
    try:
        yaml.safe_load(body.yaml)  # validate before writing
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")
    CONFIG_PATH.write_text(body.yaml)
    return {"ok": True}


# ── Chat (SSE) ────────────────────────────────────────────────────────────────

class ChatBody(BaseModel):
    message: str
    model: str          # display_name
    max_iterations: int | None = None  # override cfg default; used by CSV row processing
    history: list[dict] = []
    disabled_servers: list[str] = []


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _chat_generator(body: ChatBody) -> AsyncGenerator[str, None]:
    if not _model_map or body.model not in _model_map:
        yield _sse("error", {"message": f"Unknown model: {body.model}"})
        return

    ollama_model = _model_map[body.model]
    cfg = _cfg
    if body.max_iterations is not None:
        import copy
        cfg = copy.deepcopy(_cfg)
        cfg["agent"]["max_iterations"] = body.max_iterations
    sm = _session_manager

    # Run blocking agent loop in a thread, bridge via asyncio queue
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def run_in_thread():
        from agent.loop import run as agent_run
        try:
            for token in agent_run(body.message, body.history, ollama_model, cfg, sm, body.disabled_servers):
                asyncio.run_coroutine_threadsafe(queue.put(token), loop).result()
        except Exception as e:
            asyncio.run_coroutine_threadsafe(
                queue.put(json.dumps({"__error__": str(e)})), loop
            ).result()
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop).result()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    tool_buffer = ""
    text_buffer = ""

    while True:
        token = await queue.get()
        if token is None:
            break

        # Detect tool-call marker emitted by agent loop
        # Format: *[Calling tool: <name>...]*\n
        if token.startswith("*[Calling tool:"):
            # Flush any pending text first
            if text_buffer:
                yield _sse("text", {"chunk": text_buffer})
                text_buffer = ""
            tool_name = re.sub(r"^\*\[Calling tool: (.+?)\.\.\.\]\*.*$", r"\1", token.strip())
            yield _sse("tool_call", {"tool": tool_name, "status": "calling"})
        elif token.startswith("*[Tool result:"):
            # Format: *[Tool result: <raw_result>]*\n
            raw = re.sub(r"^\*\[Tool result: (.*)\]\*\s*$", r"\1", token.strip(), flags=re.DOTALL)
            if text_buffer:
                yield _sse("text", {"chunk": text_buffer})
                text_buffer = ""
            yield _sse("tool_result", {"result": raw})
        else:
            # Check for embedded error
            try:
                parsed = json.loads(token)
                if "__error__" in parsed:
                    yield _sse("error", {"message": parsed["__error__"]})
                    continue
            except (json.JSONDecodeError, TypeError):
                pass
            text_buffer += token
            # Stream text chunks as they accumulate
            if len(text_buffer) >= 4 or "\n" in text_buffer:
                yield _sse("text", {"chunk": text_buffer})
                text_buffer = ""

    if text_buffer:
        yield _sse("text", {"chunk": text_buffer})

    yield _sse("done", {})


@app.post("/api/chat")
async def api_chat(body: ChatBody):
    return StreamingResponse(
        _chat_generator(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Example CSV files ─────────────────────────────────────────────────────────

@app.get("/api/examples")
async def api_examples():
    """Lists available example CSV files from the examples/ directory."""
    if not EXAMPLES_DIR.exists():
        return {"files": []}
    files = sorted(p.name for p in EXAMPLES_DIR.glob("*.csv"))
    return {"files": files}


@app.get("/api/examples/{filename}")
async def api_example_file(filename: str):
    """Returns the content of a named example CSV file."""
    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = EXAMPLES_DIR / filename
    if not path.exists() or path.suffix.lower() != ".csv":
        raise HTTPException(status_code=404, detail=f"Example '{filename}' not found")
    from fastapi.responses import Response
    return Response(
        content=path.read_bytes(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── CSV preview ───────────────────────────────────────────────────────────────

@app.post("/api/csv/preview")
async def api_csv_preview(file: UploadFile):
    content = await file.read()
    try:
        text = content.decode("utf-8-sig")  # strip BOM if present
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for i, row in enumerate(reader):
        if i >= 200:  # cap preview
            break
        rows.append(dict(row))

    if not rows:
        raise HTTPException(status_code=400, detail="CSV is empty or has no data rows")

    return {
        "columns": list(rows[0].keys()),
        "rows": rows,
        "total_rows": len(rows),
        "filename": file.filename,
    }


# ── CSV run (SSE) ─────────────────────────────────────────────────────────────

class CSVRunBody(BaseModel):
    rows: list[dict]
    columns: list[str]
    model: str
    filename: str = ""
    disabled_servers: list[str] = []
    # "freshdesk_tickets" | "freshservice_assets"
    import_type: str = "freshdesk_tickets"


# Number of consecutive rows with no tool call before halting as model drift
_DRIFT_THRESHOLD = 3


def _build_row_prompt(import_type: str, row: dict, row_num: int, total: int) -> str:
    data_str = json.dumps(row, ensure_ascii=False, indent=2)
    if import_type == "freshdesk_tickets":
        return (
            f"You are importing row {row_num} of {total} into Freshdesk.\n"
            f"Call create_ticket ONCE using EXACTLY the field values provided below.\n"
            f"Rules:\n"
            f"- Do NOT translate, rename, or modify any values.\n"
            f"- Do NOT call get_ticket, list_tickets, or any other tool.\n"
            f"- Stop immediately after create_ticket responds — do not verify or follow up.\n\n"
            f"{data_str}"
        )
    elif import_type == "freshservice_assets":
        return (
            f"You are importing row {row_num} of {total} into Freshservice.\n"
            f"Call create_asset ONCE using EXACTLY the field values provided below.\n"
            f"Rules:\n"
            f"- Do NOT translate, rename, or modify any values.\n"
            f"- Do NOT call list_assets, get_asset, or any other tool.\n"
            f"- Stop immediately after create_asset responds — do not verify or follow up.\n\n"
            f"{data_str}"
        )
    return data_str


async def _csv_bulk_generator(body: CSVRunBody) -> AsyncGenerator[str, None]:
    """
    Row-by-row agent processing with drift detection.

    Drift = the model stops invoking tools and produces only text instead.
    Common in weaker models (e.g. Llama 3.2 3B) after a few rows as the
    instruction-following degrades. We halt early rather than burning through
    all rows with zero results.

    SSE events emitted (in addition to the normal text/tool_call/error stream):
      row_start   {row, total}
      row_done    {row, total, success, consecutive_failures}
      drift_warning  {row, consecutive_failures, message}   — terminal on drift
      bulk_done   {total, success_count, failed_count}      — terminal on clean finish
    """
    if not _model_map or body.model not in _model_map:
        yield _sse("error", {"message": f"Unknown model: {body.model}"})
        return

    total = len(body.rows)
    consecutive_failures = 0
    success_count = 0
    failed_count = 0

    # Auto-disable the irrelevant MCP server for the entire run
    auto_disabled = list(body.disabled_servers)
    if body.import_type == "freshdesk_tickets" and "freshservice" not in auto_disabled:
        auto_disabled.append("freshservice")
    elif body.import_type == "freshservice_assets" and "freshdesk" not in auto_disabled:
        auto_disabled.append("freshdesk")

    peak_consecutive_failures = 0
    first_drift_row: int | None = None

    for i, row in enumerate(body.rows):
        row_num = i + 1
        yield _sse("row_start", {"row": row_num, "total": total})

        prompt = _build_row_prompt(body.import_type, row, row_num, total)
        chat_body = ChatBody(
            message=prompt,
            model=body.model,
            history=[],
            disabled_servers=auto_disabled,
            max_iterations=3,
        )

        tool_called = False
        tool_error = False
        async for chunk in _chat_generator(chat_body):
            if chunk.startswith("event: tool_call\n"):
                tool_called = True
            # Detect tool failures via the actual tool result (not model prose)
            if chunk.startswith("event: tool_result\n"):
                try:
                    # SSE format: "event: ...\ndata: {...}\n\n"
                    data_line = chunk.split("\n", 2)[1].removeprefix("data: ")
                    data = json.loads(data_line)
                    result_raw = data.get("result", "")
                    result_obj = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
                    if isinstance(result_obj, dict) and result_obj.get("success") is False:
                        tool_error = True
                except Exception:
                    if '"success": false' in chunk.lower():
                        tool_error = True
            yield chunk

        # A row counts as successful only if a tool was called AND it didn't error
        row_success = tool_called and not tool_error

        if row_success:
            consecutive_failures = 0
            success_count += 1
        else:
            consecutive_failures += 1
            failed_count += 1
            if consecutive_failures > peak_consecutive_failures:
                peak_consecutive_failures = consecutive_failures
            if consecutive_failures == _DRIFT_THRESHOLD:
                first_drift_row = row_num

        yield _sse("row_done", {
            "row": row_num,
            "total": total,
            "success": row_success,
            "tool_called": tool_called,
            "tool_error": tool_error,
            "consecutive_failures": consecutive_failures,
        })

        # Emit a drift notice each time the streak crosses a new multiple of the
        # threshold — gives progressive visibility without flooding the stream
        if consecutive_failures > 0 and consecutive_failures % _DRIFT_THRESHOLD == 0:
            yield _sse("drift_warning", {
                "row": row_num,
                "consecutive_failures": consecutive_failures,
                "success_count": success_count,
                "failed_count": failed_count,
            })

    yield _sse("bulk_done", {
        "total": total,
        "success_count": success_count,
        "failed_count": failed_count,
        "peak_consecutive_failures": peak_consecutive_failures,
        "first_drift_row": first_drift_row,
        "drift_detected": first_drift_row is not None,
    })


async def _csv_run_generator(body: CSVRunBody) -> AsyncGenerator[str, None]:
    if not _model_map or body.model not in _model_map:
        yield _sse("error", {"message": f"Unknown model: {body.model}"})
        return

    async for chunk in _csv_bulk_generator(body):
        yield chunk


@app.post("/api/csv/run")
async def api_csv_run(body: CSVRunBody):
    return StreamingResponse(
        _csv_run_generator(body),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=7860,
        reload=False,
        log_level="warning",
    )
