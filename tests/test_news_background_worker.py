"""Tests fuer news_background_worker.py (Baustein "Wichtige Nachrichten", siehe
plans/2026-08-09-jarvis-news-baustein.md)."""

from __future__ import annotations

import news_background_worker as worker_module
from news_background_worker import NewsBackgroundWorker, _is_excluded_by_category, classify_headline_importance
from news_source import NewsHeadline


class _FakeLLM:
    """Minimaler Ersatz fuer LLMClient.ask() - kein echter Modellaufruf."""

    def __init__(self, response: str):
        self._response = response

    def ask(self, messages, max_output_tokens=None, user_text=None):
        return self._response


def _headline(id_suffix: str = "1", title: str = "Titel", link: str | None = None) -> NewsHeadline:
    resolved_link = link or f"https://correctiv.org/artikel-{id_suffix}"
    return NewsHeadline(
        id=resolved_link,
        title=title,
        summary="Zusammenfassung.",
        link=resolved_link,
        published="",
    )


def test_is_excluded_by_category_faktencheck():
    headline = _headline(link="https://correctiv.org/faktencheck/2026/08/06/beispiel/")
    assert _is_excluded_by_category(headline) is True


def test_is_excluded_by_category_in_eigener_sache():
    headline = _headline(link="https://correctiv.org/in-eigener-sache/2026/08/06/beispiel/")
    assert _is_excluded_by_category(headline) is True


def test_is_excluded_by_category_normal_article():
    headline = _headline(link="https://correctiv.org/aktuelles/wirtschaft/2026/08/06/beispiel/")
    assert _is_excluded_by_category(headline) is False


def test_classify_headline_importance_wichtig():
    assert classify_headline_importance(_FakeLLM("wichtig"), _headline()) is True


def test_classify_headline_importance_normal():
    assert classify_headline_importance(_FakeLLM("normal"), _headline()) is False


def test_classify_headline_importance_unparseable_defaults_to_false():
    assert classify_headline_importance(_FakeLLM("keine ahnung ehrlich gesagt"), _headline()) is False


def test_classify_headline_importance_swallows_exceptions():
    class _BrokenLLM:
        def ask(self, *args, **kwargs):
            raise RuntimeError("kein Modell erreichbar")

    assert classify_headline_importance(_BrokenLLM(), _headline()) is False


def test_check_skips_excluded_categories_without_classifying(tmp_path, monkeypatch):
    headlines = [
        _headline("1", "Faktencheck-Titel", link="https://correctiv.org/faktencheck/2026/08/06/x/"),
        _headline("2", "Echte Nachricht", link="https://correctiv.org/aktuelles/wirtschaft/2026/08/06/y/"),
    ]
    monkeypatch.setattr(worker_module, "fetch_news_headlines", lambda url, max_items: headlines)

    classified_titles = []

    def _record_and_classify(llm, headline):
        classified_titles.append(headline.title)
        return True

    monkeypatch.setattr(worker_module, "classify_headline_importance", _record_and_classify)

    news_worker = NewsBackgroundWorker({"news_enabled": False}, llm=None, base_path=tmp_path)
    news_worker._check()

    assert classified_titles == ["Echte Nachricht"]
    pending = news_worker.drain_important_news()
    assert len(pending) == 1
    assert pending[0]["title"] == "Echte Nachricht"


def test_check_stores_only_important_headlines_and_dedupes(tmp_path, monkeypatch):
    headlines = [_headline("1", "Wichtige Sache"), _headline("2", "Unwichtige Sache")]
    monkeypatch.setattr(worker_module, "fetch_news_headlines", lambda url, max_items: headlines)
    monkeypatch.setattr(
        worker_module,
        "classify_headline_importance",
        lambda llm, headline: "Wichtige" in headline.title,
    )

    news_worker = NewsBackgroundWorker({"news_enabled": False}, llm=None, base_path=tmp_path)
    news_worker._check()

    pending = news_worker.drain_important_news()
    assert len(pending) == 1
    assert pending[0]["title"] == "Wichtige Sache"

    # Zweiter Check mit denselben Schlagzeilen (bereits bekannt) - keine erneute
    # Klassifikation, nichts Neues wartet.
    news_worker._check()
    assert news_worker.drain_important_news() == []


def test_drain_important_news_clears_the_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module, "fetch_news_headlines", lambda url, max_items: [_headline("x")])
    monkeypatch.setattr(worker_module, "classify_headline_importance", lambda llm, headline: True)

    news_worker = NewsBackgroundWorker({"news_enabled": False}, llm=None, base_path=tmp_path)
    news_worker._check()

    first_drain = news_worker.drain_important_news()
    second_drain = news_worker.drain_important_news()

    assert len(first_drain) == 1
    assert second_drain == []


def test_check_safely_records_error_without_raising(tmp_path, monkeypatch):
    def _boom(url, max_items):
        raise RuntimeError("Netzwerkfehler")

    monkeypatch.setattr(worker_module, "fetch_news_headlines", _boom)

    news_worker = NewsBackgroundWorker({"news_enabled": False}, llm=None, base_path=tmp_path)
    news_worker._check_safely()

    cache = news_worker._load_cache()
    assert "Netzwerkfehler" in cache.get("last_error", "")


def test_due_for_check_true_when_never_checked(tmp_path):
    news_worker = NewsBackgroundWorker({"news_enabled": False}, llm=None, base_path=tmp_path)
    assert news_worker._due_for_check(None) is True


def test_due_for_check_false_within_interval(tmp_path):
    from datetime import datetime

    news_worker = NewsBackgroundWorker(
        {"news_enabled": False, "news_check_interval_minutes": 240}, llm=None, base_path=tmp_path
    )
    assert news_worker._due_for_check(datetime.now().isoformat(timespec="seconds")) is False
