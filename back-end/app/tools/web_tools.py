"""Web-related tools for the AI agent."""

from langchain_core.tools import tool


@tool
def search_web(query: str) -> str:
    """Search the web for information using DuckDuckGo.

    Args:
        query: The search query string.
    """
    try:
        from ddgs import DDGS

        results = []
        ddgs = DDGS()
        for r in ddgs.text(query, max_results=5):
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            results.append(f"**{title}**\n{body}\nURL: {href}")

        if not results:
            return f"No results found for '{query}'."

        return "\n\n---\n\n".join(results)

    except ImportError:
        return (
            "[Web search unavailable: ddgs not installed. "
            "Run: pip install ddgs]"
        )
    except Exception as e:
        return f"Search error: {e}"


@tool
def web_scrape(url: str) -> str:
    """Fetch a web page and extract its main text content. Use this tool when
    you need the full details from a specific URL — for example, after
    search_web returns a relevant link and the snippet is not enough, or when
    the user provides a URL and asks you to read, summarize, or extract
    information from it.

    This returns clean readable text (no HTML tags, no scripts, no ads).
    Output is truncated to ~8000 characters to fit context limits.

    Args:
        url: The full URL to scrape (must start with http:// or https://).
    """
    import re

    try:
        import httpx
        from readability import Document
    except ImportError:
        return (
            "[Web scrape unavailable: missing dependencies. "
            "Run: pip install httpx readability-lxml lxml]"
        )

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()

        # Extract main content using readability
        doc = Document(response.text)
        title = doc.title()

        # Get the cleaned HTML summary, then strip remaining tags
        summary_html = doc.summary()

        # Strip HTML tags to get plain text
        text = re.sub(r"<[^>]+>", " ", summary_html)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Replace common HTML entities
        for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                             ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
            text = text.replace(entity, char)

        if not text:
            return f"Could not extract readable content from {url}"

        # Truncate to ~8000 chars
        max_len = 8000
        if len(text) > max_len:
            text = text[:max_len] + "\n\n... (truncated)"

        return f"**{title}**\n\n{text}"

    except httpx.HTTPStatusError as e:
        return f"Error: HTTP {e.response.status_code} fetching {url}"
    except httpx.ConnectError:
        return f"Error: Could not connect to {url}"
    except httpx.TimeoutException:
        return f"Error: Request timed out for {url}"
    except Exception as e:
        return f"Error scraping {url}: {e}"
