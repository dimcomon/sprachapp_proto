# SprachApp Proto

## Status
- Aktueller Stand: MVP3 (Weiterentwicklung)
- Stabiler Stand: MVP2 (Tag v0.2.0, abgeschlossen)
- Regel: Keine Änderungen an MVP2-Qualitätslogik

## Zweck
CLI-basierte Sprachlern-App mit lokalem ASR (openai-whisper) zur Aufnahme,
Bewertung und Speicherung strukturierter Sprachantworten (News / Book / Selfcheck).

## Start (Golden Path)
python3 sprachapp_main.py news
python3 sprachapp_main.py book
python3 sprachapp_main.py selfcheck
python3 sprachapp_main.py report --last 20   # Alias: stats

## Workflow (empfohlen)

1) Üben (News oder Book):
   - python3 sprachapp_main.py news --news-file news.txt --questions 1
   - python3 sprachapp_main.py book --book-file book.txt --questions 1 --chunk 0

2) Auswertung:
   - python3 sprachapp_main.py report --progress --last 200

3) Nächster Schritt:
   - Lies die Zeile `NEXT (global): ...` und wiederhole gezielt (z.B. q1 kurz/sauber).

## Dokumentation
- RUN.md – lokaler Start & Setup
- DEV_NOTES.md – technische Rahmenbedingungen
- MVP3.md – aktueller Entwicklungsfokus

## Hinweis
MVP2-Logik (Quality-Flags, Warnungen, Tutor-Flows) ist bewusst abgeschlossen
und wird in MVP3 nicht verändert.
