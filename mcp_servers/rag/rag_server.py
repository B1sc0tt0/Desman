# rag_server.py
"""
Local RAG MCP server for Desman.

Provides semantic document retrieval backed by ChromaDB (embedded, disk-persistent)
with embeddings generated via Ollama — no cloud dependency, works on Pi 5 / M1.

Workflow:
  1. ingest_document()  — chunk + embed + store a file
  2. query()            — semantic search, returns top-k chunks
  3. list_collections() / list_documents() — inspect what is stored
  4. delete_document()  / delete_collection() — cleanup

The agent calls these like any other MCP tool.  The typical pattern before
acting on a customer profile is:
  query("customer name email company") → extract facts → call Freshdesk/Freshservice tools
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import chromadb
import ollama as _ollama
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("RAG Server")

# ── Configuration ────────────────────────────────────────────────────────────
_HERE = Path(__file__).parent
CHROMA_DIR  = os.getenv("RAG_CHROMA_DIR",  str(_HERE / "chroma_db"))
EMBED_MODEL = os.getenv("RAG_EMBED_MODEL", "nomic-embed-text")
CHUNK_SIZE  = int(os.getenv("RAG_CHUNK_SIZE",    "800"))
CHUNK_OVERLAP = int(os.getenv("RAG_CHUNK_OVERLAP", "100"))
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

# ── Chroma client (lazy, module-level singleton) ──────────────────────────────
_chroma: chromadb.PersistentClient | None = None


def _get_chroma() -> chromadb.PersistentClient:
    global _chroma
    if _chroma is None:
        Path(CHROMA_DIR).mkdir(parents=True, exist_ok=True)
        _chroma = chromadb.PersistentClient(
            path=CHROMA_DIR,
            settings=chromadb.Settings(anonymized_telemetry=False),
        )
    return _chroma


# ── Helpers ───────────────────────────────────────────────────────────────────

def _embed(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts via Ollama."""
    client = _ollama.Client(host=OLLAMA_HOST)
    embeddings = []
    for text in texts:
        resp = client.embeddings(model=EMBED_MODEL, prompt=text)
        embeddings.append(resp["embedding"])
    return embeddings


def _chunk_text(text: str) -> list[str]:
    """
    Paragraph-aware chunker.  Splits on blank lines first, then enforces
    CHUNK_SIZE with CHUNK_OVERLAP to avoid breaking mid-sentence.
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 <= CHUNK_SIZE:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            # Paragraph itself may exceed CHUNK_SIZE — hard-split with overlap
            while len(para) > CHUNK_SIZE:
                chunks.append(para[:CHUNK_SIZE])
                para = para[max(0, CHUNK_SIZE - CHUNK_OVERLAP):]
            current = para

    if current:
        chunks.append(current)

    return chunks or [text]   # always return at least one chunk


def _read_file(file_path: str) -> str:
    """Parse a document into plain text.  Supports PDF, DOCX, TXT, MD."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
            if not text.strip():
                raise RuntimeError(
                    f"No text could be extracted from '{path.name}'. "
                    "This is likely a scanned or image-based PDF. "
                    "Run OCR first (e.g. 'ocrmypdf input.pdf output.pdf') then re-upload."
                )
            return text
        except ImportError:
            raise RuntimeError(
                "pypdf is required for PDF ingestion.\n"
                "Install it: pip install pypdf"
            )

    if suffix == ".docx":
        try:
            from docx import Document
            doc = Document(str(path))
            return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError(
                "python-docx is required for DOCX ingestion.\n"
                "Install it: pip install python-docx"
            )

    # Plain text / Markdown / anything else
    return path.read_text(encoding="utf-8")


def _delete_doc_chunks(col: chromadb.Collection, doc_id: str) -> int:
    """Remove all existing chunks for doc_id from the collection. Returns count removed."""
    existing = col.get(where={"doc_id": {"$eq": doc_id}}, include=["metadatas"])
    ids = existing.get("ids", [])
    if ids:
        col.delete(ids=ids)
    return len(ids)


# ════════════════════════════════════════════════
#  TOOLS
# ════════════════════════════════════════════════

@mcp.tool()
def ingest_document(
    file_path: str,
    collection: str,
    doc_id: str | None = None,
) -> dict:
    """Ingest a document into the RAG knowledge base.

    Reads the file, splits it into chunks, generates embeddings via Ollama,
    and stores everything in ChromaDB.  Calling this again with the same
    doc_id replaces the previous version.

    Args:
        file_path: Absolute (or cwd-relative) path to the file.
                   Supported formats: PDF, DOCX, TXT, MD.
        collection: Logical bucket to store this document in.
                    Examples: "customers", "policies", "onboarding".
        doc_id: Stable identifier for this document.
                Defaults to the filename stem (e.g. "acme_profile").
                Re-use the same doc_id to update an existing document.
    """
    path = Path(file_path)
    if doc_id is None:
        doc_id = path.stem

    try:
        raw_text = _read_file(file_path)
    except (FileNotFoundError, RuntimeError) as exc:
        return {"success": False, "error": str(exc)}

    if not raw_text.strip():
        return {"success": False, "error": f"No text content found in '{path.name}'. The file may be empty."}

    chunks = _chunk_text(raw_text)
    try:
        embeddings = _embed(chunks)
    except Exception as exc:
        return {
            "success": False,
            "error": f"Embedding failed (is '{EMBED_MODEL}' pulled in Ollama?): {exc}",
        }

    db = _get_chroma()
    col = db.get_or_create_collection(collection)

    # Replace existing chunks for this doc_id
    removed = _delete_doc_chunks(col, doc_id)

    ids       = [f"{doc_id}__chunk_{i}" for i in range(len(chunks))]
    metadatas = [{"doc_id": doc_id, "chunk_index": i, "source": str(path)} for i in range(len(chunks))]

    col.add(ids=ids, documents=chunks, embeddings=embeddings, metadatas=metadatas)

    return {
        "success": True,
        "doc_id": doc_id,
        "collection": collection,
        "chunks_stored": len(chunks),
        "chunks_replaced": removed,
    }


