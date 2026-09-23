"""Calendar, catalog, and peak-visibility helpers for nextpass."""
import hashlib
import json
import math
import unicodedata
from datetime import datetime, timezone
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
    for a given NORAD/rise/set tuple.
    """
    if reminder_minutes is not None and (isinstance(reminder_minutes, bool) or
            not isinstance(reminder_minutes, int) or reminder_minutes < 0):
        raise ValueError('reminder_minutes must be a non-negative integer or None')

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
        uid_source = '{}|{}|{}'.format(norad, _utc_ical(rise_text, 'rise'), _utc_ical(set_text, 'set'))
        uid = hashlib.sha256(uid_source.encode('utf-8')).hexdigest() + '@nextpass'
        peak = _aware_datetime(row['peak'], 'peak') if row.get('peak') is not None else None
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
    destination = Path(path)
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


def annotate_visibility(rows, satellites, observer, ts, ephemeris,
                        max_sun_altitude=-6):
    """Annotate pass rows with satellite sunlight and observer darkness at peak.

    ``visible_at_peak`` is true only when the satellite is sunlit and the Sun
    is at or below max_sun_altitude at the observer, evaluated at the row's
    peak instant. It does not describe illumination or visibility over the
    complete pass.
    """
    if (not isinstance(max_sun_altitude, (int, float)) or isinstance(max_sun_altitude, bool)
            or not math.isfinite(max_sun_altitude) or not -90 <= max_sun_altitude <= 90):
        raise ValueError('max_sun_altitude must be a finite number between -90 and 90 degrees')
    sun = ephemeris['sun']
    earth = ephemeris['earth']
    for row in rows:
        norad = row['norad']
        if norad not in satellites:
            raise ValueError('no satellite supplied for NORAD {}'.format(norad))
        moment = ts.from_datetime(_aware_datetime(row['peak'], 'peak'))
        sunlit = bool(satellites[norad].at(moment).is_sunlit(ephemeris))
        apparent_sun = (earth + observer).at(moment).observe(sun).apparent()
        sun_altitude = float(apparent_sun.altaz()[0].degrees)
        if not math.isfinite(sun_altitude) or not -90 <= sun_altitude <= 90:
            raise ValueError('computed solar altitude must be finite and between -90 and 90 degrees')
        dark = sun_altitude <= max_sun_altitude
        row['satellite_sunlit_at_peak'] = sunlit
        row['sun_altitude_at_peak_deg'] = round(sun_altitude, 2)
        row['visible_at_peak'] = sunlit and dark
    return rows
