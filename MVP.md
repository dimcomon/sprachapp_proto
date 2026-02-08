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

## MVP6 – KI-Coach & Backend-Trennung (abgeschlossen, eingefroren)

Ziel: App-fähige Architektur für KI-Feedback, sauber entkoppelt vom Tutor-Code.

### MVP6-A – Architektur & Entkopplung (abgeschlossen)
- Einheitliches Coach-Interface:
  - CoachRequest / CoachResponse
- Zentrale Backend-Auswahl über Factory:
  - get_coach_backend()
  - Umschaltung per Env-Var (COACH_BACKEND)
- MockCoachBackend als Referenz-Implementierung
- Zentrale Ausgabe:
  - print_coach_block()
- Tutor-Code kennt kein OpenAI / kein externes Backend mehr
- Alt-Code (coach.py) obsolet, aber noch vorhanden

Status: ✅ abgeschlossen (eingefroren)

---

### MVP6-B – OpenAI-Backend & Qualitätsintegration (abgeschlossen)
- OpenAICoachBackend (Responses API)
- Umschaltung ausschließlich per Env-Var:
  - COACH_BACKEND=openai
- Einheitliche, strikt strukturierte Coach-Antwort:
  - Einschätzung
  - Verbesserungen
  - Fokus
- Mode-spezifische Didaktik:
  - retell / q1 / q2 / q3
- ASR-/Qualitäts-Integration:
  - QWARN / low_quality / too_short / silence
  - Coach reagiert mit Aufnahme-Hinweisen statt Inhaltskritik
- Fallback-Mechanismus bei Backend-Fehlern
- C1: Logging & Limits:
  - Latenz-Logging
  - Modell-/Fallback-Transparenz
  - Token-Limit
  - Optionales Call-Limit pro Session
- Getestet mit:
  - news
  - book
  - define (alt, eingefroren)

Status: ✅ abgeschlossen (eingefroren, Tag: mvp6-b-freeze)

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