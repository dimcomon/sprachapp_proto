# SprachApp – MVP-Übersicht

## MVP1 – Basis
- CLI-Grundstruktur
- Audioaufnahme + ASR (Whisper)
- Wiedergabe (Retell) / einfache Fragen
Status: abgeschlossen

## MVP2 – Tutor-Flows
- News- und Book-Tutor
- Chunking
- Q1–Q3
- Speicherung von Sessions
Status: abgeschlossen

## MVP3 – Analyse & Qualität
- Zentrale Qualitätslogik (Flags, low_quality)
- Einheitliche Warn- und Debug-Ausgabe
- Report / Stats / Progress-Ansicht
- Filter (low_quality, empty)
Status: abgeschlossen

## MVP4 – Didaktik & Lernsteuerung
- Schwierigkeitsstufen (easy / medium / hard)
- Themen-Varianz (Perspektive, Fokus)
- Sprachliche Variation (Umformulieren, Synonyme)
- Manueller Fokus-Modus
- Define-Tutor (Begriff erklären → Wiedergabe → Q1–Q3)
Status: abgeschlossen (eingefroren)

## MVP5-A – Coach (Stub)
- Erste Coaching-Ebene über bestehende Sessions
- Coach liest:
  - Modus (Wiedergabe, Q1–Q3)
  - Transkript
  - vorhandene Stats / Flags
- Ausgabe:
  - Nur Text (CLI)
  - Keine neue Qualitätslogik
  - Kein neues DB-Schema
- Integration in:
  - define
  - news
  - book
- Vorbereitung für:
  - spätere KI-/LLM-Anbindung
  - App-Frontend (iOS)
Status: in Arbeit

## Coach (MVP5-A)

### Define mit Coach
```bash
python3 sprachapp_main.py define --term "endoskop"