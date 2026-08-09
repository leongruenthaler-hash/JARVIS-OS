"""Tests fuer news_source.py (Baustein "Wichtige Nachrichten", siehe
plans/2026-08-09-jarvis-news-baustein.md)."""

import news_source

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>CORRECTIV</title>
<item>
<title>Erste Schlagzeile</title>
<link>https://correctiv.org/artikel-eins</link>
<description><![CDATA[<p>Ein <b>wichtiger</b> Text mit HTML.</p>]]></description>
<pubDate>Sun, 09 Aug 2026 10:00:00 +0200</pubDate>
</item>
<item>
<title>Zweite Schlagzeile</title>
<link>https://correctiv.org/artikel-zwei</link>
<description>Reiner Text ohne HTML.</description>
<pubDate>Sun, 09 Aug 2026 09:00:00 +0200</pubDate>
</item>
<item>
<title></title>
<link>https://correctiv.org/ohne-titel</link>
<description>Wird uebersprungen, kein Titel.</description>
</item>
</channel>
</rss>
"""


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_news_headlines_parses_items(monkeypatch):
    monkeypatch.setattr(
        news_source.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(_SAMPLE_RSS.encode("utf-8")),
    )

    headlines = news_source.fetch_news_headlines("https://example.org/feed", max_items=10)

    assert len(headlines) == 2
    assert headlines[0].title == "Erste Schlagzeile"
    assert headlines[0].id == "https://correctiv.org/artikel-eins"
    assert headlines[1].title == "Zweite Schlagzeile"


def test_fetch_news_headlines_strips_html_from_summary(monkeypatch):
    monkeypatch.setattr(
        news_source.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(_SAMPLE_RSS.encode("utf-8")),
    )

    headlines = news_source.fetch_news_headlines("https://example.org/feed", max_items=10)

    assert "<" not in headlines[0].summary
    assert "wichtiger" in headlines[0].summary


def test_fetch_news_headlines_respects_max_items(monkeypatch):
    monkeypatch.setattr(
        news_source.urllib.request,
        "urlopen",
        lambda request, timeout: _FakeResponse(_SAMPLE_RSS.encode("utf-8")),
    )

    headlines = news_source.fetch_news_headlines("https://example.org/feed", max_items=1)

    assert len(headlines) == 1


def test_clean_summary_truncates_long_text():
    long_text = "Wort " * 200
    cleaned = news_source._clean_summary(long_text, limit=50)
    assert len(cleaned) <= 51
    assert cleaned.endswith("…")
