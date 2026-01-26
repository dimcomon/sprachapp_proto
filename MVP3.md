# MVP3 – Weiterentwicklung

Ziel: Funktionale Erweiterungen auf stabiler MVP2-Basis (keine Änderungen an Qualitätslogik).
- Entscheidung: `stats` bleibt Analyse-Subcommand (Report/DB-Auswertung) und ist kein Teil der Tutor-Flows (`news`/`book`).
-report ist Alias für stats
- --progress: Median wc/wpm/uniq + Quoten lowq/empty je Modus
-Diagnosezeile bei lowq>=0.34 / empty>=0.34
-Tippzeile unter Diagnose (deutsch)
-Filter: --only-lowq, --only-empty
-CSV wird auch bei 0 Treffern geschrieben (Header-only)
