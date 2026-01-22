from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import sys
import traceback
import shutil
import subprocess
import wave
import struct
import math
import json


from sprachapp.core.db import DB_PATH, ensure_db, get_con


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _run_import_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    modules = [
        "sprachapp.cli",
        "sprachapp.core.db",
        "sprachapp.core.stats",
        "sprachapp.modules.tutor_book",
        "sprachapp.modules.tutor_news",      # NEU
        "sprachapp.modules._tutor_common",   # NEU
        "sprachapp.modules.report",
    ]
    for m in modules:
        try:
            __import__(m)
            results.append(CheckResult(f"import:{m}", True, "OK"))
        except Exception as e:
            results.append(CheckResult(f"import:{m}", False, f"{type(e).__name__}: {e}"))
    return results


def _run_db_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        ensure_db()
        results.append(CheckResult("db:ensure_db", True, "OK"))
    except Exception as e:
        results.append(CheckResult("db:ensure_db", False, f"{type(e).__name__}: {e}"))
        return results

    # Datei existiert?
    try:
        exists = Path(DB_PATH).exists()
        results.append(CheckResult("db:file_exists", exists, str(DB_PATH)))
        if not exists:
            return results
    except Exception as e:
        results.append(CheckResult("db:file_exists", False, f"{type(e).__name__}: {e}"))
        return results

    # Verbindung + Tabellen
    try:
        con = get_con()
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        con.close()
        results.append(CheckResult("db:connect", True, "OK"))
        results.append(CheckResult("db:tables", True, ", ".join(tables) if tables else "(none)"))
        results.append(CheckResult("db:has_sessions", "sessions" in tables, "sessions" if "sessions" in tables else "missing"))
    except Exception as e:
        results.append(CheckResult("db:connect/tables", False, f"{type(e).__name__}: {e}"))
        return results

    # created_at Spalte?
    try:
        con = get_con()
        cur = con.cursor()
        cur.execute("PRAGMA table_info(sessions)")
        cols = [r[1] for r in cur.fetchall()]
        con.close()
        results.append(CheckResult("db:sessions_columns", True, ", ".join(cols)))
        results.append(CheckResult("db:has_created_at", "created_at" in cols, "created_at" if "created_at" in cols else "missing"))
    except Exception as e:
        results.append(CheckResult("db:sessions_columns", False, f"{type(e).__name__}: {e}"))

    # Sessions count
    try:
        con = get_con()
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM sessions")
        n = int(cur.fetchone()[0])
        con.close()
        results.append(CheckResult("db:sessions_count", True, str(n)))
    except Exception as e:
        results.append(CheckResult("db:sessions_count", False, f"{type(e).__name__}: {e}"))

    return results


def _run_audio_path_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    audio_dir = Path("data/audio")

    try:
        audio_dir.parent.mkdir(parents=True, exist_ok=True)
        results.append(CheckResult("fs:data_dir", True, str(audio_dir.parent.resolve())))
    except Exception as e:
        results.append(CheckResult("fs:data_dir", False, f"{type(e).__name__}: {e}"))
        return results

    try:
        audio_dir.mkdir(parents=True, exist_ok=True)
        results.append(CheckResult("fs:audio_dir_exists", audio_dir.exists() and audio_dir.is_dir(), str(audio_dir.resolve())))
    except Exception as e:
        results.append(CheckResult("fs:audio_dir_exists", False, f"{type(e).__name__}: {e}"))
        return results

    # Schreibtest: Datei anlegen/löschen
    try:
        tmp = audio_dir / ".selfcheck_write_test"
        tmp.write_text("ok", encoding="utf-8")
        tmp.unlink(missing_ok=True)
        results.append(CheckResult("fs:audio_dir_writable", True, "OK"))
    except Exception as e:
        results.append(CheckResult("fs:audio_dir_writable", False, f"{type(e).__name__}: {e}"))

    return results


