# Narralyzer

**Start here: [Listen to Everyday Systems Podcast episode 106 — Narralogue](https://podcast.everydaysystems.com/episode/106/).** Reinhard explains the practice and how it fits into everyday language learning. The episode page includes audio and a transcript.

[Narralogue Explorer](https://narralyzer.everydaysystems.com/) tracks an everyday language-learning practice: speak continuously in your target language for a timed session, describing the world around you. Record occasionally, inspect patterns, and turn a few useful corrections into practice.

The public explorer includes Reinhard's metrics, analyses, Anki sentence examples, and experimental proficiency ratings. Full transcripts appear only after individual approval. Short quotations used in analyses and rating evidence remain visible. Recordings are not published.

Read the [Narralogue practice guide](docs/narralogue.md) for the idea behind the tool.

## Try it yourself

The pipeline is currently designed for macOS with Apple Silicon (local MLX Whisper). Install Python 3, ffmpeg, and the Python dependencies:

```sh
brew install ffmpeg
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p inbox
```

Put recordings with timestamps such as `261006_0630.mp3` into `inbox/`. Run:

```sh
python3 scripts/narralyze.py process
```

By default the readable transcript uses OpenAI when an API key is available, with a separate local Whisper timing pass. For fully local processing use `NARRALYZE_BACKEND=local`. See [transcription and credentials](docs/transcription.md).

An assistant then authors the qualitative analysis and independently evidenced proficiency rating for each new session. This is a human/assistant workflow, not an automatic scoring API. [AGENTS.md](AGENTS.md), [analysis format](docs/analysis-format.md), and [proficiency methodology](docs/proficiency-methodology.md) define the contracts. Stamp the completed outputs, then rebuild:

```sh
python3 scripts/narralyze.py stamp-analysis de/2026-10-06_0630
python3 scripts/narralyze.py stamp-proficiency de/2026-10-06_0630
python3 scripts/narralyze.py rebuild
python3 -m http.server 8765 --bind 127.0.0.1
```

View your full local data at `http://127.0.0.1:8765/explorer/` and the filtered public preview at `http://127.0.0.1:8765/build/public/`. Rebuilding uses your own `sessions/`; it does not import the demonstration data shipped at the repository root.

## Sharing and publishing

All full transcripts are private by default. After reviewing one, approve its exact current text:

```sh
python3 scripts/narralyze.py share-transcript de/2026-10-06_0630
python3 scripts/narralyze.py list-sharing
python3 scripts/narralyze.py unshare-transcript de/2026-10-06_0630
```

Changes invalidate approval automatically. New recordings are never implicitly approved. These commands rebuild locally; publish afterward to change the live site. Revocation removes a transcript from the next live build; it cannot recall copies or erase past public Git commits.

See [publishing](docs/publishing.md) for separate GitHub Pages and private ChatGPT Sites outputs. Configure your own repository/domain using `config/publishing.example.json` before publishing a fork. Never commit your recording workspace or full private data.

Scores are experimental monologue estimates, not CEFR test results. Speech recognition can normalize mistakes and omit fillers. Compare model provenance and recording conditions before interpreting changes as progress.
