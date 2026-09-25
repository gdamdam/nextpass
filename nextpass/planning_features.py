"""Calendar, catalog, and peak-visibility helpers for nextpass."""
import hashlib
import json
import math
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path


def _aware_datetime(value, field):
    if not isinstance(value, str):
        raise ValueError('{} must be an ISO-8601 datetime string'.format(field))
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('{} must be an ISO-8601 datetime string'.format(field)) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('{} must include a timezone'.format(field))
    return parsed


def _ical_escape(value):
    """Escape a value for an iCalendar TEXT property."""
    value = str(value).replace('\\', '\\\\')
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    value = value.replace('\n', '\\n')
    value = value.replace(';', '\\;').replace(',', '\\,')
    return value


def _fold_ical_line(line):
    """Fold one content line at 75 UTF-8 octets without splitting a character."""
    parts = []
    current = ''
    width = 0
    for character in line:
        encoded_width = len(character.encode('utf-8'))
        if width + encoded_width > 75:
            parts.append(current)
            current = ' '
            width = 1
        current += character
        width += encoded_width
    parts.append(current)
    return '\r\n'.join(parts)


def _utc_ical(value, field):
    return _aware_datetime(value, field).astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def export_calendar(rows, path, reminder_minutes=15):
    """Write predicted passes as RFC 5545 VEVENTs and return the output Path.

    Events span rise to set. A VALARM is included when reminder_minutes is a
    positive integer; pass None or 0 to omit reminders. The event UID is stable
    for a given NORAD and pass peak rounded to the nearest minute. When replacing
    a prior nextpass calendar, nearby recalculated peaks keep their old UID.
    """
    if reminder_minutes is not None and (isinstance(reminder_minutes, bool) or
            not isinstance(reminder_minutes, int) or reminder_minutes < 0):
        raise ValueError('reminder_minutes must be a non-negative integer or None')

    destination = Path(path)
    old_events = []
    if destination.exists():
        prior = destination.read_text(encoding='utf-8').replace('\r\n ', '')
        for block in prior.split('BEGIN:VEVENT')[1:]:
            body = block.split('END:VEVENT', 1)[0]
            fields = dict(line.split(':', 1) for line in body.splitlines() if ':' in line)
            if {'UID', 'X-NEXTPASS-NORAD', 'X-NEXTPASS-PEAK'} <= fields.keys():
                try:
                    old_events.append((int(fields['X-NEXTPASS-NORAD']),
                                       datetime.strptime(fields['X-NEXTPASS-PEAK'], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc),
                                       fields['UID']))
                except ValueError:
                    pass
    used_uids = set()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//nextpass//Satellite Passes//EN',
             'CALSCALE:GREGORIAN', 'METHOD:PUBLISH']
    for row in rows:
        rise_text, set_text = row['rise'], row['set']
        rise = _aware_datetime(rise_text, 'rise')
        setting = _aware_datetime(set_text, 'set')
        if setting <= rise:
            raise ValueError('set must be later than rise')
        norad = row.get('norad')
        if isinstance(norad, bool) or not isinstance(norad, int) or norad <= 0:
            raise ValueError('norad must be a positive integer')
        satellite = row.get('satellite', 'Satellite {}'.format(norad))
        geometry = row.get('geometry', 'Unknown')
        peak = _aware_datetime(row['peak'], 'peak') if row.get('peak') is not None else None
        identity_time = peak or rise + (setting - rise) / 2
        rounded_minute = int((identity_time.timestamp() + 30) // 60)
        uid_source = '{}|{}'.format(norad, rounded_minute)
        uid = hashlib.sha256(uid_source.encode('utf-8')).hexdigest() + '@nextpass'
        if peak:
            choices = [(abs((old_peak - peak.astimezone(timezone.utc)).total_seconds()), old_uid)
                       for old_norad, old_peak, old_uid in old_events
                       if old_norad == norad and old_uid not in used_uids]
            if choices:
                distance, old_uid = min(choices)
                if distance <= 20 * 60:
                    uid = old_uid
        used_uids.add(uid)
        summary = '{} pass ({})'.format(satellite, geometry)
        details = ['Satellite: {}'.format(satellite), 'NORAD: {}'.format(norad),
                   'Geometry: {}'.format(geometry),
                   'Rise: {}'.format(rise.isoformat()),
                   'Peak: {}'.format(peak.isoformat() if peak else 'not supplied'),
                   'Set: {}'.format(setting.isoformat())]
        for key, label, suffix in (
                ('max_elevation_deg', 'Peak elevation', ' degrees'),
                ('peak_azimuth_deg', 'Peak azimuth', ' degrees'),
                ('range_at_peak_km', 'Range at peak', ' km'),
                ('window_minutes', 'Pass duration', ' minutes')):
            if key in row:
                details.append('{}: {}{}'.format(label, row[key], suffix))
        lines.extend(['BEGIN:VEVENT', 'UID:{}'.format(uid), 'DTSTAMP:{}'.format(stamp),
                      'X-NEXTPASS-NORAD:{}'.format(norad),
                      'X-NEXTPASS-PEAK:{}'.format(_utc_ical(row['peak'], 'peak') if peak else _utc_ical(rise_text, 'rise')),
                      'DTSTART:{}'.format(_utc_ical(rise_text, 'rise')),
                      'DTEND:{}'.format(_utc_ical(set_text, 'set')),
                      'SUMMARY:{}'.format(_ical_escape(summary)),
                      'DESCRIPTION:{}'.format(_ical_escape('\n'.join(details)))])
        if reminder_minutes:
            lines.extend(['BEGIN:VALARM', 'ACTION:DISPLAY',
                          'DESCRIPTION:{}'.format(_ical_escape(summary)),
                          'TRIGGER:-PT{}M'.format(reminder_minutes), 'END:VALARM'])
        lines.append('END:VEVENT')
    lines.append('END:VCALENDAR')
    with destination.open('w', encoding='utf-8', newline='') as output:
        output.write('\r\n'.join(_fold_ical_line(line) for line in lines) + '\r\n')
    return destination


def _positive_norad(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _catalog_entry(norad, entry):
    if not _positive_norad(norad):
        raise ValueError('NORAD IDs must be positive integers')
    if not isinstance(entry, (tuple, list)) or len(entry) != 3:
        raise ValueError('catalog entries must be (label, group, name) triples')
    label, group, name = entry
    if any(not isinstance(value, str) or not value.strip()
           for value in (label, group, name)):
        raise ValueError('catalog label, group, and name must be non-empty strings')
    for field, value in (('label', label), ('group', group)):
        if ',' in value or any(unicodedata.category(char) == 'Cc' for char in value):
            raise ValueError('catalog {} cannot contain commas or control characters'.format(field))
    return (label.strip(), group.strip(), name.strip())


def load_catalog(path, builtin):
    """Merge a JSON catalog into builtin {NORAD: (label, group, name)} data.

    JSON records with an existing NORAD ID replace that built-in record. The
    supplied builtin mapping is copied and never modified.
    """
    if not isinstance(builtin, dict):
        raise ValueError('builtin catalog must be a mapping')
    catalog = {}
    for norad, entry in builtin.items():
        if not _positive_norad(norad):
            raise ValueError('NORAD IDs must be positive integers')
        catalog[norad] = _catalog_entry(norad, entry)

    if path is not None:
        try:
            records = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise ValueError('cannot read catalog JSON: {}'.format(exc)) from exc
        if not isinstance(records, list):
            raise ValueError('catalog JSON must be an array')
        seen_norads = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError('each catalog record must be an object')
            norad = record.get('norad')
            if not _positive_norad(norad):
                raise ValueError('NORAD IDs must be positive integers')
            if norad in seen_norads:
                raise ValueError('duplicate NORAD ID: {}'.format(norad))
            seen_norads.add(norad)
            catalog[norad] = _catalog_entry(
                norad, (record.get('label'), record.get('group'), record.get('name')))

    labels = {}
    for norad, (label, _group, _name) in catalog.items():
        key = label.casefold()
        if key in labels:
            raise ValueError('duplicate catalog label: {}'.format(label))
        labels[key] = norad
    return catalog


def load_catalog_extras(path, builtin=None):
    """Read optional display metadata without changing load_catalog's tuple API."""
    extras = {norad: dict(values) for norad, values in (builtin or {}).items()}
    if path is None:
        return extras
    records = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(records, list):
        raise ValueError('catalog JSON must be an array')
    for record in records:
        if not isinstance(record, dict) or not _positive_norad(record.get('norad')):
            raise ValueError('each catalog record needs a positive integer norad')
        values = extras.setdefault(record['norad'], {})
        if 'color' in record:
            color = record['color']
            if (not isinstance(color, list) or len(color) != 3 or
                    any(not isinstance(channel, int) or isinstance(channel, bool) or
                        not 0 <= channel <= 255 for channel in color)):
                raise ValueError('catalog color must be an RGB array of three integers 0..255')
            values['color'] = tuple(color)
        if 'radio_hint' in record:
            hint = record['radio_hint']
            if (not isinstance(hint, str) or not hint.strip() or len(hint) > 200 or
                    any(unicodedata.category(char) == 'Cc' for char in hint)):
                raise ValueError('catalog radio_hint must be a short non-empty sentence')
            values['radio_hint'] = hint.strip()
        if 'verified' in record:
            verified = record['verified']
            if not isinstance(verified, str):
                raise ValueError('catalog verified must be YYYY-MM-DD')
            try:
                parsed = date.fromisoformat(verified)
            except ValueError as exc:
                raise ValueError('catalog verified must be YYYY-MM-DD') from exc
            if parsed.isoformat() != verified:
                raise ValueError('catalog verified must be YYYY-MM-DD')
            values['verified'] = verified
    return extras


def annotate_visibility(rows, satellites, observer, ts, ephemeris,
                        max_sun_altitude=-6, ground_daylight=False):
    """Annotate peak visibility and sample the entire reception window.

    Samples identify candidate intervals; apparent magnitude, weather and
    local obstructions still require separate information.
    """
    if (not isinstance(max_sun_altitude, (int, float)) or isinstance(max_sun_altitude, bool)
            or not math.isfinite(max_sun_altitude) or not -90 <= max_sun_altitude <= 90):
        raise ValueError('max_sun_altitude must be a finite number between -90 and 90 degrees')
    sun = ephemeris['sun']
    earth = ephemeris['earth']
    if ground_daylight:
        from skyfield.api import wgs84
    for row in rows:
        norad = row['norad']
        if norad not in satellites:
            raise ValueError('no satellite supplied for NORAD {}'.format(norad))
        def conditions(instant):
            moment = ts.from_datetime(instant)
            lit = bool(satellites[norad].at(moment).is_sunlit(ephemeris))
            apparent = (earth + observer).at(moment).observe(sun).apparent()
            altitude = float(apparent.altaz()[0].degrees)
            if not math.isfinite(altitude) or not -90 <= altitude <= 90:
                raise ValueError('computed solar altitude must be finite and between -90 and 90 degrees')
            return lit, altitude
        peak = _aware_datetime(row['peak'], 'peak')
        sunlit, sun_altitude = conditions(peak)
        dark = sun_altitude <= max_sun_altitude
        row['satellite_sunlit_at_peak'] = sunlit
        row['sun_altitude_at_peak_deg'] = round(sun_altitude, 2)
        row['visible_at_peak'] = sunlit and dark
        if ground_daylight:
            subpoint = wgs84.subpoint(satellites[norad].at(ts.from_datetime(peak)))
            ground = earth + wgs84.latlon(subpoint.latitude.degrees, subpoint.longitude.degrees)
            row['ground_sun_altitude_at_peak_deg'] = round(float(
                ground.at(ts.from_datetime(peak)).observe(sun).apparent().altaz()[0].degrees), 2)
        if 'rise' in row and 'set' in row:
            rise = _aware_datetime(row['rise'], 'rise')
            setting = _aware_datetime(row['set'], 'set')
            if setting <= rise:
                raise ValueError('set must be later than rise')
            count = max(2, min(121, math.ceil((setting-rise).total_seconds()/30)+1))
            candidates = []
            daylight = 0
            for index in range(count):
                instant = rise + (setting-rise) * index/(count-1)
                lit, altitude = conditions(instant)
                if lit and altitude <= max_sun_altitude:
                    candidates.append((index, instant))
                if ground_daylight:
                    moment = ts.from_datetime(instant)
                    subpoint = wgs84.subpoint(satellites[norad].at(moment))
                    ground = earth + wgs84.latlon(subpoint.latitude.degrees, subpoint.longitude.degrees)
                    sun_altitude = ground.at(moment).observe(sun).apparent().altaz()[0].degrees
                    daylight += sun_altitude > 0
            if ground_daylight:
                row['daylight_ground_track_minutes'] = round(
                    (setting-rise).total_seconds() / 60 * daylight / count, 1)
            runs = []
            for index, instant in candidates:
                if not runs or index != runs[-1][-1][0] + 1:
                    runs.append([])
                runs[-1].append((index, instant))
            best = max(runs, key=lambda run: len(run)) if runs else []
            row['visual_candidate_start'] = best[0][1].isoformat() if best else None
            row['visual_candidate_end'] = best[-1][1].isoformat() if best else None
            row['visual_candidate_minutes'] = round((best[-1][1]-best[0][1]).total_seconds()/60, 1) if best else 0
            row['visible_during_pass'] = bool(candidates)
    return rows