def _run_report_pipeline_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        from sprachapp.modules.report import fetch_last_sessions
        rows = fetch_last_sessions(last=3, mode=None)
        results.append(CheckResult("report:fetch_last_sessions", True, f"rows={len(rows)}"))
    except Exception as e:
        results.append(CheckResult("report:fetch_last_sessions", False, f"{type(e).__name__}: {e}"))
    return results


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _run_payload_checks(sample_n: int = 20) -> list[CheckResult]:
    results: list[CheckResult] = []

    # Minimal-Keys, die compute_stats typischerweise liefert
    required_keys = {
        "word_count",
        "unique_words",
        "unique_ratio",
        "avg_word_len",
        "filler_count",
    }

    # Optionale Keys, die je nach Mode ergänzt werden
    optional_num_keys = {"duration_seconds", "wpm"}
    optional_dict_keys = {"target_terms_check", "bonus_terms_check"}

    try:
        con = get_con()
        cur = con.cursor()
        rows = cur.execute(
            "SELECT id, mode, stats_payload FROM sessions ORDER BY id DESC LIMIT ?",
            (int(sample_n),),
        ).fetchall()
        con.close()
    except Exception as e:
        results.append(CheckResult("db:payload_fetch", False, f"{type(e).__name__}: {e}"))
        return results

    if not rows:
        results.append(CheckResult("db:payload_validate", True, "no sessions (skipped)"))
        return results

    bad_json: list[int] = []
    missing_required: list[int] = []
    bad_types: list[int] = []

    for sid, mode, stats_payload in rows:
        # 1) JSON parse
        payload = None
        try:
            if isinstance(stats_payload, dict):
                payload = stats_payload
            elif isinstance(stats_payload, (bytes, bytearray)):
                payload = json.loads(stats_payload.decode("utf-8"))
            elif isinstance(stats_payload, str):
                payload = json.loads(stats_payload) if stats_payload.strip() else {}
            else:
                payload = {}
        except Exception:
            bad_json.append(int(sid))
            continue

        if not isinstance(payload, dict):
            bad_json.append(int(sid))
            continue

        # 2) Required keys vorhanden?
        if not required_keys.issubset(payload.keys()):
            missing_required.append(int(sid))
            continue

        # 3) Typchecks (minimal, robust)
        # required
        if not isinstance(payload.get("word_count"), int): bad_types.append(int(sid)); continue
        if not isinstance(payload.get("unique_words"), int): bad_types.append(int(sid)); continue
        if not _is_num(payload.get("unique_ratio")): bad_types.append(int(sid)); continue
        if not _is_num(payload.get("avg_word_len")): bad_types.append(int(sid)); continue
        if not isinstance(payload.get("filler_count"), int): bad_types.append(int(sid)); continue

        # optional numeric
        for k in optional_num_keys:
            if k in payload and payload[k] is not None and not _is_num(payload[k]):
                bad_types.append(int(sid))
                break
        else:
            # optional dicts (target/bonus checks)
            for k in optional_dict_keys:
                if k in payload and payload[k] is not None and not isinstance(payload[k], dict):
                    bad_types.append(int(sid))
                    break

    # Zusammenfassung
    ok = (len(bad_json) == 0 and len(missing_required) == 0 and len(bad_types) == 0)

    results.append(CheckResult("db:payload_validate", ok, f"checked={len(rows)}"))
    if bad_json:
        results.append(CheckResult("db:payload_bad_json", False, f"ids={bad_json[:10]}{'...' if len(bad_json)>10 else ''}"))
    else:
        results.append(CheckResult("db:payload_bad_json", True, "OK"))

    if missing_required:
        results.append(CheckResult("db:payload_missing_required", False, f"ids={missing_required[:10]}{'...' if len(missing_required)>10 else ''}"))
    else:
        results.append(CheckResult("db:payload_missing_required", True, "OK"))

    if bad_types:
        results.append(CheckResult("db:payload_bad_types", False, f"ids={bad_types[:10]}{'...' if len(bad_types)>10 else ''}"))
    else:
        results.append(CheckResult("db:payload_bad_types", True, "OK"))

    return results


def run_selfcheck(verbose: bool = False, load_model: bool = False, list_devices: bool = False, smoke_asr: bool = False) -> int:
    checks: list[CheckResult] = []
    checks += _run_import_checks()
    checks += _run_ffmpeg_checks()
    checks += _run_db_checks()
    checks += _run_audio_path_checks()
    checks += _run_report_pipeline_checks()
    checks += _run_whisper_checks(load_model=load_model)
    checks += _run_sounddevice_checks(list_devices=list_devices)
    checks += _run_asr_smoke_test(run_asr=smoke_asr)
    checks += _run_payload_checks(sample_n=50)

    ok_all = all(c.ok for c in checks)

    print("\nSELF-CHECK RESULT:", "OK" if ok_all else "FAIL")
    print("-" * 80)
    for c in checks:
        status = "OK " if c.ok else "ERR"
        print(f"{status}  {c.name:<28}  {c.detail}")
    print("-" * 80)

    if (not ok_all) and verbose:
        print("\nVERBOSE TRACE (first error):")
        for c in checks:
            if not c.ok:
                # Best-effort: show a traceback for import/db errors only when they happen live
                # (Most errors already contain enough detail; this is a safety valve.)
                break

    return 0 if ok_all else 1


