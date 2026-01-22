import re

def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s

def cut_at_punkt(text: str) -> str:
    t = text.strip()
    if not t:
        return t

    # tolerant: punkt, punkt., punkt! punkt? (case-insensitive)
    m = list(re.finditer(r"\bpunkt\b[.!?]?", t, flags=re.IGNORECASE))
    if not m:
        return t

    last = m[-1].start()
    return t[:last].strip()

def tokenize_words_de(s: str) -> list[str]:
    return re.findall(r"[a-zäöüß]+", s.lower())

def overlap_metrics(source: str, spoken: str) -> dict:
    sw = tokenize_words_de(normalize_text(source))
    tw = tokenize_words_de(normalize_text(spoken))
    if not sw or not tw:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    sset, tset = set(sw), set(tw)
    inter = len(sset & tset)
    precision = inter / len(tset)
    recall = inter / len(sset)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}