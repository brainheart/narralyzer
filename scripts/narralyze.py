#!/usr/bin/env python3
"""Narralogue session analyzer.

Subcommands:
  process   Deduplicate, transcribe, triage, and file every audio file in inbox/.
  rebuild   Rescan sessions/ and regenerate data/sessions.json + explorer/data.js
            (run after editing any analysis.json by hand).
  snapshot-analysis <session|all>
            Archive current qualitative analysis files before regenerating them.
  stamp-analysis <session|all>
            Validate/render Anki suggestions, then record analysis hashes.
  stamp-proficiency <session|all>
            Validate evidence, compute the 0–100 score, and preserve score history.
  approve-review <review-dir> <lang>
            Promote a human-confirmed narralogue from intake/review/.

Each session directory contains:
  audio.mp3        the original recording
  transcript.json  raw Whisper verbose_json (word-level timestamps)
  transcript.txt   plain text transcript
  metrics.json     computed quantitative metrics
  source.json      immutable intake provenance and content hash
  analysis-input.json stable input hashes for qualitative regeneration
  analysis.json    structured qualitative scores (written by Codex)
  analysis.md      prose qualitative analysis (written by Codex)
"""

import json
import hashlib
import getpass
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Also support importlib-based tests that do not place scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import proficiency
import publication

import requests

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
SESSIONS = ROOT / "sessions"
DATA = ROOT / "data"
EXPLORER = ROOT / "explorer"
INTAKE = ROOT / "intake"
DUPLICATES = INTAKE / "duplicates"
REVIEW = INTAKE / "review"

PIPELINE_VERSION = "2026-09-26.1"
ANALYSIS_RUBRIC_VERSION = "2026-09-20.1"
ANKI_GUIDANCE = {
    "field": "anki_suggestions",
    "target_issues": 5,
    "examples_per_issue": 3,
    "translation_language": "English",
    "instructions": (
        "Select the five highest-value, distinct issues supported by this session: "
        "recurring errors, explicit word searches, or useful grammar/vocabulary gaps. "
        "Do not infer mistakes from garbled ASR or invent issues to fill a quota. "
        "If fewer than five are justified, explain in anki_selection_note. "
        "For each issue provide issue, reason, and exactly three examples, each with "
        "sentence and translation. Write natural, complete sentences in the session "
        "language, with faithful English translations, suited to the learner's level "
        "and everyday situations. Vary the relevant forms (such as gender, singular/"
        "plural, agreement, tense or preposition) without adding unrelated difficulty. "
        "These are authored practice examples, not transcript quotations. Leave all "
        "sentences unclozed and unblanked for manual Anki card creation. Keep each "
        "issue's explanation short. The script renders these into analysis.md when "
        "stamp-analysis runs; do not add a second manual Anki section."
    ),
}
ANKI_START = "<!-- narralyzer:anki:start -->"
ANKI_END = "<!-- narralyzer:anki:end -->"
EXPECTED_LANGS = {"de", "en", "fr", "es"}

AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".mp4", ".webm", ".ogg", ".flac", ".aac"}

LANG_CODES = {
    "german": "de", "french": "fr", "spanish": "es", "english": "en",
    "italian": "it", "portuguese": "pt", "dutch": "nl",
}
LANG_NAMES = {v: k.capitalize() for k, v in LANG_CODES.items()}


def normalize_lang(raw: str) -> str:
    """Whisper API returns 'german'; local whisper returns 'de'. Accept both."""
    raw = (raw or "").lower()
    if raw in LANG_NAMES:
        return raw
    return LANG_CODES.get(raw, raw or "unknown")

# Pause threshold: a gap between consecutive words longer than this counts
# as a pause (i.e. non-speech time) rather than normal articulation rhythm.
PAUSE_THRESHOLD = 0.5

# Hesitation fillers as Whisper tends to render them. Whisper frequently
# omits fillers entirely, so treat these counts as a lower bound.
FILLERS = {
    "äh", "ähm", "ähh", "hm", "hmm", "mhm", "mhmm",
    "euh", "euhm", "heu",
    "eh", "ehm", "em", "este",
    "uh", "um", "uhm", "er", "erm",
}

# "How do you say...?" lookup questions worth flagging for later study.
LOOKUP_PATTERNS = [
    r"wie sagt man", r"wie heißt", r"was bedeutet", r"wie nennt man",
    r"comment dit[- ]on", r"comment on dit", r"comment s'appelle",
    r"c[oó]mo se dice", r"c[oó]mo se llama", r"qu[eé] significa",
    r"how do you say", r"how do i say", r"what's the word",
]

# Strong broadcast/interview cues. These never reject a recording alone: the
# conservative intake classifier also requires unusually little first-person
# speech. Borderline material is kept under intake/review, never deleted.
BROADCAST_PATTERNS = [
    r"\b(?:willkommen (?:zu|bei)|unser(?:e|er)? (?:gast|gäste)|abonnier(?:en|t)|podcast|interview)\b",
    r"\b(?:bienvenue (?:à|dans)|notre invité|abonnez-vous|podcast|interview)\b",
    r"\b(?:bienvenid[oa]s?|nuestro invitado|suscríbete|podcast|entrevista)\b",
]
FIRST_PERSON_PATTERNS = [
    r"\b(?:ich|mich|mir|mein(?:e|en|em|er|es)?|wir|uns|unser(?:e|en|em|er|es)?)\b",
    r"\b(?:je|j['’]|moi|me|mon|ma|mes|nous|notre|nos)\b",
    r"\b(?:yo|me|mí|mi|mis|nosotros|nosotras|nuestro|nuestra|nuestros|nuestras)\b",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, data: dict):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


