#!/usr/bin/env python3
"""Predict satellite radio passes using CelesTrak GP data and Skyfield."""
import argparse
import csv
import json
import math
import os
import sys
import tempfile
import re
from datetime import datetime, timedelta, time, timezone, date
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

# NORAD IDs verified against the live CelesTrak catalog on 2026-09-22. A wrong number
# silently predicts a different object, so confirm against CelesTrak before editing.
# label, group, CelesTrak OBJECT_NAME
CATALOG = {
    57166: ('M2-3',   'meteor',   'METEOR-M2 3'),
    59051: ('M2-4',   'meteor',   'METEOR-M2 4'),
    25544: ('ISS',    'stations', 'ISS (ZARYA)'),
    48274: ('CSS',    'stations', 'CSS (TIANHE)'),
    39444: ('AO-73',  'amateur',  'FUNCUBE-1 (AO-73)'),
    44909: ('RS-44',  'amateur',  'RS-44 & BREEZE-KM R/B'),
    27607: ('SO-50',  'amateur',  'SAUDISAT 1C (SO-50)'),
    61781: ('AO-123', 'amateur',  'ASRTU-1 (AO-123)'),
}
GROUPS = ('meteor', 'stations', 'amateur')
SATELLITES = {cat: entry[0] for cat, entry in CATALOG.items()}
APP_VERSION = '1.4.0'

# Required by Skyfield's EarthSatellite.from_omm().
OMM_REQUIRED_FIELDS = (
    'OBJECT_NAME', 'OBJECT_ID', 'EPOCH', 'MEAN_MOTION', 'ECCENTRICITY',
    'INCLINATION', 'RA_OF_ASC_NODE', 'ARG_OF_PERICENTER', 'MEAN_ANOMALY',
    'EPHEMERIS_TYPE', 'CLASSIFICATION_TYPE', 'NORAD_CAT_ID',
    'ELEMENT_SET_NO', 'REV_AT_EPOCH', 'BSTAR', 'MEAN_MOTION_DOT',
    'MEAN_MOTION_DDOT',
)
OMM_NUMERIC_FIELDS = (
    'MEAN_MOTION', 'ECCENTRICITY', 'INCLINATION', 'RA_OF_ASC_NODE',
    'ARG_OF_PERICENTER', 'MEAN_ANOMALY', 'EPHEMERIS_TYPE', 'NORAD_CAT_ID',
    'ELEMENT_SET_NO', 'REV_AT_EPOCH', 'BSTAR', 'MEAN_MOTION_DOT',
    'MEAN_MOTION_DDOT',
)
OMM_INTEGER_FIELDS = ('EPHEMERIS_TYPE', 'NORAD_CAT_ID', 'ELEMENT_SET_NO', 'REV_AT_EPOCH')


def select(spec, catalog=None):
    """Resolve a --satellites spec of labels, groups or NORAD IDs to {norad: label}."""
    catalog = CATALOG if catalog is None else catalog
    labels = {cat: entry[0] for cat, entry in catalog.items()}
    groups = sorted({entry[1] for entry in catalog.values()})
    if spec is None:
        return labels
    if not spec.strip():
        raise ValueError('Satellite selection cannot be empty')
    chosen = {}
    for token in (piece.strip() for piece in spec.split(',')):
        if not token:
            continue
        key = token.upper()
        matched = {cat: label for cat, (label, group, _name) in catalog.items()
                   if key == label.upper() or key == group.upper() or token == str(cat)}
        if not matched:
            raise ValueError(f"Unknown satellite '{token}'. Choose labels ("
                             + ', '.join(labels.values()) + '), groups ('
                             + ', '.join(groups) + ') or NORAD IDs.')
        chosen.update(matched)
    if not chosen:
        raise ValueError('Satellite selection cannot be empty')
    return {cat: labels[cat] for cat in labels if cat in chosen}


def default_cache_dir():
    """Return a user-writable cache location for orbital element data."""
    cache_home = os.environ.get('XDG_CACHE_HOME')
    return (Path(cache_home) if cache_home else Path.home() / '.cache') / 'nextpass'


