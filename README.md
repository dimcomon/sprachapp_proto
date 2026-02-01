# SprachApp Proto

## Status
- Aktueller Stand: MVP4-B (Didaktik abgeschlossen)
- Letzter stabiler Tag: v0.4.0-b
- Regel: Keine Änderungen an zentraler Qualitätslogik (seit MVP2)

## Zweck
CLI-basierte Sprachlern-App mit lokalem ASR (openai-whisper) zur Aufnahme,
Bewertung und Speicherung strukturierter Sprachantworten (News / Book / Selfcheck).

## Start (Golden Path)
python3 sprachapp_main.py news
python3 sprachapp_main.py book
python3 sprachapp_main.py selfcheck
python3 sprachapp_main.py report --last 20   # Alias: stats
Siehe RUN.md für vollständige Beispiele und Optionen.

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

## Coach (MVP5-A)
Die App enthält einen ersten Coach (Textausgabe), der nach jeder Session
kurzes Feedback gibt. Der Coach nutzt bestehende Transkripte und Statistiken
und ist vorbereitet für eine spätere KI-/LLM-Anbindung.
