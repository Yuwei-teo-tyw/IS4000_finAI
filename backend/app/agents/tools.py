"""
Tools for the LangGraph agents.

`tavily_search` is a real LangChain tool: it's bound to the LLM with
`.bind_tools()` in each specialist node, and the model itself decides
whether/when to call it based on the conversation - no keyword heuristics.
"""
import os
import requests
from langchain_core.tools import tool

from app.agents.report_generator import generate_report


@tool
def generate_client_report(report_type: str, title: str, summary: str) -> str:
    """
    Generate a client-ready, formatted report (e.g. PDF) summarizing the
    financial analysis or recommendations discussed in the conversation.

    Use this when the user asks for a document, report, or summary they
    can save, share, or download, rather than continuing the discussion
    in chat.

    PLACEHOLDER: the underlying document-generation logic (PDF/formatting)
    is undecided and not yet implemented - calling this returns a stub
    response. Wire the real generator into report_generator.py once the
    output format is decided; the tool-calling contract here won't need
    to change.

    Args:
        report_type: desired output format, e.g. "pdf", "markdown", "summary"
        title: a short, descriptive title for the report
        summary: the financial analysis/content to include in the report
    """
    return generate_report(report_type, title, summary)


@tool
def propose_financial_action(action_type: str, amount: float, description: str) -> str:
    """
    Propose a financial action that would move real money - placing a trade,
    transferring funds, rebalancing a portfolio, etc. Use this instead of
    just describing the action in text whenever the user asks you to
    actually *do* something with their money, not just discuss it.

    Calling this does NOT execute anything by itself - it only registers
    the proposed action. A human-approval gate sits in front of it in the
    graph and requires explicit user confirmation before anything proceeds.

    PLACEHOLDER: there is no real brokerage/banking integration behind this
    yet. When one exists, wire the actual API call in behind the same
    approval gate rather than removing it.

    Args:
        action_type: e.g. "buy", "sell", "transfer", "rebalance"
        amount: dollar amount involved
        description: a precise, human-readable description of exactly what would happen
    """
    return f"PROPOSED (not executed): {action_type} - {description} - ${amount:,.2f}"


@tool
def tavily_search(query: str, max_results: int = 3) -> str:
    """
    Search the web using Tavily to find current, up-to-date information.

    Use this when the user's question depends on information that may have
    changed recently - current prices, versions, news, market data, recent
    releases, etc. Do not use it for stable, well-known facts.

    Args:
        query: The search query.
        max_results: Maximum number of results to return (default: 3).

    Returns:
        Formatted search results with titles, URLs, and content snippets.
    """
    try:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            return "Error: TAVILY_API_KEY not found in environment variables."

        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": True,
                "include_images": False,
                "include_raw_content": False,
            },
            timeout=10,
        )
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return f"No search results found for query: {query}"

        formatted = f"Search results for: {query}\n\n"
        for i, result in enumerate(results, 1):
            title = result.get("title", "No title")
            url = result.get("url", "No URL")
            content = result.get("content", "No content available")
            formatted += f"{i}. {title}\n   URL: {url}\n   Content: {content[:300]}\n\n"
        return formatted

    except requests.RequestException as e:
        return f"Error performing search request: {str(e)}."
    except Exception as e:
        return f"Error performing search: {str(e)}."