def unique_dir(parent: Path, stem: str) -> Path:
    """Return a not-yet-existing child directory without overwriting evidence."""
    candidate = parent / stem
    suffix = 2
    while candidate.exists():
        candidate = parent / f"{stem}-{suffix}"
        suffix += 1
    return candidate


def parse_filename_date(name: str):
    """Parse YYMMDD_HHMM (or YYYYMMDD_HHMM) from a filename."""
    m = re.search(r"(\d{4})?(\d{2})(\d{2})(\d{2})[_\-]?(\d{2})(\d{2})", name)
    if not m:
        return None, None
    if m.group(1):  # YYYYMMDD_HHMM
        year = m.group(1)
        month, day, hh, mm = m.group(2), m.group(3), m.group(4), m.group(5)
        # regex above groups differently for 8-digit dates; reparse explicitly
        m2 = re.search(r"(\d{4})(\d{2})(\d{2})[_\-]?(\d{2})(\d{2})", name)
        year, month, day, hh, mm = m2.groups()
    else:  # YYMMDD_HHMM
        m2 = re.search(r"(\d{2})(\d{2})(\d{2})[_\-]?(\d{2})(\d{2})", name)
        yy, month, day, hh, mm = m2.groups()
        year = "20" + yy
    return f"{year}-{month}-{day}", f"{hh}:{mm}"


MLX_MODEL = "mlx-community/whisper-large-v3-turbo"
API_MODEL = "gpt-transcribe"
TRANSCRIPTION_PROMPT = (
    "A language learner speaking spontaneously. Transcribe in the original "
    "language, preserving grammatical mistakes, false starts, repetitions and "
    "fillers as spoken. Do not correct, paraphrase or translate the speech."
)


def transcribe_api(path: Path, key: str) -> dict:
    """Current text model plus an independent local Whisper timing pass.

    GPT-Transcribe has no word timestamps. Never invent or attach Whisper word
    times to different GPT words: quantitative metrics retain the Whisper word
    stream, explicitly identified in metadata. Both texts are preserved.
    """
    model = os.environ.get("NARRALYZE_API_MODEL", API_MODEL)
    if model not in {API_MODEL, "whisper-1"}:
        raise ValueError("NARRALYZE_API_MODEL must be gpt-transcribe or whisper-1")
    if model == "whisper-1":
        data = [
            ("model", model), ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
    else:
        data = [("model", model), ("prompt", TRANSCRIPTION_PROMPT)]
    with open(path, "rb") as f:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": (path.name, f, mimetypes.guess_type(path.name)[0]
                             or "application/octet-stream")},
            data=data,
            timeout=900,
        )
    resp.raise_for_status()
    out = resp.json()
    if not isinstance(out.get("text"), str):
        raise ValueError("Transcription API response is missing text")
    if model == "whisper-1":
        out["transcription_backend"] = "openai-api/whisper-1"
        return out
    print("  text transcribed with gpt-transcribe; running local Whisper for metrics", flush=True)
    timing = transcribe_local(path)
    if out["text"].strip() and not timing.get("words"):
        raise ValueError("Whisper returned no word timestamps; cannot compute reliable pace metrics")
    languages = [normalize_lang(item["code"]) for item in out.get("languages", [])
                 if isinstance(item, dict) and item.get("code")]
    return {
        **timing,
        "text": out["text"],
        "language": languages[0] if len(languages) == 1 else timing.get("language", ""),
        "detected_languages": languages,
        "language_source": "gpt-transcribe" if len(languages) == 1 else "timing_fallback",
        "transcription_backend": f"openai-api/{model}",
        "transcription_prompt": TRANSCRIPTION_PROMPT,
        "api_response": out,
        "timing_backend": timing["transcription_backend"],
        "timing_text": timing.get("text", ""),
        "timing_language": normalize_lang(timing.get("language", "")),
        "transcription_note": (
            "Readable transcript: gpt-transcribe. Word/segment timestamps and all "
            "quantitative language/pace metrics: independent local Whisper pass. "
            "These timestamps are not aligned to the GPT transcript. Grammar "
            "correction or omitted fillers remain possible in either model."
        ),
    }


def transcribe_local(path: Path) -> dict:
    import mlx_whisper
    # condition_on_previous_text=False prevents the repetition-loop
    # hallucinations Whisper is prone to on long pauses / wind noise.
    out = mlx_whisper.transcribe(
        str(path), path_or_hf_repo=MLX_MODEL, word_timestamps=True,
        verbose=None, condition_on_previous_text=False,
    )
    # Normalize to the API's verbose_json shape: flatten word timestamps
    # from segments into a top-level "words" list.
    words = []
    for seg in out.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": float(w["start"]),
                "end": float(w["end"]),
            })
    out["words"] = words
    out["transcription_backend"] = f"local/{MLX_MODEL}"
    return out


def load_api_key() -> str | None:
    """Use the environment or Narralyzer's macOS Keychain entry; never log it."""
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key
    if sys.platform != "darwin":
        return None
    try:
        from keyring.backends.macOS import Keyring
    except ImportError:
        return None
    return Keyring().get_password("narralyzer-openai-api", getpass.getuser())


