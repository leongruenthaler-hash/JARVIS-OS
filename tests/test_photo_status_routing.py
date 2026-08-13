"""Test fuer den in der Faehigkeits-Simulation (2026-08-13) live gefundenen
Foto-Bug: "Wie viele Fotos hast du schon indiziert?" wurde als Such-Anfrage
interpretiert (extract_photo_count_query fand kein Praeposition-Muster und
liess "hast du schon indiziert" als Suchbegriff stehen) statt den Index-Stand
zu nennen. Siehe docs/current-system-assessment.md, Abschnitt 41."""

from unittest.mock import MagicMock

import jarvis


def test_how_many_indexed_routes_to_status_not_search():
    worker = MagicMock()
    worker.status.return_value = "Fotos-Index ist bereit. Letzter Scan: ..., aktuell sichtbare Fotos: 508."

    answer = jarvis.handle_photo_command("Wie viele Fotos hast du schon indiziert?", worker)

    worker.status.assert_called_once()
    worker.count_search.assert_not_called()
    assert "508" in answer


def test_content_count_query_still_uses_count_search():
    worker = MagicMock()
    worker.count_search.return_value = "Ich finde 3 passende Foto(s) für Urlaub."

    answer = jarvis.handle_photo_command("Wie viele Fotos habe ich vom Urlaub?", worker)

    worker.count_search.assert_called_once()
    worker.status.assert_not_called()
    assert "3" in answer
