"""Simple live pointing display for terminal users."""
from datetime import datetime, timezone
import sys
import time


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


def show_live(satellites, observer, ts, tz, interval=2):
    """Refresh the display until interrupted. Terminal only; no network polling."""
    try:
        while True:
            now = datetime.now(timezone.utc)
            lines = [f'NEXTPASS LIVE | {now.astimezone(tz):%Y-%m-%d %H:%M:%S %Z}',
                     'Azimuth is clockwise from north. Ctrl-C to stop.',
                     'Satellite          Azimuth  Elevation   Range    Position']
            for name, _norad, az, el, distance in snapshot(satellites, observer, ts, now):
                lines.append(f'{name[:18]:18} {az:7.1f}°  {el:8.1f}°  '
                             f'{distance:7.0f} km  {"above horizon" if el > 0 else "below horizon"}')
            if sys.stdout.isatty():
                print('\x1b[H\x1b[J', end='')
            print('\n'.join(lines), flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print('\nLive tracking stopped.')
