"""Optional SatNOGS transmitter metadata for nextpass.

The orbital predictor remains useful without this module's network access.  Radio
metadata is deliberately treated as a published catalog snapshot: it describes
what SatNOGS records, not what a spacecraft is transmitting right now.
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


SATNOGS_API = "https://db.satnogs.org/api/transmitters/"
SATNOGS_LICENSE = "CC BY-SA 4.0"
SATNOGS_ATTRIBUTION = "SatNOGS DB (CC BY-SA 4.0)"
RADIO_CACHE_NAME = "radio.json"
RADIO_CACHE_TTL = 86400
FETCH_TIMEOUT = 20


class RadioMetadataError(ValueError):
    """The radio catalog response or local override is not usable."""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_band(value):
    """Parse a MHz range such as ``137-138`` into inclusive Hz bounds."""
    if value is None or isinstance(value, (tuple, list)):
        if value is None:
            return None
        if len(value) != 2:
            raise RadioMetadataError("radio band must contain two bounds")
        low, high = value
    elif isinstance(value, str):
        parts = value.strip().replace("–", "-").split("-")
        if len(parts) != 2:
            raise RadioMetadataError("radio band must be written LOW-HIGH in MHz")
        low, high = parts
    else:
        raise RadioMetadataError("radio band must be written LOW-HIGH in MHz")
    try:
        low, high = float(low), float(high)
    except (TypeError, ValueError) as exc:
        raise RadioMetadataError("radio band bounds must be numbers in MHz") from exc
    if not math.isfinite(low) or not math.isfinite(high) or low < 0 or high < low:
        raise RadioMetadataError("radio band must have finite nonnegative bounds")
    low_hz, high_hz = low * 1_000_000, high * 1_000_000
    if not math.isfinite(low_hz) or not math.isfinite(high_hz):
        raise RadioMetadataError("radio band bounds are too large")
    return (low_hz, high_hz)


def _number(value, field, *, integer=False):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RadioMetadataError(f"invalid radio field: {field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RadioMetadataError(f"invalid radio field: {field}") from exc
    if not math.isfinite(number) or number < 0:
        raise RadioMetadataError(f"invalid radio field: {field}")
    if integer:
        if not number.is_integer():
            raise RadioMetadataError(f"radio field {field} must be an integer")
        return int(number)
    return number


def _text(value, default="unknown"):
    return value.strip() if isinstance(value, str) and value.strip() else default


def _norad(row, hint=None):
    value = row.get("norad_cat_id", row.get("norad", row.get("NORAD_CAT_ID", hint)))
    if isinstance(value, dict):
        value = value.get("norad_cat_id", value.get("id"))
    if value is None:
        return None
    return _number(value, "norad_cat_id", integer=True)


def _frequency(row, aliases):
    for key in aliases:
        if key in row and row[key] not in (None, ""):
            return _number(row[key], key)
    return None


def normalize_transmitter(row, norad_hint=None, source="SatNOGS DB", fetched_at=None):
    """Validate and normalize one API or local transmitter row.

    Unknown values remain ``"unknown"``.  In particular, protocol is never
    guessed from a mode or description.
    """
    if not isinstance(row, dict):
        raise RadioMetadataError("radio transmitter must be a JSON object")
    nested = row.get("satellite") if isinstance(row.get("satellite"), dict) else {}
    merged = dict(nested)
    merged.update(row)
    norad = _norad(merged, norad_hint)
    if norad is None:
        raise RadioMetadataError("radio transmitter is missing NORAD_CAT_ID")

    low = _frequency(merged, ("downlink_low", "downlink_low_hz", "downlink_frequency_hz"))
    high = _frequency(merged, ("downlink_high", "downlink_high_hz", "downlink_frequency_hz"))
    if low is None and high is None:
        low = _frequency(merged, ("frequency_hz", "center_frequency", "frequency"))
        high = low
    if low is None:
        low = high
    if high is None:
        high = low
    # A local file may choose MHz explicitly; SatNOGS publishes frequencies in Hz.
    if low is None and high is None:
        low = _frequency(merged, ("downlink_low_mhz", "frequency_mhz"))
        high = _frequency(merged, ("downlink_high_mhz", "frequency_mhz"))
        if low is not None:
            low *= 1_000_000
        if high is not None:
            high *= 1_000_000
        if any(value is not None and not math.isfinite(value) for value in (low, high)):
            raise RadioMetadataError("radio downlink frequency is too large")
        if low is None:
            low = high
        if high is None:
            high = low
    if low is not None and high is not None and high < low:
        raise RadioMetadataError("radio downlink range has high below low")
    mode = _text(merged.get("expected_mode", merged.get("mode")))
    protocol = _text(merged.get("protocol"))
    baud = _number(merged.get("baud", merged.get("baudrate")), "baud")
    record = {
        "norad": norad,
        "norad_cat_id": norad,
        "transmitter_id": _text(merged.get("transmitter_id", merged.get("uuid", merged.get("id"))), "unknown"),
        "description": _text(merged.get("description")),
        "downlink_low_hz": low,
        "downlink_high_hz": high,
        "frequency_hz": low if low is not None and high == low else None,
        "expected_mode": mode,
        "mode": mode,
        "frequency_range_hz": [low, high] if low is not None and high is not None else None,
        "baud": baud,
        "protocol": protocol,
        "catalog_status": "not-live",
        "status_label": "catalog-status-not-live",
        "catalog_transmitter_status": _text(merged.get("catalog_transmitter_status", merged.get("status"))),
        "source": source,
        "license": SATNOGS_LICENSE if source == "SatNOGS DB" else "user-provided",
    }
    if fetched_at:
        record["fetched_at_utc"] = fetched_at
    # Keep useful documented generic fields without treating them as live state.
    for key in ("service", "type", "alive", "unconfirmed", "inverted", "invert",
                "updated", "citation", "downlink_drift"):
        if key in merged:
            record[key] = merged[key]
    return record


def _rows(payload):
    """Extract the transmitter list from current or legacy DRF envelopes."""
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise RadioMetadataError("SatNOGS response must be a JSON array or object")
    for key in ("results", "transmitters", "data", "items"):
        if key in payload:
            if not isinstance(payload[key], list):
                raise RadioMetadataError(f"SatNOGS response field {key} must be an array")
            return payload[key]
    # Local override files may be keyed by NORAD ID.
    if payload and all(isinstance(key, str) and key.strip().lstrip("+").isdigit()
                       and isinstance(value, list) for key, value in payload.items()):
        rows = []
        for norad, values in payload.items():
            for value in values:
                if not isinstance(value, dict):
                    raise RadioMetadataError("radio transmitter must be a JSON object")
                row = dict(value)
                row.setdefault("norad_cat_id", norad)
                rows.append(row)
        return rows
    # A single transmitter is accepted for local files, but not an arbitrary object.
    if any(key in payload for key in ("norad_cat_id", "downlink_low", "mode", "uuid")):
        return [payload]
    raise RadioMetadataError("SatNOGS response has no transmitter list")


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_cache(path):
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("transmitters"), list):
        return None
    timestamp = payload.get("fetched_at_utc")
    if not isinstance(timestamp, str):
        return None
    try:
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    coverage = payload.get("coverage", {})
    if not isinstance(coverage, dict):
        return None
    for norad, entry in coverage.items():
        if not isinstance(norad, str) or not norad.strip().lstrip("+").isdigit() or not isinstance(entry, dict):
            return None
        stamp = entry.get("fetched_at_utc")
        count = entry.get("count")
        if not isinstance(stamp, str) or isinstance(count, bool) or not isinstance(count, int) or count < 0:
            return None
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return None
    records = []
    try:
        for row in payload["transmitters"]:
            if not isinstance(row, dict):
                raise RadioMetadataError("cached radio transmitter must be a JSON object")
            records.append(normalize_transmitter(
                row, source="SatNOGS DB", fetched_at=row.get("fetched_at_utc", timestamp)))
    except RadioMetadataError:
        return None
    payload["transmitters"] = records
    return payload


def _fetch_norad(norad, opener=None):
    query = urlencode({"format": "json", "satellite__norad_cat_id": norad})
    url = f"{SATNOGS_API}?{query}"
    opener = opener or urlopen
    origin = urlsplit(SATNOGS_API)
    pages = []
    visited = set()
    next_url = url
    for page_number in range(100):
        parsed = urlsplit(next_url)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            raise RadioMetadataError("SatNOGS pagination link left the official origin")
        if next_url in visited:
            raise RadioMetadataError("SatNOGS pagination cycle detected")
        visited.add(next_url)
        request = Request(next_url, headers={"Accept": "application/json", "User-Agent": "nextpass-radio/1.8.0"})
        try:
            with opener(request, timeout=FETCH_TIMEOUT) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else next_url
                final = urlsplit(final_url)
                if (final.scheme, final.netloc) != (origin.scheme, origin.netloc):
                    raise RadioMetadataError("SatNOGS response redirected outside the official origin")
                payload = json.load(response)
        except RadioMetadataError:
            raise
        except (OSError, ValueError, TypeError) as exc:
            raise RadioMetadataError(f"SatNOGS fetch failed for NORAD {norad}: {exc}") from exc
        pages.extend(_rows(payload))
        next_link = payload.get("next") if isinstance(payload, dict) else None
        if not next_link:
            break
        next_url = urljoin(next_url, next_link)
    else:
        raise RadioMetadataError("SatNOGS pagination exceeded the 100-page limit")

    fetched_at = utc_now()
    records = []
    for row in pages:
        # Verify the row's own NORAD value; an ignored server-side filter must
        # never relabel a record as the requested satellite.
        normalized = normalize_transmitter(row, fetched_at=fetched_at)
        if normalized["norad"] == norad:
            records.append(normalized)
    return records, url, fetched_at


def _matches_band(record, band):
    if band is None:
        return True
    low, high = record.get("downlink_low_hz"), record.get("downlink_high_hz")
    return low is not None and high is not None and high >= band[0] and low <= band[1]


def load_radio_metadata(norads, cache_dir, *, offline=False, refresh=False, band=None,
                        radio_file=None, opener=None, warn=None):
    """Load optional metadata and return an export-ready structured object.

    ``norads`` may be any iterable of integer NORAD IDs.  Local rows supplement
    fetched rows and replace a fetched row with the same transmitter ID.
    """
    norads = [int(value) for value in norads]
    band = parse_band(band)
    cache_path = Path(cache_dir) / RADIO_CACHE_NAME
    cache = _read_cache(cache_path)
    # A local file is an explicitly offline source unless the caller separately
    # asks for --refresh-radio.
    local_only = radio_file is not None and not refresh
    fetched_at = cache.get("fetched_at_utc") if cache else None
    coverage = dict(cache.get("coverage", {})) if cache else {}
    for row in (cache.get("transmitters", []) if cache else []):
        coverage.setdefault(str(row.get("norad")), {
            "fetched_at_utc": row.get("fetched_at_utc", fetched_at if cache else None),
            "count": 1,
        })
    now = datetime.now(timezone.utc).timestamp()
    missing = any(str(norad) not in coverage for norad in norads)
    stale = set()
    for norad in norads:
        stamp = coverage.get(str(norad), {}).get("fetched_at_utc")
        try:
            stamp_age = now - datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except (AttributeError, TypeError, ValueError):
            stamp_age = math.inf
        if stamp_age >= RADIO_CACHE_TTL:
            stale.add(norad)
    should_fetch = not offline and not local_only and (refresh or cache is None or missing or stale)
    fetch_norads = norads if refresh or cache is None else [norad for norad in norads
                                                             if str(norad) not in coverage or norad in stale]
    records = list(cache.get("transmitters", [])) if cache else []
    source_urls = list(cache.get("source_urls", [])) if cache else []
    fetched_any = False
    if should_fetch:
        for norad in fetch_norads:
            try:
                fetched, url, stamp = _fetch_norad(norad, opener=opener)
            except RadioMetadataError as exc:
                if warn:
                    warn(str(exc))
                continue
            fetched_any = True
            records = [row for row in records if row.get("norad") != norad] + fetched
            source_urls.append(url)
            fetched_at = stamp
            coverage[str(norad)] = {"fetched_at_utc": stamp, "count": len(fetched)}
        if fetched_any:
            envelope = {
                "schema": 1,
                "source": "SatNOGS DB",
                "source_urls": sorted(set(source_urls)),
                "fetched_at_utc": fetched_at or utc_now(),
                "catalog_status": "not-live",
                "status_label": "catalog-status-not-live",
                "license": SATNOGS_LICENSE,
                "attribution": SATNOGS_ATTRIBUTION,
                "coverage": coverage,
                "transmitters": records,
            }
            _atomic_json(cache_path, envelope)
            cache = envelope
        elif cache is None and not radio_file:
            raise RadioMetadataError("No valid SatNOGS radio data was fetched and no cache is available")
    elif offline and cache is None and radio_file is None:
        raise RadioMetadataError(f"No valid cached radio data at {cache_path}; run once online or use --radio-file.")
    if radio_file:
        try:
            local_payload = json.loads(Path(radio_file).read_text())
        except (OSError, ValueError, TypeError) as exc:
            raise RadioMetadataError(f"Cannot read --radio-file {radio_file}: {exc}") from exc
        local_rows = _rows(local_payload)
        local_records = [normalize_transmitter(row, source="local radio file") for row in local_rows]
        records = [row for row in records if not any(
            local.get("transmitter_id") != "unknown"
            and row.get("norad") == local.get("norad")
            and row.get("transmitter_id") == local.get("transmitter_id")
            for local in local_records)] + local_records

    selected = {str(norad): [row for row in records if row.get("norad") == norad and _matches_band(row, band)]
                for norad in norads}
    availability = {}
    for norad in norads:
        entry = coverage.get(str(norad))
        local_records = [row for row in records if row.get("norad") == norad]
        selected_records = selected[str(norad)]
        if selected_records:
            availability[str(norad)] = {"status": "available", "count": len(selected_records)}
            if entry and entry.get("fetched_at_utc"):
                availability[str(norad)]["fetched_at_utc"] = entry["fetched_at_utc"]
        elif band is not None and (local_records or (entry and entry.get("count", 0) > 0)):
            availability[str(norad)] = {"status": "filtered", "reason": "no transmitter records match the requested band",
                                         "count": 0}
            if entry and entry.get("fetched_at_utc"):
                availability[str(norad)]["fetched_at_utc"] = entry["fetched_at_utc"]
        elif local_records:
            availability[str(norad)] = {"status": "empty", "reason": "no transmitter records available locally",
                                         "count": 0}
            if entry and entry.get("fetched_at_utc"):
                availability[str(norad)]["fetched_at_utc"] = entry["fetched_at_utc"]
        elif entry is None:
            availability[str(norad)] = {"status": "unavailable", "reason": "not covered by this cache/fetch"}
        elif entry.get("count", 0) == 0:
            availability[str(norad)] = {"status": "empty", "reason": "catalog returned no transmitter records",
                                         "fetched_at_utc": entry.get("fetched_at_utc")}
        else:
            availability[str(norad)] = {"status": "empty", "reason": "catalog records are not present locally",
                                         "count": 0, "fetched_at_utc": entry.get("fetched_at_utc")}
    return {
        "schema": 1,
        "source": "SatNOGS DB" if cache or any(row.get("source") == "SatNOGS DB" for row in records) else "local radio file",
        "source_urls": sorted(set(source_urls)),
        "fetched_at_utc": fetched_at,
        "catalog_status": "not-live",
        "status_label": "catalog-status-not-live",
        "license": SATNOGS_LICENSE if cache or any(row.get("source") == "SatNOGS DB" for row in records) else "user-provided",
        "attribution": SATNOGS_ATTRIBUTION if cache or any(row.get("source") == "SatNOGS DB" for row in records) else "Local radio file",
        "band_mhz": [band[0] / 1_000_000, band[1] / 1_000_000] if band else None,
        "coverage": coverage,
        "availability": availability,
        "satellites": selected,
    }


# Short aliases are useful to callers and preserve a small, discoverable API.
fetch_radio = _fetch_norad
normalize_radio = normalize_transmitter
load_radio = load_radio_metadata
