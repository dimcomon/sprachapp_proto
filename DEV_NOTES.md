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

## LLM / Backend (MVP6)
- LLM-Coach optional (env-gesteuert)
  - `COACH_USE_LLM=1` aktiviert LLM
  - Fallback auf Stub bei Fehlern
- Minimales Logging (keine Inhalte)
  - Aktivieren mit `COACH_LOG=1`
  - Pro Call: mode, success, latency_ms
- Timeouts & Limits:
  - `COACH_TIMEOUT_S` (Default: 12s)
  - `COACH_MAX_OUTPUT_TOKENS` (Default: 250)

## Hinweise
- Keine Transkripte oder Nutzerinhalte werden geloggt
- Alle Runtime-Daten (Audio/DB) sind **nicht Teil des Repos**