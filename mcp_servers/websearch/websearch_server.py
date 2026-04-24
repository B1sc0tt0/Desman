# websearch_server.py
"""
Web search MCP server for Desman.

Uses the Perplexity Sonar API (search model) — requires a PERPLEXITY_API_KEY.
Set the key in mcp_servers/websearch/.env or via Settings → External APIs in the UI.
"""
import os

import httpx
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("Web Search Server")

_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
_MODEL = "sonar"


_MAX_CITATIONS = 8


@mcp.tool()
def search(query: str) -> dict:
    """Search the web using Perplexity Sonar. Returns a research summary and source URLs.

    Args:
        query: Search query string (e.g. "Clariant AG Swiss specialty chemicals recent news")

    Returns:
        dict with 'summary' (synthesized answer), 'citations' (source URLs),
        and 'results' list of {title, url, snippet} for downstream workers.
        Contains 'error' key if the search failed.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "").strip()
    if not api_key:
        return {
            "results": [],
            "error": (
                "PERPLEXITY_API_KEY is not set. "
                "Add it in Settings → External APIs or in mcp_servers/websearch/.env."
            ),
        }

    payload = {
        "model": _MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Return factual, structured research. Be specific and cite sources.",
            },
            {"role": "user", "content": query},
        ],
        "max_tokens": 2048,
        "return_citations": True,
        "search_recency_filter": "year",
    }

    try:
        resp = httpx.post(
            _PERPLEXITY_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        return {"results": [], "error": f"Perplexity API error {exc.response.status_code}: {exc.response.text[:200]}"}
    except Exception as exc:
        return {"results": [], "error": str(exc)}

    summary = ""
    choices = data.get("choices", [])
    if choices:
        summary = choices[0].get("message", {}).get("content", "")

    citations = data.get("citations", [])[:_MAX_CITATIONS]

    # Build results list: summary entry + individual citation URLs
    results = []
    if summary:
        results.append({"title": "Research Summary", "url": "", "snippet": summary})
    for url in citations:
        results.append({"title": "", "url": url, "snippet": ""})

    return {
        "summary": summary,
        "citations": citations,
        "results": results,
    }


# ── Start server ──────────────────────────────
if __name__ == '__main__':
    mcp.run(transport='stdio')
