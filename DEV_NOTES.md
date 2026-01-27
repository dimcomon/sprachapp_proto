# Development Notes

## Runtime
- Python: 3.13
- ASR: openai-whisper (lokal, via transcribe_with_whisper)
- ffmpeg: System-Dependency, muss im PATH liegen
- Entry: sprachapp_main.py → sprachapp.cli.main()

## CLI (Golden Path)
- Tutor: python3 sprachapp_main.py news | book
- Analyse: python3 sprachapp_main.py report
- Fokus: python3 sprachapp_main.py focus q1
- Hinweise/Checks: python3 sprachapp_main.py selfcheck

## Architektur-Hinweise
- Qualitätslogik ist zentral und stabil (keine Änderungen ab MVP2)
- Didaktische Anpassungen erfolgen ausschließlich über Prompts
- Fokus-Modus ist manuell (kein Automatismus)