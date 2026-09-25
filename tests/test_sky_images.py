import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import meteor_passes as app
ROOT = Path(__file__).resolve().parents[1]
class DayPlotTests(unittest.TestCase):
    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = app.main(['--location-config','/nonexistent','--lat','0','--lon','0','--altitude','0','--timezone','UTC','--elements',str(ROOT/'examples/elements-2026-09-21.json'),'--satellites','M2-4','--date','2026-09-21','--days','1','--no-plot',*extra])
        return code, err.getvalue()
    def test_all_passes(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'passes.json'
            code,err=self.run_cli('--all-passes','--json',str(path))
            self.assertEqual(code,0,err)
            data=json.loads(path.read_text())
            self.assertEqual(data['horizon_deg'],0)
            self.assertTrue(any(r['max_elevation_deg']<20 for r in data['passes']))
    def test_full_day_and_validation(self):
        with patch('sky_images.require_matplotlib'), patch('sky_images.save_day_plot') as save:
            code,err=self.run_cli('--days','7','--day-plot','day.png')
            self.assertEqual(code,0,err)
            rows=save.call_args.args[0]
            self.assertEqual({r['peak'][:10] for r in rows},{'2026-09-21'})
            self.assertTrue(any(r['max_elevation_deg']<20 for r in rows))
            # Explicit thresholds must not conflict with the day-plot override.
            self.assertEqual(self.run_cli('--day-plot','day.png','--min-elevation','0')[0],0)
            for extra in [('--satellites','meteor'),('--hours','10:00-12:00'),('--visible-only',),('--day-plot','bad.txt')]:
                self.assertEqual(self.run_cli('--day-plot','day.png',*extra)[0],2)
    def test_formats_and_empty(self):
        try:
            __import__('matplotlib.pyplot')
        except ImportError:
            self.skipTest('optional Matplotlib not installed')
        with tempfile.TemporaryDirectory() as d:
            for ext,magic in [('png',b'\x89PNG'),('pdf',b'%PDF'),('svg',b'<?xml')]:
                path=Path(d)/('day.'+ext)
                code,err=self.run_cli('--day-plot',str(path))
                self.assertEqual(code,0,err)
                self.assertTrue(path.read_bytes().startswith(magic))
            with patch('meteor_passes.predict',return_value=[]):
                self.assertEqual(self.run_cli('--day-plot',str(Path(d)/'empty.png'))[0],0)
