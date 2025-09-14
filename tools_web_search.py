import json
import time
import html
from typing import Dict, Any, List, Tuple
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def web_search_tool_def() -> dict:
    return {
        "name": "web_search",
        "description": "Search the web for real-time information and return top result links with titles.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "The query to search for (include keywords, versions, dates as needed).",
                },
                "explanation": {
                    "type": "string",
                    "description": "Short note on why this search is being performed.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of results to return (default 10).",
                    "minimum": 1,
                },
            },
            "required": ["search_term"],
        },
    }


def _http_get(url: str, timeout: int = 10) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _parse_duckduckgo_html(html_text: str) -> List[Tuple[str, str]]:
    # Very light parsing: collect anchors that look like result links.
    # Support multiple DDG variants (html, html.duckduckgo.com, lite).
    results: List[Tuple[str, str]] = []

    def _extract_links_with_marker(marker: str) -> List[Tuple[str, str]]:
        links: List[Tuple[str, str]] = []
        start = 0
        m = marker
        while True:
            idx = html_text.find(m, start)
            if idx == -1:
                break
            # find href="..."
            href_idx = html_text.find("href=\"", idx)
            if href_idx == -1:
                start = idx + len(m)
                continue
            href_start = href_idx + len("href=\"")
            href_end = html_text.find("\"", href_start)
            if href_end == -1:
                start = idx + len(m)
                continue
            url = html_text[href_start:href_end]
            # extract title between > and <
            tag_close = html_text.find(">", href_end)
            if tag_close == -1:
                start = idx + len(m)
                continue
            title_end = html_text.find("<", tag_close + 1)
            if title_end == -1:
                start = idx + len(m)
                continue
            title = html.unescape(html_text[tag_close + 1:title_end]).strip()
            if url.startswith("http") and title:
                links.append((title, url))
            start = title_end + 1
        return links

    # Try several common markers used across DDG variants
    markers = [
        "class=\"result__a\"",          # standard html
        "class=\"result-link\"",        # lite variant
        "<a rel=\"nofollow\"",          # generic
        "class=\"result__title\"",      # container title
    ]
    for m in markers:
        results.extend(_extract_links_with_marker(m))
        if results:
            break

    # Deduplicate by URL while preserving order
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for title, url in results:
        if url in seen:
            continue
        seen.add(url)
        deduped.append((title, url))
    return deduped


def _search_duckduckgo(term: str, max_results: int) -> List[Dict[str, str]]:
    q = quote_plus(term)
    candidate_urls = [
        f"https://duckduckgo.com/html/?q={q}&ia=web",
        f"https://html.duckduckgo.com/html/?q={q}&ia=web",
        f"https://lite.duckduckgo.com/lite/?q={q}",
    ]

    last_error: Exception | None = None
    for url in candidate_urls:
        try:
            html_text = _http_get(url)
            pairs = _parse_duckduckgo_html(html_text)
            if not pairs:
                continue
            out: List[Dict[str, str]] = []
            for title, link in pairs[:max_results]:
                out.append({"title": title, "url": link})
            return out
        except (URLError, HTTPError, TimeoutError, Exception) as e:
            last_error = e
            continue

    # If all attempts failed or yielded no pairs, surface empty list
    return []


def web_search_impl(input: Dict[str, Any]) -> str:
    term = (input.get("search_term") or "").strip()
    if not term:
        raise ValueError("missing 'search_term'")
    max_results = int(input.get("max_results") or 10)

    start_ts = time.time()
    engine = "duckduckgo"
    note = None
    results: List[Dict[str, str]] = []

    try:
        results = _search_duckduckgo(term, max_results)
    except (URLError, HTTPError, TimeoutError, Exception) as e:
        note = f"duckduckgo failed: {type(e).__name__}: {e}"
        results = []

    if not results and note is None:
        note = "duckduckgo returned no parseable results"

    return json.dumps({
        "query": term,
        "engine": engine,
        "results": results,
        "took_ms": int((time.time() - start_ts) * 1000),
        **({"note": note} if note else {}),
    })
