"""Web search tool — Tavily backend.

Provides Researcher with live web search for competitive intelligence, market
research, and citation-backed findings. Uses Tavily's search API, which is
purpose-built for AI agents and returns clean source URLs with snippets.

API key is loaded from TAVILY_API_KEY env var (local dev) or SSM param
/sdlc-agents/researcher-tavily-api-key (production), mirroring the credential
pattern used by asana_mcp.py.
"""

import os

import boto3
from strands import tool
from tavily import TavilyClient


_ssm = None
_client = None


def _get_ssm():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _get_api_key() -> str:
    val = os.environ.get("TAVILY_API_KEY")
    if val:
        return val
    resp = _get_ssm().get_parameter(
        Name="/sdlc-agents/researcher-tavily-api-key",
        WithDecryption=True,
    )
    return resp["Parameter"]["Value"]


def _get_client() -> TavilyClient:
    global _client
    if _client is None:
        _client = TavilyClient(api_key=_get_api_key())
    return _client


@tool
def web_search(
    query: str,
    max_results: int = 5,
    search_depth: str = "basic",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> dict:
    """Search the web for current information with source URLs.

    Use this for competitive intelligence, market research, pricing checks,
    product launch tracking, and any claim that needs a citable source.
    Every result includes a URL — use it in the Sources section of your reply.

    Args:
        query: Search query. Be specific. Prefer "Competitor X pricing 2026"
            over "pricing info".
        max_results: How many results to return. Default 5. Max 10.
        search_depth: "basic" (faster, cheaper) or "advanced" (slower, richer
            content). Use "advanced" when you need page content, not just
            snippets.
        include_domains: Restrict search to these domains (e.g.
            ["asana.com", "monday.com"]).
        exclude_domains: Exclude these domains.

    Returns:
        Dict with:
        - answer: Tavily's synthesized answer (if available)
        - results: List of {title, url, content, score}
        - query: The query that was run
    """
    client = _get_client()
    kwargs = {
        "query": query,
        "max_results": min(max(max_results, 1), 10),
        "search_depth": search_depth if search_depth in ("basic", "advanced") else "basic",
        "include_answer": True,
    }
    if include_domains:
        kwargs["include_domains"] = include_domains
    if exclude_domains:
        kwargs["exclude_domains"] = exclude_domains

    response = client.search(**kwargs)

    return {
        "query": query,
        "answer": response.get("answer", ""),
        "results": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "score": r.get("score", 0),
            }
            for r in response.get("results", [])
        ],
    }
