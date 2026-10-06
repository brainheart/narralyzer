import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import publication
import publish


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.record = {'id': 'de/2026-10-01_0644', 'lang': 'de',
                       'transcript': 'A private transcript that must not ship.',
                       'wpm': 90, 'analysis_md': 'A short analysis with evidence.',
                       'proficiency': {'status': 'rated', 'score': 50},
                       'future_raw_field': 'private future content',
                       'original_filename': 'private-recording.mp3',
                       'segments': [{'text': 'private words'}]}

    def test_default_omits_raw_data_but_preserves_analysis_and_metrics(self):
        result = publication.public_records([self.record], {})[0]
        self.assertEqual(result['transcript'], publication.OMITTED)
        self.assertEqual(result['analysis_md'], self.record['analysis_md'])
        self.assertEqual(result['wpm'], 90)
        self.assertEqual(result['proficiency']['score'], 50)
        self.assertNotIn('future_raw_field', result)
        self.assertNotIn('original_filename', result)
        self.assertNotIn('segments', result)
        self.assertEqual(self.record['transcript'], 'A private transcript that must not ship.')

    def test_only_matching_approval_shares_current_text(self):
        approvals = {self.record['id']: {'sha256': publication.digest(self.record['transcript'])}}
        self.assertEqual(publication.public_records([self.record], approvals)[0]['transcript'], self.record['transcript'])
        changed = dict(self.record, transcript='New unreviewed content')
        self.assertEqual(publication.sharing_state(changed, approvals), 'changed')
        self.assertEqual(publication.public_records([changed], approvals)[0]['transcript'], publication.OMITTED)
        other = dict(self.record, id='fr/2026-10-02_0631')
        self.assertEqual(publication.public_records([other], approvals)[0]['transcript'], publication.OMITTED)

    def test_nested_raw_fields_are_not_exported(self):
        self.record['analysis'] = {'summary': 'fine', 'transcript': 'leak', 'other': {'segments': ['leak']}}
        result = publication.public_records([self.record], {})[0]
        self.assertEqual(result['analysis'], {'summary': 'fine', 'other': {}})

    def test_approval_revocation_and_invalid_file_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / 'sessions' / self.record['id']
            session.mkdir(parents=True)
            (session / 'transcript.txt').write_text(self.record['transcript'] + '\n')
            publication.set_approval(root, self.record['id'], True)
            self.assertEqual(publication.sharing_state(self.record, publication.load_approvals(root)), 'approved')
            publication.set_approval(root, self.record['id'], False)
            self.assertEqual(publication.load_approvals(root), {})
            (root / 'config/transcript-sharing.json').write_text('{"approved": true}')
            with self.assertRaises(ValueError):
                publication.load_approvals(root)
            with self.assertRaises(ValueError):
                publication.set_approval(root, '../../escape', True)

    def test_build_separates_private_and_public_and_cleans_stale_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'explorer').mkdir()
            (root / 'explorer/index.html').write_text('<script src="data.js"></script>')
            (root / 'site/.openai').mkdir(parents=True)
            (root / 'site/.openai/hosting.json').write_text('{}')
            (root / 'build/public').mkdir(parents=True)
            (root / 'build/public/transcript.txt').write_text('old accidental copy')
            publication.build(root, [self.record])
            public = (root / 'build/public/data.js').read_text()
            private = (root / 'site/public/explorer/data.js').read_text()
            self.assertNotIn(self.record['transcript'], public)
            self.assertIn(self.record['transcript'], private)
            self.assertIn('omitted', private)
            self.assertFalse((root / 'build/public/transcript.txt').exists())
            self.assertIn('data.js?v=', (root / 'build/public/index.html').read_text())

    def test_audit_rejects_private_payload_and_full_text_in_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'data').mkdir()
            (root / 'data/sessions.json').write_text(json.dumps([self.record]))
            safe = publication.javascript(publication.public_records([self.record], {}), '', 'public').encode()
            self.assertEqual(publish.audit(root, {'data.js': safe}), 1)
            with self.assertRaises(ValueError):
                publish.audit(root, {'data.js': publication.javascript([self.record], '', 'public').encode()})
            with self.assertRaises(ValueError):
                publish.audit(root, {'data.js': safe, 'leak.txt': self.record['transcript'].encode()})


if __name__ == '__main__':
    unittest.main()