@mcp.tool()
def query(
    query: str,
    collection: str,
    top_k: int = 3,
) -> dict:
    """Semantic search over a RAG collection.

    IMPORTANT: Call list_collections() first to confirm the collection name
    before calling this tool. Never guess a collection name.

    Embeds the query via Ollama and returns the most relevant document chunks.
    Use the returned text as context before calling action tools.

    Args:
        query: Natural-language question or keyword phrase.
        collection: Collection to search — must be an exact name from list_collections().
        top_k: Number of chunks to return (default 3; use 1 for short profiles).
    """
    query_text = query
    # Coerce top_k in case the model passes it as a string
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 3

    db = _get_chroma()
    try:
        col = db.get_collection(collection)
    except Exception:
        # Surface available collections so the model can self-correct
        try:
            available = [c.name for c in db.list_collections()]
        except Exception:
            available = []
        hint = f" Available collections: {available}" if available else " No collections exist yet — ingest a document first."
        return {"success": False, "error": f"Collection '{collection}' not found.{hint}"}

    chunk_count = col.count()
    if chunk_count == 0:
        return {"success": False, "error": f"Collection '{collection}' is empty. Ingest a document first."}

    try:
        q_embedding = _embed([query_text])[0]
    except Exception as exc:
        return {"success": False, "error": f"Embedding failed: {exc}"}

    n = max(1, min(top_k, chunk_count))
    try:
        results = col.query(
            query_embeddings=[q_embedding],
            n_results=n,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        return {"success": False, "error": f"Query failed: {exc}"}

    hits = []
    for i, doc in enumerate(results["documents"][0]):
        hits.append({
            "rank": i + 1,
            "doc_id":      results["metadatas"][0][i].get("doc_id"),
            "source":      results["metadatas"][0][i].get("source"),
            "chunk_index": results["metadatas"][0][i].get("chunk_index"),
            "distance":    round(results["distances"][0][i], 4),
            "text":        doc,
        })

    return {"success": True, "collection": collection, "results": hits}


@mcp.tool()
def list_collections() -> dict:
    """List all RAG collections and their document counts.

    Returns every collection that has been created via ingest_document,
    with the number of chunks stored in each.
    """
    db = _get_chroma()
    cols = db.list_collections()
    return {
        "success": True,
        "collections": [
            {"name": c.name, "chunk_count": c.count()}
            for c in cols
        ],
    }


@mcp.tool()
def list_documents(collection: str) -> dict:
    """List all documents stored in a collection.

    Returns each unique doc_id along with its source file path and
    how many chunks it was split into.

    Args:
        collection: Collection name to inspect.
    """
    db = _get_chroma()
    try:
        col = db.get_collection(collection)
    except Exception:
        return {"success": False, "error": f"Collection '{collection}' not found."}

    all_meta = col.get(include=["metadatas"])["metadatas"]

    docs: dict[str, dict] = {}
    for m in all_meta:
        did = m.get("doc_id", "unknown")
        if did not in docs:
            docs[did] = {"doc_id": did, "source": m.get("source", ""), "chunk_count": 0}
        docs[did]["chunk_count"] += 1

    return {
        "success": True,
        "collection": collection,
        "documents": list(docs.values()),
    }


@mcp.tool()
def delete_document(collection: str, doc_id: str) -> dict:
    """Remove a single document (all its chunks) from a collection.

    Args:
        collection: Collection the document lives in.
        doc_id: Identifier of the document to remove.
    """
    db = _get_chroma()
    try:
        col = db.get_collection(collection)
    except Exception:
        return {"success": False, "error": f"Collection '{collection}' not found."}

    removed = _delete_doc_chunks(col, doc_id)
    if removed == 0:
        return {"success": False, "error": f"No chunks found for doc_id '{doc_id}' in '{collection}'."}

    return {"success": True, "collection": collection, "doc_id": doc_id, "chunks_removed": removed}


@mcp.tool()
def delete_collection(collection: str) -> dict:
    """Delete an entire RAG collection and all documents within it.

    This is irreversible — all stored embeddings and text are removed.

    Args:
        collection: Name of the collection to delete.
    """
    db = _get_chroma()
    try:
        db.delete_collection(collection)
    except Exception as exc:
        return {"success": False, "error": str(exc)}

    return {"success": True, "collection": collection, "message": "Collection deleted."}


if __name__ == "__main__":
    mcp.run()
