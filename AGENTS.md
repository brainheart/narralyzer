# Narralyzer

Analyzer for **narralogue** sessions — Reinhard's language-learning Everyday
System: speak without pause for a timed session (currently 10 min/day),
describing the world around you. German 6 days/week, French 1 day/week,
Spanish starting soon. Roughly one session per fortnight/month gets recorded
and dropped here for analysis to track progress over time and across
languages at different maturity levels.

## Workflow (when Reinhard drops files in `inbox/` and asks to process)

1. Run `python3 scripts/narralyze.py process`
   - SHA-256 exact duplicates are moved to `intake/duplicates/` with a
     `disposition.json`; they are not transcribed or analyzed again.
   - Transcribes each audio file with OpenAI `gpt-transcribe` when credentials
     are available, plus an independent local mlx-whisper `large-v3-turbo`
     pass for word timestamps and comparable quantitative metrics. Without
     credentials or on API HTTP failure, automatic mode uses local Whisper
     and records the fallback reason. Force with `NARRALYZE_BACKEND=api|local`.
     Read `docs/transcription.md` for model provenance and secure key setup.
   - Conservatively checks duration, detected language, speech quantity,
     repetition hallucinations, and strong broadcast/interview cues. Suspect
     files go to `intake/review/` with their audio, transcript, metrics, and
     explicit reasons; they never silently become sessions or get deleted.
   - Detects language, parses date from filename (`YYMMDD_HHMM`), moves the
     file to `sessions/<lang>/<YYYY-MM-DD_HHMM>/` with `transcript.json`,
     `transcript.txt`, `metrics.json`, `source.json`, and `analysis-input.json`.
2. **Codex does the qualitative pass** for each new session: read
   `transcript.txt` and write, in the session directory:
   - `analysis.md` — prose analysis: grammar/vocab errors with corrections,
     sophistication assessment (clause complexity, tense variety, idiomaticity),
     vocabulary highlights, and 3–5 concrete suggestions. Anki practice is
     authored in `analysis.json` as described below; the script renders it into
     `analysis.md` during stamping (do not duplicate it manually).
   - `analysis.json` — structured fields used by the dashboard:
     ```json
     {
       "errors_per_100_words": 2.1,
       "error_count": 25,
       "cefr_estimate": "B2",
       "sophistication_score": 6,      // 1-10, comparable within a language over time
       "summary": "one sentence",
       "topics": ["..."],
       "notable_errors": [{"said": "...", "better": "...", "type": "gender"}],
       "lookup_questions": ["..."],
       "anki_suggestions": [
         {"issue": "priority learning target", "reason": "why this session supports it",
          "examples": [{"sentence": "Full target-language sentence.",
                        "translation": "Full English translation."}]}
       ]
     }
     ```
   - Caveat to remember: Whisper silently corrects some grammar errors and
     drops most fillers, so error counts and filler counts are lower bounds.
   - **Anki format:** select the five highest-value distinct issues, with
     **exactly three complete example sentences and English translations per
     issue** (the schema above abbreviates the examples list). Keep sentences
     unclozed for Reinhard to edit. Vary relevant grammar/forms in natural,
     level-appropriate situations. Avoid ASR guesses or padding; if fewer than
     five issues are justified, supply `anki_selection_note` explaining why.
     Read [docs/analysis-format.md](docs/analysis-format.md) for the full contract.
3. Run `python3 scripts/narralyze.py stamp-analysis <lang>/<id>` to validate
   the Anki structure, render its tables into `analysis.md`, and tie output
   hashes to exact inputs and the rubric. Then run
   `python3 scripts/narralyze.py rebuild` to refresh `data/sessions.json`
   and `explorer/data.js`, including the rendered Anki section.
   Also read `docs/proficiency-methodology.md` and author the separate
   `proficiency-rating.json` for every new or regenerated session: four
   independently evidenced bands, or an explicit `withheld` decision. Run
   `stamp-proficiency <lang>/<id>` before `rebuild`. Never infer the new 0–100
   score from the legacy CEFR label, raw speed, or native-language status.
   Existing analyses need not be overwritten for a score-only backfill.
   Changed scores are automatically archived; changed inputs invalidate them.
