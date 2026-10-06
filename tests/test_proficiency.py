import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('proficiency', ROOT / 'scripts/proficiency.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class ProficiencyTests(unittest.TestCase):
    def rating(self, band=3):
        return {'rubric_version': p.VERSION, 'status': 'rated', 'rater': 'test',
                'summary': 'test', 'limitations': 'test',
                'dimensions': {d: {'band': band, 'quotes': ['A whole sentence.'],
                                   'rationale': 'Supported judgment.'} for d in p.DIMENSIONS}}

    def test_anchors_and_half_up(self):
        for band, expected in enumerate([0, 17, 33, 50, 67, 83, 100]):
            self.assertEqual(p.calculate(self.rating(band), 'A whole sentence.'), expected)
        self.assertEqual(p.calculate(self.rating(.75), 'A whole sentence.'), 13)

    def test_invalid_bands_missing_dimension_and_quote(self):
        for value in [True, -1, 6.25, .3, float('nan'), float('inf'), '3']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.calculate(self.rating(value), 'A whole sentence.')
        rating = self.rating()
        del rating['dimensions']['fluency']
        with self.assertRaises(ValueError):
            p.calculate(rating, 'A whole sentence.')
        with self.assertRaisesRegex(ValueError, 'not present'):
            p.calculate(self.rating(), 'Different source.')

    def test_missing_is_not_zero(self):
        rating = self.rating()
        rating.update(status='withheld', dimensions={})
        self.assertIsNone(p.calculate(rating, ''))
        self.assertEqual(p.calculate(self.rating(0), 'A whole sentence.'), 0)

    def fixture(self, root):
        (root / 'docs').mkdir()
        (root / 'scripts').mkdir()
        (root / 'docs/proficiency-methodology.md').write_text('rubric')
        (root / 'scripts/proficiency.py').write_text('implementation')
        sdir = root / 'session'
        sdir.mkdir()
        for name in p.INPUTS:
            (sdir / name).write_text('A whole sentence.' if name.endswith('.txt') else '{}')
        (sdir / 'proficiency-rating.json').write_text(json.dumps(self.rating()))
        return sdir

    def test_idempotence_history_and_staleness(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdir = self.fixture(root)
            self.assertEqual(p.load_current(sdir, root)['status'], 'unrated')
            self.assertEqual(p.stamp([sdir], root), 1)
            original = (sdir / 'proficiency.json').read_bytes()
            self.assertEqual(p.stamp([sdir], root), 0)
            self.assertEqual((sdir / 'proficiency.json').read_bytes(), original)
            self.assertEqual(p.load_current(sdir, root)['score'], 50)
            for path in [sdir/'metrics.json', root/'docs/proficiency-methodology.md', root/'scripts/proficiency.py']:
                before = path.read_text()
                path.write_text(before + ' ')
                self.assertIsNone(p.load_current(sdir, root)['score'])
                path.write_text(before)
            (sdir / 'proficiency-rating.json').write_text(json.dumps(self.rating(4)))
            self.assertEqual(p.load_current(sdir, root)['status'], 'stale')
            self.assertEqual(p.stamp([sdir], root), 1)
            self.assertEqual(p.load_current(sdir, root)['score'], 67)
            self.assertEqual(next((sdir/'proficiency-history').glob('*.json')).read_bytes(), original)

    def test_all_validated_before_any_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sdir = self.fixture(root)
            bad = root / 'bad'
            bad.mkdir()
            (bad/'proficiency-rating.json').write_text('{}')
            (bad/'transcript.txt').write_text('A whole sentence.')
            with self.assertRaises(ValueError):
                p.stamp([sdir, bad], root)
            self.assertFalse((sdir/'proficiency.json').exists())

    def test_actual_backfill_evidence_and_independent_arithmetic(self):
        rated = withheld = 0
        for path in (ROOT/'sessions').glob('*/*/proficiency.json'):
            saved = json.loads(path.read_text())
            current = p.load_current(path.parent, ROOT)
            self.assertIn(current['status'], ('rated', 'withheld'), str(path))
            if current['status'] == 'rated':
                # Independent computation in integer quarter-band units.
                units = sum(round(v['band']*4) for v in current['dimensions'].values())
                expected = (units*100 + 48)//96
                self.assertEqual(saved['score'], expected)
                rated += 1
            else:
                self.assertIsNone(saved['score'])
                withheld += 1
        self.assertGreaterEqual(rated, 36)
        self.assertGreaterEqual(withheld, 5)


if __name__ == '__main__':
    unittest.main()
