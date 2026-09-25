"""Simple live pointing display for terminal users."""
from datetime import datetime, timezone
import json
import sys
import time
from nextpass.tracking_features import pointing


def snapshot(satellites, observer, ts, now=None):
    """Return current look angles, with below-horizon objects marked clearly."""
    now = now or datetime.now(timezone.utc)
    moment = ts.from_datetime(now)
    result = []
    for norad, sat in satellites.items():
        altitude, azimuth, distance = (sat - observer).at(moment).altaz()
        result.append((sat.name, norad, azimuth.degrees, altitude.degrees,
                       distance.km))
    return sorted(result, key=lambda row: -row[3])


def show_live(satellites, observer, ts, tz, interval=2, format='table', frequency_mhz=None):
    """Refresh the display until interrupted. Terminal only; no network polling."""
    try:
        while True:
            now = datetime.now(timezone.utc)
            if format == 'jsonl':
                for norad, sat in satellites.items():
                    record = pointing(sat, observer, ts, now, frequency_mhz)
                    print(json.dumps(dict(satellite=sat.name, norad=norad, **record)), flush=True)
                time.sleep(interval)
                continue
            lines = [f'NEXTPASS LIVE | {now.astimezone(tz):%Y-%m-%d %H:%M:%S %Z}',
                     'Azimuth is clockwise from north. Ctrl-C to stop.',
                     'Satellite          Azimuth  Elevation   Range    Position']
            for name, _norad, az, el, distance in snapshot(satellites, observer, ts, now):
                lines.append(f'{name[:18]:18} {az:7.1f}°  {el:8.1f}°  '
                             f'{distance:7.0f} km  {"above horizon" if el > 0 else "below horizon"}')
                if frequency_mhz is not None:
                    sat = satellites[_norad]
                    tuned = pointing(sat, observer, ts, now, frequency_mhz)['receive_frequency_hz']
                    lines.append(f'  {name}: receive at {tuned} Hz for {frequency_mhz:g} MHz nominal downlink')
            if sys.stdout.isatty():
                print('\x1b[H\x1b[J', end='')
            print('\n'.join(lines), flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        if format == 'table':
            print('\nLive tracking stopped.')
