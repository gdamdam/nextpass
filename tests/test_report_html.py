import contextlib
import io
import json
import tempfile
import unittest
from datetime import timezone
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

import meteor_passes as app
from nextpass.report_html import _card

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

    def test_jsonl_live_stream_is_not_interrupted_by_report_confirmation(self):
        with tempfile.TemporaryDirectory() as d:
            report = Path(d) / 'passes.html'
            with patch('nextpass.live_view.show_live',
                       side_effect=lambda *args, **kwargs: print(json.dumps({'tick': 1}))):
                code, out, err = self.run_cli('--report', str(report), '--live',
                                              '--live-format', 'jsonl')
            self.assertEqual(code, 0, err)
            self.assertEqual([json.loads(line) for line in out.splitlines()], [{'tick': 1}])
            self.assertIn('Saved report', err)

    def _card(self, **extra):
        row = {
            'rank': 1, 'satellite': 'Test sat', 'norad': 123,
            'rise': '2026-09-21T20:00:00+00:00',
            'peak': '2026-09-21T20:12:00+00:00',
            'set': '2026-09-21T20:20:00+00:00',
            'rise_azimuth_deg': 10, 'peak_azimuth_deg': 90, 'set_azimuth_deg': 170,
            'window_minutes': 20, 'range_at_peak_km': 800,
            'max_elevation_deg': 45, 'geometry': 'test',
            'visible_at_peak': False,
        }
        row.update(extra)
        args = SimpleNamespace(frequency=None)
        with patch('nextpass.meteor_passes.sample_track', return_value=([0, 90], [0, 45])):
            return _card(row, timezone.utc, {123: object()}, None, None, args, None)

    def test_report_visual_uses_whole_pass_visibility_and_candidate_window(self):
        html = self._card(visible_during_pass=True,
                          visual_candidate_start='2026-09-21T20:10:00+00:00',
                          visual_candidate_end='2026-09-21T20:15:00+00:00')
        self.assertIn('<dd>candidate (20:10–20:15)</dd>', html)

    def test_report_visual_falls_back_to_peak_visibility(self):
        self.assertIn('<dd>no</dd>', self._card())


if __name__ == '__main__':
    unittest.main()
