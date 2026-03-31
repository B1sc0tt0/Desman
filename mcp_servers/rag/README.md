# RAG MCP Server

Local knowledge base for Desman. Upload documents and query them semantically — no cloud dependency, runs entirely on-device.

Uses **ChromaDB** (embedded, disk-persistent) for vector storage and **Ollama** for embeddings (`nomic-embed-text` by default).

## Enabling RAG

The RAG server is **disabled by default** to avoid loading the Ollama embedding model when it is not needed (especially relevant when running smaller local models that are already under memory pressure).

To enable it, set `enabled: true` in `config.local.yaml`:

```yaml
mcp_servers:
  - name: "rag"
    folder: "rag"
    script: "rag_server.py"
    enabled: true  # change from false to true
```

Restart Desman after editing the config.

## Setup

```bash
# Install RAG dependencies
uv pip install -e ".[rag]"

# Pull the embedding model (one-time, ~270 MB)
ollama pull nomic-embed-text
```

No `.env` file needed — all settings are optional environment variables (see Configuration below).

## Available tools (6)

| Tool | Description |
|---|---|
| `ingest_document` | Chunk, embed, and store a file (PDF, DOCX, TXT, MD) |
| `query` | Semantic search — returns top-k most relevant chunks |
| `list_collections` | List all collections and their document counts |
| `list_documents` | List documents stored in a collection |
| `delete_document` | Remove a document (all its chunks) from a collection |
| `delete_collection` | Delete an entire collection |

## Typical workflow

1. Upload a document via the **RAG** panel in the Desman UI (or call `ingest_document` directly)
2. Ask the agent a question — it will call `list_collections`, then `query` on the relevant collection
3. The agent uses the retrieved chunks as context before calling action tools

## Configuration

Set these in `mcp_servers/rag/.env` or as environment variables:

| Variable | Default | Description |
|---|---|---|
| `RAG_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `RAG_CHROMA_DIR` | `mcp_servers/rag/chroma_db` | Where ChromaDB persists data |
| `RAG_CHUNK_SIZE` | `800` | Characters per chunk |
| `RAG_CHUNK_OVERLAP` | `100` | Overlap between consecutive chunks |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |

## Model guidance

- **3B models** — unreliable for RAG. The two-step chain (`list_collections` → `query`) requires two sequential tool calls; 3B models often skip the first step or describe the call as prose instead of invoking it.
- **7B–8B models** — recommended minimum for RAG workflows. `llama3.1:8b` and `qwen2.5:7b` handle the sequential chain reliably.
- **Cloud models** — work well; tool-call fidelity is high across all providers.
