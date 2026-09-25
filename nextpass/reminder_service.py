"""Long-running local reminder loop for upcoming passes."""
import json
import platform
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _notify(title, message):
    system = platform.system()
    if system == 'Darwin':
        # Pass text as arguments; never interpolate satellite names into AppleScript.
        subprocess.run(['osascript', '-e', 'on run argv', '-e',
                        'display notification (item 2 of argv) with title (item 1 of argv)',
                        '-e', 'end run', title, message], check=False)
    elif system == 'Linux':
        try:
            subprocess.run(['notify-send', title, message], check=False)
        except FileNotFoundError:
            print(f'{title}: {message}', flush=True)
    else:
        print(f'{title}: {message}', flush=True)


def watch(args, initial_rows):
    """Notify before each pass and refresh predictions every six hours."""
    rows = initial_rows
    sent = []
    refresh_at = time.monotonic() + 6 * 3600
    print('Reminder service running. Press Ctrl-C to stop.', flush=True)
    try:
        while True:
            now = datetime.now(timezone.utc)
            for row in rows:
                start = datetime.fromisoformat(row['rise']).astimezone(timezone.utc)
                lead = timedelta(minutes=args.reminder_minutes)
                peak = datetime.fromisoformat(row['peak']).astimezone(timezone.utc)
                already_sent = any(norad == row['norad'] and abs((old_peak - peak).total_seconds()) < 20 * 60
                                   for norad, old_peak in sent)
                if not already_sent and start - lead <= now < start:
                    _notify('NextPass: {} in {} min'.format(row['satellite'], args.reminder_minutes),
                            'Reception window starts {}. Peak elevation {}°.'.format(
                                start.astimezone().strftime('%H:%M %Z'), row['max_elevation_deg']))
                    sent.append((row['norad'], peak))
            if time.monotonic() >= refresh_at:
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / 'passes.json'
                    command = [sys.executable, '-m', 'nextpass',
                               '--location-config', str(args.location_config), '--days', str(args.days),
                               '--lat', str(args.lat), '--lon', str(args.lon),
                               '--altitude', str(args.altitude), '--timezone', args.timezone,
                               '--min-elevation', str(args.min_elevation), '--horizon', str(args.horizon),
                               '--no-plot', '--color', 'never', '--json', str(output)]
                    if args.satellites:
                        command += ['--satellites', args.satellites]
                    if args.catalog:
                        command += ['--catalog', str(args.catalog)]
                    if args.hours:
                        command += ['--hours', args.hours]
                    if args.all_passes:
                        command += ['--all-passes']
                    if args.visible_only:
                        command += ['--visible-only']
                    elif args.visibility:
                        command += ['--visibility']
                    if args.ephemeris:
                        command += ['--ephemeris', str(args.ephemeris)]
                    command += ['--max-sun-altitude', str(args.max_sun_altitude)]
                    if args.offline:
                        command += ['--offline']
                    if args.ics:
                        command += ['--ics', str(args.ics), '--reminder-minutes', str(args.reminder_minutes)]
                    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                    if result.returncode == 0:
                        rows = json.loads(output.read_text())['passes']
                    else:
                        print('NextPass reminder refresh failed: ' + result.stderr.strip(), file=sys.stderr)
                refresh_at = time.monotonic() + 6 * 3600
            time.sleep(30)
    except KeyboardInterrupt:
        print('Reminder service stopped.', flush=True)
