# Transcription models and credentials

Verified against the [OpenAI file transcription guide](https://developers.openai.com/api/docs/guides/speech-to-text)
on 26 September 2026. OpenAI recommends **gpt-transcribe** for recorded speech.
It does not supply the word timestamps needed for this project's pause metrics.
The local timing model remains `mlx-community/whisper-large-v3-turbo`.

## Default workflow

- The readable `transcript.txt` comes from **gpt-transcribe**, with a prompt to
  preserve mistakes, false starts, repetitions and fillers. This is a request,
  not a guarantee of verbatim transcription; grammar and filler counts remain
  lower bounds. No corrective text-model postprocessing is applied.
- A separate local Whisper pass supplies `words`, `segments`, and the existing
  quantitative metrics. These timestamps belong to the **Whisper words**, not
  to the GPT transcript. No fabricated alignment is attempted.
- `transcript.json` preserves the GPT API response, prompt, readable text,
  Whisper `timing_text`, word/segment data, model identifiers and language
  sources. The file is included in the usual provenance hashes.
- `metrics.json` records `metrics_backend`, `transcript_word_count`, and a
  `transcription_note`. `total_words`, WPM, articulation WPM, lexical diversity
  and fillers retain the existing Whisper-based methodology. For qualitative
  error rates based on the GPT text, use **transcript_word_count**, record the
  denominator explicitly, and warn against treating the model change as a
  learning improvement or regression.
- Auto mode falls back to local Whisper if no key is configured or the API
  returns an HTTP error. The reason is printed and saved in both transcript and
  metrics. Network/invalid-response errors stop the run, leaving inbox audio
  intact. A missing timing result also stops hybrid processing rather than
  inventing pace statistics.

## Key setup

Run this for a hidden-input macOS dialog:

```bash
python3 scripts/configure_api_key.py
```

Paste the key and click Save. The Python `keyring` macOS backend stores it under
service `narralyzer-openai-api`, with the current macOS username as account.
The key is not printed, placed in command-line arguments, or written into the
project. A Keychain access prompt may appear. The setup requires the installed
`keyring` package. `OPENAI_API_KEY` in the environment takes precedence when set.

The API key needs permission to make audio/model requests; a read-only key is
insufficient. Prefer narrowly scoped permissions. See [OpenAI permissions](https://developers.openai.com/api/docs/guides/rbac).

## Explicit modes

```bash
# Require API transcription; fail rather than silently use a local text model.
NARRALYZE_BACKEND=api python3 scripts/narralyze.py process

# Entirely local transcription; no credential lookup or API request.
NARRALYZE_BACKEND=local python3 scripts/narralyze.py process

# Legacy API model for an intentional comparison or compatibility need.
NARRALYZE_BACKEND=api NARRALYZE_API_MODEL=whisper-1 python3 scripts/narralyze.py process
```

The GPT path still requires the local Whisper dependencies for timing.
The API has a 25 MB upload limit; this pipeline does not silently truncate or
split oversized uploads. Original audio is always preserved. Existing sessions
are not retranscribed automatically when the default model changes.
