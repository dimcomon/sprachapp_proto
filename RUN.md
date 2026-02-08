# sprachapp_proto – Local Run

## Requirements
- Python 3.13
- ffmpeg (System-Dependency, im PATH)

## Setup
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

pip install -r requirements.txt

## Environment (.env)
Die App liest Konfiguration aus `sprachapp.env` im Projekt-Root.

Minimal erforderlich:
OPENAI_API_KEY=sk-...
COACH_BACKEND=openai

Optional (C1 – Logging & Limits):
COACH_LOG=1
COACH_MAX_OUTPUT_TOKENS=280
COACH_MAX_CALLS=0

## ffmpeg Check
ffmpeg -version

## Run (Golden Path)
Hinweis:
- Standardmäßig wird das Mock-Backend genutzt.
- Für KI-Feedback:
  - COACH_BACKEND=openai in sprachapp.env setzen.
  
# News Tutor
python3 sprachapp_main.py news --news-file news.txt --level easy --retell-seconds 60

# Book Tutor
python3 sprachapp_main.py book --book-file book.txt --level easy --retell-seconds 60

# Report / Progress
python3 sprachapp_main.py report --progress --last 200

## Fokus (manuell)
# gezielt Q1 üben
python3 sprachapp_main.py focus q1 --rounds 3 --q-seconds 15

## Abbrechen
# In Vorbereitung oder während Aufnahme:
# Ctrl+C -> "Abgebrochen." (kein Traceback)

### Focus (gezieltes Üben)
# 3x Frage 1 (These) kurz üben
python3 sprachapp_main.py focus q1 --rounds 3 --q-seconds 15
# 2x Retell kurz üben (30s pro Runde)
python3 sprachapp_main.py focus retell --rounds 2 --minutes 0.5

# danach Fortschritt ansehen
python3 sprachapp_main.py report --progress --last 200
