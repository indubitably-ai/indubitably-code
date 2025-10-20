import json
import time
import html
import re
import gzip
import zlib
from typing import Dict, Any, List, Tuple
from tools.handler import ToolOutput
from tools.schemas import WebSearchInput
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor
import http.cookiejar as cookiejar
from urllib.parse import urlencode
from urllib.error import URLError, HTTPError


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def web_search_tool_def() -> dict:
    return {
        "name": "web_search",
        "description": (
            "Perform a real-time web search to fetch fresh links, titles, and metadata beyond the model's training cutoff. Provide a descriptive `search_term`, explain the intent via `explanation` when helpful for auditing, and optionally "
            "set `max_results` to bound how many top hits are returned (defaults to 10). The tool queries DuckDuckGo HTML first, then falls back to its JSON API, Bing, and Wikipedia, reporting which engine produced the results and including diagnostic notes "
            "when fallbacks were required. The JSON response lists normalized URLs and titles so agents can cite sources directly in their answers. Example: investigate 'OpenTelemetry collector release 2025' by calling web_search with max_results=5 and summarizing the first few URLs. Avoid using this tool for proprietary data that requires authentication, for exhaustive crawling (results are capped per call), or when the answer is already available locally to reduce latency and cost."
        ),
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


def _http_get(url: str, timeout: int = 10, opener=None) -> str:
    req = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        },
    )
    open_fn = opener.open if opener is not None else urlopen
    with open_fn(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _http_post(url: str, data: dict, timeout: int = 10, opener=None) -> str:
    payload = urlencode(data).encode("utf-8")
    req = Request(
        url,
        data=payload,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://duckduckgo.com",
            "Referer": "https://duckduckgo.com/html/",
        },
        method="POST",
    )
    open_fn = opener.open if opener is not None else urlopen
    with open_fn(req, timeout=timeout) as resp:
        raw = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        charset = resp.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def _parse_duckduckgo_html(html_text: str) -> List[Tuple[str, str]]:
    # Very light parsing: collect anchors that look like result links.
    # Support multiple DDG variants (html, html.duckduckgo.com, lite).
    results: List[Tuple[str, str]] = []

    def _ddg_unwrap_url(url: str) -> str:
        # DuckDuckGo often wraps links as /l/?uddg=<encoded>
        try:
            parsed = urlparse(url)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query)
                if "uddg" in qs and qs["uddg"]:
                    return unquote(qs["uddg"][0])
            if url.startswith("/l/") or url.startswith("/lite/l/"):
                qs = parse_qs(urlparse("https://duckduckgo.com" + url).query)
                if "uddg" in qs and qs["uddg"]:
                    return unquote(qs["uddg"][0])
        except Exception:
            pass
        return url

    def _strip_tags(text: str) -> str:
        # Remove HTML tags to get readable title text
        return re.sub(r"<[^>]+>", "", text)

    def _extract_links_with_marker(marker: str) -> List[Tuple[str, str]]:
        links: List[Tuple[str, str]] = []
        start = 0
        m = marker
        while True:
            idx = html_text.find(m, start)
            if idx == -1:
                break
            # find href=... allowing both single and double quotes
            href_idx = html_text.find("href=", idx)
            if href_idx == -1:
                start = idx + len(m)
                continue
            quote_char = html_text[href_idx + len("href=") : href_idx + len("href=") + 1]
            if quote_char not in ('"', "'"):
                start = idx + len(m)
                continue
            href_start = href_idx + len("href=") + 1
            href_end = html_text.find(quote_char, href_start)
            if href_end == -1:
                start = idx + len(m)
                continue
            url = html_text[href_start:href_end]
            # unwrap DDG redirect URLs
            if (url.startswith("/l/") or "duckduckgo.com/l/" in url) and "uddg=" in url:
                url = _ddg_unwrap_url(url)
            # extract title between > and </a>, allow nested tags
            tag_close = html_text.find(">", href_end)
            if tag_close == -1:
                start = idx + len(m)
                continue
            anchor_end = html_text.find("</a>", tag_close + 1)
            if anchor_end == -1:
                start = idx + len(m)
                continue
            inner = html_text[tag_close + 1:anchor_end]
            title = html.unescape(_strip_tags(inner)).strip()
            if (url.startswith("http") or url.startswith("https")) and title:
                links.append((title, url))
            elif title and (url.startswith("/l/") or "duckduckgo.com/l/" in url):
                # If unwrap did not run earlier, try once more
                unwrapped = _ddg_unwrap_url(url)
                if unwrapped.startswith("http"):
                    links.append((title, unwrapped))
            start = anchor_end + 1
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
    cj = cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(cj))

    candidate_urls = [
        f"https://duckduckgo.com/html/?q={q}&ia=web",
        f"https://html.duckduckgo.com/html/?q={q}&ia=web",
        f"https://lite.duckduckgo.com/lite/?q={q}",
    ]

    last_error: Exception | None = None
    for url in candidate_urls:
        try:
            html_text = _http_get(url, opener=opener)
            pairs = _parse_duckduckgo_html(html_text)
            if pairs:
                out: List[Dict[str, str]] = []
                for title, link in pairs[:max_results]:
                    out.append({"title": title, "url": link})
                return out
        except (URLError, HTTPError, TimeoutError, Exception) as e:
            last_error = e
            continue

    # Try HTML POST endpoint which can behave better with cookies
    try:
        html_text = _http_post(
            "https://duckduckgo.com/html/",
            {"q": term, "ia": "web"},
            opener=opener,
        )
        pairs = _parse_duckduckgo_html(html_text)
        if pairs:
            out: List[Dict[str, str]] = []
            for title, link in pairs[:max_results]:
                out.append({"title": title, "url": link})
            return out
    except (URLError, HTTPError, TimeoutError, Exception) as e:
        last_error = e

    # If all attempts failed or yielded no pairs, surface empty list
    return []