def transcribe(path: Path) -> dict:
    """Prefer GPT-Transcribe; record any fallback rather than hide it."""
    backend = os.environ.get("NARRALYZE_BACKEND", "auto")
    if backend not in {"auto", "api", "local"}:
        raise ValueError("NARRALYZE_BACKEND must be auto, api or local")
    key = load_api_key() if backend != "local" else None
    if backend == "api" and not key:
        raise ValueError("API mode requires OPENAI_API_KEY or scripts/configure_api_key.py setup")
    print(f"  transcribing {path.name} ...", flush=True)
    fallback_reason = None
    if backend != "local" and key:
        try:
            return transcribe_api(path, key)
        except requests.HTTPError as e:
            if backend == "api":
                raise
            fallback_reason = f"API HTTP {e.response.status_code}"
            print(f"  {fallback_reason}, "
                  "falling back to local mlx-whisper", flush=True)
    elif backend == "auto":
        fallback_reason = "No OpenAI API key is configured (environment or Keychain)"
        print(f"  {fallback_reason}; using local Whisper ({MLX_MODEL})", flush=True)
    out = transcribe_local(path)
    if fallback_reason:
        out["transcription_fallback_reason"] = fallback_reason
    return out


def audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def tokenize(text: str):
    return [w.lower() for w in re.findall(r"[^\W\d_]+(?:['’\-][^\W\d_]+)*", text)]


def mattr(tokens, window=50):
    """Moving-average type-token ratio: TTR comparable across session lengths."""
    if len(tokens) < window:
        return len(set(tokens)) / len(tokens) if tokens else 0.0
    ratios = [
        len(set(tokens[i:i + window])) / window
        for i in range(len(tokens) - window + 1)
    ]
    return sum(ratios) / len(ratios)


# Cap on identical consecutive words: natural speech repeats a word two or
# three times; dozens in a row is a Whisper hallucination loop. Runs longer
# than this are truncated for metric purposes and flagged.
MAX_REPEAT_RUN = 4


def strip_repetition_loops(words):
    """Remove Whisper repetition-loop hallucinations from the word list.

    Handles both single-word loops ("brave brave brave ...") and phrase
    loops ("Und wer ist da? Und wer ist da? ..."): any 1-gram repeated more
    than MAX_REPEAT_RUN times, or any 2-8-gram repeated more than twice,
    consecutively, is truncated to the allowed count.
    """
    toks = [re.sub(r"[^\w'’\-]", "", w["word"].lower()) for w in words]
    keep = [True] * len(words)
    for n in range(1, 9):
        cap = MAX_REPEAT_RUN if n == 1 else 2
        i = 0
        while i + n <= len(toks):
            j = i + n
            reps = 1
            while j + n <= len(toks) and toks[j:j + n] == toks[i:i + n]:
                reps += 1
                j += n
            if reps > cap:
                for k in range(i + cap * n, i + reps * n):
                    keep[k] = False
            i = j if reps > 1 else i + 1
    cleaned = [w for w, k in zip(words, keep) if k]
    return cleaned, keep.count(False)


def compute_metrics(whisper: dict, duration: float) -> dict:
    words, hallucinated = strip_repetition_loops(whisper.get("words") or [])
    text = (" ".join(w["word"] for w in words) if words else
            whisper.get("timing_text", whisper.get("text", "")))
    tokens = tokenize(text)
    n = len(tokens)
    minutes = duration / 60 if duration else 1

    # Gap analysis from word timestamps. Leading and trailing silence count
    # as pauses too.
    gaps = []
    if words:
        gaps.append(max(0.0, words[0]["start"]))
        for a, b in zip(words, words[1:]):
            gaps.append(max(0.0, b["start"] - a["end"]))
        gaps.append(max(0.0, duration - words[-1]["end"]))
    pauses = [g for g in gaps if g > PAUSE_THRESHOLD]
    pause_time = sum(pauses)
    speech_time = max(0.0, duration - pause_time)

    # Longest fluent run: consecutive words with no pause between them.
    longest_run_words, longest_run_sec = 0, 0.0
    run_words, run_start = 0, None
    for i, w in enumerate(words):
        gap_before = gaps[i] if i < len(gaps) else 0
        if gap_before > PAUSE_THRESHOLD or run_start is None:
            run_words, run_start = 0, w["start"]
        run_words += 1
        run_sec = w["end"] - run_start
        if run_words > longest_run_words:
            longest_run_words = run_words
        if run_sec > longest_run_sec:
            longest_run_sec = run_sec

    inter_word = gaps[1:-1] if len(gaps) > 2 else []
    fillers = [t for t in tokens if t in FILLERS]
    lookups = sum(
        len(re.findall(p, text, flags=re.IGNORECASE)) for p in LOOKUP_PATTERNS
    )
    word_lengths = [len(t) for t in tokens]

    return {
        "metrics_backend": whisper.get("timing_backend", whisper.get("transcription_backend", "")),
        "transcript_word_count": len(tokenize(whisper.get("text", ""))),
        "transcription_note": whisper.get("transcription_note", ""),
        "transcription_fallback_reason": whisper.get("transcription_fallback_reason"),
        "duration_sec": round(duration, 1),
        "total_words": n,
        "unique_words": len(set(tokens)),
        "ttr": round(len(set(tokens)) / n, 3) if n else 0,
        "mattr_50": round(mattr(tokens), 3),
        "wpm": round(n / minutes, 1),
        "articulation_wpm": round(n / (speech_time / 60), 1) if speech_time else 0,
        "speech_ratio": round(speech_time / duration, 3) if duration else 0,
        "speech_time_sec": round(speech_time, 1),
        "pause_time_sec": round(pause_time, 1),
        "num_pauses": len(pauses),
        "pauses_over_2s": len([p for p in pauses if p > 2]),
        "pauses_over_5s": len([p for p in pauses if p > 5]),
        "mean_inter_word_gap": round(sum(inter_word) / len(inter_word), 3) if inter_word else 0,
        "max_pause_sec": round(max(pauses), 1) if pauses else 0,
        "longest_run_words": longest_run_words,
        "longest_run_sec": round(longest_run_sec, 1),
        "avg_word_length": round(sum(word_lengths) / n, 2) if n else 0,
        "pct_words_7plus_chars": round(
            100 * len([l for l in word_lengths if l >= 7]) / n, 1) if n else 0,
        "filler_count": len(fillers),
        "fillers_per_min": round(len(fillers) / minutes, 2),
        "lookup_questions": lookups,
        "pause_threshold_sec": PAUSE_THRESHOLD,
        "hallucinated_words_removed": hallucinated,
    }


