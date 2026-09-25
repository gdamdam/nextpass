import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import meteor_passes as app

ROOT = Path(__file__).resolve().parents[1]


class ReportTests(unittest.TestCase):
    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = app.main(['--location-config', '/nonexistent-nextpass-test',
                            '--lat', '0', '--lon', '0', '--altitude', '0', '--timezone', 'UTC',
                            '--elements', str(ROOT / 'examples/elements-2026-09-21.json'),
                            '--satellites', 'meteor', '--date', '2026-09-21', '--days', '1',
                            '--no-plot', '--color', 'never', *extra])
        return code, out.getvalue(), err.getvalue()

    def test_report_has_schedule_and_one_chart_per_top_pass(self):
        with tempfile.TemporaryDirectory() as d:
            report, data = Path(d) / 'out' / 'passes.html', Path(d) / 'passes.json'
            code, out, err = self.run_cli('--top', '2', '--report', str(report), '--json', str(data))
            self.assertEqual(code, 0, err)
            self.assertIn('Saved report', out)
            html = report.read_text()
            passes = json.loads(data.read_text())['passes']
            self.assertGreater(len(passes), 2)
            self.assertEqual(html.count('<svg'), 2)
            for row in passes:
                self.assertIn(row['peak'][11:16], html)
            self.assertNotIn('class="mask"', html)

    def test_horizon_mask_is_shaded(self):
        with tempfile.TemporaryDirectory() as d:
            mask = Path(d) / 'horizon.json'
            mask.write_text(json.dumps([{'az': 0, 'el': 5}, {'az': 180, 'el': 15}]))
            report = Path(d) / 'passes.html'
            code, _, err = self.run_cli('--horizon-file', str(mask), '--report', str(report))
            self.assertEqual(code, 0, err)
            self.assertIn('class="mask"', report.read_text())

    def test_rejects_non_html_suffix(self):
        self.assertEqual(self.run_cli('--report', 'passes.pdf')[0], 2)


if __name__ == '__main__':
    unittest.main()
