# Narralogue proficiency: methodology and limits

Rubric: `narralogue-0-100-v1`, introduced 1 October 2026.

## What the old CEFR labels meant

The existing `cefr_estimate` and `sophistication_score` were authored by Codex
after reading each transcript. Python stored and displayed them; it did not
calculate CEFR from WPM, vocabulary diversity or errors. The workflow asked for
grammar, vocabulary, clause complexity, tense variety and idiomaticity, but had
no anchored scoring rubric, trained-rater calibration, second-rater agreement
or validation against an examination. Labels such as B2+ and A2/B1 were already
informal subdivisions. They remain visible as **legacy estimates**, unchanged.

That was useful descriptive feedback, but not enough to support precise CEFR
measurement. A fluent-looking transcript, a low error count, or native language
status cannot establish C2. Automatic recognition may repair grammar, invent
words, omit fillers, or impose sentence boundaries. Earlier error counts also
used differing conventions; they must not be interpreted as a calibrated scale.

## What the new number measures

An **experimental, CEFR-informed estimate of performance in this particular
monologue**, using its transcript and timing diagnostics. It is not a full CEFR
qualification, a percentage of a language mastered, or an estimate of native
likeness. No listening, reading, writing, interaction or pronunciation score is
inferred. Fluency is especially provisional without direct audio review.

