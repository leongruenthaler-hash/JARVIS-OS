from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[SearchResult] = []
        self._in_title = False
        self._in_snippet = False
        self._current_title = ""
        self._current_url = ""
        self._current_snippet = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        attributes = dict(attrs)
        css_class = attributes.get("class", "")

        if tag == "a" and "result__a" in css_class:
            self._in_title = True
            self._current_title = ""
            self._current_snippet = ""
            self._current_url = clean_duckduckgo_url(attributes.get("href", ""))

        if tag in {"a", "div"} and "result__snippet" in css_class:
            self._in_snippet = True

    def handle_data(self, data: str):
        if self._in_title:
            self._current_title += data
        elif self._in_snippet:
            self._current_snippet += data

    def handle_endtag(self, tag: str):
        if tag == "a" and self._in_title:
            self._in_title = False
            title = normalize_space(self._current_title)
            if title and self._current_url:
                self.results.append(
                    SearchResult(
                        title=title,
                        url=self._current_url,
                        snippet="",
                    )
                )

        if tag in {"a", "div"} and self._in_snippet:
            self._in_snippet = False
            snippet = normalize_space(self._current_snippet)
            if snippet and self.results:
                self.results[-1].snippet = snippet


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text))).strip()


def clean_duckduckgo_url(url: str) -> str:
    if not url:
        return ""

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "uddg" in query:
        return query["uddg"][0]

    return url


def search_web(query: str, max_results: int = 3) -> list[SearchResult]:
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://duckduckgo.com/html/?q={encoded_query}&kl=de-de"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            )
        },
    )

    with urllib.request.urlopen(request, timeout=12) as response:
        page = response.read().decode("utf-8", errors="replace")

    parser = DuckDuckGoHTMLParser()
    parser.feed(page)

    clean_results = []
    seen_urls = set()
    for result in parser.results:
        if not result.url or result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        clean_results.append(result)
        if len(clean_results) >= max_results:
            break

    return clean_results


def check_internet_access() -> tuple[bool, str]:
    request = urllib.request.Request(
        "https://duckduckgo.com/",
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            )
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            status = getattr(response, "status", 200)
    except Exception as exc:
        return False, str(exc)

    return 200 <= status < 400, f"HTTP {status}"


def format_search_results(results: list[SearchResult]) -> str:
    lines = []
    for index, result in enumerate(results, start=1):
        snippet = shorten_text(result.snippet or "Kein Ausschnitt verfügbar.", max_length=180)
        lines.append(
            f"[{index}] {result.title}\n"
            f"URL: {result.url}\n"
            f"Ausschnitt: {snippet}"
        )
    return "\n\n".join(lines)


def shorten_text(text: str, max_length: int) -> str:
    text = normalize_space(text)
    if len(text) <= max_length:
        return text

    return text[: max_length - 1].rstrip() + "…"
