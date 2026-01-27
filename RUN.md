# sprachapp_proto – Local Run

## Requirements
- Python 3.13
- ffmpeg (System-Dependency, im PATH)

## Setup
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

pip install torch openai-whisper sounddevice numpy

## ffmpeg Check
ffmpeg -version

## Run (Golden Path)
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