def _parse_bing_html(html_text: str) -> List[Tuple[str, str]]:
    # Minimal parser for Bing SERP: look for result blocks and extract <a> in <h2>
    results: List[Tuple[str, str]] = []

    # Use regex to find anchors inside h2s commonly used by Bing
    for match in re.finditer(r"<h2[^>]*>\s*<a[^>]*href=(['\"])(?P<href>.*?)\1[^>]*>(?P<title>.*?)</a>\s*</h2>", html_text, re.IGNORECASE | re.DOTALL):
        url = html.unescape(match.group("href")).strip()
        title_html = match.group("title")
        title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        if url.startswith("http") and title:
            results.append((title, url))
    return results


def _search_bing(term: str, max_results: int) -> List[Dict[str, str]]:
    q = quote_plus(term)
    url = f"https://www.bing.com/search?q={q}&setlang=en-US"
    try:
        html_text = _http_get(url)
        pairs = _parse_bing_html(html_text)
        out: List[Dict[str, str]] = []
        for title, link in pairs[:max_results]:
            out.append({"title": title, "url": link})
        return out
    except (URLError, HTTPError, TimeoutError, Exception):
        return []


def _search_duckduckgo_api(term: str, max_results: int) -> List[Dict[str, str]]:
    # Use DDG Instant Answer API as a low-friction fallback
    q = quote_plus(term)
    url = f"https://api.duckduckgo.com/?q={q}&format=json&no_html=1&no_redirect=1&t=indubitably-code"
    try:
        txt = _http_get(url)
        data = json.loads(txt)

        results: List[Dict[str, str]] = []

        # Top-level Results array sometimes present
        for item in data.get("Results", []) or []:
            title = (item.get("Text") or "").strip()
            link = (item.get("FirstURL") or "").strip()
            if title and link:
                results.append({"title": title, "url": link})
                if len(results) >= max_results:
                    return results

        def add_related(items):
            for it in items:
                if "Topics" in it:
                    add_related(it.get("Topics") or [])
                else:
                    title = (it.get("Text") or "").strip()
                    link = (it.get("FirstURL") or "").strip()
                    if title and link:
                        results.append({"title": title, "url": link})
                        if len(results) >= max_results:
                            return True
            return False

        related = data.get("RelatedTopics") or []
        add_related(related)
        return results[:max_results]
    except Exception:
        return []


def _search_wikipedia(term: str, max_results: int) -> List[Dict[str, str]]:
    # Simple Wikipedia search parser
    q = quote_plus(term)
    url = f"https://en.wikipedia.org/w/index.php?search={q}&title=Special:Search&ns0=1"
    try:
        html_text = _http_get(url)
        results: List[Dict[str, str]] = []
        for m in re.finditer(r'<div class="mw-search-result-heading"[^>]*>\s*<a href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', html_text, re.IGNORECASE | re.DOTALL):
            href = m.group("href").strip()
            title_html = m.group("title")
            title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            if href.startswith("/"):
                link = "https://en.wikipedia.org" + href
            else:
                link = href
            if title and link:
                results.append({"title": title, "url": link})
                if len(results) >= max_results:
                    break
        return results
    except Exception:
        return []


def web_search_impl(params: WebSearchInput) -> ToolOutput:
    term = (params.search_term or "").strip()
    max_results = int(params.max_results or 10)

    start_ts = time.time()
    engine = "duckduckgo"
    note = None
    results: List[Dict[str, str]] = []

    try:
        results = _search_duckduckgo(term, max_results)
    except (URLError, HTTPError, TimeoutError, Exception) as e:
        note = f"duckduckgo failed: {type(e).__name__}: {e}"
        results = []

    if not results:
        fallback = _search_duckduckgo_api(term, max_results)
        if fallback:
            engine = "duckduckgo_api"
            if note is None:
                note = "duckduckgo html yielded no results; used instant answer api"
            results = fallback

    if not results:
        fallback = _search_bing(term, max_results)
        if fallback:
            engine = "bing"
            if note is None:
                note = "duckduckgo returned no parseable results; used bing fallback"
            results = fallback

    if not results:
        fallback = _search_wikipedia(term, max_results)
        if fallback:
            engine = "wikipedia"
            if note is None:
                note = "used wikipedia fallback"
            results = fallback

    if not results and note is None:
        note = "duckduckgo returned no parseable results"

    try:
        payload = {
            "query": term,
            "engine": engine,
            "results": results,
            "took_ms": int((time.time() - start_ts) * 1000),
        }
        if note:
            payload["note"] = note
        return ToolOutput(content=json.dumps(payload), success=True)
    except Exception as exc:
        return ToolOutput(content=f"Web search failed: {exc}", success=False, metadata={"error_type": "search_error"})
