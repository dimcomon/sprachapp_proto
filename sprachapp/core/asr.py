def transcribe_with_whisper(audio_path: str) -> str:
    import whisper  # type: ignore

    # CPU: small ist guter Kompromiss
    model = whisper.load_model("small")
    result = model.transcribe(
        audio_path,
        language="de",
        task="transcribe",
        fp16=False,
        temperature=0.0,
        condition_on_previous_text=False,
    )
    return (result.get("text") or "").strip()