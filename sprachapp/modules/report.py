from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from typing import Any

from sprachapp.core.db import get_con

from collections import defaultdict
from statistics import mean, median


@dataclass
class Row:
    id: int
    created_at: str | None
    topic: str | None
    mode: str | None
    wpm: float | None
    unique_ratio: float | None
    target_rate: float | None
    bonus_rate: float | None
    q3ok: bool | None = None 
    asr_empty: bool | None = None
    low_quality: bool | None = None
    word_count: int | None = None



def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def _pick_stats(payload: dict) -> tuple[float | None, float | None, float | None, float | None]:
    # payload ist dein stats_payload JSON
    wpm = _safe_float(payload.get("wpm"))
    unique_ratio = _safe_float(payload.get("unique_ratio"))

    target_rate = None
    tr = payload.get("target_terms_check")
    if isinstance(tr, dict):
        target_rate = _safe_float(tr.get("rate"))

    bonus_rate = None
    br = payload.get("bonus_terms_check")
    if isinstance(br, dict):
        bonus_rate = _safe_float(br.get("rate"))

    return wpm, unique_ratio, target_rate, bonus_rate


def fetch_last_sessions(last: int = 20, mode: str | None = None) -> list[Row]:
    """
    Erwartete Tabelle: sessions
    Erwartete Spalten: id, topic, mode, stats_payload (JSON-Text), optional created_at
    """
    con = get_con()
    cur = con.cursor()

    base_cols = "id, topic, mode, stats_payload"
    try_sql = "SELECT id, created_at, topic, mode, stats_payload FROM sessions"
    fallback_sql = f"SELECT {base_cols} FROM sessions"

    where = []
    params: list[Any] = []
    if mode:
        where.append("mode = ?")
        params.append(mode)

    order_limit = " ORDER BY id DESC LIMIT ?"
    params2 = params + [int(last)]

    try:
        sql = try_sql + ((" WHERE " + " AND ".join(where)) if where else "") + order_limit
        rows = cur.execute(sql, params2).fetchall()
        has_created_at = True
    except Exception:
        sql = fallback_sql + ((" WHERE " + " AND ".join(where)) if where else "") + order_limit
        rows = cur.execute(sql, params2).fetchall()
        has_created_at = False

    out: list[Row] = []
    for r in rows:
        if has_created_at:
            sid, created_at, topic, mode_val, stats_payload = r
        else:
            sid, topic, mode_val, stats_payload = r
            created_at = None

        payload = {}
        try:
            if isinstance(stats_payload, str) and stats_payload.strip():
                payload = json.loads(stats_payload)
            elif isinstance(stats_payload, (bytes, bytearray)):
                payload = json.loads(stats_payload.decode("utf-8"))
        except Exception:
            payload = {}

        wpm, unique_ratio, target_rate, bonus_rate = _pick_stats(payload)

        asr_empty = None
        if isinstance(payload, dict) and "asr_empty" in payload:
            v = payload.get("asr_empty")
            if v is True:
                asr_empty = True
            elif v is False:
                asr_empty = False

        low_quality = None
        if isinstance(payload, dict) and "low_quality" in payload:
            v = payload.get("low_quality")
            if v is True:
                low_quality = True
            elif v is False:
                low_quality = False

        q3ok = None
        if (mode_val or "") == "q3" and isinstance(payload, dict):
            v = payload.get("q3_has_causal")
            if v is True:
                q3ok = True
            elif v is False:
                q3ok = False

        word_count = None
        if isinstance(payload, dict) and "word_count" in payload:
            try:
                word_count = int(payload.get("word_count"))
            except Exception:
                word_count = None

        out.append(
            Row(
                id=int(sid),
                created_at=created_at,
                topic=topic,
                mode=mode_val,
                wpm=wpm,
                unique_ratio=unique_ratio,
                target_rate=target_rate,
                bonus_rate=bonus_rate,
                q3ok=q3ok,
                asr_empty=asr_empty,
                low_quality=low_quality,
                word_count=word_count,
            )
        )

    con.close()
    return out


def print_table(rows: list[Row]) -> None:
    if not rows:
        print("Keine Sessions gefunden.")
        return

    headers = ["id", "created_at", "mode", "topic", "wpm", "uniq", "target", "bonus", "q3ok"]
    data = []
    for x in rows:
        data.append([
            str(x.id),
            (x.created_at or ""),
            (x.mode or ""),
            (x.topic or ""),
            "" if x.wpm is None else f"{x.wpm:.1f}",
            "" if x.unique_ratio is None else f"{x.unique_ratio:.3f}",
            "" if x.target_rate is None else f"{x.target_rate:.3f}",
            "" if x.bonus_rate is None else f"{x.bonus_rate:.3f}",
            "" if x.q3ok is None else ("Y" if x.q3ok else "N"),
        ])

    # einfache Spaltenbreiten
    widths = [len(h) for h in headers]
    for row in data:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(row: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

    print(fmt_row(headers))
    print(fmt_row(["-" * w for w in widths]))
    for row in data:
        print(fmt_row(row))


def write_csv(rows: list[Row], out_path: str) -> None:
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "created_at", "topic", "mode", "wpm", "unique_ratio", "target_rate", "bonus_rate"])
        for x in rows:
            w.writerow([
                x.id,
                x.created_at or "",
                x.topic or "",
                x.mode or "",
                "" if x.wpm is None else f"{x.wpm:.1f}",
                "" if x.unique_ratio is None else f"{x.unique_ratio:.4f}",
                "" if x.target_rate is None else f"{x.target_rate:.4f}",
                "" if x.bonus_rate is None else f"{x.bonus_rate:.4f}",
            ])
    print(f"CSV geschrieben: {out_path}")


