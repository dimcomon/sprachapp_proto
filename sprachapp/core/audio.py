from __future__ import annotations
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write as wav_write

def list_input_devices():
    devs = sd.query_devices()
    for i, d in enumerate(devs):
        if d.get("max_input_channels", 0) > 0:
            print(f"[{i}] {d['name']} (in:{d['max_input_channels']})")

def wav_duration_seconds(path: Path) -> float:
    import wave
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return frames / float(rate)

def cleanup_audio_retention(audio_dir: Path, keep_last: int = 0, keep_days: int = 0):
    if not audio_dir.exists():
        return

    files = sorted(
        [p for p in audio_dir.glob("*.wav") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if keep_last and keep_last > 0:
        for p in files[keep_last:]:
            try:
                p.unlink()
            except Exception:
                pass

    if keep_days and keep_days > 0:
        cutoff = time.time() - (keep_days * 86400)
        for p in files:
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
            except Exception:
                pass

def record_mic_to_wav(
    out_path: Path,
    minutes: float = 2.0,
    channels: int = 1,
    device: int | None = None,
):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Device validieren
    try:
        if device is not None:
            sd.query_devices(device, "input")
    except Exception:
        print(f"Warnung: device {device} ist ungültig. Fallback auf Default-Mikrofon.")
        device = None

    # bevorzugt 16 kHz, sonst fallback
    try:
        sample_rate = 16000
        sd.check_input_settings(device=device, samplerate=sample_rate, channels=channels)
    except Exception:
        dev = sd.query_devices(device, "input") if device is not None else sd.query_devices(None, "input")
        sample_rate = int(dev["default_samplerate"])

    seconds = max(1.0, minutes * 60.0)
    frames = int(sample_rate * seconds)

    print(f"Aufnahme (blockierend)... {seconds:.0f}s @ {sample_rate} Hz, device={device}")
    audio = sd.rec(frames, samplerate=sample_rate, channels=channels, dtype="float32", device=device)
    sd.wait()

    audio_i16 = np.clip(audio, -1.0, 1.0)
    audio_i16 = (audio_i16 * 32767.0).astype(np.int16)

    wav_write(str(out_path), sample_rate, audio_i16)
    print(f"Saved: {out_path}")