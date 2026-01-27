# MVP3 – Weiterentwicklung

Ziel: Funktionale Erweiterungen auf stabiler MVP2-Basis (keine Änderungen an Qualitätslogik).

- Entscheidung: `stats` bleibt Analyse-Subcommand (Report/DB-Auswertung) und ist kein Teil der Tutor-Flows (`news` / `book`).
- `report` ist Alias für `stats`
- `--progress`: Median von `wc` / `wpm` / `uniq` sowie Quoten für `lowq` / `empty` je Modus
- Diagnosezeile bei `lowq >= 0.34` oder `empty >= 0.34`
- Tippzeile unter Diagnose (deutsch)
- Filter: `--only-lowq`, `--only-empty`
- CSV wird auch bei 0 Treffern geschrieben (nur Header)
- Neuer CLI-Modus: `focus q1` für gezieltes, kurzes Wiederholen
- Sessions werden normal gespeichert, kein Eingriff in Chunk- oder Lernfortschritt
- Auswertung anschließend über `report --progress`
- `focus retell` für kurzes Retell-Training (z. B. 2 Runden à 0.5 min)

## Status
MVP3 abgeschlossen.

Enthält:
- Fortschrittsanalyse (Median/Quoten)
- Diagnose + Tipps (deutsch)
- Fokus-Modus (q1/q2/q3/retell)
- Empfohlener Fokus (heuristikfrei)
- Vollständig getestete Regressionen

Selfcheck: OK