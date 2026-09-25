"""Pointing, Doppler, footprint and pass-conflict calculations."""
import csv
import math
from datetime import datetime, timedelta, timezone

LIGHT_KM_S = 299792.458
EARTH_RADIUS_KM = 6371.0


def pointing(sat, observer, ts, when, frequency_mhz=None):
    """Return an instantaneous look angle and first-order downlink correction."""
    from skyfield.api import wgs84

    instant = ts.from_datetime(when)
    altitude, azimuth, distance = (sat - observer).at(instant).altaz()
    subpoint = wgs84.subpoint(sat.at(instant))
    height = float(subpoint.elevation.km)
    footprint = EARTH_RADIUS_KM * math.acos(EARTH_RADIUS_KM / (EARTH_RADIUS_KM + max(0, height)))
    record = dict(time_utc=when.astimezone(timezone.utc).isoformat(timespec='seconds'),
                  azimuth_deg=round(float(azimuth.degrees), 2),
                  elevation_deg=round(float(altitude.degrees), 2),
                  range_km=round(float(distance.km), 2),
                  subsatellite_lat_deg=round(float(subpoint.latitude.degrees), 3),
                  subsatellite_lon_deg=round(float(subpoint.longitude.degrees), 3),
                  footprint_radius_km=round(footprint, 1))
    if frequency_mhz is not None:
        earlier = ts.from_datetime(when - timedelta(seconds=1))
        later = ts.from_datetime(when + timedelta(seconds=1))
        before = (sat - observer).at(earlier).distance().km
        after = (sat - observer).at(later).distance().km
        range_rate = (float(after) - float(before)) / 2
        record['range_rate_km_s'] = round(range_rate, 5)
        record['nominal_downlink_hz'] = round(frequency_mhz * 1_000_000)
        record['receive_frequency_hz'] = round(frequency_mhz * 1_000_000 * (1 - range_rate / LIGHT_KM_S))
    return record


def annotate_overlaps(rows):
    """Flag simultaneous reception windows on different satellites."""
    for row in rows:
        row['overlaps'] = []
    for index, first in enumerate(rows):
        a, b = datetime.fromisoformat(first['rise']), datetime.fromisoformat(first['set'])
        for second in rows[index + 1:]:
            if first['norad'] == second['norad']:
                continue
            c, d = datetime.fromisoformat(second['rise']), datetime.fromisoformat(second['set'])
            if max(a, c) < min(b, d):
                first['overlaps'].append(second['satellite'])
                second['overlaps'].append(first['satellite'])


def write_track_csv(path, rows, satellites, observer, ts, step_seconds=30, frequency_mhz=None):
    """Sample each pass for plotting or import into rotor-control software."""
    fields = ['satellite', 'norad', 'time_utc', 'azimuth_deg', 'elevation_deg',
              'range_km', 'subsatellite_lat_deg', 'subsatellite_lon_deg',
              'footprint_radius_km']
    if frequency_mhz is not None:
        fields += ['range_rate_km_s', 'nominal_downlink_hz', 'receive_frequency_hz']
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            start = datetime.fromisoformat(row['rise'])
            end = datetime.fromisoformat(row['set'])
            count = max(1, math.ceil((end - start).total_seconds() / step_seconds))
            for index in range(count + 1):
                when = min(end, start + timedelta(seconds=index * step_seconds))
                writer.writerow(dict(satellite=row['satellite'], norad=row['norad'],
                                     **pointing(satellites[row['norad']], observer, ts, when, frequency_mhz)))


def ground_plot(row, sat, ts, width=57, height=15):
    """Small local latitude/longitude view of one pass's subsatellite path."""
    from skyfield.api import wgs84

    start, end = datetime.fromisoformat(row['rise']), datetime.fromisoformat(row['set'])
    times = [start + (end - start) * index / 60 for index in range(61)]
    peak_index = round((datetime.fromisoformat(row['peak']) - start) / (end - start) * 60)
    points = []
    for when in times:
        subpoint = wgs84.subpoint(sat.at(ts.from_datetime(when)))
        points.append((float(subpoint.longitude.degrees), float(subpoint.latitude.degrees)))
    longitude_anchor = points[30][0]
    longitudes = [longitude_anchor + ((lon - longitude_anchor + 180) % 360 - 180) for lon, _ in points]
    latitudes = [lat for _, lat in points]
    west, east = min(longitudes) - 5, max(longitudes) + 5
    south, north = max(-90, min(latitudes) - 5), min(90, max(latitudes) + 5)
    if east - west < 10:
        center = (west + east) / 2
        west, east = center - 5, center + 5
    if north - south < 10:
        center = (north + south) / 2
        south, north = center - 5, center + 5
    grid = [[' ' for _ in range(width)] for _ in range(height)]
    if south <= 0 <= north:
        y = round((north - 0) / (north - south) * (height - 1))
        grid[y] = ['-' for _ in range(width)]
    if west <= 0 <= east:
        x = round((0 - west) / (east - west) * (width - 1))
        for line in grid:
            line[x] = '|'
    for index, (lon, lat) in enumerate(zip(longitudes, latitudes)):
        x = round((lon - west) / (east - west) * (width - 1))
        y = round((north - lat) / (north - south) * (height - 1))
        grid[y][x] = 'A' if index == 0 else 'B' if index == 60 else 'P' if index == peak_index else '*'
    return '\n'.join(''.join(line).rstrip() for line in grid) + (
        f'\nA start · P peak · B end | latitude {south:.1f}° to {north:.1f}°; '
        f'longitude {west:.1f}° to {east:.1f}°')
