# Anki-ready practice in session analyses

For the separate 0–100 monologue score, follow
[proficiency-methodology.md](proficiency-methodology.md). It has its own
evidence file, stamping command and history; do not add fabricated numeric
precision to `cefr_estimate` or rewrite legacy Anki analyses for a score backfill.

Starting with rubric `2026-09-20.1`, every new or regenerated qualitative
analysis includes `anki_suggestions` in `analysis.json`. Codex authors the
examples after reading the transcript; Python does not generate or translate
language examples and does not make an additional model API call.

## Selection and writing

- Choose the **five highest-value distinct issues**, in priority order:
  repeated errors, explicit word searches, and useful gaps in grammar or
  vocabulary. Give each a short `issue` title and a `reason` grounded in this
  session. Do not promote a likely transcription artifact into a learning need.
- Write **exactly three complete sentences per issue**, each with a faithful
  English translation. Aim for fifteen usable sentence pairs, not fifteen
  new topics. Use natural, everyday situations suited to the learner's level.
- Vary forms relevant to the issue: singular/plural and articles for a noun,
  agreement for an adjective, or contrasting persons/tenses/prepositions for a
  construction. Do not mechanically impose every kind of variation on every word.
- Leave sentences intact: no cloze syntax, blanks, fragments, or automatic
  hidden words. Reinhard will make his own cloze deletions.
- These are **new practice examples**, not quotations or claims about what
  happened in the recording. Keep them distinct from the correction ledger.
- If there are fewer than five defensible targets, use fewer and explain in
  `anki_selection_note`. Zero is allowed with an explanation (for example an
  unreliable transcript or a native-English baseline with no useful learning
  targets). Do not manufacture mistakes to reach five.

Example of one issue (a normal session supplies five such objects):

```json
{
  "issue": "insecto: masculine noun and plural",
  "reason": "The speaker explicitly searched for the word for insect.",
  "examples": [
    {
      "sentence": "Hay un insecto en la ventana.",
      "translation": "There is an insect on the window."
    },
    {
      "sentence": "Los insectos son pequeños.",
      "translation": "The insects are small."
    },
    {
      "sentence": "Este insecto es pequeño, pero esos insectos son grandes.",
      "translation": "This insect is small, but those insects are big."
    }
  ]
}
```

Keep `lookup_questions` for backward compatibility and direct lookup answers.
The sentence practice belongs in `anki_suggestions`, not in that string list.

## Pipeline and regeneration

1. `process` records the new rubric and Anki authoring guidance in each new
   `analysis-input.json`, alongside the source hashes.
2. Author the existing qualitative fields plus `anki_suggestions` in
   `analysis.json`, and the usual prose in `analysis.md`.
3. Run `stamp-analysis <lang/id>`. It validates the structured suggestions and
   adds/replaces a clearly marked Anki section in `analysis.md`, with a bilingual
   table for each issue. It then hashes the final outputs. Do not manually add
   another Anki section. Repeated stamping does not duplicate tables.
4. Run `rebuild` **after stamping**, so the explorer's detailed analysis includes
   those tables and its structured data retains the sentence pairs.

Validation checks counts, required text, duplicate issues/sentences, and cloze
syntax. The qualitative author must still check grammaticality, complete
sentences, translation accuracy, and pedagogical relevance.

Existing analyses remain readable and rebuildable without the new field. They
are not silently rewritten or relabeled with the new rubric. To update one,
first run `snapshot-analysis <lang/id>`, then author its sentence examples,
stamp, and rebuild. Attempting to stamp an old-format analysis without the new
field fails before changing its prose, input manifest, or provenance. Existing
audio and transcripts need no retranscription.
