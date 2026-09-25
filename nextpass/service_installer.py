#!/usr/bin/env python3
"""Install or remove a per-user macOS LaunchAgent for NextPass reminders."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = 'org.nextpass.reminders'


def main(argv):
    if sys.platform != 'darwin' or argv not in (['install'], ['uninstall']):
        print('Usage on macOS: nextpass --service install|uninstall', file=sys.stderr)
        return 2
    launch_dir = Path.home() / 'Library' / 'LaunchAgents'
    plist = launch_dir / (LABEL + '.plist')
    domain = 'gui/{}'.format(os.getuid())
    service = domain + '/' + LABEL
    if argv[0] == 'uninstall':
        subprocess.run(['launchctl', 'bootout', service], check=False, capture_output=True)
        plist.unlink(missing_ok=True)
        print('Removed NextPass reminder service.')
        return 0
    source_root = Path(__file__).resolve().parents[1]
    project = source_root if (source_root / 'pyproject.toml').exists() else Path.home()
    location = Path.home() / '.config' / 'radio' / 'location.json'
    if not location.exists():
        print('Save your location with nextpass --save-location before installing reminders.', file=sys.stderr)
        return 2
    logs = Path.home() / '.cache' / 'nextpass'
    logs.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(logs, 0o700)
    launch_dir.mkdir(parents=True, exist_ok=True)
    config = {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, '-m', 'nextpass', '--watch', '--no-plot'],
        'WorkingDirectory': str(project),
        'RunAtLoad': True,
        'KeepAlive': True,
        'StandardOutPath': str(logs / 'reminders.log'),
        'StandardErrorPath': str(logs / 'reminders-error.log'),
    }
    temporary = plist.with_suffix('.plist.tmp')
    with temporary.open('wb') as handle:
        plistlib.dump(config, handle)
    os.replace(temporary, plist)
    subprocess.run(['launchctl', 'bootout', service], check=False, capture_output=True)
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], capture_output=True, text=True)
    if result.returncode:
        print(result.stderr.strip() or 'launchctl bootstrap failed', file=sys.stderr)
        return result.returncode
    print('Installed and started NextPass reminder service. Logs: {}'.format(logs))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
