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