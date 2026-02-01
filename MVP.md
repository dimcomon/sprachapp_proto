# SprachApp – MVP-Übersicht (Source of Truth)

Diese Datei ist die verbindliche Übersicht über den Entwicklungsstand
und die geplanten Schritte bis zur fertigen App.

---

## MVP1 – Basis (abgeschlossen)
- CLI-Grundstruktur
- Audioaufnahme + ASR (Whisper lokal)
- Transkript + Basis-Statistiken
- Retell / einfache Fragen
- Speicherung von Sessions

Status: ✅ abgeschlossen

---

## MVP2 – Tutor-Flows (abgeschlossen)
- News- und Book-Tutor
- Chunking von Texten
- Retell + Q1–Q3
- Persistente Sessions
- Wiederholungs- und Next-Logik

Status: ✅ abgeschlossen

---

## MVP3 – Analyse & Qualität (abgeschlossen)
- Zentrale Qualitätslogik (Flags, low_quality)
- Einheitliche Warn- und Debug-Ausgabe
- Report / Stats / Progress
- Filter (low_quality, empty)
- CSV-Export

Status: ✅ abgeschlossen

---

## MVP4 – Didaktik & Lernsteuerung (abgeschlossen, eingefroren)
- Einheitliche Q1–Q3-Didaktik
- Schwierigkeitsstufen (easy / medium / hard)
- Sprachliche Variation (Prompts)
- Vorbereitung (prep: enter / timed / none)
- Fokus-Modus (focus qX)
- Define-Tutor (Begriff → Retell → Q1–Q3)
- Konsolidierter Coach-Output
- Verkürzte Defaults, steuerbar per CLI
- Code-Hygiene, Freeze, Tag

Status: ✅ abgeschlossen (eingefroren)

---

## MVP5 – Coach & Feedback (abgeschlossen)
- Zentrale Coach-Ausgabe
- Coach liest:
  - Modus (retell, q1–q3)
  - Transkript
  - vorhandene Stats / Flags
- Ausgabe:
  - Textbasiert (CLI)
  - Keine neue Qualitätslogik
  - Kein neues DB-Schema
- Einheitlich integriert in:
  - news
  - book
  - define
- Basis für spätere KI-/Backend-Anbindung

Status: ✅ abgeschlossen

---

## MVP6 – Backend-Trennung (geplant)
Ziel: App-fähige Architektur vorbereiten.

- Backend-Interface für Coach
- Austauschbare Implementierungen:
  - OpenAI
  - Mock / lokal
- Feature-Flag (Backend-Auswahl)
- Tutor-Code kennt kein OpenAI mehr direkt

Status: ⏳ geplant

---

## MVP7 – Server & API (geplant)
- Client/Server-Trennung
- REST / WebSocket API
- Audio-Upload / Streaming
- Session-Handling serverseitig
- Nutzerkontext / Auth-Grundlage

Status: ⏳ geplant

---

## MVP8 – iOS App (geplant)
- SwiftUI App
- Voice UX (Start/Stop/Prep)
- Anzeige von Coach-Feedback
- Fortschritt & Verlauf
- Onboarding

Status: ⏳ geplant