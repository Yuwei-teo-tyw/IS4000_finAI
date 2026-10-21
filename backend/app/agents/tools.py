"""
Tools for the LangGraph agents.

`tavily_search` is a real LangChain tool: it's bound to the LLM with
`.bind_tools()` in the General Assistant node, and the model itself decides
whether/when to call it based on the conversation - no keyword heuristics.
"""
import os
import requests
from langchain_core.tools import tool


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
