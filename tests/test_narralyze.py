import importlib.util
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "narralyze.py"
SPEC = importlib.util.spec_from_file_location("narralyze", SCRIPT)
narralyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(narralyze)


class TranscriptionTests(unittest.TestCase):
    def timing(self):
        return {"text": "Un gato.", "language": "es",
                "transcription_backend": "local/test-whisper",
                "words": [{"word": "Un", "start": 1, "end": 2},
                          {"word": "gato.", "start": 2, "end": 3}]}

    def test_new_api_text_preserves_separate_timing_and_metrics(self):
        response = mock.Mock()
        response.json.return_value = {"text": "Veo un gato negro.", "languages": [{"code": "es"}]}
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "sample.wav"
            audio.write_bytes(b"fixture")
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(narralyze.requests, "post", return_value=response) as post, \
                    mock.patch.object(narralyze, "transcribe_local", return_value=self.timing()):
                result = narralyze.transcribe_api(audio, "test-placeholder")
        request = dict(post.call_args.kwargs["data"])
        self.assertEqual(request["model"], "gpt-transcribe")
        self.assertNotIn("timestamp_granularities[]", request)
        self.assertNotIn("language", request)
        self.assertIn("grammatical mistakes", request["prompt"])
        self.assertEqual(result["text"], "Veo un gato negro.")
        self.assertEqual(result["timing_text"], "Un gato.")
        self.assertEqual(result["words"], self.timing()["words"])
        metrics = narralyze.compute_metrics(result, 10)
        self.assertEqual(metrics["total_words"], 2)
        self.assertEqual(metrics["transcript_word_count"], 4)
        self.assertEqual(metrics["metrics_backend"], "local/test-whisper")
        self.assertAlmostEqual(metrics["speech_ratio"], 0.2)

    def test_legacy_api_override_retains_timestamp_parameters(self):
        response = mock.Mock()
        response.json.return_value = self.timing()
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "sample.mp3"
            audio.write_bytes(b"fixture")
            with mock.patch.dict(os.environ, {"NARRALYZE_API_MODEL": "whisper-1"}), \
                    mock.patch.object(narralyze.requests, "post", return_value=response) as post, \
                    mock.patch.object(narralyze, "transcribe_local") as local:
                result = narralyze.transcribe_api(audio, "test-placeholder")
        self.assertIn(("timestamp_granularities[]", "word"), post.call_args.kwargs["data"])
        self.assertEqual(result["transcription_backend"], "openai-api/whisper-1")
        local.assert_not_called()

    def test_forced_api_missing_key_fails_without_local_fallback(self):
        with mock.patch.dict(os.environ, {"NARRALYZE_BACKEND": "api"}), \
                mock.patch.object(narralyze, "load_api_key", return_value=None), \
                mock.patch.object(narralyze, "transcribe_local") as local:
            with self.assertRaisesRegex(ValueError, "requires"):
                narralyze.transcribe(Path("fixture.mp3"))
        local.assert_not_called()

    def test_no_key_fallback_is_recorded(self):
        with mock.patch.dict(os.environ, {"NARRALYZE_BACKEND": "auto"}), \
                mock.patch.object(narralyze, "load_api_key", return_value=None), \
                mock.patch.object(narralyze, "transcribe_local", return_value=self.timing()):
            result = narralyze.transcribe(Path("fixture.mp3"))
        self.assertIn("No OpenAI API key", result["transcription_fallback_reason"])

    def test_local_mode_does_not_access_keychain_or_api(self):
        with mock.patch.dict(os.environ, {"NARRALYZE_BACKEND": "local"}), \
                mock.patch.object(narralyze, "load_api_key") as key, \
                mock.patch.object(narralyze, "transcribe_api") as api, \
                mock.patch.object(narralyze, "transcribe_local", return_value=self.timing()):
            narralyze.transcribe(Path("fixture.mp3"))
        key.assert_not_called()
        api.assert_not_called()

    def test_environment_key_takes_priority(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-placeholder"}):
            self.assertEqual(narralyze.load_api_key(), "test-placeholder")

    def test_http_failure_records_status_without_response_secrets(self):
        response = mock.Mock(status_code=403)
        error = narralyze.requests.HTTPError("sensitive response not for logs", response=response)
        with mock.patch.dict(os.environ, {"NARRALYZE_BACKEND": "auto"}), \
                mock.patch.object(narralyze, "load_api_key", return_value="test-placeholder"), \
                mock.patch.object(narralyze, "transcribe_api", side_effect=error), \
                mock.patch.object(narralyze, "transcribe_local", return_value=self.timing()):
            result = narralyze.transcribe(Path("fixture.mp3"))
        self.assertEqual(result["transcription_fallback_reason"], "API HTTP 403")


class IntakeAssessmentTests(unittest.TestCase):
    def base_metrics(self):
        return {
            "duration_sec": 600.0,
            "total_words": 800,
            "wpm": 80.0,
            "speech_ratio": 0.75,
            "hallucinated_words_removed": 0,
        }

    def test_typical_first_person_session_is_accepted(self):
        text = "Ich gehe mit meinem Kater spazieren und ich sehe einen Baum. " * 20
        result = narralyze.assess_recording(text, "de", self.base_metrics())
        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["classification"], "likely_narralogue")

    def test_english_first_person_session_is_accepted(self):
        text = (
            "I am walking with my cat and I can see the houses and trees. " * 20
        )
        result = narralyze.assess_recording(text, "en", self.base_metrics())
        self.assertEqual(result["decision"], "accepted")
        self.assertEqual(result["classification"], "likely_narralogue")

    def test_unexpected_language_goes_to_review(self):
        result = narralyze.assess_recording(
            "Sto descrivendo la strada davanti a me.", "it", self.base_metrics())
        self.assertEqual(result["decision"], "needs_review")
        self.assertIn("unexpected_language", [r["code"] for r in result["reasons"]])

    def test_broadcast_like_recording_goes_to_review(self):
        text = (
            "Willkommen zu unserem Podcast. Unser Gast spricht im Interview. "
            "Bitte abonnieren."
        )
        result = narralyze.assess_recording(text, "de", self.base_metrics())
        self.assertEqual(result["decision"], "needs_review")
        self.assertIn(
            "possible_broadcast_or_interview",
            [r["code"] for r in result["reasons"]],
        )


