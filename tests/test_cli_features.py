import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import meteor_passes as app

ROOT = Path(__file__).resolve().parents[1]


class FeatureCliTests(unittest.TestCase):
    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = app.main(['--location-config', '/nonexistent-nextpass-test',
                            '--lat', '0', '--lon', '0', '--altitude', '0', '--timezone', 'UTC',
                            '--elements', str(ROOT / 'examples/elements-2026-09-21.json'),
                            '--satellites', 'meteor', '--date', '2026-09-21', '--days', '1',
                            '--no-plot', '--color', 'never', *extra])
        return code, out.getvalue(), err.getvalue()

    def test_optional_radio_failure_preserves_exports(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'passes.json'
            with patch('radio_metadata.urlopen', side_effect=OSError('outage')):
                code, out, err = self.run_cli('--radio', '--cache-dir', directory, '--json', str(output))
            self.assertEqual(code, 0, err)
            data = json.loads(output.read_text())
            self.assertTrue(data['passes'])
            self.assertEqual(data['radio']['status'], 'unavailable')
            self.assertIn('PASS SCHEDULE', out)
            self.assertIn('keeping pass predictions', err)

    def test_csv_schema_is_stable_with_empty_results(self):
        with tempfile.TemporaryDirectory() as directory:
            headers = []
            for minimum in ('20', '90'):
                output = Path(directory) / (minimum + '.csv')
                code, _, err = self.run_cli('--min-elevation', minimum, '--csv', str(output))
                self.assertEqual(code, 0, err)
                with output.open() as handle:
                    reader = csv.DictReader(handle)
                    headers.append(reader.fieldnames)
                    rows = list(reader)
                self.assertEqual(bool(rows), minimum == '20')
            self.assertEqual(*headers)
            self.assertIn('norad', headers[0])

    def test_band_requires_radio_and_is_validated(self):
        for extra in [('--band', '137-138'), ('--band', 'invalid'), ('--radio', '--band', 'invalid')]:
            code, _, err = self.run_cli(*extra)
            self.assertEqual(code, 2, err)

    def test_one_sided_mhz_local_file_can_render_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'local.json'
            local.write_text(json.dumps([{'norad_cat_id': 57166, 'downlink_low_mhz': 137.9}]))
            output = Path(directory) / 'passes.json'
            code, out, err = self.run_cli('--radio-file', str(local), '--cache-dir', directory, '--json', str(output))
            self.assertEqual(code, 0, err)
            self.assertIn('137.9 MHz', out)
            self.assertTrue(output.exists())

    def test_custom_catalog_new_norad_reaches_prediction_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / 'catalog.json'
            catalog.write_text(json.dumps([{'norad': 99901, 'label': 'TESTSAT', 'group': 'custom', 'name': 'Synthetic test'}]))
            row = json.loads((ROOT / 'examples/elements-2026-09-21.json').read_text())[0]
            row['NORAD_CAT_ID'] = 99901
            elements = Path(directory) / 'elements.json'
            elements.write_text(json.dumps([row]))
            output = Path(directory) / 'passes.json'
            code, _, err = self.run_cli('--catalog', str(catalog), '--satellites', 'custom', '--elements', str(elements), '--json', str(output))
            self.assertEqual(code, 0, err)
            data = json.loads(output.read_text())
            self.assertTrue(data['passes'])
            self.assertTrue(all(r['satellite'] == 'TESTSAT' and r['norad'] == 99901 for r in data['passes']))
            self.assertNotIn(99901, app.CATALOG)

    def test_ics_export_and_disabled_alarm(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'passes.ics'
            for minutes in ('15', '0'):
                code, _, err = self.run_cli('--ics', str(output), '--reminder-minutes', minutes)
                self.assertEqual(code, 0, err)
                content = output.read_text()
                self.assertIn('BEGIN:VEVENT', content)
                self.assertEqual('BEGIN:VALARM' in content, minutes == '15')

    def test_duration_ranking_and_private_location_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'passes.json'
            code, _, err = self.run_cli('--rank-by', 'duration', '--json', str(output))
            self.assertEqual(code, 0, err)
            rows = json.loads(output.read_text())['passes']
            ranked = sorted(rows, key=lambda row: row['rank'])
            self.assertEqual([row['window_minutes'] for row in ranked],
                             sorted([row['window_minutes'] for row in rows], reverse=True))
            location = Path(directory) / 'location.json'
            code, _, err = self.run_cli('--save-location', '--location-config', str(location))
            self.assertEqual(code, 0, err)
            self.assertEqual(location.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(location.read_text())['timezone'], 'UTC')

    def test_live_mode_reaches_display(self):
        with patch('live_view.show_live') as live:
            code, _, err = self.run_cli('--live')
        self.assertEqual(code, 0, err)
        live.assert_called_once()

    def test_offline_visibility_missing_ephemeris_never_downloads(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('skyfield.api.Loader', side_effect=AssertionError('download attempted')):
                code, _, err = self.run_cli('--visible-only', '--offline', '--cache-dir', directory)
            self.assertEqual(code, 2)
            self.assertIn('--elements supplies orbital data directly', err)

    def test_visible_only_filters_before_ranking_and_closes_ephemeris(self):
        def annotate(rows, *_args):
            for index, row in enumerate(rows):
                row.update(satellite_sunlit_at_peak=True, sun_altitude_at_peak_deg=-10,
                           visible_at_peak=index % 2 == 0)
        with tempfile.TemporaryDirectory() as directory:
            bsp = Path(directory) / 'planet.bsp'
            bsp.touch()
            output = Path(directory) / 'passes.json'
            ephemeris = Mock()
            with patch('skyfield.api.load_file', return_value=ephemeris), patch('planning_features.annotate_visibility', side_effect=annotate):
                code, out, err = self.run_cli('--visible-only', '--ephemeris', str(bsp), '--json', str(output))
            self.assertEqual(code, 0, err)
            ephemeris.close.assert_called_once()
            data = json.loads(output.read_text())
            self.assertTrue(data['passes'])
            self.assertTrue(all(row['visible_at_peak'] for row in data['passes']))
            self.assertEqual(sorted(row['rank'] for row in data['passes']), list(range(1, len(data['passes']) + 1)))
            self.assertIn('At peak:', out)
