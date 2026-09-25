"""Recent volunteer reception reports from AMSAT, separate from radio catalog data."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL = 'https://www.amsat.org/status/api/v1/summary.php?hours=24'


def load_recent_reports(labels, cache_dir, offline=False):
    cache = Path(cache_dir) / 'amsat-reports.json'
    payload = None
    cache_age = None
    if cache.exists():
        cache_age = datetime.now(timezone.utc).timestamp() - cache.stat().st_mtime
    if cache_age is not None and (offline or cache_age < 3600):
        try:
            payload = json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
    if payload is None and not offline:
        try:
            with urlopen(Request(URL, headers={'Accept': 'application/json', 'User-Agent': 'nextpass/1.8'}), timeout=15) as response:
                payload = json.load(response)
            if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
                raise ValueError('unexpected AMSAT response')
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(payload))
            cache_age = 0
        except (OSError, ValueError) as exc:
            if not cache.exists():
                return dict(status='unavailable', reason=str(exc), source=URL)
            try:
                payload = json.loads(cache.read_text())
            except (OSError, ValueError):
                return dict(status='unavailable', reason=str(exc), source=URL)
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        return dict(status='unavailable', reason='No cached AMSAT reports', source=URL)
    selected = {}
    for label in labels:
        matches = [row for row in payload['data'] if isinstance(row, dict) and
                   str(row.get('name', '')).split('_[', 1)[0].upper() == label.upper()]
        if matches:
            selected[label] = matches
    return dict(status='stale_cached_reports' if cache_age is not None and cache_age >= 3600 else 'recent_user_reports',
                window_hours=24, source=URL,
                cache_age_hours=round(cache_age / 3600, 1) if cache_age is not None else None,
                satellites=selected,
                warning='Volunteer reports describe past reception elsewhere; they do not prove current or local transmitter activity.')