class DuplicateProcessingTests(unittest.TestCase):
    def test_exact_duplicate_is_not_transcribed_or_added_as_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inbox = root / "inbox"
            sessions = root / "sessions"
            data = root / "data"
            explorer = root / "explorer"
            duplicates = root / "intake" / "duplicates"
            review = root / "intake" / "review"
            inbox.mkdir()
            canonical = sessions / "de" / "2026-06-06_0711"
            canonical.mkdir(parents=True)
            payload = b"same recording bytes"
            (canonical / "audio.mp3").write_bytes(payload)
            (canonical / "metrics.json").write_text(json.dumps({
                "id": "de/2026-06-06_0711",
                "date": "2026-06-06",
                "time": "07:11",
            }))
            (inbox / "260606_0711.mp3").write_bytes(payload)

            replacements = {
                "ROOT": root,
                "INBOX": inbox,
                "SESSIONS": sessions,
                "DATA": data,
                "EXPLORER": explorer,
                "INTAKE": root / "intake",
                "DUPLICATES": duplicates,
                "REVIEW": review,
            }
            with mock.patch.multiple(narralyze, **replacements), \
                    mock.patch.object(narralyze, "transcribe") as transcribe:
                narralyze.process_inbox()

            transcribe.assert_not_called()
            self.assertFalse((inbox / "260606_0711.mp3").exists())
            dispositions = list(duplicates.glob("*/disposition.json"))
            self.assertEqual(len(dispositions), 1)
            disposition = json.loads(dispositions[0].read_text())
            self.assertEqual(disposition["decision"], "duplicate")
            self.assertEqual(
                disposition["duplicate_of"],
                "sessions/de/2026-06-06_0711",
            )
            self.assertEqual(len(list(sessions.glob("*/*/metrics.json"))), 1)


