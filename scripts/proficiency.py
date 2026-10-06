"""Versioned, evidence-backed monologue ratings; never infer them from CEFR labels."""
import hashlib
import json
import math
from datetime import datetime, timezone

VERSION = "narralogue-0-100-v1"
DIMENSIONS = ("range", "accuracy", "coherence", "fluency")
INPUTS = ("transcript.txt", "transcript.json", "metrics.json", "source.json")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return " ".join(text.split())


def calculate(rating, transcript):
    """Validate authored evidence and deterministically calculate the displayed integer."""
    if not isinstance(rating, dict) or rating.get("rubric_version") != VERSION:
        raise ValueError("missing or unsupported proficiency rubric_version")
    for key in ("rater", "limitations", "summary"):
        if not isinstance(rating.get(key), str) or not rating[key].strip():
            raise ValueError(f"proficiency requires {key}")
    if rating.get("status") == "withheld":
        if rating.get("dimensions"):
            raise ValueError("withheld ratings must not contain scored dimensions")
        return None
    if rating.get("status") != "rated":
        raise ValueError("status must be rated or withheld")
    parts = rating.get("dimensions")
    if not isinstance(parts, dict) or set(parts) != set(DIMENSIONS):
        raise ValueError("all four dimensions are required; missing is not zero")
    for key, part in parts.items():
        if not isinstance(part, dict):
            raise ValueError(f"invalid {key} dimension")
        band = part.get("band")
        if (type(band) not in (int, float) or not math.isfinite(band)
                or not 0 <= band <= 6 or band * 4 != int(band * 4)):
            raise ValueError(f"{key}: band must be 0–6 in quarter-band steps")
        if not isinstance(part.get("rationale"), str) or not part["rationale"].strip():
            raise ValueError(f"{key}: missing rationale")
        quotes = part.get("quotes")
        if not isinstance(quotes, list) or not quotes:
            raise ValueError(f"{key}: at least one transcript quote is required")
        for quote in quotes:
            if (not isinstance(quote, str) or not quote.strip()
                    or normalized(quote) not in normalized(transcript)):
                raise ValueError(f"{key}: quote is not present in the transcript")
    # Equal 25% weights. Explicit half-up rounding, not Python's banker's rounding.
    return math.floor(sum(p["band"] for p in parts.values()) * 100 / 24 + 0.5)


def provenance(sdir, root):
    paths = {name: sdir / name for name in INPUTS}
    paths["proficiency-rating.json"] = sdir / "proficiency-rating.json"
    paths["rubric"] = root / "docs/proficiency-methodology.md"
    paths["scoring_code"] = root / "scripts/proficiency.py"
    return {name: digest(path) for name, path in paths.items()}


def prepare(sdir, root):
    rating = json.loads((sdir / "proficiency-rating.json").read_text())
    score = calculate(rating, (sdir / "transcript.txt").read_text())
    return {"schema_version": 1, "rating": rating, "score": score,
            "input_hashes": provenance(sdir, root)}


def stamp(sdirs, root):
    # Validate the complete selection before writing anything.
    pending = [(sdir, prepare(sdir, root)) for sdir in sdirs
               if (sdir / "proficiency-rating.json").exists()]
    count = 0
    for sdir, result in pending:
        path = sdir / "proficiency.json"
        old = json.loads(path.read_text()) if path.exists() else None
        if old and all(old.get(k) == v for k, v in result.items()):
            continue
        now = datetime.now(timezone.utc).isoformat()
        if old:
            history = sdir / "proficiency-history"
            history.mkdir(exist_ok=True)
            # Full old ratings, score, and input identities remain recoverable.
            (history / (digest(path) + ".json")).write_bytes(path.read_bytes())
        result["generated_at"] = now
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        count += 1
    return count


def load_current(sdir, root):
    path = sdir / "proficiency.json"
    if not path.exists():
        return {"status": "unrated", "score": None,
                "summary": "Not yet assessed with the new rubric."}
    try:
        saved = json.loads(path.read_text())
        expected = prepare(sdir, root)
        if any(saved.get(k) != v for k, v in expected.items()):
            return {"status": "stale", "score": None,
                    "summary": "Inputs, rating or rubric changed; reassessment and stamping required."}
        return {**saved["rating"], "score": saved["score"],
                "generated_at": saved["generated_at"]}
    except (ValueError, OSError, KeyError, TypeError):
        return {"status": "stale", "score": None,
                "summary": "Rating or its source evidence is missing/invalid; reassess before using."}
