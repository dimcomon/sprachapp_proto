# Development Notes

## Runtime
- Python: 3.13
- ASR: openai-whisper (lokal, via `transcribe_with_whisper`)
- ffmpeg: System-Dependency (muss im PATH liegen)
- Entry: `sprachapp_main.py` → `sprachapp.cli.main()`

## CLI – Golden Path
### Tutor-Flows
- News: `python3 sprachapp_main.py news`
- Book: `python3 sprachapp_main.py book`
- Define: `python3 sprachapp_main.py define`

### Analyse & Feedback
- Report: `python3 sprachapp_main.py report`
- Progress: `python3 sprachapp_main.py report --progress`

### Fokus & Checks
- Fokus (gezielt): `python3 sprachapp_main.py focus q1`
- Systemcheck: `python3 sprachapp_main.py selfcheck`

## Architektur-Hinweise
- Qualitätslogik ist zentralisiert (`compute_quality_flags`)
- Tutor-Module (`news`, `book`, `define`) enthalten **keine** eigene Qualitätsheuristik
- Coach-Ausgabe ist vereinheitlicht (`_print_coach_block`)
- Logs und UX-Ausgabe sind strikt getrennt

## LLM / Backend (MVP6 – Stand: eingefroren)

### Coach-Architektur
- Einheitliches Interface:
  - `CoachRequest` / `CoachResponse`
- Zentrale Backend-Auswahl:
  - `get_coach_backend()`
  - Umschaltung ausschließlich per Env-Var

### Backends
- `MockCoachBackend`
  - Referenz / Offline-Betrieb
- `OpenAICoachBackend`
  - OpenAI Responses API
  - vollständig entkoppelt vom Tutor-Code

### Aktivierung
- Backend-Auswahl:
  - `COACH_BACKEND=mock | openai`
- API-Key:
  - `OPENAI_API_KEY` (aus `sprachapp.env`)

### Logging & Limits (C1)
- Logging aktivieren:
  - `COACH_LOG=1`
- Pro Call (nur Metadaten):
  - mode
  - success
  - latency_ms
  - optional: fallback-Hinweis
- Limits:
  - `COACH_TIMEOUT_S` (Default: 15s)
  - `COACH_MAX_OUTPUT_TOKENS` (Default: 280)
  - `COACH_MAX_CALLS` (Default: 0 = unbegrenzt)

### Fehlerbehandlung
- Klare User-Meldungen bei:
  - Timeout
  - Auth / Billing
  - Rate-Limit
- Automatischer Modell-Fallback bei Fehlern

### Datenschutz
- Keine Transkripte
- Keine Source-Texte
- Keine Prompt-Inhalte im Log

## Hinweise
- Keine Transkripte oder Nutzerinhalte werden geloggt
- Alle Runtime-Daten (Audio/DB) sind **nicht Teil des Repos**