def warning(message):
    print('WARNING: ' + message, file=sys.stderr)


def load_elements(cat, cache, offline=False, refresh=False, ts=None, label=None):
    path = cache / f'{cat}.json'
    cached = None
    validation_ts = ts

    def check_constructible(row):
        nonlocal validation_ts
        if validation_ts is None:
            from skyfield.api import load
            validation_ts = load.timescale(builtin=True)
        validate_constructible(row, validation_ts)

    try:
        cached = json.loads(path.read_text())
        row = validate(cached, cat)
        check_constructible(row)
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    age = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) if cached else math.inf
    if offline:
        if cached is None:
            raise ValueError(f'No valid cached data for {cat}. Run once online or use --elements.')
        return cached, f'cache: {path}'
    if cached and age < 21600 and not refresh:
        return cached, f'cache: {path}'
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={cat}&FORMAT=JSON'
    try:
        request = Request(url, headers={'User-Agent': f'nextpass/{APP_VERSION}'})
        with urlopen(request, timeout=25) as response:
            data = json.load(response)
        row = validate(data, cat)
        check_constructible(row)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if cached is None:
            raise ValueError(f'Cannot fetch {label or SATELLITES.get(cat, str(cat))}: {exc}. Try again later or supply --elements JSON.') from exc
        warning(f'Fetch failed for {label or SATELLITES.get(cat, str(cat))}; using cached elements ({exc}).')
        return cached, f'fallback cache: {path}'
    cache.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f'.{cat}.', suffix='.tmp', dir=cache)
    try:
        with os.fdopen(fd, 'w') as tmp:
            json.dump(data, tmp, indent=2)
            tmp.write('\n')
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return data, url


def validate(data, cat):
    if not isinstance(data, list) or not data:
        raise ValueError('Expected a nonempty CelesTrak JSON array')
    matches = [row for row in data if isinstance(row, dict) and _is_integer(row.get('NORAD_CAT_ID')) and int(row['NORAD_CAT_ID']) == cat]
    if len(matches) != 1:
        raise ValueError(f'Expected exactly one element set for NORAD {cat}')
    row = matches[0]
    for field in OMM_REQUIRED_FIELDS:
        if field not in row or row[field] is None:
            raise ValueError(f'Missing orbital field: {field}')
    if not isinstance(row['EPOCH'], str) or not row['EPOCH'].strip():
        raise ValueError('Invalid orbital field: EPOCH')
    try:
        datetime.fromisoformat(row['EPOCH'].replace('Z', '+00:00'))
    except (TypeError, ValueError) as exc:
        raise ValueError(f'Invalid orbital field: EPOCH ({exc})') from exc
    for field in ('OBJECT_NAME', 'OBJECT_ID', 'CLASSIFICATION_TYPE'):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f'Invalid orbital field: {field}')
    try:
        values = {field: float(row[field]) for field in OMM_NUMERIC_FIELDS}
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'Invalid numeric orbital field: {exc}') from exc
    if any(not math.isfinite(value) for value in values.values()):
        raise ValueError('Orbital fields must be finite numbers')
    if values['MEAN_MOTION'] <= 0:
        raise ValueError('MEAN_MOTION must be positive')
    if not 0 <= values['ECCENTRICITY'] < 1:
        raise ValueError('ECCENTRICITY must be in [0, 1)')
    if not 0 <= values['INCLINATION'] <= 180:
        raise ValueError('INCLINATION must be in [0, 180]')
    if int(values['NORAD_CAT_ID']) != cat:
        raise ValueError(f'Element set NORAD_CAT_ID does not match {cat}')
    for field in OMM_INTEGER_FIELDS:
        if not _is_integer(row[field]):
            raise ValueError(f'{field} must be an integer')
    return row


