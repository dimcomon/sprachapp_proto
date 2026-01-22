# SprachApp Proto (MVP2)

## Status
- Version/Tag: v0.2.0
- Ziel: stabile Tutor-Flows (book/news) mit einheitlichen Quality-Flags und genau einem Warning-Block pro Aufnahme.

## Start (CLI)
### Selfcheck
python3 sprachapp_main.py selfcheck
python3 sprachapp_main.py selfcheck --smoke-asr

### News
python3 sprachapp_main.py news --news-file news.txt --repeat --device 0 --minutes 0.3 --questions 3 --q-seconds 10 --prep none

### Book
python3 sprachapp_main.py book --book-file book.txt --repeat --device 0 --minutes 0.3 --questions 3 --q-seconds 10 --prep none

## Daten
- SQLite DB: data/sprachapp.sqlite3
- Audio: data/audio/

## Quality Flags (Payload)
- asr_empty
- retell_empty
- too_short
- suspected_silence
- hallucination_hit
- stopword_ratio
- low_quality
- q3_has_causal (nur q3)

## Hinweis
Wenn Whisper „Geistertext“ erzeugt (z.B. bei Stille), wird low_quality gesetzt und es erscheint genau ein Warnblock.