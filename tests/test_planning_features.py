import json
import tempfile
import unittest
from pathlib import Path

import planning_features as features

ROOT = Path(__file__).resolve().parents[1]


class PlanningFeatureTests(unittest.TestCase):
    def test_catalog_optional_metadata_merges_and_validates(self):
        base = {25544: {'color': (1, 2, 3), 'radio_hint': 'Original hint.'}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps([
                {'norad': 25544, 'label': 'ISS', 'group': 'stations', 'name': 'ISS',
                 'color': [20, 30, 40], 'radio_hint': 'ISS SSTV 145.800 MHz.',
                 'verified': '2026-09-25'},
                {'norad': 99901, 'label': 'TEST', 'group': 'custom', 'name': 'Test'},
            ]))
            self.assertEqual(features.load_catalog_extras(path, base)[25544]['color'], (20, 30, 40))
            self.assertEqual(features.load_catalog_extras(path, base)[25544]['verified'], '2026-09-25')
            self.assertEqual(features.load_catalog_extras(path, base)[99901], {})
            self.assertEqual(base[25544]['color'], (1, 2, 3))
            for invalid in ([256, 0, 0], [True, 0, 0], [1, 2]):
                path.write_text(json.dumps([{'norad': 99901, 'color': invalid}]))
                with self.assertRaisesRegex(ValueError, 'color'):
                    features.load_catalog_extras(path)

    def test_calendar_uses_utc_stable_uid_escaped_text_and_alarm(self):
        row = {
            'norad': 25544,
            'satellite': 'ISS, ZARYA; \u00e9' * 12,
            'geometry': 'Good, clear',
            'rise': '2026-09-23T08:00:00-07:00',
            'peak': '2026-09-23T08:05:00-07:00',
            'set': '2026-09-23T08:10:00-07:00',
            'max_elevation_deg': 44.2,
        }
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / 'first.ics'
            second = Path(directory) / 'second.ics'
            features.export_calendar([row], first)
            features.export_calendar([row], second)
            text = first.read_bytes().decode('utf-8')
            second_text = second.read_bytes().decode('utf-8')

        self.assertIn('DTSTART:20260923T150000Z\r\n', text)
        self.assertIn('DTEND:20260923T151000Z\r\n', text)
        self.assertIn('TRIGGER:-PT15M\r\n', text)
        self.assertIn('SUMMARY:ISS\\, ZARYA\\; é', text)
        unfolded = text.replace('\r\n ', '')
        self.assertIn('Peak elevation: 44.2 degrees', unfolded)
        self.assertEqual(text.count('BEGIN:VEVENT'), 1)
        uids = [line for line in text.split('\r\n') if line.startswith('UID:')]
        self.assertEqual(uids, [line for line in second_text.split('\r\n') if line.startswith('UID:')])
        # Every folded physical content line is at most 75 UTF-8 octets.
        self.assertTrue(all(len(line.encode('utf-8')) <= 75 for line in text.split('\r\n') if line))

    def test_calendar_allows_disabling_alarm_and_checks_reminder(self):
        row = {'norad': 1, 'satellite': 'Bird', 'geometry': 'Low',
               'rise': '2026-09-23T10:00:00+00:00',
               'peak': '2026-09-23T10:01:00+00:00',
               'set': '2026-09-23T10:02:00+00:00'}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'pass.ics'
            features.export_calendar([row], output, reminder_minutes=0)
            self.assertNotIn('BEGIN:VALARM', output.read_text(encoding='utf-8'))
            with self.assertRaises(ValueError):
                features.export_calendar([row], output, reminder_minutes=True)

    def test_calendar_keeps_uid_after_small_prediction_shift(self):
        row = {'norad': 25544, 'satellite': 'ISS',
               'rise': '2026-09-23T10:00:00+00:00',
               'peak': '2026-09-23T10:05:00+00:00',
               'set': '2026-09-23T10:10:00+00:00'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'passes.ics'
            features.export_calendar([row], path)
            old_uid = next(line for line in path.read_text().splitlines() if line.startswith('UID:'))
            shifted = dict(row, rise='2026-09-23T10:03:00+00:00',
                           peak='2026-09-23T10:08:00+00:00', set='2026-09-23T10:13:00+00:00')
            features.export_calendar([shifted], path)
            new_uid = next(line for line in path.read_text().splitlines() if line.startswith('UID:'))
            self.assertEqual(old_uid, new_uid)

    def test_catalog_merges_without_mutating_and_validates_labels_and_ids(self):
        builtin = {10: ('Old', 'demo', 'Old object')}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'catalog.json'
            path.write_text(json.dumps([
                {'norad': 10, 'label': 'New', 'group': 'demo', 'name': 'Updated'},
                {'norad': 11, 'label': 'Extra', 'group': 'other', 'name': 'Other object'},
            ]), encoding='utf-8')
            loaded = features.load_catalog(path, builtin)
            self.assertEqual(loaded, {10: ('New', 'demo', 'Updated'), 11: ('Extra', 'other', 'Other object')})
            self.assertEqual(builtin, {10: ('Old', 'demo', 'Old object')})

            path.write_text(json.dumps([
                {'norad': 11, 'label': 'old', 'group': 'other', 'name': 'Duplicate label'},
            ]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate catalog label'):
                features.load_catalog(path, builtin)
            path.write_text(json.dumps([
                {'norad': True, 'label': 'Bad', 'group': 'other', 'name': 'Bad ID'},
            ]), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'positive integers'):
                features.load_catalog(path, builtin)
            for field, value in (('label', 'Bad,Label'), ('group', 'bad\ngroup')):
                record = {'norad': 11, 'label': 'Okay', 'group': 'okay', 'name': 'Object'}
                record[field] = value
                path.write_text(json.dumps([record]), encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'commas or control characters'):
                    features.load_catalog(path, builtin)

    def test_visibility_uses_satellite_sunlight_and_apparent_solar_altitude_at_peak(self):
        class Timescale:
            def from_datetime(self, value):
                return value

        class SatelliteState:
            def __init__(self, lit):
                self.lit = lit

            def is_sunlit(self, _ephemeris):
                return self.lit

        class Satellite:
            def __init__(self, lit):
                self.lit = lit
                self.requested_time = None

            def at(self, moment):
                self.requested_time = moment
                return SatelliteState(self.lit)

        class Altitude:
            def __init__(self, degrees):
                self.degrees = degrees

        class Apparent:
            def __init__(self, degrees):
                self.degrees = degrees

            def apparent(self):
                return self

            def altaz(self):
                return Altitude(self.degrees), None, None

        class ObserverPosition:
            def __init__(self, degrees):
                self.degrees = degrees

            def observe(self, _sun):
                return Apparent(self.degrees)

        class Observer:
            def __init__(self, degrees):
                self.degrees = degrees

            def at(self, _moment):
                return ObserverPosition(self.degrees)

        class Earth:
            def __add__(self, observer):
                return observer

        rows = [
            {'norad': 1, 'peak': '2026-09-23T10:05:00+00:00'},
            {'norad': 2, 'peak': '2026-09-23T10:05:00+00:00'},
            {'norad': 3, 'peak': '2026-09-23T10:05:00+00:00'},
        ]
        satellites = {1: Satellite(True), 2: Satellite(False), 3: Satellite(True)}
        result = features.annotate_visibility(rows, satellites, Observer(-8), Timescale(),
                                              {'earth': Earth(), 'sun': object()}, -6)
        self.assertIs(result, rows)
        self.assertEqual([row['visible_at_peak'] for row in rows], [True, False, True])
        self.assertEqual([row['satellite_sunlit_at_peak'] for row in rows], [True, False, True])
        self.assertEqual([row['sun_altitude_at_peak_deg'] for row in rows], [-8, -8, -8])
        self.assertEqual(satellites[1].requested_time.isoformat(), '2026-09-23T10:05:00+00:00')

        for altitude, expected in ((-5, False), (-6, True)):
            daylight_row = [{'norad': 1, 'peak': '2026-09-23T10:05:00+00:00'}]
            features.annotate_visibility(daylight_row, satellites, Observer(altitude), Timescale(),
                                         {'earth': Earth(), 'sun': object()}, -6)
            self.assertEqual(daylight_row[0]['visible_at_peak'], expected)

        with self.assertRaisesRegex(ValueError, 'computed solar altitude'):
            features.annotate_visibility([{'norad': 1, 'peak': '2026-09-23T10:05:00+00:00'}],
                                         satellites, Observer(-91), Timescale(),
                                         {'earth': Earth(), 'sun': object()}, -6)
        with self.assertRaisesRegex(ValueError, 'between -90 and 90'):
            features.annotate_visibility([], satellites, Observer(-8), Timescale(),
                                         {'earth': Earth(), 'sun': object()}, 91)


if __name__ == '__main__':
    unittest.main()
