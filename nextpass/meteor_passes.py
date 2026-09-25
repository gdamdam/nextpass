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
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
from nextpass.version import APP_VERSION
from nextpass.planning_features import load_catalog, load_catalog_extras
from nextpass.horizon import load_mask, mask_elevation, clear_window

_CATALOG_PATH = Path(__file__).with_name('catalog.json')
# Git checkouts without symlink support contain the symlink target as text.
# The build hook still copies the root JSON into wheels, while source runs use
# that root file directly on such platforms.
if _CATALOG_PATH.read_text(encoding='utf-8').strip() == '../catalog.json':
    _CATALOG_PATH = _CATALOG_PATH.parent.parent / 'catalog.json'
CATALOG = load_catalog(_CATALOG_PATH, {})
CATALOG_EXTRA = load_catalog_extras(_CATALOG_PATH)
GROUPS = tuple(dict.fromkeys(entry[1] for entry in CATALOG.values()))
SATELLITES = {cat: entry[0] for cat, entry in CATALOG.items()}

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


def warning(message, bold=False):
    text = 'WARNING: ' + message
    print(f'\033[1m{text}\033[0m' if bold else text, file=sys.stderr)


def stderr_bold(mode):
    return mode == 'always' or (mode == 'auto' and sys.stderr.isatty() and 'NO_COLOR' not in os.environ
                                and os.environ.get('TERM') != 'dumb')


def load_elements(cat, cache, offline=False, refresh=False, ts=None, label=None, http_state=None):
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
    if http_state is not None and http_state.get('blocked'):
        if cached is None:
            raise ValueError(f'CelesTrak returned an HTTP error earlier; cannot fetch {label or cat}. Supply --elements or retry later.')
        warning(f'Skipping CelesTrak request for {label or cat} after an HTTP error; using cached elements.')
        return cached, f'fallback cache: {path}'
    url = f'https://celestrak.org/NORAD/elements/gp.php?CATNR={cat}&FORMAT=JSON'
    try:
        request = Request(url, headers={'User-Agent': f'nextpass/{APP_VERSION}'})
        with urlopen(request, timeout=25) as response:
            data = json.load(response)
        row = validate(data, cat)
        check_constructible(row)
    except HTTPError as exc:
        if http_state is not None:
            http_state['blocked'] = True
        if cached is None:
            raise ValueError(f'CelesTrak returned HTTP {exc.code} for {label or cat}; stopped further requests. Try later or supply --elements JSON.') from exc
        warning(f'CelesTrak returned HTTP {exc.code} for {label or cat}; stopped further requests and using cached elements.')
        return cached, f'fallback cache: {path}'
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


