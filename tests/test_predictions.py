import contextlib
import copy
import io
import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from zoneinfo import ZoneInfo

import meteor_passes as app
from skyfield.api import EarthSatellite, load, wgs84

ROOT = Path(__file__).resolve().parents[1]

class PredictionTests(unittest.TestCase):
    def test_catalog_listing_and_custom_hint_through_cli(self):
        listing = io.StringIO()
        with contextlib.redirect_stdout(listing):
            self.assertEqual(app.main(['--list-satellites']), 0)
        self.assertIn('ELEKTRO-L 3', listing.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            catalog = Path(directory) / 'custom.json'
            catalog.write_text(json.dumps([{'norad': 57166, 'label': 'LONGCUSTOMSAT',
                                            'group': 'meteor', 'name': 'METEOR-M2 3',
                                            'color': [1, 2, 3],
                                            'radio_hint': 'Custom downlink test.'}]))
            code, out, err = self.run_cli('--date', '2026-09-21', '--days', '1',
                                          '--catalog', str(catalog), '--satellites',
                                          'LONGCUSTOMSAT', '--no-plot', '--color', 'never')
            self.assertEqual(code, 0, err)
            self.assertIn('Custom downlink test.', ' '.join(out.split()))
            self.assertNotIn('METEOR LRPT 137.900', out)

    def test_equal_hours_and_boolean_location_are_rejected(self):
        self.assertIn('start and end must differ', self.run_cli('--hours', '08:00-08:00')[2])
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'location.json'
            config.write_text(json.dumps({'lat': True, 'lon': 0, 'altitude': 0,
                                          'timezone': 'UTC'}))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = app.main(['--location-config', str(config), '--elements',
                                 str(ROOT / 'examples/elements-2026-09-21.json'),
                                 '--satellites', 'meteor'])
            self.assertEqual(code, 2)
            self.assertIn('boolean', err.getvalue())

    def test_live_jsonl_is_machine_readable(self):
        from nextpass.live_view import show_live
        ts = load.timescale(builtin=True)
        sat = EarthSatellite.from_omm(ts, json.loads((ROOT / 'examples/elements-2026-09-21.json').read_text())[0])
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('nextpass.live_view.time.sleep', side_effect=KeyboardInterrupt):
            show_live({57166: sat}, wgs84.latlon(0, 0), ts, ZoneInfo('UTC'),
                      format='jsonl', frequency_mhz=137.9)
        records = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['norad'], 57166)
        self.assertIn('receive_frequency_hz', records[0])

    def test_celestrak_http_error_stops_further_queries(self):
        elements = json.loads((ROOT / 'examples/elements-2026-09-21.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            for row in elements:
                (cache / f"{row['NORAD_CAT_ID']}.json").write_text(json.dumps([row]))
            state = {}
            error = HTTPError('https://celestrak.org/', 503, 'Unavailable', {}, None)
            with patch.object(app, 'urlopen', side_effect=error) as fetch, \
                 contextlib.redirect_stderr(io.StringIO()):
                for row in elements:
                    data, _source = app.load_elements(row['NORAD_CAT_ID'], cache,
                                                      refresh=True, http_state=state)
                    self.assertEqual(data[0]['NORAD_CAT_ID'], row['NORAD_CAT_ID'])
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(state['blocked'])
            error.close()

    def test_builtin_catalog_is_packaged_data(self):
        records = json.loads((ROOT / 'catalog.json').read_text())
        self.assertEqual(set(app.CATALOG), {record['norad'] for record in records})
        self.assertEqual(app.GROUPS, tuple(dict.fromkeys(record['group'] for record in records)))
        self.assertEqual(app.CATALOG_EXTRA[44903]['verified'], '2026-09-25')
        self.assertEqual(app.APP_VERSION, '1.9.0')

    def test_long_orbit_search_extends_past_three_hours(self):
        class LongOrbit:
            model = type('Model', (), {'no_kozai': 2 * 3.141592653589793 / (12 * 60)})()
            def find_events(self, _observer, start, end, **_kwargs):
                self.start, self.end = start.utc_datetime(), end.utc_datetime()
                return [], []
            def __sub__(self, _observer):
                return None
        sat = LongOrbit()
        ts = load.timescale(builtin=True)
        start = datetime(2026, 9, 21, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(app.predict(sat, None, ts, start, start + timedelta(hours=1),
                                     ZoneInfo('UTC'), 10, 20), [])
        self.assertLess(sat.start, start - timedelta(hours=12))

    def test_doppler_track_and_conflicts(self):
        from nextpass.tracking_features import annotate_overlaps, ground_plot, pointing
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(0, 0)
        sat = EarthSatellite.from_omm(ts, json.loads((ROOT / 'examples/elements-2026-09-21.json').read_text())[0])
        start = datetime(2026, 9, 21, tzinfo=ZoneInfo('UTC'))
        row = app.predict(sat, observer, ts, start, start + timedelta(days=1),
                          ZoneInfo('UTC'), 10, 20)[0]
        arrival = pointing(sat, observer, ts, datetime.fromisoformat(row['rise']), 137.9)
        departure = pointing(sat, observer, ts, datetime.fromisoformat(row['set']), 137.9)
        self.assertGreater(arrival['receive_frequency_hz'], 137900000)
        self.assertLess(departure['receive_frequency_hz'], 137900000)
        self.assertIn('footprint_radius_km', arrival)
        self.assertIn('A', ground_plot(row, sat, ts))
        other = dict(row, satellite='OTHER', norad=99901)
        annotate_overlaps([row, other])
        self.assertEqual(row['overlaps'], ['OTHER'])

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
                self.assertLess(rise, peak)
                self.assertLess(peak, setting)
                for boundary in (rise, setting):
                    altitude = (sat-observer).at(ts.from_datetime(boundary)).altaz()[0].degrees
                    self.assertAlmostEqual(altitude, 10, delta=.15)
                self.assertGreaterEqual(r['max_elevation_deg'],20)

    def test_export_ranking_hours_and_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'passes.json'
            csv = Path(directory)/'passes.csv'
            code, stdout, err = self.run_cli('--date','2026-09-21','--days','3','--hours','08:00-22:00','--json',str(output),'--csv',str(csv))
            self.assertEqual(code,0,err)
            data=json.loads(output.read_text())
            rows=data['passes']
            self.assertTrue(rows)
            self.assertTrue(all(8<=datetime.fromisoformat(r['peak']).hour<22 for r in rows))
            ranked=sorted(rows,key=lambda r:r['rank'])
            self.assertEqual([r['max_elevation_deg'] for r in ranked], sorted([r['max_elevation_deg'] for r in rows],reverse=True))
            self.assertIn('satellite',csv.read_text())

    def test_stale_dates_rejected(self):
        code,out,err=self.run_cli('--date','2027-01-01','--days','1')
        self.assertEqual(code,2)
        self.assertIn('orbital epoch',err)

    def test_stale_warnings_print_last_and_bold(self):
        both = io.StringIO()
        with contextlib.redirect_stdout(both), contextlib.redirect_stderr(both):
            code = app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'), '--lat','0','--lon','0',
                             '--altitude','0','--timezone','UTC','--elements', str(ROOT/'examples/elements-2026-09-21.json'),
                             '--date','2026-09-29','--days','1','--satellites','meteor','--no-plot','--color','always'])
        text = both.getvalue()
        self.assertEqual(code, 0, text)
        self.assertIn('\033[1mWARNING: M2-3: date range extends', text)
        self.assertGreater(text.index('WARNING'), text.index('PASS SCHEDULE'))

    def test_invalid_options(self):
        for options in [('--days','0'),('--lat','91'),('--horizon','30','--min-elevation','20'),('--offline','--refresh')]:
            self.assertEqual(self.run_cli(*options)[0],2)

    def test_missing_offline_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,'No valid cached'):
                app.load_elements(57166,Path(directory),offline=True)

    def test_validation_requires_complete_omm_and_rejects_bad_cache(self):
        elements = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())
        incomplete = copy.deepcopy(elements[0])
        del incomplete['BSTAR']
        with self.assertRaisesRegex(ValueError, 'BSTAR'):
            app.validate([incomplete], 57166)
        invalid_epoch = copy.deepcopy(elements[0])
        invalid_epoch['EPOCH'] = '2026-09-21T06:53:42+00:00'
        with self.assertRaisesRegex(ValueError, 'cannot be loaded by Skyfield'):
            app.validate_constructible(invalid_epoch, load.timescale(builtin=True))
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache/'57166.json').write_text(json.dumps([incomplete]))
            with patch.object(app, 'urlopen', side_effect=OSError('offline')):
                with self.assertRaisesRegex(ValueError, 'Cannot fetch'):
                    app.load_elements(57166, cache)

    def test_corrupt_cache_recovers_from_download_and_leaves_no_temp_file(self):
        elements = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())

        class Response(io.StringIO):
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            (cache/'57166.json').write_text('{not json')
            replaced = []
            real_replace = os.replace
            def capture_replace(source, target):
                replaced.append(Path(source).name)
                return real_replace(source, target)
            with patch.object(app, 'urlopen', side_effect=[Response(json.dumps(elements)), Response(json.dumps(elements))]), \
                    patch.object(app.os, 'replace', side_effect=capture_replace):
                data, source = app.load_elements(57166, cache, refresh=True)
                app.load_elements(57166, cache, refresh=True)
            self.assertEqual(app.validate(data, 57166)['NORAD_CAT_ID'], 57166)
            self.assertIn('celestrak.org', source)
            self.assertEqual(len(set(replaced)), 2)
            self.assertEqual(list(cache.glob('*.tmp')), [])

    def test_concurrent_refreshes_use_independent_atomic_temp_files(self):
        elements = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())

        class Response(io.StringIO):
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            barrier = threading.Barrier(2)
            errors = []
            replace = os.replace
            def synchronized_replace(source, destination):
                barrier.wait(timeout=5)
                return replace(source, destination)
            def fetch(*_args, **_kwargs):
                return Response(json.dumps(elements))
            def refresh():
                try:
                    app.load_elements(57166, cache, refresh=True)
                except BaseException as exc:
                    errors.append(exc)
            with patch.object(app, 'urlopen', side_effect=fetch), patch.object(app.os, 'replace', side_effect=synchronized_replace):
                threads = [threading.Thread(target=refresh) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertEqual(app.validate(json.loads((cache/'57166.json').read_text()), 57166)['NORAD_CAT_ID'], 57166)
            self.assertEqual(list(cache.glob('*.tmp')), [])

    def test_invalid_download_keeps_valid_cache_and_falls_back(self):
        elements = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())

        class Response(io.StringIO):
            def __enter__(self): return self
            def __exit__(self, *_args): return False

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            cached = [elements[0]]
            cache.mkdir(exist_ok=True)
            (cache/'57166.json').write_text(json.dumps(cached))
            invalid = copy.deepcopy(cached[0])
            del invalid['BSTAR']
            with patch.object(app, 'urlopen', return_value=Response(json.dumps([invalid]))), \
                 contextlib.redirect_stderr(io.StringIO()):
                data, source = app.load_elements(57166, cache, refresh=True)
            self.assertEqual(data, cached)
            self.assertTrue(source.startswith('fallback cache:'))
            self.assertEqual(json.loads((cache/'57166.json').read_text()), cached)

    def test_satellite_selection_by_label_group_and_norad(self):
        self.assertEqual(app.select(None), app.SATELLITES)
        self.assertEqual(app.select('iss'), {25544:'ISS'})
        self.assertEqual(app.select('meteor'), {57166:'M2-3', 59051:'M2-4'})
        self.assertEqual(app.select('stations'), {25544:'ISS', 48274:'CSS'})
        self.assertEqual(set(app.select('amateur')), {39444,44909,27607,61781,43017,24278})
        self.assertEqual(app.select('61781'), {61781:'AO-123'})
        # Mixed tokens dedupe and keep catalog order regardless of how they were typed.
        self.assertEqual(list(app.select('iss,meteor,ISS')), [57166,59051,25544])
        with self.assertRaisesRegex(ValueError,'Unknown satellite'):
            app.select('nope')
        self.assertEqual(self.run_cli('--satellites','nope')[0], 2)

    def test_elements_file_skips_absent_objects(self):
        # The fixture holds only the two METEOR birds; missing built-ins are skipped.
        code, out, err = self.run_cli('--days','1','--date','2026-09-21')
        self.assertEqual(code, 0)
        self.assertIn('no element set for NORAD 25544', err)
        self.assertNotIn('ISS', out)
        code, out, err = self.run_cli('--days','1','--date','2026-09-21','--satellites','meteor')
        self.assertEqual(code, 0)
        self.assertNotIn('no element set', err)

    def test_null_elements_file_and_empty_or_unusable_selection_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            null_elements = Path(directory) / 'null.json'
            null_elements.write_text('null')
            code, _out, err = self.run_cli('--elements', str(null_elements), '--satellites', 'meteor')
            self.assertEqual(code, 2)
            self.assertIn('--elements must contain', err)
        self.assertEqual(self.run_cli('--satellites', ',')[0], 2)
        code, _out, err = self.run_cli('--satellites', 'iss')
        self.assertEqual(code, 2)
        self.assertIn('No selected satellites', err)

    def test_version_and_hours_reject_offsets(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as raised:
                app.parser().parse_args(['--version'])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn(app.APP_VERSION, output.getvalue())
        code, _out, err = self.run_cli('--hours', '08:00+01:00-22:00')
        self.assertEqual(code, 2)
        self.assertIn('without timezone offsets', err)

    def test_peak_matches_dense_reference_sampling(self):
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(0, 0, elevation_m=0)
        tz = ZoneInfo('UTC')
        row = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())[0]
        satellite = EarthSatellite.from_omm(ts, row)
        start = datetime(2026, 9, 21, tzinfo=tz)
        passes = app.predict(satellite, observer, ts, start, start.replace(day=22), tz, 10, 20)
        self.assertTrue(passes)
        # Sample a full day without find_events, sharing only the propagator.
        times = ts.linspace(ts.from_datetime(start), ts.from_datetime(start + timedelta(days=1)), 8641)
        elevations = (satellite - observer).at(times).altaz()[0].degrees
        sampled_peaks, segment = [], []
        for index, elevation in enumerate(elevations):
            if elevation >= 10:
                segment.append(index)
            elif segment:
                best = max(segment, key=lambda i: elevations[i])
                if elevations[best] >= 20:
                    sampled_peaks.append(best)
                segment = []
        self.assertEqual(len(passes), len(sampled_peaks))
        for predicted, index in zip(passes, sampled_peaks):
            peak = datetime.fromisoformat(predicted['peak'])
            self.assertLess(abs((peak - times[index].utc_datetime()).total_seconds()), 11)
            self.assertAlmostEqual(predicted['max_elevation_deg'], elevations[index], delta=0.1)

    def test_independent_pyephem_reference_cases(self):
        """Compare saved AOS/peak/LOS and elevation values from libastro."""
        fixture = json.loads((ROOT / 'tests/fixtures/pyephem-reference-2026-09-21.json').read_text())
        elements = {row['NORAD_CAT_ID']: row for row in json.loads(
            (ROOT / 'examples/elements-2026-09-21.json').read_text())}
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(0, 0, elevation_m=0)
        for case in fixture['cases']:
            start = datetime.fromisoformat(case['start'])
            end = datetime.fromisoformat(case['end'])
            tz = ZoneInfo(case['timezone'])
            actual = []
            for norad in sorted(elements):
                actual.extend(app.predict(EarthSatellite.from_omm(ts, elements[norad]), observer, ts,
                                          start, end, tz, case['horizon_deg'], case['minimum_peak_deg']))
            expected = sorted(case['passes'], key=lambda row: row['peak'])
            actual.sort(key=lambda row: row['peak'])
            self.assertEqual(len(actual), len(expected), case['name'])
            for predicted, reference in zip(actual, expected):
                self.assertEqual(predicted['norad'], reference['norad'], case['name'])
                for field in ('rise', 'peak', 'set'):
                    predicted_utc = datetime.fromisoformat(predicted[field]).astimezone(ZoneInfo('UTC'))
                    reference_utc = datetime.fromisoformat(reference[field])
                    self.assertLessEqual(abs((predicted_utc - reference_utc).total_seconds()), 3,
                                         f"{case['name']} {predicted['norad']} {field}")
                self.assertAlmostEqual(predicted['max_elevation_deg'], reference['max_elevation_deg'], delta=.2)

            # The reference TLEs are the exact quantized inputs sent to PyEphem.
            # This second check separates implementation differences from OMM->TLE
            # field precision loss before comparing production's from_omm path.
            same_tle = []
            for norad in sorted(elements):
                line1, line2 = case['reference_tles'][str(norad)]
                satellite = EarthSatellite(line1, line2, ts=ts)
                same_tle.extend(app.predict(satellite, observer, ts, start, end, tz,
                                            case['horizon_deg'], case['minimum_peak_deg']))
            same_tle.sort(key=lambda row: row['peak'])
            self.assertEqual(len(same_tle), len(expected), f"{case['name']} same TLE")
            for predicted, reference in zip(same_tle, expected):
                self.assertEqual(predicted['norad'], reference['norad'])
                for field in ('rise', 'peak', 'set'):
                    self.assertLessEqual(abs((datetime.fromisoformat(predicted[field])
                                              - datetime.fromisoformat(reference[field])).total_seconds()), 3)
                self.assertAlmostEqual(predicted['max_elevation_deg'], reference['max_elevation_deg'], delta=.2)
            elevations = [row['max_elevation_deg'] for row in expected]
            self.assertLess(min(elevations), 40)
            self.assertGreater(max(elevations), 60)
        dst = next(case for case in fixture['cases'] if case['name'] == 'auckland-dst-transition')
        offsets = {datetime.fromisoformat(row['peak']).utcoffset() for row in self._actual_for_reference_case(dst, elements, ts, observer)}
        self.assertEqual(offsets, {timedelta(hours=12), timedelta(hours=13)})
        midnight = next(case for case in fixture['cases'] if case['name'] == 'midnight-straddling-window')
        midnight_tz = ZoneInfo(midnight['timezone'])
        self.assertTrue(any(
            datetime.fromisoformat(row['rise']).astimezone(midnight_tz).date()
            != datetime.fromisoformat(row['peak']).astimezone(midnight_tz).date()
            for row in midnight['passes']))

    @staticmethod
    def _actual_for_reference_case(case, elements, ts, observer):
        start = datetime.fromisoformat(case['start'])
        end = datetime.fromisoformat(case['end'])
        tz = ZoneInfo(case['timezone'])
        result = []
        for norad in sorted(elements):
            result.extend(app.predict(EarthSatellite.from_omm(ts, elements[norad]), observer, ts,
                                      start, end, tz, case['horizon_deg'], case['minimum_peak_deg']))
        return result

    def test_dst_interval_preserves_local_timezone_offsets(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'dst.json'
            code, _out, err = self.run_cli('--date', '2026-10-31', '--days', '3',
                                            '--allow-stale', '--satellites', 'meteor',
                                            '--timezone', 'America/Los_Angeles',
                                            '--no-plot', '--json', str(output))
            self.assertEqual(code, 0, err)
            data = json.loads(output.read_text())
            self.assertTrue(data['start'].endswith('-07:00'))
            self.assertTrue(data['end'].endswith('-08:00'))

    def test_all_catalog_entries_accept_omm_fixture_shape(self):
        base = json.loads((ROOT/'examples/elements-2026-09-21.json').read_text())[0]
        expanded = []
        for norad, (label, _group, object_name) in app.CATALOG.items():
            row = copy.deepcopy(base)
            row.update({'NORAD_CAT_ID': norad, 'OBJECT_NAME': object_name,
                        'OBJECT_ID': f'2023-{norad:03d}A'})
            expanded.append(row)
        with tempfile.TemporaryDirectory() as directory:
            elements = Path(directory) / 'all.json'
            output = Path(directory) / 'all-results.json'
            elements.write_text(json.dumps(expanded))
            code, _out, err = self.run_cli('--elements', str(elements), '--date', '2026-09-21',
                                            '--days', '1', '--no-plot', '--json', str(output))
            self.assertEqual(code, 0, err)
            data = json.loads(output.read_text())
            self.assertEqual({row['norad'] for row in data['sources']}, set(app.CATALOG))

    def test_geostationary_reports_fixed_look_angle_not_passes(self):
        goes = {"OBJECT_NAME": "GOES 18", "OBJECT_ID": "2022-021A", "EPOCH": "2026-09-23T12:28:26.859648",
                "MEAN_MOTION": 1.0027214, "ECCENTRICITY": 3.557e-05, "INCLINATION": 0.0446,
                "RA_OF_ASC_NODE": 342.8132, "ARG_OF_PERICENTER": 248.2021, "MEAN_ANOMALY": 181.479,
                "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 51850,
                "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 757, "BSTAR": 0,
                "MEAN_MOTION_DOT": 9.5e-07, "MEAN_MOTION_DDOT": 0}
        with tempfile.TemporaryDirectory() as directory:
            elements = Path(directory) / 'goes.json'
            output = Path(directory) / 'goes-results.json'
            elements.write_text(json.dumps([goes]))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                # San Francisco sees GOES-18 (137.2 W) well above the horizon.
                code = app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'),
                                 '--lat', '37.77', '--lon', '-122.42', '--altitude', '0', '--timezone', 'UTC',
                                 '--elements', str(elements), '--satellites', 'goes18', '--date', '2026-09-23',
                                 '--days', '1', '--no-plot', '--json', str(output)])
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn('does not move', out.getvalue())
            # Stationary look angles don't drift with element age, so no refresh warning.
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err := io.StringIO()):
                app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'),
                          '--lat', '37.77', '--lon', '-122.42', '--altitude', '0', '--timezone', 'UTC',
                          '--elements', str(elements), '--satellites', 'goes18', '--date', '2026-10-02',
                          '--days', '1', '--no-plot'])
            self.assertNotIn('from epoch', err.getvalue())
            data = json.loads(output.read_text())
            self.assertEqual(data['passes'], [])
            [fixed] = data['stationary']
            self.assertTrue(fixed['above_horizon'])
            self.assertAlmostEqual(fixed['subsatellite_longitude_deg'], -137.2, delta=1)
            self.assertGreater(fixed['elevation_deg'], 30)
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'),
                                 '--lat', '37.77', '--lon', '-122.42', '--altitude', '0', '--timezone', 'UTC',
                                 '--elements', str(elements), '--satellites', 'goes18', '--date', '2026-09-23',
                                 '--days', '1', '--color', 'never'])
            self.assertEqual(code, 0)
            self.assertIn('P = fixed position', out.getvalue())
            # GOES-18 sits at ~43.7 deg elevation from San Francisco; a 60 deg
            # horizon puts it below the reportable window.
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                code = app.main(['--location-config', str(ROOT/'tests/nonexistent-private-location.json'),
                                 '--lat', '37.77', '--lon', '-122.42', '--altitude', '0', '--timezone', 'UTC',
                                 '--elements', str(elements), '--satellites', 'goes18', '--date', '2026-09-23',
                                 '--days', '1', '--horizon', '60', '--min-elevation', '60',
                                 '--json', str(output)])
            self.assertEqual(code, 0)
            data = json.loads(output.read_text())
            self.assertFalse(data['stationary'][0]['above_horizon'])
            self.assertIn('Below your horizon', out.getvalue())

    def test_inclined_geosynchronous_orbit_keeps_passes(self):
        ts = load.timescale(builtin=True)
        goes = {"OBJECT_NAME": "GOES 18", "OBJECT_ID": "2022-021A", "EPOCH": "2026-09-23T12:28:26.859648",
                "MEAN_MOTION": 1.0027214, "ECCENTRICITY": 3.557e-05, "INCLINATION": 0.0446,
                "RA_OF_ASC_NODE": 342.8132, "ARG_OF_PERICENTER": 248.2021, "MEAN_ANOMALY": 181.479,
                "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 51850,
                "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 757, "BSTAR": 0,
                "MEAN_MOTION_DOT": 9.5e-07, "MEAN_MOTION_DDOT": 0}
        self.assertTrue(app.is_geostationary(EarthSatellite.from_omm(ts, goes)))
        # is_geostationary is now only a period prefilter; inclination/eccentricity
        # no longer disqualify it there, so the geometric check must keep the passes.
        for changes in ({'INCLINATION': 60}, {'ECCENTRICITY': 0.3}):
            sat = EarthSatellite.from_omm(ts, {**goes, **changes})
            self.assertTrue(app.is_geostationary(sat), changes)
        # Same inclination change, but with the ascending node rotated so the ground
        # track's figure-eight actually sweeps over the (0, 0) test observer instead
        # of staying parked near GOES-18's real slot at -137 deg longitude.
        inclined = EarthSatellite.from_omm(ts, {**goes, 'INCLINATION': 60, 'RA_OF_ASC_NODE': 180})
        start = datetime(2026, 9, 23, tzinfo=ZoneInfo('UTC'))
        end = start + timedelta(days=1)
        passes = app.predict(inclined, wgs84.latlon(0, 0, elevation_m=0), ts, start, end,
                              ZoneInfo('UTC'), 0, 0)
        self.assertTrue(passes)

    def test_unreadable_location_config(self):
        if os.geteuid() == 0:
            self.skipTest('root bypasses file permissions')
        with tempfile.TemporaryDirectory() as directory:
            blocked = Path(directory)/'location.json'
            blocked.write_text('{"lat":1,"lon":2,"altitude":3,"timezone":"UTC"}')
            blocked.chmod(0o000)
            try:
                # Explicit coordinates make an unreadable config a warning, not an error.
                code, _out, err = self.run_cli('--location-config',str(blocked),'--days','1','--date','2026-09-21','--satellites','meteor')
                self.assertEqual(code, 0)
                self.assertIn('Cannot read', err)
                # With nothing on the command line it stays fatal, and says why.
                out2, err2 = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out2), contextlib.redirect_stderr(err2):
                    code2 = app.main(['--location-config',str(blocked),'--elements',str(ROOT/'examples/elements-2026-09-21.json'),'--days','1'])
                self.assertEqual(code2, 2)
                self.assertIn('could not be read', err2.getvalue())
            finally:
                blocked.chmod(0o600)

if __name__=='__main__':
    unittest.main()