4. Tell Reinhard the headline numbers and anything interesting vs. previous
   sessions (open `explorer/index.html` in a browser for charts).

## Layout

- `inbox/` — drop zone for new recordings (filename contains YYMMDD_HHMM)
- `intake/duplicates/` — preserved exact duplicates plus their disposition
- `intake/review/` — preserved questionable/non-session recordings, transcripts,
  metrics, and transparent review reasons
- `sessions/<lang>/<date_time>/` — audio + transcript + metrics + analysis
- `data/sessions.json` — merged central table
- `explorer/index.html` — dashboard (static; reads `explorer/data.js`)
- `scripts/narralyze.py` — the pipeline

Other commands: `redo <lang>/<id>` re-transcribes a filed session in place;
`remetric <lang>/<id>` recomputes metrics from the saved transcript (use after
changing metric code). Both trigger a rebuild. `backfill-provenance` adds
content hashes and analysis-input manifests to legacy sessions. Before replacing
an existing qualitative analysis, run `snapshot-analysis <lang>/<id>` (or
`snapshot-analysis all`) to preserve the old outputs and their exact inputs
under `analysis-history/`; after replacement, run `stamp-analysis`.
If human review confirms that a quarantined item is a narralogue, run
`approve-review <review-dir> <lang>`; the original machine disposition is
retained as `intake-review.json` in the promoted session.

## Transcription quality lessons (June 2026)

- Whisper produces **repetition-loop hallucinations** on long pauses / street
  noise. Mitigated twice over: local transcription runs with
  `condition_on_previous_text=False`, and `strip_repetition_loops()` removes
  surviving 1-gram (>4×) and 2-8-gram (>2×) consecutive repeats before
  metrics (`hallucinated_words_removed` in metrics.json). Still **read each
  new transcript with an eye for garbled passages** before trusting error
  counts; note `transcript_quality` in analysis.json.
- Quiet morning cat-walk recordings transcribe well; afternoon town-walk
  recordings (traffic) come out partly garbled — pause/pace metrics stay
  valid (timing-based) but error analysis becomes unreliable. Suggested to
  Reinhard he record morning sessions.

## Metric notes

- Pause threshold is 0.5 s (`PAUSE_THRESHOLD`); speech_ratio = 1 − pause time/duration.
- `articulation_wpm` = words per minute of actual speaking time (pace when
  talking), vs `wpm` = words over the whole session (includes pauses).
- `mattr_50` = moving-average type-token ratio, window 50 — lexical diversity
  comparable across sessions of different lengths (plain TTR is not).
- Word-level timestamps come from Whisper; treat sub-100 ms gap differences
  as noise.
- With GPT-Transcribe, the readable transcript and metric word stream differ.
  `total_words` and pace/diversity metrics still use Whisper; use
  `transcript_word_count` for error rates based on the GPT transcript, and
  state that denominator and the model change in the qualitative analysis.

## Public and private publishing

When asked to publish results, update **both** the existing invitation-only GPT Site and the public GitHub Pages site. Follow `docs/publishing.md` and the Sites skill. `rebuild` now refreshes private Sites assets and a separate `build/public/`; `python3 scripts/publish.py --public` tests, audits, and pushes the allowlisted public export. Finish the native Sites packaging/deployment and verify both targets.

All full transcripts default to omitted publicly. Only the owner's explicit session selection authorizes `share-transcript <lang/id>`; approval binds to the exact text, and changed text must be reviewed again. Use `unshare-transcript` to revoke and `list-sharing` to inspect. Never publish raw sessions, audio, ASR JSON, private Git history, or the complete private `explorer/data.js` to GitHub. Analysis excerpts remain public as requested. Preserve the private Site's access policy.