The Council of Europe's [spoken-performance table](https://www.coe.int/en/web/common-european-framework-reference-languages/table-3-cefr-3.3-common-reference-levels-qualitative-aspects-of-spoken-language-use)
distinguishes range, accuracy, fluency, interaction and coherence. We use the
four relevant to monologue and omit interaction rather than inventing it.
The [Companion Volume](https://rm.coe.int/commom-european-framework-of-reference-for-language-learning-teaching/16809ea0d4)
(printed pp. 37, 142, 183–185) explains why C2 is not a native-speaker standard
and expands the descriptive framework. Our adaptation, weights and numerical
subdivisions below are local design choices, not Council of Europe scales.

## Calculation and anchors

Rate each dimension independently on 0–6, allowing quarter-band steps:

| Local band | Reference anchor | Displayed equivalent |
| --- | --- | ---: |
| 0 | Below A1 / floor of this local scale | 0 |
| 1 | A1 | 17 |
| 2 | A2 | 33 |
| 3 | B1 | 50 |
| 4 | B2 | 67 |
| 5 | C1 | 83 |
| 6 | C2 | 100 |

`score = round_half_up(100 × (range + accuracy + coherence + fluency) / 24)`

Each dimension has equal 25% weight. This avoids claiming empirically optimized
weights we do not have. The aggregate can hide an uneven profile: inspect the
four ratings. It does not generate a new official CEFR label. A zero is a genuine
floor rating, never missing data. The 0 anchor is our below-A1 floor, **not a
claim that all official Pre-A1 descriptors mean zero ability**.

The [CEFR permits local subdivisions](https://www.coe.int/en/web/common-european-framework-reference-languages/level-%20descriptions).
Our evenly spaced anchors are a convenient display convention, not proof of
equal learning effort or equal psychometric distance. 80 is not twice the
proficiency of 40. Quarter-bands and integer totals provide recording resolution,
not demonstrated measurement accuracy; a one-point difference is not evidence
of learning. No statistical confidence interval or minimum meaningful change
has yet been established.

## Rating guide

These compact working cues are our operational adaptation, not quotations or
exhaustive CEFR descriptors. Use the linked originals to resolve ambiguities.

| Anchor | Range | Accuracy | Coherence | Fluency |
| --- | --- | --- | --- | --- |
| A1 | Mainly labels/formulas | Limited basic control | Mostly isolated units | Short bursts and searching |
| A2 | Everyday sentence patterns | Basic errors recur | Simple links | Short messages despite restarts |
| B1 | Familiar-topic explanation | Familiar patterns usually work | Connected sequence | Message sustained despite planning |
| B2 | Description and argument with complexity | Good control, meaning protected | Clear connected discourse | Generally even stretches |
| C1 | Flexible, broad expression | Errors uncommon | Controlled organization | Little effort apparent |
| C2 | Precise nuance and reformulation | Complex control sustained | Flexible cohesive structure | Smooth, flexible delivery |

0 requires positive evidence of performance below A1, not an empty or corrupted
transcript. For intermediate ratings: +0.25 = occasional convincing evidence of
the next anchor; +0.50 = a mixed profile; +0.75 = mostly the next anchor with a
recurring limitation. Do not award a higher band for a single impressive phrase.
Do not subtract for a topic that simply did not elicit a skill. Record that
opportunity limit; if it prevents a defensible judgment, withhold the composite.

### Evidence procedure

1. Read the **whole** readable transcript and the timing/quality metadata.
   First form judgments without deriving them from previous CEFR labels or
   chronology. This initial retrospective pass was not blinded: prior labels
   were visible in the workspace, which is a validation limitation.
2. For each dimension, retain exact transcript excerpts, a band and a rationale
   describing both demonstrated ability and the limiting evidence. Excerpts
   are ASR text, not audio-verified quotations. An uncertainty is not an error.
3. Accuracy considers complexity attempted and recurring reliable patterns,
   not just errors/100 words. Respect ordinary spoken fragments and repairs.
   Range includes grammar and lexical flexibility; MATTR is only context, not
   a CEFR conversion. Coherence follows ideas, not ASR punctuation.
4. Fluency considers continuity, word searches and repairs, with WPM,
   articulation, speech ratio and pauses as **diagnostics only**. Street noise,
   passers-by, deliberate slow practice and topic difficulty affect these.
   No universal WPM-to-level threshold, native-English normalization, or reward
   for speaking fast is used. Timing and readable GPT text are not word-aligned.
5. Mark `withheld` with a reason when corruption, extensive language switching,
   or insufficient material prevents rating all four dimensions. Never impute
   the missing dimension, borrow the previous score, or treat it as zero.
6. Keep the original transcript backend visible. The September 23–25 GPT text
   switch is a measurement change, not evidence of language improvement.

## Is this reasonably sound?

**Suitable for exploratory personal tracking, with caveats; not validated as a
fine-grained proficiency test.** The dimension choice is grounded in the CEFR,
the calculation is reproducible, and evidence and missingness are inspectable.
The judgments themselves remain subjective, ASR-mediated, task-limited and
single-rater. Recomputing an average does not validate those judgments.

Prefer sustained patterns across several comparable sessions in one language;
review the component evidence when a number moves. Do not compare small changes
across transcription models or languages. Keep the native-English sessions as
personal context, not an automatic 100 or a calibration target.

To establish stronger validity: have a CEFR-trained teacher independently rate
a stratified sample **from audio**, blind to dates and old ratings; compare
dimension disagreement and repeat ratings; use comparable prompts, multiple
tasks, and a separate interaction sample. Only then choose meaningful-change
thresholds or revise weights. No such calibration has been performed yet.

## Files, regeneration and coverage

`proficiency-rating.json` is the authored evidence; `proficiency.json` contains
the validated rating, computed total, timestamp and SHA-256 identities of its
transcript, timing, source record, rating, rubric and scoring code. Existing
`analysis.json`, Anki material and analysis provenance are not rewritten.

Author ratings with `rubric_version`, `status` (`rated` or `withheld`), `rater`,
`summary`, `limitations`, and `dimensions`. A rated dimension has `band`,
`quotes` (nonempty list of exact transcript excerpts) and `rationale`. A withheld
rating omits dimensions and uses its summary to explain the decision.

Run `python3 scripts/narralyze.py stamp-proficiency <lang/id|all>`, then `rebuild`.
Stamping validates all selected drafts before writing, checks excerpts against
the actual transcript, and archives a replaced stamped rating under
`proficiency-history/`. It is idempotent when unchanged. Rebuild suppresses stale
scores after source/rubric changes until reassessment and stamping. Stamping is
not itself reassessment: reread changed inputs before using it. Raw audio stays
in the session directory for future re-transcription.

The initial pass selected the earliest and latest three recordings in each
language (all two English recordings): 14 reviewed sessions, including two
withheld Spanish recordings. On 3 October 2026, the remaining 27 transcripts
and their timing diagnostics were reviewed under the **same unchanged rubric**:
24 additional scores and three additional withheld decisions. That historical
backfill covered **41 sessions: 36 scored, five withheld, none awaiting a rating**.
Subsequent sessions are assessed at intake; the chart shows current coverage.
The original 12 scores and two withheld judgments are unchanged. This coverage
update changes the documentation hash, not the rating rules or scale.

The five withheld sessions are German 8 June and 12 August, and Spanish 9 August,
30 August and 6 September. Substantial recognition corruption or language
ambiguity prevents defensible four-dimension scoring; each session records its
specific reason. Their gaps are not zero or evidence of decline. Audio review
or retranscription may make them assessable later. Future unreviewed sessions
still say **Not rated** until their evidence is read; no scores are mechanically
expanded from old labels. Full coverage of the assessable recordings removes
the initial date-selection gap but does not establish a validated trend or make
these occasional recordings representative of all practice.
