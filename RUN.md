# sprachapp_proto – Local Run

## Requirements
- Python 3.13
- ffmpeg (System-Dependency, im PATH)

## Setup
python3.13 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

pip install torch whisper sounddevice numpy

## ffmpeg Check
ffmpeg -version

## Run (Golden Path)
python3 sprachapp_main.py news
python3 sprachapp_main.py book
python3 sprachapp_main.py selfcheck

### Focus (gezieltes Üben)
# 3x Frage 1 (These) kurz üben
python3 sprachapp_main.py focus q1 --rounds 3 --q-seconds 15
# 2x Retell kurz üben (30s pro Runde)
python3 sprachapp_main.py focus retell --rounds 2 --minutes 0.5

# danach Fortschritt ansehen
python3 sprachapp_main.py report --progress --last 200
