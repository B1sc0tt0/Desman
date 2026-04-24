# websearch_server.py
"""
Web search MCP server for Desman.

Uses DuckDuckGo Search — no API key required.

Use this tool to research companies, industries, and prospects
before a demo or discovery call.
"""
import time

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("Web Search Server")


@mcp.tool()
def search(query: str, max_results: int = 5) -> dict:
    """Use this tool to research companies, industries, and prospects before a demo or
    discovery call. Searches the web using DuckDuckGo — no API key required.

    Args:
        query: Search query string (e.g. "Clariant AG Swiss specialty chemicals")
        max_results: Maximum results to return (default 5, capped at 10)

    Returns:
        dict with 'results': list of {title, url, snippet} entries,
        and optional 'error' key if the search failed.
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "results": [],
            "error": (
                "ddgs is not installed. "
                "Run: uv pip install ddgs"
            ),
        }

    max_results = min(max_results, 10)

    def _run():
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        raw = _run()
    except Exception as exc:
        err_str = str(exc).lower()
        # Rate limit — wait 2 s and retry once
        if any(indicator in err_str for indicator in ("ratelimit", "rate limit", "202", "429")):
            time.sleep(2)
            try:
                raw = _run()
            except Exception as exc2:
                return {"results": [], "error": f"Rate limited after retry: {exc2}"}
        else:
            return {"results": [], "error": str(exc)}

    results = [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        }
        for r in (raw or [])
    ]
    return {"results": results}


# ── Start server ──────────────────────────────
if __name__ == '__main__':
    mcp.run(transport='stdio')