def print_summary(rows: list[Row]) -> None:
    if not rows:
        print("Keine Sessions gefunden.")
        return

    groups = defaultdict(list)
    for r in rows:
        groups[r.mode or ""] .append(r)

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else mean(vals)

    print("SUMMARY (Durchschnittswerte):")
    for mode, items in sorted(groups.items()):
        wpm = avg([x.wpm for x in items])
        uniq = avg([x.unique_ratio for x in items])
        targ = avg([x.target_rate for x in items])
        bon = avg([x.bonus_rate for x in items])

        def f(x, d=1):
            if x is None:
                return "-"
            return f"{x:.{d}f}"

        # Empty-ASR Rate (nur wo asr_empty gesetzt ist)
        empties = [x.asr_empty for x in items if x.asr_empty is not None]
        empty_rate = None
        if empties:
            empty_rate = sum(1 for v in empties if v is True) / len(empties)

        # Q3-OK Rate (nur für q3, nur wo q3ok gesetzt ist)
        q3oks = [x.q3ok for x in items if x.q3ok is not None]
        q3ok_rate = None
        if q3oks:
            q3ok_rate = sum(1 for v in q3oks if v is True) / len(q3oks)

        extra = []
        extra.append(f"empty={f(empty_rate,2)}")
        if mode == "q3":
            extra.append(f"q3ok={f(q3ok_rate,2)}")

        print(
            f"- {mode:6s} | n={len(items):3d} | wpm={f(wpm,1)} | uniq={f(uniq,3)} | target={f(targ,3)} | bonus={f(bon,3)} | "
            + " | ".join(extra)
        )
def print_progress(rows: list[Row]) -> None:
    if not rows:
        print("Keine Sessions gefunden.")
        return

    groups = defaultdict(list)
    for r in rows:
        groups[(r.mode or "").strip()].append(r)

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else mean(vals)

    def _median(vals):
        vals = [v for v in vals if v is not None]
        return None if not vals else median(vals)

    def rate_bool(vals, want=True):
        vals = [v for v in vals if v is not None]
        if not vals:
            return None
        return sum(1 for v in vals if v is want) / len(vals)

    def f(x, d=2):
        if x is None:
            return "-"
        return f"{x:.{d}f}"

    print("PROGRESS (je Modus, Median für wpm/uniq):")
    best_reco = None
    best_prio = 999  # kleiner = wichtiger
    for mode, items in sorted(groups.items()):
        wpm = _median([x.wpm for x in items])
        uniq = _median([x.unique_ratio for x in items])
        lowq = rate_bool([x.low_quality for x in items], want=True)
        empty = rate_bool([x.asr_empty for x in items], want=True)
        extra = [f"lowq={f(lowq,2)}", f"empty={f(empty,2)}"]
        wc = _median([x.word_count for x in items])

        if mode == "q3":
            q3ok = rate_bool([x.q3ok for x in items], want=True)
            extra.append(f"q3ok={f(q3ok,2)}")

        print(
            f"- {mode:6s} | n={len(items):3d} | wc={f(wc,0)} | wpm={f(wpm,1)} | uniq={f(uniq,3)} | "
            + " | ".join(extra)
        )

        # Diagnose (rein aus Quoten, keine neue Heuristik)
        notes = []
        if lowq is not None and lowq >= 0.34:
            notes.append("CHECK: häufige Qualitätsprobleme")
        if empty is not None and empty >= 0.34:
            notes.append("CHECK: häufig ASR-leer")
        if notes:
            print(f"  -> {mode:6s} | " + " | ".join(notes))
            if lowq is not None and lowq >= 0.34:
                print(f"     TIPP: kürzer wiederholen; 1–2 klare Sätze, näher ans Mikro")
            if empty is not None and empty >= 0.34:
                print(f"     TIPP: Eingabegerät, Pegel (Gain) und Umgebungsgeräusche prüfen")
        
        # Empfehlung (B2.2): Kandidaten sammeln (global wird 1x gedruckt)
        reco = None
        prio = None

        if empty is not None and empty >= 0.34:
            prio = 1
            reco = f"NEXT (global): Technik – Eingabegerät/Pegel prüfen, 1 Testaufnahme (selfcheck --smoke-asr)"

        elif lowq is not None and lowq >= 0.34:
            prio = 2
            reco = f"NEXT (global): Qualität – 3x sehr kurz (1–2 Sätze), näher ans Mikro, danach erneut q1/retell"

        elif wc is not None and wc < 12:
            prio = 3
            reco = f"NEXT (global): Länge – mindestens 2 Sätze / ~20 Wörter"

        elif uniq is not None and uniq < 0.55:
            prio = 4
            reco = f"NEXT (global): Wortschatz – vermeide Wiederholung, nutze 2 Synonyme/Umformulierungen."

        if reco and prio is not None and prio < best_prio:
            best_prio = prio
            best_reco = reco
    if best_reco:
        print(best_reco)


