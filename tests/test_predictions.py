import contextlib
import io
import json
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import meteor_passes as app
from skyfield.api import EarthSatellite, load, wgs84

class PredictionTests(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'), '--lat','0','--lon','0','--altitude','0','--timezone','UTC','--elements', str(ROOT/'examples/elements-2026-09-21.json'), *args])
        return code, out.getvalue(), err.getvalue()

    def test_events_and_daily_boundaries(self):
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(0, 0, elevation_m=0)
        tz = ZoneInfo('UTC')
        elements = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())
        for row in elements:
            sat = EarthSatellite.from_omm(ts, row)
            start, middle, end = [datetime(2026, 9, d, tzinfo=tz) for d in (21,22,23)]
            first = app.predict(sat, observer, ts, start, middle, tz, 10, 20)
            second = app.predict(sat, observer, ts, middle, end, tz, 10, 20)
            both = app.predict(sat, observer, ts, start, end, tz, 10, 20)
            self.assertEqual([r['peak'] for r in first+second], [r['peak'] for r in both])
            self.assertTrue(both)
            for r in both:
                rise, peak, setting = [datetime.fromisoformat(r[k]) for k in ('rise','peak','set')]
                self.assertLess(rise, peak); self.assertLess(peak, setting)
                for boundary in (rise, setting):
                    altitude = (sat-observer).at(ts.from_datetime(boundary)).altaz()[0].degrees
                    self.assertAlmostEqual(altitude, 10, delta=.15)
                self.assertGreaterEqual(r['max_elevation_deg'],20)

    def test_export_ranking_hours_and_known_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'passes.json'; csv = Path(directory)/'passes.csv'
            code, stdout, err = self.run_cli('--date','2026-09-21','--days','3','--hours','08:00-22:00','--json',str(output),'--csv',str(csv))
            self.assertEqual(code,0,err)
            data=json.loads(output.read_text()); rows=data['passes']; self.assertTrue(rows)
            self.assertTrue(all(8<=datetime.fromisoformat(r['peak']).hour<22 for r in rows))
            ranked=sorted(rows,key=lambda r:r['rank'])
            self.assertEqual([r['max_elevation_deg'] for r in ranked], sorted([r['max_elevation_deg'] for r in rows],reverse=True))
            self.assertIn('satellite',csv.read_text())

    def test_stale_dates_rejected(self):
        code,out,err=self.run_cli('--date','2027-01-01','--days','1')
        self.assertEqual(code,2); self.assertIn('orbital epoch',err)

    def test_invalid_options(self):
        for options in [('--days','0'),('--lat','91'),('--horizon','30','--min-elevation','20'),('--offline','--refresh')]:
            self.assertEqual(self.run_cli(*options)[0],2)

    def test_missing_offline_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'No valid cached'):
                app.load_elements(57166,Path(directory),offline=True)

    def test_satellite_selection_by_label_group_and_norad(self):
        self.assertEqual(app.select(None), app.SATELLITES)
        self.assertEqual(app.select('iss'), {25544:'ISS'})
        self.assertEqual(app.select('meteor'), {57166:'M2-3', 59051:'M2-4'})
        self.assertEqual(app.select('stations'), {25544:'ISS', 48274:'CSS'})
        self.assertEqual(set(app.select('amateur')), {39444,44909,27607,61781})
        self.assertEqual(app.select('61781'), {61781:'AO-123'})
        # Mixed tokens dedupe and keep catalog order regardless of how they were typed.
        self.assertEqual(list(app.select('iss,meteor,ISS')), [57166,59051,25544])
        with self.assertRaisesRegex(ValueError,'Unknown satellite'):
            app.select('nope')
        self.assertEqual(self.run_cli('--satellites','nope')[0], 2)

    def test_elements_file_skips_absent_objects(self):
        # The fixture holds only the two METEOR birds; the other six are skipped, not fatal.
        code, out, err = self.run_cli('--days','1','--date','2026-09-21')
        self.assertEqual(code, 0)
        self.assertIn('no element set for NORAD 25544', err)
        self.assertNotIn('ISS', out)
        code, out, err = self.run_cli('--days','1','--date','2026-09-21','--satellites','meteor')
        self.assertEqual(code, 0)
        self.assertNotIn('no element set', err)

if __name__=='__main__': unittest.main()