class ReviewApprovalTests(unittest.TestCase):
    def test_human_review_can_promote_english_narralogue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            review = root / "intake" / "review"
            item = review / "260809_0646_deadbeef"
            item.mkdir(parents=True)
            audio = item / "audio.mp3"
            audio.write_bytes(b"english narralogue recording")
            (item / "transcript.txt").write_text("I see a tree and a cat.\n")
            (item / "transcript.json").write_text(json.dumps({
                "text": "I see a tree and a cat.",
                "language": "en",
                "transcription_backend": "test",
            }))
            (item / "metrics.json").write_text(json.dumps({
                "id": "en/2026-08-09_0646",
                "lang": "en",
                "language": "English",
                "date": "2026-08-09",
                "time": "06:46",
                "duration_sec": 600,
                "original_filename": "260809_0646.mp3",
                "transcription_backend": "test",
                "intake_assessment": {"decision": "needs_review"},
            }))
            (item / "disposition.json").write_text(json.dumps({
                "original_filename": "260809_0646.mp3",
                "audio_sha256": narralyze.sha256_file(audio),
                "audio_bytes": audio.stat().st_size,
                "processed_at": "2026-08-25T00:00:00+00:00",
                "decision": "needs_review",
            }))

            replacements = {
                "ROOT": root,
                "SESSIONS": sessions,
                "DATA": root / "data",
                "EXPLORER": root / "explorer",
                "INTAKE": root / "intake",
                "DUPLICATES": root / "intake" / "duplicates",
                "REVIEW": review,
            }
            with mock.patch.multiple(narralyze, **replacements):
                narralyze.approve_review(item.name, "en")

            session = sessions / "en" / "2026-08-09_0646"
            metrics = json.loads((session / "metrics.json").read_text())
            self.assertEqual(metrics["lang"], "en")
            self.assertEqual(
                metrics["intake_assessment"]["classification"],
                "human_confirmed_narralogue",
            )
            self.assertTrue((session / "intake-review.json").exists())
            self.assertTrue((session / "source.json").exists())
            self.assertFalse(item.exists())