def assess_recording(text: str, lang: str, metrics: dict) -> dict:
    """Conservatively decide whether a transcript looks like a narralogue.

    This is intentionally a triage check, not a semantic oracle. Recordings
    that trigger a strong warning are preserved for human review rather than
    treated as sessions or deleted.
    """
    duration = metrics.get("duration_sec", 0)
    words = metrics.get("total_words", 0)
    wpm = metrics.get("wpm", 0)
    speech_ratio = metrics.get("speech_ratio", 0)
    hallucinated = metrics.get("hallucinated_words_removed", 0)
    transcript_total = words + hallucinated
    hallucination_ratio = hallucinated / transcript_total if transcript_total else 0
    lowered = text.lower()
    broadcast_cues = sum(
        len(re.findall(pattern, lowered, flags=re.IGNORECASE))
        for pattern in BROADCAST_PATTERNS
    )
    first_person_markers = sum(
        len(re.findall(pattern, lowered, flags=re.IGNORECASE))
        for pattern in FIRST_PERSON_PATTERNS
    )

    reasons = []
    warnings = []
    if lang not in EXPECTED_LANGS:
        reasons.append({
            "code": "unexpected_language",
            "detail": (
                f"detected language {lang!r}; expected one of "
                f"{', '.join(sorted(EXPECTED_LANGS))}"
            ),
        })
    if duration < 90:
        reasons.append({
            "code": "too_short",
            "detail": f"duration is only {duration:.1f} seconds",
        })
    elif duration > 1800:
        reasons.append({
            "code": "too_long",
            "detail": f"duration is {duration / 60:.1f} minutes",
        })
    elif duration < 240 or duration > 900:
        warnings.append({
            "code": "unusual_duration",
            "detail": f"duration is {duration / 60:.1f} minutes",
        })
    if words < 40 or wpm < 5 or speech_ratio < 0.08:
        reasons.append({
            "code": "almost_no_speech",
            "detail": (
                f"{words} words, {wpm} WPM, speech ratio {speech_ratio:.1%}"
            ),
        })
    elif words < 100 or wpm < 15 or speech_ratio < 0.2:
        warnings.append({
            "code": "little_detected_speech",
            "detail": (
                f"{words} words, {wpm} WPM, speech ratio {speech_ratio:.1%}"
            ),
        })
    if hallucinated >= 50 and hallucination_ratio >= 0.25:
        reasons.append({
            "code": "transcription_hallucination",
            "detail": (
                f"removed {hallucinated} repeated words "
                f"({hallucination_ratio:.1%} of timestamped words)"
            ),
        })
    if broadcast_cues >= 2 and first_person_markers < 5:
        reasons.append({
            "code": "possible_broadcast_or_interview",
            "detail": (
                f"found {broadcast_cues} broadcast/interview cues but only "
                f"{first_person_markers} first-person markers"
            ),
        })

    return {
        "decision": "needs_review" if reasons else "accepted",
        "classification": "uncertain" if reasons else "likely_narralogue",
        "reasons": reasons,
        "warnings": warnings,
        "signals": {
            "detected_language": lang,
            "duration_sec": duration,
            "total_words": words,
            "wpm": wpm,
            "speech_ratio": speech_ratio,
            "broadcast_cues": broadcast_cues,
            "first_person_markers": first_person_markers,
            "hallucination_ratio": round(hallucination_ratio, 3),
        },
        "policy_version": PIPELINE_VERSION,
    }


def existing_audio_index() -> dict:
    """Map content hashes to their canonical filed session."""
    index = {}
    for path in sorted(SESSIONS.glob("*/*/audio*")):
        if path.is_file() and path.suffix.lower() in AUDIO_EXTS:
            index.setdefault(sha256_file(path), str(path.parent.relative_to(ROOT)))
    return index