def write_private_json(path, payload, indent=None):
    """Atomically write JSON with owner-only permissions, replacing any existing file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        os.chmod(handle.name, 0o600)
        json.dump(payload, handle, indent=indent)
        handle.write('\n')
        temp_path = handle.name
    os.replace(temp_path, path)


def direction(degrees):
    names = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return names[int((degrees + 11.25) // 22.5) % 16]


def predict(sat, observer, ts, start, end, tz, horizon, min_elevation, label=None, mask=None):
    # A HEO pass can last much longer than three hours. Search at least one
    # whole orbit on both sides so a rise preceding the requested interval is
    # paired with its culmination and set.
    period_hours = 2 * math.pi / sat.model.no_kozai / 60
    pad = timedelta(hours=max(3, period_hours * 1.1))
    t, events = sat.find_events(observer, ts.from_datetime(start - pad),
                               ts.from_datetime(end + pad), altitude_degrees=horizon)
    topocentric = sat - observer
    rise, peaks = None, []
    result = []
    for moment, event in zip(t, events):
        if event == 0:
            rise, peaks = moment, []
        elif event == 1 and rise is not None:
            peaks.append(moment)
        elif event == 2 and rise is not None and peaks:
            rise_t, set_t = rise, moment
            clear_minutes = blocked_minutes = None
            horizon_mask = False
            if mask is not None:
                # Clip the reported window to the samples that clear the surveyed
                # mask too, so rise/set/peak reflect what is actually receivable.
                times = ts.linspace(rise_t, set_t, 241)
                alt_arr, az_arr, dist_arr = topocentric.at(times).altaz()
                clear_idx = clear_window(az_arr.degrees, alt_arr.degrees, mask, horizon)
                if not clear_idx:
                    rise, peaks = None, []
                    continue
                first_i, last_i = clear_idx[0], clear_idx[-1]
                peak_i = max(clear_idx, key=lambda i: alt_arr.degrees[i])
                rise_t, set_t = times[first_i], times[last_i]
                peak_dt = times[peak_i].utc_datetime()
                alt_deg = float(alt_arr.degrees[peak_i])
                az_deg = float(az_arr.degrees[peak_i])
                distance_km = float(dist_arr.km[peak_i])
                rise_az = float(az_arr.degrees[first_i])
                set_az = float(az_arr.degrees[last_i])
                window_minutes = round(float(set_t - rise_t) * 1440, 2)
                step_minutes = float(times[1] - times[0]) * 1440
                clear_minutes = round(len(clear_idx) * step_minutes, 2)
                blocked_minutes = round(max(0.0, window_minutes - clear_minutes), 2)
                horizon_mask = True
            else:
                peak = max(peaks, key=lambda p: topocentric.at(p).altaz()[0].degrees)
                peak_dt = peak.utc_datetime()
                alt, az, distance = topocentric.at(peak).altaz()
                alt_deg, az_deg, distance_km = float(alt.degrees), float(az.degrees), float(distance.km)
                rise_az = float(topocentric.at(rise_t).altaz()[1].degrees)
                set_az = float(topocentric.at(set_t).altaz()[1].degrees)
                window_minutes = round(float(set_t - rise_t) * 1440, 2)
            # Include by peak time, which makes adjacent date queries nonoverlapping.
            if start <= peak_dt < end and alt_deg >= min_elevation:
                row = dict(satellite=label or SATELLITES.get(sat.model.satnum, str(sat.model.satnum)), norad=sat.model.satnum,
                    rise=rise_t.utc_datetime().astimezone(tz).isoformat(timespec='seconds'),
                    peak=peak_dt.astimezone(tz).isoformat(timespec='seconds'),
                    set=set_t.utc_datetime().astimezone(tz).isoformat(timespec='seconds'),
                    max_elevation_deg=round(alt_deg, 2),
                    rise_azimuth_deg=round(rise_az, 1), peak_azimuth_deg=round(az_deg, 1),
                    set_azimuth_deg=round(set_az, 1),
                    range_at_peak_km=round(distance_km, 1),
                    window_minutes=window_minutes,
                    geometry='Excellent' if alt_deg >= 60 else 'Good' if alt_deg >= 40 else 'Fair' if alt_deg >= 20 else 'Low',
                    epoch_utc=sat.epoch.utc_datetime().isoformat(timespec='seconds'))
                if horizon_mask:
                    row['horizon_mask'] = True
                    row['clear_minutes'] = clear_minutes
                    row['blocked_minutes'] = blocked_minutes
                result.append(row)
            rise, peaks = None, []
    return result


def sample_track(sat, observer, ts, rise_iso, set_iso, samples=241):
    """Az/el degrees along a pass; shared by the terminal and image plots."""
    t0, t1 = [ts.from_datetime(datetime.fromisoformat(value)) for value in (rise_iso, set_iso)]
    alt, az, _ = (sat - observer).at(ts.linspace(t0, t1, samples)).altaz()
    return az.degrees, alt.degrees


def is_geostationary(sat):
    """Cheap prefilter: True for a ~1 rev/day orbit, geostationary or not.

    Period alone can't tell whether the orbit actually holds still in the
    sky; the caller confirms that geometrically with find_events.
    """
    revs_per_day = sat.model.no_kozai * 1440 / (2 * math.pi)
    return 0.9 < revs_per_day < 1.1


def fixed_look_angle(sat, observer, ts, when, label, horizon, mask=None):
    from skyfield.api import wgs84
    moment = ts.from_datetime(when)
    alt, az, distance = (sat - observer).at(moment).altaz()
    _lat, lon = wgs84.latlon_of(sat.at(moment))
    above_flat_horizon = bool(alt.degrees > horizon)
    above_horizon = bool(alt.degrees > max(horizon, mask_elevation(mask, az.degrees))) if mask is not None else above_flat_horizon
    result = dict(satellite=label, norad=sat.model.satnum,
                subsatellite_longitude_deg=round(float(lon.degrees), 1),
                elevation_deg=round(float(alt.degrees), 1),
                azimuth_deg=round(float(az.degrees), 1),
                range_km=round(float(distance.km), 1),
                above_horizon=above_horizon)
    if mask is not None:
        result['blocked_by_horizon_mask'] = bool(above_flat_horizon and not above_horizon)
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
    p.add_argument('--all-passes', action='store_true', help='Include low passes; override horizon and minimum elevation to 0 degrees')
    p.add_argument('--hours', help='Only peaks in local hour range, e.g. 08:00-22:00; overnight ranges allowed')
    p.add_argument('--color', choices=['auto','always','never'], default='auto', help='Colors optimized for black terminals; auto disables color when redirected')
    p.add_argument('--plots', type=int, default=1, help='Draw this many best passes in the terminal')
    p.add_argument('--no-plot', dest='plots', action='store_const', const=0, help='Show schedule without sky plots')
    p.add_argument('--plot-rank', type=int, help='Draw a particular ranked pass instead of the best passes')
    p.add_argument('--day-plot', type=Path, help='Save PNG/PDF/SVG of ALL passes for one satellite on --date (default today); uses one full local day and horizon 0, ignoring elevation thresholds')
    p.add_argument('--top', type=int, default=5, help='Number of best opportunities to highlight')
    p.add_argument('--rank-by', choices=('elevation', 'duration', 'imagery'), default='elevation',
                   help='Rank by elevation, duration, or daylight ground-track time for imagery')
    p.add_argument('--live', action='store_true', help='Refresh current satellite azimuth, elevation and range until Ctrl-C')
    p.add_argument('--live-interval', type=float, default=2, help='Seconds between live updates (default 2)')
    p.add_argument('--live-format', choices=('table', 'jsonl'), default='table', help='Live display or machine-readable pointing stream')
    p.add_argument('--frequency', type=float, help='Nominal downlink MHz for first-order Doppler estimates')
    p.add_argument('--track-csv', type=Path, help='Export sampled ground track, footprint, and rotor azimuth/elevation as CSV')
    p.add_argument('--track-step', type=int, default=30, help='Seconds between track CSV points')
    p.add_argument('--ground-track', action='store_true', help='Show subsatellite coordinates and footprint at pass peak')
    p.add_argument('--watch', action='store_true', help='Run a local reminder loop; keep it running with your OS service manager')
    p.add_argument('--service', choices=('install', 'uninstall'), help='Install or remove the per-user macOS reminder service')
    p.add_argument('--save-location', action='store_true', help='Save --lat, --lon, --altitude and --timezone to the private location file, then exit')
    p.add_argument('--horizon-file', type=Path, help='JSON horizon mask (list of {"az","el"} points) overriding the "horizon" key in the location file')
    p.add_argument('--survey-horizon', action='store_true', help='Enter compass azimuth / level elevation measurements of local obstacles interactively and save them as the location horizon mask, then exit')
    p.add_argument('--declination', type=float, help='Magnetic declination for --survey-horizon, degrees east positive; compass reading + declination = true azimuth')
    p.add_argument('--refresh', action='store_true', help='Refresh orbital elements instead of using a cache younger than 6 hours')
    p.add_argument('--offline', action='store_true', help='Use cached orbital elements without network access')
    p.add_argument('--radio', action='store_true', help='Include optional SatNOGS transmitter metadata (network/cache)')
    p.add_argument('--recent-reports', action='store_true', help='Show recent volunteer AMSAT reception reports, separate from radio catalog')
    p.add_argument('--band', help='Limit radio metadata to overlapping downlinks in a MHz range, e.g. 137-138')
    p.add_argument('--refresh-radio', action='store_true', help='Refresh SatNOGS transmitter metadata (also enables --radio)')
    p.add_argument('--radio-file', type=Path, help='Local JSON transmitter metadata supplement/override; no network required')
    p.add_argument('--satellites', help='Comma-separated labels ('
        + ', '.join(SATELLITES.values()) + '), groups (' + ', '.join(GROUPS) + ') or NORAD IDs; default all')
    p.add_argument('--list-satellites', action='store_true', help='List the built-in or merged --catalog entries and exit')
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
    p = parser()
    args = p.parse_args(argv)
    try:
        if args.service:
            from nextpass.service_installer import main as service_main
            return service_main([args.service])
        from nextpass.planning_features import export_calendar, annotate_visibility
        if args.reminder_minutes < 0:
            raise ValueError('--reminder-minutes must be nonnegative')
        if not -90 <= args.max_sun_altitude <= 90:
            raise ValueError('--max-sun-altitude must be between -90 and 90')
        if args.band is not None:
            from nextpass.radio_metadata import parse_band
            parse_band(args.band)
            if not (args.radio or args.refresh_radio or args.radio_file):
                raise ValueError('--band requires --radio, --refresh-radio or --radio-file')
        catalog = load_catalog(args.catalog, CATALOG) if args.catalog else CATALOG
        catalog_extra = load_catalog_extras(args.catalog, CATALOG_EXTRA)
        if args.satellites:
            for token in (part.strip() for part in args.satellites.split(',')):
                if token.isdecimal() and 0 < int(token) < 1_000_000_000 and int(token) not in catalog:
                    catalog = dict(catalog)
                    cat = int(token)
                    catalog[cat] = (f'NORAD-{cat}', 'custom', f'NORAD {cat}')
        if args.list_satellites:
            print(f"{'NORAD':>9}  {'LABEL':<8} {'GROUP':<10} {'VERIFIED':<10} OBJECT")
            for cat, (label, group, name) in catalog.items():
                verified = catalog_extra.get(cat, {}).get('verified', '—')
                print(f'{cat:>9}  {label:<8} {group:<10} {verified:<10} {name}')
            return 0
        config = {}
        location_path = args.location_config.expanduser()
        config_error = None
        try:
            if location_path.exists() and not args.save_location:
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
        for key in ('lat', 'lon', 'altitude'):
            if isinstance(getattr(args, key), bool):
                raise ValueError(f'{key} must be a number, not a boolean')
        args.lat, args.lon, args.altitude = float(args.lat), float(args.lon), float(args.altitude)
        if args.save_location:
            if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180 or not math.isfinite(args.altitude):
                raise ValueError('Invalid observer coordinates or altitude')
            ZoneInfo(args.timezone)
            write_private_json(location_path, dict(lat=args.lat, lon=args.lon, altitude=args.altitude, timezone=args.timezone))
            print(f'Saved private location to {location_path}')
            return 0
        if args.survey_horizon:
            from nextpass.horizon import survey
            points = survey(declination=args.declination)
            horizon_points = [{'az': az, 'el': el} for az, el in points]
            if args.horizon_file:
                write_private_json(args.horizon_file, dict(horizon=horizon_points), indent=2)
                print(f'Saved horizon mask ({len(points)} points) to {args.horizon_file}')
            else:
                config['horizon'] = horizon_points
                write_private_json(location_path, config, indent=2)
                print(f'Saved horizon mask ({len(points)} points) to {location_path}')
            return 0
        mask = load_mask(config, args.horizon_file)
        if args.plots < 0 or (args.plot_rank is not None and args.plot_rank < 1):
            raise ValueError('--plots must be nonnegative and --plot-rank must be positive')
        if not math.isfinite(args.live_interval) or args.live_interval < 0.25:
            raise ValueError('--live-interval must be at least 0.25 seconds')
        if args.live_format == 'jsonl' and not args.live:
            raise ValueError('--live-format jsonl requires --live')
        if args.live_format == 'jsonl' and args.day_plot:
            raise ValueError('--live-format jsonl cannot be combined with --day-plot')
        if args.frequency is not None and (not math.isfinite(args.frequency) or args.frequency <= 0):
            raise ValueError('--frequency must be a positive finite MHz value')
        if not 1 <= args.track_step <= 3600:
            raise ValueError('--track-step must be 1..3600 seconds')
        if args.watch and (args.date or args.elements or args.live):
            raise ValueError('--watch uses current predictions; omit --date, --elements and --live')
        if args.watch and args.reminder_minutes == 0:
            raise ValueError('--watch requires --reminder-minutes greater than zero')
        if not 1 <= args.days <= 366 or args.top < 1:
            raise ValueError('--days must be 1..366 and --top must be positive')
        if not -90 <= args.lat <= 90 or not -180 <= args.lon <= 180 or not math.isfinite(args.altitude):
            raise ValueError('Invalid observer coordinates or altitude')
        # Overrides precede validation so explicit thresholds cannot conflict with them.
        if args.all_passes or args.day_plot:
            args.horizon, args.min_elevation = 0, 0
        if not 0 <= args.horizon < 90 or not args.horizon <= args.min_elevation <= 90:
            raise ValueError('Require 0 <= horizon <= min-elevation <= 90, with horizon < 90')
        if args.offline and args.refresh:
            raise ValueError('--offline and --refresh cannot be combined')
        if args.elements and (args.offline or args.refresh):
            raise ValueError('--elements supplies orbital data directly; omit --offline and --refresh')
        if args.offline and args.refresh_radio:
            raise ValueError('--offline and --refresh-radio cannot be combined')
        tz = ZoneInfo(args.timezone)
        if args.day_plot:
            if args.hours or args.visible_only:
                raise ValueError('--day-plot includes all passes; omit --hours and --visible-only')
            if args.day_plot.suffix.lower() not in ('.png', '.pdf', '.svg'):
                raise ValueError('--day-plot filename must end in .png, .pdf or .svg')
            from nextpass.sky_images import require_matplotlib
            require_matplotlib()
            parent = args.day_plot.parent or Path('.')
            if parent.exists() and not os.access(parent, os.W_OK):
                raise ValueError(f'--day-plot directory is not writable: {parent}')
            args.date = args.date or datetime.now(tz).date()
            args.days = 1
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
            if a == b:
                raise ValueError('--hours start and end must differ')
            hour_filter = a, b
        from skyfield.api import load, wgs84
        ts = load.timescale(builtin=True)
        observer = wgs84.latlon(args.lat, args.lon, elevation_m=args.altitude)
        provided = None
        if args.elements:
            provided = json.loads(args.elements.read_text())
            if not isinstance(provided, list) or not provided:
                raise ValueError('--elements must contain a nonempty CelesTrak JSON array')
        rows, sources, satellites, stationary = [], [], {}, []
        http_state = {}
        # Printed after the schedule so they are the last thing seen, not scrolled away.
        stale_warnings = []
        selected = select(args.satellites, catalog)
        if args.day_plot and len(selected) != 1:
            raise ValueError('--day-plot requires exactly one satellite, e.g. --satellites M2-4')
        for cat, name in selected.items():
            if provided is not None and not [row for row in provided if isinstance(row, dict) and _is_integer(row.get('NORAD_CAT_ID')) and int(row['NORAD_CAT_ID']) == cat]:
                warning(f'{name}: no element set for NORAD {cat} in {args.elements}; skipping.')
                continue
            data, source = (provided, str(args.elements)) if provided is not None else load_elements(cat, args.cache_dir, args.offline, args.refresh, ts=ts, label=name, http_state=http_state)
            sat = validate_constructible(validate(data, cat), ts)
            satellites[cat] = sat
            max_age = max(abs(float(ts.from_datetime(d)-sat.epoch)) for d in (start, end))
            if max_age > 14 and not args.allow_stale:
                raise ValueError(f'{name}: requested dates are up to {max_age:.1f} days from orbital epoch. Use elements near your dates (--elements), shorten the range, or explicitly --allow-stale for rough planning.')
            stale = (f'{name}: date range extends {max_age:.1f} days from epoch; refresh nearer the pass. '
                     'Predictions may be inaccurate.') if max_age > 7 else None
            sources.append(dict(satellite=name, norad=cat, source=source, epoch_utc=sat.epoch.utc_datetime().isoformat(timespec='seconds'), max_epoch_distance_days=round(max_age, 2)))
            if is_geostationary(sat):
                # Period alone doesn't prove the orbit holds still in the sky, so confirm
                # geometrically: an inclined geosynchronous orbit that crosses the horizon
                # must keep its passes, while one that never crosses it has no rise/set
                # events and would otherwise vanish silently, so report its fixed look
                # angle instead. A lone culmination event (no rise or set) still counts
                # as never crossing the horizon.
                _t, events = sat.find_events(observer, ts.from_datetime(start), ts.from_datetime(end),
                                              altitude_degrees=args.horizon)
                if not any(event in (0, 2) for event in events):
                    # A fixed look angle barely changes with element age, so no refresh nag.
                    stationary.append(fixed_look_angle(sat, observer, ts, start, name, args.horizon, mask=mask))
                    continue
            if stale:
                stale_warnings.append(stale)
            rows.extend(predict(sat, observer, ts, start, end, tz, args.horizon, args.min_elevation, label=name, mask=mask))
        if not satellites:
            raise ValueError('No selected satellites have usable orbital elements')
        if args.day_plot and stationary:
            raise ValueError(f"{stationary[0]['satellite']} is geostationary and has no passes to plot")
        if hour_filter:
            a, b = hour_filter
            def allowed(row):
                h = datetime.fromisoformat(row['peak']).time()
                return a <= h < b if a < b else h >= a or h < b
            rows = [r for r in rows if allowed(r)]
        visibility = None
        if args.visibility or args.visible_only or args.rank_by == 'imagery':
            from skyfield.api import Loader, load_file
            ephemeris_path = args.ephemeris.expanduser() if args.ephemeris else args.cache_dir / 'de421.bsp'
            if ephemeris_path.exists():
                ephemeris = load_file(str(ephemeris_path))
            elif args.ephemeris or args.offline:
                raise ValueError(f'Visibility requires a local planetary ephemeris at {ephemeris_path}. Supply --ephemeris or run online once.')
            else:
                ephemeris = Loader(str(args.cache_dir))('de421.bsp')
            try:
                if args.rank_by == 'imagery':
                    annotate_visibility(rows, satellites, observer, ts, ephemeris,
                                        args.max_sun_altitude, ground_daylight=True)
                else:
                    annotate_visibility(rows, satellites, observer, ts, ephemeris, args.max_sun_altitude)
            finally:
                ephemeris.close()
            visibility = dict(evaluation='peak and sampled reception window; not a guarantee of visibility',
                              max_sun_altitude_deg=args.max_sun_altitude, ephemeris=str(ephemeris_path))
            if args.visible_only:
                rows = [row for row in rows if row.get('visible_during_pass', row['visible_at_peak'])]
        rows.sort(key=lambda r: datetime.fromisoformat(r['peak']))
        from nextpass.tracking_features import annotate_overlaps, pointing, write_track_csv
        annotate_overlaps(rows)
        if args.frequency is not None or args.ground_track:
            for row in rows:
                sample = pointing(satellites[row['norad']], observer, ts,
                                  datetime.fromisoformat(row['peak']), args.frequency, mask=mask)
                row['peak_track'] = sample
                if args.frequency is not None:
                    row['doppler_schedule_hz'] = {
                        phase: pointing(satellites[row['norad']], observer, ts,
                                        datetime.fromisoformat(row[phase]),
                                        args.frequency, mask=mask)['receive_frequency_hz']
                        for phase in ('rise', 'peak', 'set')}
        rank_key = ((lambda r: (-r['daylight_ground_track_minutes'], -r['max_elevation_deg']))
                    if args.rank_by == 'imagery' else
                    (lambda r: (-r['window_minutes'], -r['max_elevation_deg']))
                    if args.rank_by == 'duration' else
                    (lambda r: (-r['max_elevation_deg'], r['range_at_peak_km'])))
        ranked = sorted(rows, key=rank_key)
        for rank, row in enumerate(ranked, 1):
            row['rank'] = rank
        radio = None
        if args.radio or args.refresh_radio or args.radio_file:
            from nextpass.radio_metadata import load_radio_metadata
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
        reports = None
        if args.recent_reports:
            from nextpass.recent_reports import load_recent_reports
            reports = load_recent_reports([catalog[cat][0] for cat in satellites], args.cache_dir, args.offline)
        metadata = dict(location=dict(lat=args.lat, lon=args.lon, altitude_m=args.altitude), timezone=args.timezone,
            start=start.isoformat(), end=end.isoformat(), horizon_deg=args.horizon, minimum_peak_deg=args.min_elevation,
            horizon_mask_points=len(mask) if mask else 0,
            ranking=('Daylight ground-track time descending, then peak elevation descending' if args.rank_by == 'imagery' else
                     'Reception window duration descending, then peak elevation descending' if args.rank_by == 'duration' else
                     'Peak elevation descending, then range at peak ascending') + '; geometric opportunity, not predicted signal strength or transmitter status.',
            sources=sources, passes=rows)
        if visibility is not None:
            metadata['visibility'] = visibility
        if radio is not None:
            metadata['radio'] = radio
        if reports is not None:
            metadata['recent_reports'] = reports
        if stationary:
            metadata['stationary'] = stationary
        from nextpass.terminal_view import render
        if not (args.live and args.live_format == 'jsonl'):
            render(rows, ranked, sources, args, start, end, tz, satellites, observer, ts,
                   radio=radio, stationary=stationary, reports=reports,
                   catalog_extra=catalog_extra, mask=mask)
        for path in (args.json_path, args.csv_path, args.ics, args.track_csv):
            if path:
                path.parent.mkdir(parents=True, exist_ok=True)
        if args.json_path:
            args.json_path.write_text(json.dumps(metadata, indent=2) + '\n')
        if args.csv_path:
            fields = ['satellite', 'norad', 'rise', 'peak', 'set', 'max_elevation_deg',
                      'rise_azimuth_deg', 'peak_azimuth_deg', 'set_azimuth_deg',
                      'range_at_peak_km', 'window_minutes', 'geometry', 'epoch_utc', 'rank',
                      'satellite_sunlit_at_peak', 'sun_altitude_at_peak_deg', 'visible_at_peak',
                      'visual_candidate_start', 'visual_candidate_end', 'visual_candidate_minutes', 'visible_during_pass',
                      'ground_sun_altitude_at_peak_deg', 'daylight_ground_track_minutes',
                      'overlaps', 'peak_track', 'doppler_schedule_hz']
            if mask is not None:
                fields += ['horizon_mask', 'clear_minutes', 'blocked_minutes']
            with args.csv_path.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        if args.track_csv:
            write_track_csv(args.track_csv, rows, satellites, observer, ts, args.track_step, args.frequency)
        if args.day_plot:
            from nextpass.sky_images import save_day_plot
            save_day_plot(rows, satellites, observer, ts, tz, start, args.day_plot, label=next(iter(selected.values())), mask=mask)
            print(f'\nSaved day sky plot: {args.day_plot}')
        if args.ics:
            export_calendar(rows, args.ics, reminder_minutes=args.reminder_minutes)
        if stale_warnings:
            print(file=sys.stderr)
            bold = stderr_bold(args.color)
            for message in stale_warnings:
                warning(message, bold=bold)
            print('Add --refresh for current elements, and re-run nearer the pass or with fewer --days: '
                  'accuracy falls with distance from the element epoch.', file=sys.stderr)
        if args.live:
            from nextpass.live_view import show_live
            show_live(satellites, observer, ts, tz, args.live_interval,
                      format=args.live_format, frequency_mhz=args.frequency)
        if args.watch:
            from nextpass.reminder_service import watch
            watch(args, rows)
        return 0
    except ImportError as exc:
        print(f'Import failed: {exc}. Check the installation and dependencies.', file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