# Check-Bereich Erweitert
def _run_ffmpeg_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    path = shutil.which("ffmpeg")
    results.append(CheckResult("bin:ffmpeg_in_path", bool(path), path or "not found"))
    if not path:
        return results

    try:
        p = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=5)
        ok = (p.returncode == 0)
        first = (p.stdout.splitlines()[0] if p.stdout else "").strip()
        results.append(CheckResult("bin:ffmpeg_runs", ok, first or f"rc={p.returncode}"))
    except Exception as e:
        results.append(CheckResult("bin:ffmpeg_runs", False, f"{type(e).__name__}: {e}"))
    return results


def _run_whisper_checks(load_model: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        import whisper  # type: ignore
        results.append(CheckResult("asr:whisper_import", True, "OK"))
    except Exception as e:
        results.append(CheckResult("asr:whisper_import", False, f"{type(e).__name__}: {e}"))
        return results

    if not load_model:
        results.append(CheckResult("asr:whisper_model_load", True, "skipped (--load-model off)"))
        return results

    try:
        import whisper  # type: ignore
        whisper.load_model("base")
        results.append(CheckResult("asr:whisper_model_load", True, "base"))
    except Exception as e:
        results.append(CheckResult("asr:whisper_model_load", False, f"{type(e).__name__}: {e}"))
    return results


def _write_test_wav(path: Path, seconds: float = 1.0, sr: int = 16000) -> None:
    """
    Erzeugt eine kurze Test-WAV (leiser Sinuston), damit ASR nicht komplett leer ist.
    16-bit PCM, mono, 16kHz.
    """
    n = int(seconds * sr)
    freq = 440.0
    amp = 800  # sehr leise (max 32767)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        for i in range(n):
            sample = int(amp * math.sin(2.0 * math.pi * freq * (i / sr)))
            wf.writeframes(struct.pack("<h", sample))


def _run_asr_smoke_test(run_asr: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []
    if not run_asr:
        results.append(CheckResult("asr:smoke_test", True, "skipped (--smoke-asr off)"))
        return results

    # Import eurer Pipeline
    try:
        from sprachapp.core.asr import transcribe_with_whisper
        results.append(CheckResult("asr:smoke_import_pipeline", True, "OK"))
    except Exception as e:
        results.append(CheckResult("asr:smoke_import_pipeline", False, f"{type(e).__name__}: {e}"))
        return results

    audio_dir = Path("data/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    tmp_wav = audio_dir / ".selfcheck_asr_smoke.wav"

    try:
        _write_test_wav(tmp_wav, seconds=1.0, sr=16000)
        results.append(CheckResult("asr:smoke_wav_created", True, str(tmp_wav)))
    except Exception as e:
        results.append(CheckResult("asr:smoke_wav_created", False, f"{type(e).__name__}: {e}"))
        return results

    # Transkribieren (muss durchlaufen, Text kann leer/kurz sein)
    try:
        text = transcribe_with_whisper(str(tmp_wav))
        # nicht inhaltlich bewerten, nur "läuft" und liefert str
        ok = isinstance(text, str)
        detail = (text.strip()[:60] + ("..." if len(text.strip()) > 60 else "")) if ok else "not a str"
        results.append(CheckResult("asr:smoke_transcribe_runs", ok, detail if detail else "(empty/ok)"))
    except Exception as e:
        results.append(CheckResult("asr:smoke_transcribe_runs", False, f"{type(e).__name__}: {e}"))
    finally:
        try:
            tmp_wav.unlink(missing_ok=True)
            results.append(CheckResult("asr:smoke_cleanup", True, "OK"))
        except Exception as e:
            results.append(CheckResult("asr:smoke_cleanup", False, f"{type(e).__name__}: {e}"))

    return results


def _run_sounddevice_checks(list_devices: bool = False) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        import sounddevice as sd  # type: ignore
        results.append(CheckResult("audio:sounddevice_import", True, "OK"))
    except Exception as e:
        results.append(CheckResult("audio:sounddevice_import", False, f"{type(e).__name__}: {e}"))
        return results

    try:
        devs = sd.query_devices()
        results.append(CheckResult("audio:devices_found", True, f"count={len(devs)}"))
        if list_devices:
            inputs = []
            for i, d in enumerate(devs):
                if int(d.get("max_input_channels", 0)) > 0:
                    inputs.append(f"[{i}] {d.get('name')} (in:{d.get('max_input_channels')})")
            detail = " | ".join(inputs) if inputs else "(no input devices)"
            results.append(CheckResult("audio:input_devices", True, detail))
        else:
            results.append(CheckResult("audio:input_devices", True, "skipped (--list-devices off)"))
    except Exception as e:
        results.append(CheckResult("audio:devices_query", False, f"{type(e).__name__}: {e}"))

    return results


