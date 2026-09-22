#!/usr/bin/env python3
"""Generate the checked-in PyEphem pass references.

Run this only in the pinned reference environment documented in README.md; PyEphem
is deliberately not a runtime or test dependency of nextpass.
"""
import argparse
import json
import math
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import ephem
from sgp4.exporter import export_tle
from skyfield.api import EarthSatellite, load

ROOT = Path(__file__).resolve().parents[1]
ELEMENTS = ROOT / "examples" / "elements-2026-09-21.json"
OUTPUT = ROOT / "tests" / "fixtures" / "pyephem-reference-2026-09-21.json"
STEP_SECONDS = 2.0


def utc_datetime(value):
    return ephem.Date(value).datetime().replace(tzinfo=timezone.utc)


def pyephem_altitude(satellite, observer, moment):
    observer.date = ephem.Date(moment)
    satellite.compute(observer)
    return math.degrees(float(satellite.alt))


def crossing(left, right, left_alt, right_alt, threshold):
    """Linearly interpolate a threshold crossing, to sub-second precision."""
    fraction = (threshold - left_alt) / (right_alt - left_alt)
    return left + (right - left) * fraction


def pass_reference(satellite, observer, rise, setting, horizon, minimum):
    start = rise
    end = setting
    samples = []
    moment = start
    while moment < end:
        samples.append((moment, pyephem_altitude(satellite, observer, moment)))
        moment += timedelta(seconds=STEP_SECONDS)
    samples.append((end, pyephem_altitude(satellite, observer, end)))
    best_moment, best_altitude = max(samples, key=lambda item: item[1])
    if best_altitude < minimum:
        return None

    above = [index for index, (_moment, altitude) in enumerate(samples) if altitude >= horizon]
    if not above:
        return None
    first = above[0]
    last = above[-1]
    if first:
        rise = crossing(samples[first - 1][0], samples[first][0], samples[first - 1][1], samples[first][1], horizon)
    else:
        rise = samples[first][0]
    if last + 1 < len(samples):
        setting = crossing(samples[last][0], samples[last + 1][0], samples[last][1], samples[last + 1][1], horizon)
    else:
        setting = samples[last][0]
    return {
        "rise": rise.isoformat(timespec="milliseconds"),
        "peak": best_moment.isoformat(timespec="milliseconds"),
        "set": setting.isoformat(timespec="milliseconds"),
        "max_elevation_deg": round(best_altitude, 4),
    }


def references_for_row(row, start, end, horizon, minimum):
    timescale = load.timescale(builtin=True)
    skyfield_satellite = EarthSatellite.from_omm(timescale, row)
    tle_lines = export_tle(skyfield_satellite.model)
    satellite = ephem.readtle(row["OBJECT_NAME"], *tle_lines)
    observer = ephem.Observer()
    observer.lat = "0"
    observer.lon = "0"
    observer.elevation = 0
    observer.pressure = 0
    observer.date = ephem.Date(start - timedelta(hours=3))
    result = []
    while observer.date < ephem.Date(end + timedelta(hours=3)):
        try:
            values = observer.next_pass(satellite)
        except (ephem.AlwaysUpError, ephem.NeverUpError, ValueError):
            break
        if values[0] is None:
            break
        rise, _rise_azimuth, _peak, _peak_altitude, setting, _set_azimuth = values
        rise_dt, setting_dt = map(utc_datetime, (rise, setting))
        candidate = pass_reference(satellite, observer, rise_dt, setting_dt, horizon, minimum)
        sampled_peak = datetime.fromisoformat(candidate["peak"]) if candidate else None
        if candidate and start <= sampled_peak < end:
            candidate["norad"] = int(row["NORAD_CAT_ID"])
            result.append(candidate)
        observer.date = ephem.Date(setting_dt + timedelta(seconds=2))
    return result, tle_lines


def make_case(name, local_date, days, timezone_name, rows, horizon=10, minimum=20):
    tz = ZoneInfo(timezone_name)
    start = datetime.combine(date.fromisoformat(local_date), time(), tz)
    end = start + timedelta(days=days)
    passes = []
    tles = {}
    for row in rows:
        found, tle_lines = references_for_row(row, start.astimezone(timezone.utc), end.astimezone(timezone.utc), horizon, minimum)
        passes.extend(found)
        tles[str(row["NORAD_CAT_ID"])] = list(tle_lines)
    return {
        "name": name,
        "date": local_date,
        "days": days,
        "timezone": timezone_name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "horizon_deg": horizon,
        "minimum_peak_deg": minimum,
        "passes": sorted(passes, key=lambda item: item["peak"]),
        "reference_tles": tles,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    rows = json.loads(ELEMENTS.read_text())
    cases = [
        make_case("utc-midnight-and-high-low", "2026-09-21", 1, "UTC", rows),
        make_case("midnight-straddling-window", "2026-09-28", 2, "Europe/Moscow", rows),
        make_case("auckland-dst-transition", "2026-09-26", 3, "Pacific/Auckland", rows),
    ]
    payload = {
        "schema": 1,
        "generated_at": "2026-09-22",
        "generator": {
            "library": "PyEphem",
            "version": ephem.__version__,
            "algorithm": "libastro TLE propagation; next_pass finds geometric pass candidates, then 2-second altitude samples with linear threshold crossings",
            "independent_input": "TLE lines exported from Skyfield 1.55 sgp4.exporter using each exact saved OMM row",
            "pressure_mbar": 0,
            "observer": {"latitude_deg": 0, "longitude_deg": 0, "elevation_m": 0},
            "limitations": "Agreement is a predictor regression, not observational truth. TLE quantization and independent implementation differences are covered by test tolerances.",
        },
        "elements": str(ELEMENTS.relative_to(ROOT)),
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
