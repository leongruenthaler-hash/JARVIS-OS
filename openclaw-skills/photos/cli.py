#!/usr/bin/env python3
"""Duenner CLI-Wrapper um photos_client.py::PhotoIndex fuer die Nutzung als
OpenClaw-Skill (2026-09-07) - der Kernindex/Scan/Vision-Code stammt
unveraendert aus JARVIS-OS/app/photos_client.py + photos_helper.swift, nur die
Anbindung ans Backend (config/data_dir/remote_worker/secure_storage) wurde
durch leichte Platzhalter ersetzt (siehe die anderen Dateien in diesem Ordner).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from photos_client import PhotoIndex  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis Fotos-Suche (OpenClaw-Skill)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Fotobibliothek indexieren (einmalig/gelegentlich, kann dauern)")
    scan_parser.add_argument("--max", type=int, default=500, help="Maximale Anzahl neu zu scannender Fotos")

    search_parser = subparsers.add_parser("search", help="Im bestehenden Index suchen")
    search_parser.add_argument("query", help="Suchbegriff, z.B. 'Hund am Strand' oder 'letzten Sommer'")
    search_parser.add_argument("--max", type=int, default=25, help="Maximale Anzahl Ergebnisse")

    subparsers.add_parser("status", help="Index-Status anzeigen (Anzahl Fotos, letzter Scan)")

    args = parser.parse_args()
    index = PhotoIndex(config={})

    if args.command == "scan":
        count = index.scan(max_items=args.max)
        print(json.dumps({"scanned": count}, ensure_ascii=False))
    elif args.command == "search":
        matches = index.search(args.query, max_results=args.max)
        results = [
            {
                "id": match.photo_id,
                "filename": match.filename,
                "mediaType": match.media_type,
                "createdAt": match.created_at,
                "labels": match.labels,
                "texts": match.texts,
                "score": match.score,
            }
            for match in matches
        ]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    elif args.command == "status":
        print(index.cached_status())


if __name__ == "__main__":
    main()