class AnkiAnalysisTests(unittest.TestCase):
    def analysis(self):
        return {
            "anki_selection_note": "Only one clear lookup is supported by this sample.",
            "anki_suggestions": [{
                "issue": "insecto: masculine noun and plural",
                "reason": "An explicit word search during the walk.",
                "examples": [
                    {"sentence": "Hay un insecto en la ventana.",
                     "translation": "There is an insect on the window."},
                    {"sentence": "Los insectos son pequeños.",
                     "translation": "The insects are small."},
                    {"sentence": "Este insecto es pequeño, pero esos insectos son grandes.",
                     "translation": "This insect is small, but those insects are big."},
                ],
            }],
        }

    def test_five_issues_and_fifteen_pairs_are_valid(self):
        analysis = {"anki_suggestions": []}
        for i in range(5):
            issue = copy.deepcopy(self.analysis()["anki_suggestions"][0])
            issue["issue"] += f" {i}"
            for example in issue["examples"]:
                example["sentence"] += f" ({i})"
            analysis["anki_suggestions"].append(issue)
        narralyze.validate_anki_suggestions(analysis)
        rendered = narralyze.render_anki_section("# Analysis\n", analysis)
        self.assertEqual(rendered.count("### "), 5)
        self.assertEqual(rendered.count("| English translation |"), 5)
        self.assertEqual(rendered.count("| There is an insect on the window. |"), 5)

    def test_render_is_idempotent_and_preserves_surrounding_prose(self):
        rendered = narralyze.render_anki_section("# Analysis\n\nExisting prose.\n", self.analysis())
        rendered += "\n## Later note\nKeep this.\n"
        self.assertEqual(narralyze.render_anki_section(rendered, self.analysis()), rendered)
        changed = self.analysis()
        changed["anki_suggestions"][0]["examples"][0]["sentence"] = "Veo un insecto."
        updated = narralyze.render_anki_section(rendered, changed)
        self.assertIn("Veo un insecto.", updated)
        self.assertNotIn("Hay un insecto", updated)
        self.assertTrue(updated.startswith("# Analysis\n\nExisting prose."))
        self.assertTrue(updated.endswith("## Later note\nKeep this.\n"))

    def test_malformed_suggestions_fail(self):
        invalid = []
        invalid.append({})  # Legacy is rebuildable, but cannot be newly stamped.
        a = self.analysis()
        del a["anki_selection_note"]
        invalid.append(a)
        a = self.analysis()
        a["anki_suggestions"] *= 6
        invalid.append(a)
        for count in (0, 2, 4):
            a = self.analysis()
            examples = a["anki_suggestions"][0]["examples"]
            a["anki_suggestions"][0]["examples"] = (examples * 2)[:count]
            invalid.append(a)
        for value in (None, "", "   ", "{{c1::insect}}"):
            a = self.analysis()
            a["anki_suggestions"][0]["examples"][0]["translation"] = value
            invalid.append(a)
        a = self.analysis()
        a["anki_suggestions"][0]["examples"][0]["sentence"] = "Hay un {{c2::insecto}}."
        invalid.append(a)
        a = self.analysis()
        a["anki_suggestions"][0]["examples"][1] = a["anki_suggestions"][0]["examples"][0]
        invalid.append(a)
        a = self.analysis()
        a["anki_suggestions"] *= 2
        invalid.append(a)
        for a in invalid:
            with self.subTest(analysis=a), self.assertRaises(ValueError):
                narralyze.validate_anki_suggestions(a)

    def test_empty_selection_requires_explanation(self):
        a = {"anki_suggestions": [], "anki_selection_note": "No reliable targets in this transcript."}
        rendered = narralyze.render_anki_section("# Analysis", a)
        self.assertIn(a["anki_selection_note"], rendered)
        self.assertNotIn("| Practice sentence |", rendered)

    def test_broken_markers_are_not_silently_overwritten(self):
        for text in (narralyze.ANKI_START, narralyze.ANKI_END,
                     narralyze.ANKI_END + narralyze.ANKI_START,
                     narralyze.ANKI_START * 2 + narralyze.ANKI_END):
            with self.subTest(text=text), self.assertRaises(ValueError):
                narralyze.render_anki_section(text, self.analysis())

    def test_table_cells_escape_pipes_and_collapse_line_breaks(self):
        a = self.analysis()
        a["anki_suggestions"][0]["examples"][0]["translation"] = "The symbol |\nmeans a pipe."
        rendered = narralyze.render_anki_section("# Analysis", a)
        self.assertIn(r"| The symbol \| means a pipe. |", rendered)

    def test_stamp_hashes_rendered_output_and_rebuild_includes_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            sdir = sessions / "es" / "2026-09-20_0700"
            sdir.mkdir(parents=True)
            (sdir / "analysis.md").write_text("# Analysis\n\nKeep this prose.\n")
            narralyze.write_json(sdir / "analysis.json", self.analysis())
            narralyze.write_json(sdir / "metrics.json", {
                "id": "es/2026-09-20_0700", "date": "2026-09-20", "time": "07:00",
            })
            (sdir / "transcript.txt").write_text("A saved transcript.\n")
            with mock.patch.multiple(narralyze, ROOT=root, SESSIONS=sessions,
                                     DATA=root / "data", EXPLORER=root / "explorer"):
                narralyze.stamp_analysis("es/2026-09-20_0700")
                narralyze.rebuild()
            provenance = json.loads((sdir / "analysis.provenance.json").read_text())
            self.assertEqual(provenance["analysis_rubric_version"], "2026-09-20.1")
            self.assertEqual(provenance["output_hashes"]["analysis.md"],
                             narralyze.sha256_file(sdir / "analysis.md"))
            inputs = json.loads((sdir / "analysis-input.json").read_text())
            self.assertEqual(inputs["anki_guidance"]["examples_per_issue"], 3)
            records = json.loads((root / "data" / "sessions.json").read_text())
            self.assertIn("Los insectos son pequeños.", records[0]["analysis_md"])
            self.assertEqual(records[0]["analysis"]["anki_suggestions"],
                             self.analysis()["anki_suggestions"])

    def test_legacy_rebuild_works_and_failed_stamp_preserves_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions = root / "sessions"
            for day, analysis in ((19, self.analysis()), (20, {"summary": "Legacy"})):
                sdir = sessions / "es" / f"2026-09-{day}_0700"
                sdir.mkdir(parents=True)
                (sdir / "analysis.md").write_text("# Unchanged old prose\n")
                narralyze.write_json(sdir / "analysis.json", analysis)
                narralyze.write_json(sdir / "metrics.json", {
                    "id": f"es/2026-09-{day}_0700", "date": f"2026-09-{day}", "time": "07:00",
                })
            before = {p: p.read_bytes() for p in sessions.rglob("*") if p.is_file()}
            with mock.patch.multiple(narralyze, ROOT=root, SESSIONS=sessions,
                                     DATA=root / "data", EXPLORER=root / "explorer"):
                narralyze.rebuild()
                with self.assertRaisesRegex(ValueError, "anki_suggestions"):
                    narralyze.stamp_analysis("all")
            after = {p: p.read_bytes() for p in sessions.rglob("*") if p.is_file()}
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
