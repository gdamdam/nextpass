"""Local horizon mask: field-surveyed minimum clear elevation by azimuth."""
import json
import math


def normalize(points):
    """Validate and sort horizon points into (az, el) float tuples.

    Accepts a list of {"az":, "el":} dicts or (az, el) pairs. Azimuth wraps
    into [0, 360); elevation must be finite and 0 <= el < 90. When two points
    share an azimuth, the higher elevation wins. Raises ValueError on empty,
    non-numeric, boolean, out-of-range, or malformed input.
    """
    if not points:
        raise ValueError('Horizon mask must contain at least one point')
    parsed = []
    for point in points:
        if isinstance(point, dict):
            if 'az' not in point or 'el' not in point:
                raise ValueError(f'Horizon point missing "az"/"el": {point}')
            az, el = point['az'], point['el']
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            az, el = point
        else:
            raise ValueError(f'Invalid horizon point: {point}')
        for value in (az, el):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f'Horizon az/el must be numbers: {point}')
        az, el = float(az), float(el)
        if not math.isfinite(az) or not math.isfinite(el):
            raise ValueError(f'Horizon az/el must be finite: {point}')
        if not 0 <= el < 90:
            raise ValueError(f'Horizon elevation must be 0 <= el < 90: {point}')
        parsed.append((az % 360, el))
    best = {}
    for az, el in parsed:
        if az not in best or el > best[az]:
            best[az] = el
    return sorted(best.items())


def mask_elevation(mask, azimuth):
    """Linearly interpolate the mask's clear elevation at azimuth, wrapping at 360."""
    if not mask:
        return 0.0
    n = len(mask)
    if n == 1:
        return mask[0][1]
    az = azimuth % 360
    for i in range(n):
        a0, e0 = mask[i]
        a1, e1 = mask[(i + 1) % n]
        if i == n - 1:
            a1 += 360
        az_adj = az if az >= a0 else az + 360
        if a0 <= az_adj <= a1:
            span = a1 - a0
            frac = (az_adj - a0) / span if span else 0.0
            return e0 + (e1 - e0) * frac
    return mask[-1][1]


def load_mask(config, path=None):
    """Load a horizon mask from an explicit JSON file or the config's "horizon" key.

    The file may hold a plain list of points or an object with a "horizon" key.
    Returns a normalized list, or None when no mask is configured. A file or
    key that exists but is invalid raises ValueError.
    """
    if path is not None:
        try:
            data = json.loads(path.read_text())
        except OSError as exc:
            raise ValueError(f'Cannot read horizon file {path}: {exc}') from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid JSON in horizon file {path}: {exc}') from exc
        points = data.get('horizon') if isinstance(data, dict) else data
        if points is None:
            raise ValueError(f'{path} has no "horizon" key')
        try:
            return normalize(points)
        except ValueError as exc:
            raise ValueError(f'Invalid horizon mask in {path}: {exc}') from exc
    points = config.get('horizon')
    if points is None:
        return None
    try:
        return normalize(points)
    except ValueError as exc:
        raise ValueError(f'Invalid horizon mask in location config: {exc}') from exc


def profile_text(mask, width=72, height=9):
    """ASCII elevation-by-azimuth profile, azimuth 0..360 left to right."""
    if not mask:
        return '(no horizon mask)'
    max_el = max(el for _az, el in mask)
    top = max(10.0, math.ceil(max_el / 10) * 10)
    cols = [mask_elevation(mask, 360 * x / (width - 1)) for x in range(width)]
    lines = []
    for row in range(height):
        level = top * (height - 1 - row) / (height - 1) if height > 1 else 0.0
        lines.append(''.join('#' if cols[x] >= level else ' ' for x in range(width)))
    axis = [' '] * width
    for label, frac in (('N', 0), ('E', .25), ('S', .5), ('W', .75)):
        axis[min(width - 1, round(frac * (width - 1)))] = label
    lines.append(''.join(axis))
    return '\n'.join(lines)


def survey(read_line=input, write=print, declination=None):
    """Interactively collect compass azimuth / level elevation obstacle readings.

    Compass reading + declination (degrees east positive) = true azimuth.
    Returns a normalized mask and prints its profile.
    """
    if declination is None:
        while True:
            try:
                line = read_line('Magnetic declination in degrees (east positive; '
                                  'Enter for 0, i.e. compass set to true north): ')
            except EOFError:
                line = ''
            line = line.strip()
            if not line:
                declination = 0.0
                break
            try:
                declination = float(line)
            except ValueError:
                write('Enter a number, or press Enter for 0.')
                continue
            if not math.isfinite(declination):
                write('Enter a finite number, or press Enter for 0.')
                continue
            break
    points = []
    while True:
        try:
            line = read_line('Compass azimuth, obstacle top elevation '
                              '(e.g. 135 22); Enter to finish: ')
        except EOFError:
            break
        line = line.strip()
        if not line:
            break
        parts = line.replace(',', ' ').split()
        if len(parts) != 2:
            write('Enter two numbers: compass azimuth and elevation, e.g. "135 22".')
            continue
        try:
            az, el = float(parts[0]), float(parts[1])
        except ValueError:
            write('Enter two numbers: compass azimuth and elevation, e.g. "135 22".')
            continue
        if not math.isfinite(az) or not math.isfinite(el) or not 0 <= el < 90:
            write('Elevation must be a finite number, 0 <= el < 90 degrees.')
            continue
        points.append({'az': az + declination, 'el': el})
    if not points:
        raise ValueError('Horizon survey requires at least one point')
    mask = normalize(points)
    write(profile_text(mask))
    return mask


def clear_window(az, alt, mask, floor):
    """Indices where alt clears both the flat horizon (floor) and the mask."""
    return [i for i, (a, e) in enumerate(zip(az, alt)) if e > max(floor, mask_elevation(mask, a))]