def write_analysis_input(sdir: Path):
    """Record stable inputs so a qualitative analysis can be reproduced."""
    inputs = {
        "schema_version": 1,
        "analysis_rubric_version": ANALYSIS_RUBRIC_VERSION,
        "anki_guidance": ANKI_GUIDANCE,
        "proficiency_guidance": {
            "rubric_version": proficiency.VERSION,
            "instructions": "Read docs/proficiency-methodology.md; author proficiency-rating.json, then stamp-proficiency. Never convert the legacy CEFR label into a score.",
        },
        "generated_at": utc_now(),
        "session": str(sdir.relative_to(SESSIONS)),
        "files": {},
    }
    for name in ("source.json", "transcript.json", "transcript.txt", "metrics.json"):
        path = sdir / name
        if path.exists():
            inputs["files"][name] = {
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
    write_json(sdir / "analysis-input.json", inputs)


def write_session_files(sdir: Path, whisper: dict, metrics: dict, source: dict):
    transcript_text = whisper.get("text", "").strip() + "\n"
    write_json(sdir / "transcript.json", whisper)
    (sdir / "transcript.txt").write_text(transcript_text)
    write_json(sdir / "metrics.json", metrics)
    write_json(sdir / "source.json", source)
    write_analysis_input(sdir)


def move_with_recording(path: Path, destination: Path, metadata: dict,
                        whisper: dict | None = None, metrics: dict | None = None):
    """Preserve a duplicate/review recording plus an explicit disposition."""
    destination.mkdir(parents=True)
    if whisper is not None:
        write_json(destination / "transcript.json", whisper)
        (destination / "transcript.txt").write_text(
            whisper.get("text", "").strip() + "\n")
    if metrics is not None:
        write_json(destination / "metrics.json", metrics)
    write_json(destination / "disposition.json", metadata)
    shutil.move(str(path), destination / f"audio{path.suffix.lower()}")


def duplicate_destination(path: Path, audio_hash: str) -> Path:
    return unique_dir(DUPLICATES, f"{path.stem}_{audio_hash[:8]}")


def review_destination(path: Path, audio_hash: str) -> Path:
    return unique_dir(REVIEW, f"{path.stem}_{audio_hash[:8]}")


def process_inbox():
    files = sorted(
        p for p in INBOX.iterdir()
        if p.suffix.lower() in AUDIO_EXTS and not p.name.startswith(".")
    )
    if not files:
        print("inbox is empty")
        return
    audio_index = existing_audio_index()
    counts = {"accepted": 0, "duplicate": 0, "needs_review": 0}
    for path in files:
        print(f"processing {path.name}")
        audio_hash = sha256_file(path)
        file_info = {
            "original_filename": path.name,
            "audio_sha256": audio_hash,
            "audio_bytes": path.stat().st_size,
            "processed_at": utc_now(),
            "pipeline_version": PIPELINE_VERSION,
        }
        if audio_hash in audio_index:
            destination = duplicate_destination(path, audio_hash)
            metadata = {
                **file_info,
                "decision": "duplicate",
                "duplicate_of": audio_index[audio_hash],
                "reason": "exact SHA-256 match; not transcribed or analyzed again",
            }
            move_with_recording(path, destination, metadata)
            counts["duplicate"] += 1
            print(f"  -> {destination.relative_to(ROOT)}  [exact duplicate of "
                  f"{audio_index[audio_hash]}]")
            continue
        date, time = parse_filename_date(path.name)
        if not date:
            destination = review_destination(path, audio_hash)
            metadata = {
                **file_info,
                "decision": "needs_review",
                "reasons": [{
                    "code": "unrecognized_filename",
                    "detail": "could not parse YYMMDD_HHMM from filename",
                }],
            }
            move_with_recording(path, destination, metadata)
            counts["needs_review"] += 1
            print(f"  -> {destination.relative_to(ROOT)}  [needs review: "
                  "date not found in filename]")
            continue
        duration = audio_duration(path)
        if duration <= 0:
            destination = review_destination(path, audio_hash)
            metadata = {
                **file_info,
                "decision": "needs_review",
                "reasons": [{
                    "code": "unreadable_audio",
                    "detail": "ffprobe could not determine a positive duration",
                }],
            }
            move_with_recording(path, destination, metadata)
            counts["needs_review"] += 1
            print(f"  -> {destination.relative_to(ROOT)}  [needs review: "
                  "unreadable audio]")
            continue
        whisper = transcribe(path)
        lang = normalize_lang(whisper.get("language", ""))
        sid = f"{date}_{time.replace(':', '')}"

        metrics = compute_metrics(whisper, duration)
        assessment = assess_recording(whisper.get("text", ""), lang, metrics)
        metrics.update({
            "id": f"{lang}/{sid}", "lang": lang,
            "language": LANG_NAMES.get(lang, lang),
            "date": date, "time": time,
            "original_filename": path.name,
            "transcription_backend": whisper.get("transcription_backend", ""),
            "audio_sha256": audio_hash,
            "pipeline_version": PIPELINE_VERSION,
            "intake_assessment": assessment,
        })

        if assessment["decision"] == "needs_review":
            destination = review_destination(path, audio_hash)
            metadata = {**file_info, **assessment}
            move_with_recording(path, destination, metadata, whisper, metrics)
            counts["needs_review"] += 1
            codes = ", ".join(r["code"] for r in assessment["reasons"])
            print(f"  -> {destination.relative_to(ROOT)}  [needs review: {codes}]")
            continue

        sdir = SESSIONS / lang / sid
        if sdir.exists():
            destination = review_destination(path, audio_hash)
            metadata = {
                **file_info,
                "decision": "needs_review",
                "reasons": [{
                    "code": "session_id_collision",
                    "detail": f"{sdir.relative_to(ROOT)} already exists with different audio",
                }],
            }
            move_with_recording(path, destination, metadata, whisper, metrics)
            counts["needs_review"] += 1
            print(f"  -> {destination.relative_to(ROOT)}  [needs review: "
                  "session id collision]")
            continue

        sdir.mkdir(parents=True)
        source = {
            **file_info,
            "session_id": f"{lang}/{sid}",
            "duration_sec": round(duration, 3),
            "transcription_backend": whisper.get("transcription_backend", ""),
            "intake_assessment": assessment,
        }
        write_session_files(sdir, whisper, metrics, source)
        shutil.move(str(path), sdir / f"audio{path.suffix.lower()}")
        audio_index[audio_hash] = str(sdir.relative_to(ROOT))
        counts["accepted"] += 1
        print(f"  -> {sdir.relative_to(ROOT)}  [{metrics['language']}, "
              f"{metrics['total_words']} words, {metrics['wpm']} wpm]")
    rebuild()
    print("intake summary: " + ", ".join(
        f"{value} {key.replace('_', ' ')}" for key, value in counts.items()))


def redo(session: str, retranscribe: bool = True):
    """Re-transcribe (redo) or just recompute metrics (remetric) for a filed session."""
    sdir = SESSIONS / session
    audio = next(p for p in sdir.iterdir() if p.suffix.lower() in AUDIO_EXTS)
    old = json.loads((sdir / "metrics.json").read_text())
    duration = audio_duration(audio)
    if retranscribe:
        whisper = transcribe(audio)
    else:
        whisper = json.loads((sdir / "transcript.json").read_text())
    metrics = compute_metrics(whisper, duration)
    metrics.update({k: old[k] for k in
                    ("id", "lang", "language", "date", "time", "original_filename")})
    for key in ("audio_sha256", "pipeline_version", "intake_assessment"):
        if key in old:
            metrics[key] = old[key]
    metrics["transcription_backend"] = whisper.get("transcription_backend", "")
    write_json(sdir / "transcript.json", whisper)
    (sdir / "transcript.txt").write_text(whisper.get("text", "").strip() + "\n")
    write_json(sdir / "metrics.json", metrics)
    write_analysis_input(sdir)
    print(f"redone {session}: {metrics['total_words']} words, "
          f"{metrics['hallucinated_words_removed']} hallucinated words removed")
    rebuild()


def selected_session_dirs(selector: str):
    if selector == "all":
        return sorted(m.parent for m in SESSIONS.glob("*/*/metrics.json"))
    sdir = SESSIONS / selector
    if not (sdir / "metrics.json").exists():
        raise SystemExit(f"session not found: {selector}")
    return [sdir]


def approve_review(review_name: str, lang: str):
    """Promote a reviewed recording while retaining its machine disposition."""
    lang = normalize_lang(lang)
    if lang not in EXPECTED_LANGS:
        raise SystemExit(f"approved language must be one of {sorted(EXPECTED_LANGS)}")
    if Path(review_name).name != review_name:
        raise SystemExit("review-dir must be a direct child name of intake/review")
    rdir = REVIEW / review_name
    if not rdir.is_dir():
        raise SystemExit(f"review item not found: {rdir.relative_to(ROOT)}")

    required = ("transcript.json", "transcript.txt",
                "metrics.json", "disposition.json")
    audio = next(
        (p for p in rdir.iterdir()
         if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
        None,
    )
    missing = [name for name in required if not (rdir / name).exists()]
    if audio is None:
        missing.insert(0, "audio")
    if missing:
        raise SystemExit(f"review item is incomplete; missing: {', '.join(missing)}")

    disposition = json.loads((rdir / "disposition.json").read_text())
    metrics = json.loads((rdir / "metrics.json").read_text())
    original_name = disposition.get("original_filename", audio.name)
    date, time = parse_filename_date(original_name)
    if not date:
        raise SystemExit(f"cannot parse session date from {original_name}")
    sid = f"{date}_{time.replace(':', '')}"
    sdir = SESSIONS / lang / sid
    if sdir.exists():
        raise SystemExit(f"session already exists: {sdir.relative_to(ROOT)}")

    original_assessment = metrics.get("intake_assessment", disposition)
    approved_at = utc_now()
    human_assessment = {
        "decision": "accepted",
        "classification": "human_confirmed_narralogue",
        "reasons": [],
        "warnings": [{
            "code": "human_override",
            "detail": (
                f"machine detected {metrics.get('lang', 'unknown')!r}; "
                f"human review assigned {lang!r}"
            ),
        }],
        "reviewed_at": approved_at,
        "assigned_language": lang,
        "machine_assessment": original_assessment,
        "policy_version": PIPELINE_VERSION,
    }
    metrics.update({
        "id": f"{lang}/{sid}",
        "lang": lang,
        "language": LANG_NAMES.get(lang, lang),
        "date": date,
        "time": time,
        "intake_assessment": human_assessment,
    })
    source = {
        "schema_version": 1,
        "session_id": f"{lang}/{sid}",
        "original_filename": original_name,
        "audio_sha256": disposition.get("audio_sha256", sha256_file(audio)),
        "audio_bytes": disposition.get("audio_bytes", audio.stat().st_size),
        "duration_sec": metrics.get("duration_sec"),
        "transcription_backend": metrics.get("transcription_backend", ""),
        "processed_at": disposition.get("processed_at"),
        "approved_at": approved_at,
        "pipeline_version": PIPELINE_VERSION,
        "intake_assessment": human_assessment,
    }

    sdir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(rdir), str(sdir))
    (sdir / "disposition.json").rename(sdir / "intake-review.json")
    write_json(sdir / "metrics.json", metrics)
    write_json(sdir / "source.json", source)
    write_analysis_input(sdir)
    print(f"approved {review_name} -> {sdir.relative_to(ROOT)} "
          f"[{metrics['language']}, human-reviewed]")
    rebuild()


def backfill_provenance():
    """Add hashes/manifests to legacy sessions without altering their analysis."""
    changed = 0
    for sdir in selected_session_dirs("all"):
        audio = next(
            (p for p in sdir.iterdir()
             if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
            None,
        )
        metrics_path = sdir / "metrics.json"
        metrics = json.loads(metrics_path.read_text())
        if audio and "audio_sha256" not in metrics:
            metrics["audio_sha256"] = sha256_file(audio)
            metrics["pipeline_version"] = "legacy-backfill"
            write_json(metrics_path, metrics)
            changed += 1
        source_path = sdir / "source.json"
        if audio and not source_path.exists():
            write_json(source_path, {
                "schema_version": 1,
                "session_id": str(sdir.relative_to(SESSIONS)),
                "original_filename": metrics.get("original_filename", audio.name),
                "audio_sha256": sha256_file(audio),
                "audio_bytes": audio.stat().st_size,
                "duration_sec": metrics.get("duration_sec"),
                "transcription_backend": metrics.get("transcription_backend", ""),
                "processed_at": None,
                "pipeline_version": "legacy-backfill",
                "intake_assessment": {
                    "decision": "accepted",
                    "classification": "legacy_session_not_reassessed",
                    "reasons": [],
                    "warnings": [],
                },
            })
            changed += 1
        write_analysis_input(sdir)
    print(f"provenance ready for {len(selected_session_dirs('all'))} session(s); "
          f"{changed} legacy file(s) added or updated")


def snapshot_analysis(selector: str):
    """Archive analysis outputs before a future qualitative regeneration."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived = 0
    for sdir in selected_session_dirs(selector):
        analysis_files = [
            sdir / name for name in
            ("analysis.md", "analysis.json", "analysis.provenance.json")
            if (sdir / name).exists()
        ]
        if not analysis_files:
            print(f"no analysis to snapshot: {sdir.relative_to(SESSIONS)}")
            continue
        destination = unique_dir(sdir / "analysis-history", stamp)
        destination.mkdir(parents=True)
        for path in analysis_files:
            shutil.copy2(path, destination / path.name)
        if (sdir / "analysis-input.json").exists():
            shutil.copy2(sdir / "analysis-input.json",
                         destination / "analysis-input.json")
        write_json(destination / "snapshot.json", {
            "schema_version": 1,
            "session": str(sdir.relative_to(SESSIONS)),
            "created_at": utc_now(),
            "reason": "pre-regeneration analysis snapshot",
        })
        archived += 1
        print(f"snapshotted {sdir.relative_to(SESSIONS)} -> "
              f"{destination.relative_to(ROOT)}")
    print(f"snapshotted {archived} analysis set(s)")


def validate_anki_suggestions(analysis: dict):
    """Check the authored card structure, not linguistic correctness."""
    if not isinstance(analysis, dict):
        raise ValueError("analysis.json must contain an object")
    suggestions = analysis.get("anki_suggestions")
    if not isinstance(suggestions, list) or len(suggestions) > 5:
        raise ValueError("anki_suggestions must be a list of up to five issues")

    def require_text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be nonempty text")
        if re.search(r"\{\{c\d+::", value, re.IGNORECASE):
            raise ValueError(f"{label} must be unclozed for manual Anki editing")

    note = analysis.get("anki_selection_note", "")
    if len(suggestions) < 5 or note:
        require_text(note, "anki_selection_note (explain fewer than five issues)")
    issues, sentences = set(), set()
    for i, suggestion in enumerate(suggestions, 1):
        if not isinstance(suggestion, dict):
            raise ValueError(f"Anki issue {i} must be an object")
        for field in ("issue", "reason"):
            require_text(suggestion.get(field), f"Anki issue {i}: {field}")
        key = suggestion["issue"].strip().casefold()
        if key in issues:
            raise ValueError(f"Anki issue {i} duplicates an earlier issue")
        issues.add(key)
        examples = suggestion.get("examples")
        if not isinstance(examples, list) or len(examples) != 3:
            raise ValueError(f"Anki issue {i} must have exactly three examples")
        for example in examples:
            if not isinstance(example, dict):
                raise ValueError(f"Anki issue {i}: example must be an object")
            for field in ("sentence", "translation"):
                require_text(example.get(field), f"Anki issue {i}: {field}")
            key = " ".join(example["sentence"].split()).casefold()
            if key in sentences:
                raise ValueError(f"Anki issue {i} repeats a practice sentence")
            sentences.add(key)


def render_anki_section(markdown: str, analysis: dict) -> str:
    """Render the structured examples once, retaining all other prose."""
    validate_anki_suggestions(analysis)

    def cell(text):
        return " ".join(text.split()).replace("|", r"\|")

    lines = [ANKI_START, "## Anki practice — full sentences", "",
             "Authored practice examples, not transcript quotations. "
             "Leave intact until you choose your own cloze deletions.", ""]
    if analysis.get("anki_selection_note"):
        lines.extend([analysis["anki_selection_note"].strip(), ""])
    for i, suggestion in enumerate(analysis["anki_suggestions"], 1):
        lines.extend([
            f"### {i}. {cell(suggestion['issue'])}", "",
            cell(suggestion["reason"]), "",
            "| Practice sentence | English translation |",
            "| --- | --- |",
        ])
        for example in suggestion["examples"]:
            lines.append(f"| {cell(example['sentence'])} | "
                         f"{cell(example['translation'])} |")
        lines.append("")
    lines.append(ANKI_END)
    section = "\n".join(lines)
    if ANKI_START in markdown or ANKI_END in markdown:
        if (markdown.count(ANKI_START) != 1 or markdown.count(ANKI_END) != 1
                or markdown.index(ANKI_START) > markdown.index(ANKI_END)):
            raise ValueError("Malformed generated Anki section markers in analysis.md")
        before, rest = markdown.split(ANKI_START, 1)
        _, after = rest.split(ANKI_END, 1)
        return before + section + after
    return markdown.rstrip() + "\n\n" + section + "\n"


def stamp_analysis(selector: str):
    """Bind current qualitative outputs to the inputs/rubric that produced them."""
    prepared = []
    for sdir in selected_session_dirs(selector):
        md = sdir / "analysis.md"
        structured = sdir / "analysis.json"
        if not (md.exists() and structured.exists()):
            continue
        try:
            rendered = render_anki_section(md.read_text(), json.loads(structured.read_text()))
        except ValueError as exc:
            raise ValueError(f"{sdir.relative_to(SESSIONS)}: {exc}") from exc
        prepared.append((sdir, md, structured, rendered))
    # Validate the whole selection before changing any prose or provenance.
    for sdir, md, structured, rendered in prepared:
        if rendered != md.read_text():
            md.write_text(rendered)
        write_analysis_input(sdir)
        inputs = json.loads((sdir / "analysis-input.json").read_text())
        write_json(sdir / "analysis.provenance.json", {
            "schema_version": 1,
            "session": str(sdir.relative_to(SESSIONS)),
            "generated_at": utc_now(),
            "generator": "Codex qualitative pass",
            "analysis_rubric_version": ANALYSIS_RUBRIC_VERSION,
            "input_hashes": inputs["files"],
            "output_hashes": {
                "analysis.md": sha256_file(md),
                "analysis.json": sha256_file(structured),
            },
            "caveat": (
                "Whisper may correct grammar and omit fillers; error and filler "
                "counts are lower bounds."
            ),
        })
    print(f"stamped {len(prepared)} analysis set(s)")


def rebuild():
    records = []
    for mfile in sorted(SESSIONS.glob("*/*/metrics.json")):
        rec = json.loads(mfile.read_text())
        afile = mfile.parent / "analysis.json"
        if afile.exists():
            rec["analysis"] = json.loads(afile.read_text())
        amd = mfile.parent / "analysis.md"
        if amd.exists():
            rec["analysis_md"] = amd.read_text()
        tfile = mfile.parent / "transcript.txt"
        if tfile.exists():
            rec["transcript"] = tfile.read_text().strip()
        rec["proficiency"] = proficiency.load_current(mfile.parent, ROOT)
        records.append(rec)
    records.sort(key=lambda r: (r["date"], r["time"]))

    DATA.mkdir(exist_ok=True)
    (DATA / "sessions.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1))
    publication.build(ROOT, records)
    print(f"rebuilt data for {len(records)} session(s)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "process"
    if cmd == "process":
        process_inbox()
    elif cmd == "rebuild":
        rebuild()
    elif cmd in {"share-transcript", "unshare-transcript"}:
        if len(sys.argv) != 3:
            sys.exit(f"usage: narralyze.py {cmd} <lang/id>")
        try:
            publication.set_approval(ROOT, sys.argv[2], cmd == "share-transcript")
            rebuild()
        except (ValueError, OSError) as exc:
            sys.exit(f"Cannot change transcript sharing: {exc}")
    elif cmd == "list-sharing":
        approvals = publication.load_approvals(ROOT)
        for path in sorted(SESSIONS.glob("*/*/transcript.txt")):
            record = {"id": str(path.parent.relative_to(SESSIONS)), "transcript": path.read_text().strip()}
            print(f"{record['id']}  {publication.sharing_state(record, approvals)}")
    elif cmd == "redo":
        redo(sys.argv[2])
    elif cmd == "remetric":
        redo(sys.argv[2], retranscribe=False)
    elif cmd == "backfill-provenance":
        backfill_provenance()
    elif cmd == "snapshot-analysis":
        if len(sys.argv) < 3:
            sys.exit("usage: narralyze.py snapshot-analysis <lang/id|all>")
        snapshot_analysis(sys.argv[2])
    elif cmd == "stamp-analysis":
        if len(sys.argv) < 3:
            sys.exit("usage: narralyze.py stamp-analysis <lang/id|all>")
        try:
            stamp_analysis(sys.argv[2])
        except ValueError as exc:
            sys.exit(f"Cannot stamp analysis: {exc}")
    elif cmd == "stamp-proficiency":
        if len(sys.argv) < 3:
            sys.exit("usage: narralyze.py stamp-proficiency <lang/id|all>")
        try:
            count = proficiency.stamp(selected_session_dirs(sys.argv[2]), ROOT)
            print(f"stamped {count} changed proficiency rating(s)")
        except (ValueError, OSError) as exc:
            sys.exit(f"Cannot stamp proficiency: {exc}")
    elif cmd == "approve-review":
        if len(sys.argv) < 4:
            sys.exit("usage: narralyze.py approve-review <review-dir> <lang>")
        approve_review(sys.argv[2], sys.argv[3])
    else:
        sys.exit(f"unknown command: {cmd}")