def _is_integer(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return bool(re.fullmatch(r'[+-]?\d+', value.strip()))
    return isinstance(value, float) and math.isfinite(value) and value.is_integer()


def validate_constructible(row, ts):
    """Ensure Skyfield accepts and propagates the OMM row before use or caching."""
    try:
        from skyfield.api import EarthSatellite
        satellite = EarthSatellite.from_omm(ts, row)
        if satellite.model.satnum != int(row['NORAD_CAT_ID']):
            raise ValueError('NORAD number changed during Skyfield construction')
        state = satellite.at(satellite.epoch)
        if state.message:
            raise ValueError(f'Propagation failed: {state.message}')
        values = tuple(state.position.km) + tuple(state.velocity.km_per_s)
        if not values or any(not math.isfinite(float(value)) for value in values):
            raise ValueError('non-finite state at orbital epoch')
        return satellite
    except Exception as exc:
        raise ValueError(f'OMM element set cannot be loaded by Skyfield: {exc}') from exc


def direction(degrees):
    names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return names[int((degrees + 11.25) // 22.5) % 16]


def predict(sat, observer, ts, start, end, tz, horizon, min_elevation, label=None):
    # Padding captures complete passes that straddle a requested boundary.
    t, events = sat.find_events(observer, ts.from_datetime(start - timedelta(hours=3)),
                               ts.from_datetime(end + timedelta(hours=3)), altitude_degrees=horizon)
    topocentric = sat - observer
    rise, peaks = None, []
    result = []
    for moment, event in zip(t, events):
        if event == 0:
            rise, peaks = moment, []
        elif event == 1 and rise is not None:
            peaks.append(moment)
        elif event == 2 and rise is not None and peaks:
            peak = max(peaks, key=lambda p: topocentric.at(p).altaz()[0].degrees)
            peak_dt = peak.utc_datetime()
            alt, az, distance = topocentric.at(peak).altaz()
            # Include by peak time, which makes adjacent date queries nonoverlapping.
            if start <= peak_dt < end and alt.degrees >= min_elevation:
                rise_az = topocentric.at(rise).altaz()[1].degrees
                set_az = topocentric.at(moment).altaz()[1].degrees
                result.append(dict(satellite=label or SATELLITES.get(sat.model.satnum, str(sat.model.satnum)), norad=sat.model.satnum,
                    rise=rise.utc_datetime().astimezone(tz).isoformat(timespec='seconds'),
                    peak=peak_dt.astimezone(tz).isoformat(timespec='seconds'),
                    set=moment.utc_datetime().astimezone(tz).isoformat(timespec='seconds'),
                    max_elevation_deg=round(float(alt.degrees), 2),
                    rise_azimuth_deg=round(float(rise_az), 1), peak_azimuth_deg=round(float(az.degrees), 1),
                    set_azimuth_deg=round(float(set_az), 1),
                    range_at_peak_km=round(float(distance.km), 1),
                    window_minutes=round(float(moment-rise)*1440, 2),
                    geometry='Excellent' if alt.degrees >= 60 else 'Good' if alt.degrees >= 40 else 'Fair' if alt.degrees >= 20 else 'Low',
                    epoch_utc=sat.epoch.utc_datetime().isoformat(timespec='seconds')))
            rise, peaks = None, []
    return result


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument('--version', action='version', version=f'%(prog)s {APP_VERSION}')
    p.add_argument('--date', type=date.fromisoformat, help='First local calendar date YYYY-MM-DD; omit to start now')
    p.add_argument('--days', type=int, default=7, help='Number of local calendar days; without --date, now to this time N days later')
    p.add_argument('--location-config', type=Path, default=Path(os.environ.get('RADIO_LOCATION_CONFIG', str(Path.home()/'.config/radio/location.json'))), help='Private location JSON, stored outside the repository')
    p.add_argument('--lat', type=float)
    p.add_argument('--lon', type=float)
    p.add_argument('--altitude', type=float, help='Observer elevation in metres')
    p.add_argument('--timezone')
    p.add_argument('--min-elevation', type=float, default=20, help='Minimum peak elevation, degrees')
    p.add_argument('--horizon', type=float, default=10, help='Elevation at which the reported reception window starts/ends; 0 for geometric AOS/LOS')
    p.add_argument('--hours', help='Only peaks in local hour range, e.g. 08:00-22:00; overnight ranges allowed')
    p.add_argument('--color', choices=['auto','always','never'], default='auto', help='Colors optimized for black terminals; auto disables color when redirected')
    p.add_argument('--plots', type=int, default=1, help='Draw this many best passes in the terminal')
    p.add_argument('--no-plot', dest='plots', action='store_const', const=0, help='Show schedule without sky plots')
    p.add_argument('--plot-rank', type=int, help='Draw a particular ranked pass instead of the best passes')
    p.add_argument('--top', type=int, default=5, help='Number of best opportunities to highlight')
    p.add_argument('--refresh', action='store_true', help='Refresh orbital elements instead of using a cache younger than 6 hours')
    p.add_argument('--offline', action='store_true', help='Use cached orbital elements without network access')
    p.add_argument('--radio', action='store_true', help='Include optional SatNOGS transmitter metadata (network/cache)')
    p.add_argument('--band', help='Limit radio metadata to overlapping downlinks in a MHz range, e.g. 137-138')
    p.add_argument('--refresh-radio', action='store_true', help='Refresh SatNOGS transmitter metadata (also enables --radio)')
    p.add_argument('--radio-file', type=Path, help='Local JSON transmitter metadata supplement/override; no network required')
    p.add_argument('--satellites', help='Comma-separated labels ('
        + ', '.join(SATELLITES.values()) + '), groups (' + ', '.join(GROUPS) + ') or NORAD IDs; default all')
    p.add_argument('--elements', type=Path, help='CelesTrak JSON array of element sets; objects absent from the file are skipped with a warning')
    p.add_argument('--allow-stale', action='store_true', help='Permit dates more than 14 days from an orbital epoch; unreliable')
    p.add_argument('--cache-dir', type=Path, default=default_cache_dir(),
                   help='Orbital-element cache directory (default: XDG cache or ~/.cache/nextpass)')
    p.add_argument('--json', type=Path, dest='json_path', help='Save full results and metadata as JSON')
    p.add_argument('--csv', type=Path, dest='csv_path', help='Save chronological passes as CSV')
    p.add_argument('--catalog', type=Path, help='JSON satellite catalog entries to add or override built-ins')
    p.add_argument('--ics', type=Path, help='Export calendar events with optional advance alarms')
    p.add_argument('--reminder-minutes', type=int, default=15, help='Calendar alarm minutes before window start; 0 disables alarms')
    p.add_argument('--visibility', action='store_true', help='Annotate sunlight and observer darkness at pass peak')
    p.add_argument('--visible-only', action='store_true', help='Only passes sunlit at peak with a dark observer; enables --visibility')
    p.add_argument('--max-sun-altitude', type=float, default=-6, help='Maximum observer Sun altitude for visual filtering, degrees')
    p.add_argument('--ephemeris', type=Path, help='Local planetary BSP for visibility; otherwise cache/download de421.bsp')
    return p


def main(argv=None):
    p = parser(); args = p.parse_args(argv)
    try:
        from planning_features import load_catalog, export_calendar, annotate_visibility
        if args.reminder_minutes < 0:
            raise ValueError('--reminder-minutes must be nonnegative')
        if not -90 <= args.max_sun_altitude <= 90:
            raise ValueError('--max-sun-altitude must be between -90 and 90')
        if args.band is not None:
            from radio_metadata import parse_band
            parse_band(args.band)
            if not (args.radio or args.refresh_radio or args.radio_file):
                raise ValueError('--band requires --radio, --refresh-radio or --radio-file')
        catalog = load_catalog(args.catalog, CATALOG) if args.catalog else CATALOG
        config = {}
        location_path = args.location_config.expanduser()
        config_error = None
        try:
            if location_path.exists():
                config = json.loads(location_path.read_text())
                if not isinstance(config, dict):
                    raise ValueError('Location config must be a JSON object')
        except OSError as exc:
            # An unreadable config is only fatal when the command line does not already
            # supply every field; explicit --lat/--lon should not depend on the file.
            # Malformed JSON still raises, so a corrupt config stays loud.
            config_error = exc
            warning(f'Cannot read {location_path}: {exc}. Falling back to command-line location options.')
        for key in ('lat', 'lon', 'altitude', 'timezone'):
            if getattr(args, key) is None:
                setattr(args, key, config.get(key))
        if any(getattr(args, key) is None for key in ('lat', 'lon', 'altitude', 'timezone')):
            if config_error is not None:
                raise ValueError(f'Location missing and {location_path} could not be read ({config_error}). Fix its permissions, or pass --lat, --lon, --altitude and --timezone.')
            raise ValueError('Location missing. Create ~/.config/radio/location.json with lat, lon, altitude, timezone; see README.md. No location is embedded in the code.')
        args.lat, args.lon, args.altitude = float(args.lat), float(args.lon), float(args.altitude)
        if args.plots < 0 or (args.plot_rank is not None and args.plot_rank < 1):
            raise ValueError('--plots must be nonnegative and --plot-rank must be positive')
        if not 1 <= args.days <= 366 or args.top < 1:
            raise ValueError('--days must be 1..366 and --top must be positive')
        if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180 or not math.isfinite(args.altitude):
            raise ValueError('Invalid observer coordinates or altitude')
        if not 0 <= args.horizon < 90 or not args.horizon <= args.min_elevation <= 90:
            raise ValueError('Require 0 <= horizon <= min-elevation <= 90, with horizon < 90')
        if args.offline and args.refresh:
            raise ValueError('--offline and --refresh cannot be combined')
        if args.offline and args.refresh_radio:
            raise ValueError('--offline and --refresh-radio cannot be combined')
        tz = ZoneInfo(args.timezone)
        start = datetime.combine(args.date, time(), tz) if args.date else datetime.now(tz)
        end = start + timedelta(days=args.days)
        hour_filter = None
        if args.hours:
            parts = args.hours.split('-')
            if len(parts) != 2:
                raise ValueError('--hours must be HH:MM-HH:MM without timezone offsets')
            a, b = time.fromisoformat(parts[0]), time.fromisoformat(parts[1])
            if a.tzinfo is not None or b.tzinfo is not None:
                raise ValueError('--hours must be HH:MM-HH:MM without timezone offsets')
            hour_filter = a, b
        from skyfield.api import EarthSatellite, load, wgs84
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(args.lat, args.lon, elevation_m=args.altitude)
        provided = None
        if args.elements:
            provided = json.loads(args.elements.read_text())
            if not isinstance(provided, list) or not provided:
                raise ValueError('--elements must contain a nonempty CelesTrak JSON array')
        rows, sources, satellites = [], [], {}
        selected = select(args.satellites, catalog)
        for cat, name in selected.items():
            if provided is not None and not [row for row in provided if isinstance(row, dict) and _is_integer(row.get('NORAD_CAT_ID')) and int(row['NORAD_CAT_ID']) == cat]:
                warning(f'{name}: no element set for NORAD {cat} in {args.elements}; skipping.')
                continue
            data, source = (provided, str(args.elements)) if provided is not None else load_elements(cat, args.cache_dir, args.offline, args.refresh, ts=ts, label=name)
            sat = validate_constructible(validate(data, cat), ts)
            satellites[cat] = sat
            max_age = max(abs(float(ts.from_datetime(d)-sat.epoch)) for d in (start, end))
            if max_age > 14 and not args.allow_stale:
                raise ValueError(f'{name}: requested dates are up to {max_age:.1f} days from orbital epoch. Use elements near your dates (--elements), shorten the range, or explicitly --allow-stale for rough planning.')
            if max_age > 7:
                warning(f'{name}: date range extends {max_age:.1f} days from epoch; refresh nearer the pass. Predictions may be inaccurate.')
            sources.append(dict(satellite=name, norad=cat, source=source, epoch_utc=sat.epoch.utc_datetime().isoformat(timespec='seconds'), max_epoch_distance_days=round(max_age, 2)))
            rows.extend(predict(sat, observer, ts, start, end, tz, args.horizon, args.min_elevation, label=name))
        if not satellites:
            raise ValueError('No selected satellites have usable orbital elements')
        if hour_filter:
            a, b = hour_filter
            def allowed(row):
                h = datetime.fromisoformat(row['peak']).time()
                return a <= h < b if a < b else h >= a or h < b if a > b else True
            rows = [r for r in rows if allowed(r)]
        visibility = None
        if args.visibility or args.visible_only:
            from skyfield.api import Loader, load_file
            ephemeris_path = args.ephemeris.expanduser() if args.ephemeris else args.cache_dir / 'de421.bsp'
            if ephemeris_path.exists():
                ephemeris = load_file(str(ephemeris_path))
            elif args.ephemeris or args.offline:
                raise ValueError(f'Visibility requires a local planetary ephemeris at {ephemeris_path}. Supply --ephemeris or run online once.')
            else:
                ephemeris = Loader(str(args.cache_dir))('de421.bsp')
            try:
                annotate_visibility(rows, satellites, observer, ts, ephemeris, args.max_sun_altitude)
            finally:
                ephemeris.close()
            visibility = dict(evaluation='at pass peak only; not a guarantee of visibility',
                              max_sun_altitude_deg=args.max_sun_altitude, ephemeris=str(ephemeris_path))
            if args.visible_only:
                rows = [row for row in rows if row['visible_at_peak']]
        rows.sort(key=lambda r: datetime.fromisoformat(r['peak']))
        ranked = sorted(rows, key=lambda r: (-r['max_elevation_deg'], r['range_at_peak_km']))
        for rank, row in enumerate(ranked, 1):
            row['rank'] = rank
        radio = None
        if args.radio or args.refresh_radio or args.radio_file:
            from radio_metadata import load_radio_metadata
            # Explicit local input errors remain fatal; optional remote metadata
            # must not discard already computed pass predictions.
            try:
                radio = load_radio_metadata(
                    satellites.keys(), args.cache_dir, offline=args.offline,
                    refresh=args.refresh_radio, band=args.band, radio_file=args.radio_file,
                    warn=warning)
            except (ValueError, OSError) as exc:
                if args.radio_file:
                    raise
                warning(f'Radio metadata unavailable; keeping pass predictions ({exc}).')
                radio = dict(status='unavailable', reason=str(exc), satellites={})
        metadata = dict(location=dict(lat=args.lat, lon=args.lon, altitude_m=args.altitude), timezone=args.timezone,
            start=start.isoformat(), end=end.isoformat(), horizon_deg=args.horizon, minimum_peak_deg=args.min_elevation,
            ranking='Peak elevation descending, then range at peak ascending; geometric opportunity, NOT predicted SNR or transmitter status.',
            sources=sources, passes=rows)
        if visibility is not None:
            metadata['visibility'] = visibility
        if radio is not None:
            metadata['radio'] = radio
        from terminal_view import render
        render(rows, ranked, sources, args, start, end, tz, satellites, observer, ts, radio=radio)
        for path in (args.json_path, args.csv_path, args.ics):
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
        if args.json_path:
            args.json_path.write_text(json.dumps(metadata, indent=2) + '\n')
        if args.csv_path:
            fields = ['satellite', 'norad', 'rise', 'peak', 'set', 'max_elevation_deg',
                      'rise_azimuth_deg', 'peak_azimuth_deg', 'set_azimuth_deg',
                      'range_at_peak_km', 'window_minutes', 'geometry', 'epoch_utc', 'rank',
                      'satellite_sunlit_at_peak', 'sun_altitude_at_peak_deg', 'visible_at_peak']
            with args.csv_path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
        if args.ics:
            export_calendar(rows, args.ics, reminder_minutes=args.reminder_minutes)
        return 0
    except ImportError:
        print('Missing Skyfield. Run: python3 -m pip install -r requirements.txt', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
