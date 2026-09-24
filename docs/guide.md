# nextpass guide

[Back to the README](../README.md)

Commands below run from the repository root.

- [Quickstart](#quickstart)
- [What it tracks](#what-it-tracks)
- [Everyday commands](#everyday-commands)
- [Reading the output](#reading-the-output)
- [Terminal sky plots and colors](#terminal-sky-plots-and-colors)
- [Optional radio metadata](#optional-radio-metadata)
- [Orbital-data freshness](#orbital-data-freshness)
- [Private location](#private-location)
- [Validation](#validation)
- [Related](#related)

## Quickstart

```sh
git clone https://github.com/gdamdam/nextpass.git
cd nextpass
./predict.sh --days 7
```

Python 3.9+. On first use the launcher builds `.venv` and installs Skyfield; the
first run also downloads orbital data. You'll get a ranked list of opportunities, a
day-by-day schedule, and a sky plot of the best pass.

To install the command with pip, create an environment and install this directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install .
nextpass --version
nextpass --days 7
```

Installed runs cache orbital elements in `$XDG_CACHE_HOME/nextpass` when
`XDG_CACHE_HOME` is set, or `~/.cache/nextpass` otherwise. The source launcher
uses the same default. To keep a source checkout's cache inside the repository,
pass `--cache-dir .cache`.

> [!IMPORTANT]
> There is **no location in the code**. Create `~/.config/radio/location.json`
> (mode `600`, outside this repository) before the first run — see
> [Private location](#private-location) below.

---

## What it tracks

Eleven built-in objects, in five groups; extend or override them with `--catalog`. NORAD IDs were verified against the live CelesTrak
catalog on 2026-09-22.

| Label | Object | NORAD | Group | Why you'd chase it |
|---|---|---|---|---|
| `M2-3` | METEOR-M2 3 | 57166 | `meteor` | LRPT weather imagery, 137.900 MHz / 72k |
| `M2-4` | METEOR-M2 4 | 59051 | `meteor` | LRPT weather imagery, LRPT weather imagery |
| `ISS` | ISS (ZARYA) | 25544 | `stations` | SSTV events and APRS digipeater on 2 m; brightest thing in the sky |
| `CSS` | CSS (TIANHE) | 48274 | `stations` | Chinese space station — visual spotting, occasional SSTV |
| `AO-73` | FUNCUBE-1 | 39444 | `amateur` | BPSK telemetry beacon + SSB/CW linear transponder |
| `RS-44` | RS-44 (DOSAAF-85) | 44909 | `amateur` | Excellent high-orbit linear transponder, long passes |
| `SO-50` | SAUDISAT 1C | 27607 | `amateur` | The classic easy FM repeater bird |
| `AO-123` | ASRTU-1 | 61781 | `amateur` | V/U transponder and image downlink |
| `METOPB` | METOP-B | 38771 | `metop` | AHRPT weather imagery, L-band 1701.3 MHz |
| `METOPC` | METOP-C | 43689 | `metop` | AHRPT weather imagery, L-band 1701.3 MHz |
| `GOES18` | GOES 18 | 51850 | `geo` | HRIT/EMWIN, 1694.1 MHz; geostationary at ~137°W |

> [!NOTE]
> **GOES-18 does not move.** It orbits once per day above the equator, so it sits at a
> fixed point in your sky and never rises or sets. Instead of passes, nextpass prints
> the azimuth and elevation to aim a fixed dish at (or says it is below your horizon;
> it is only visible from roughly the Americas' Pacific side and the Pacific). The
> JSON export lists it under `stationary`. `--day-plot` rejects it.

> [!WARNING]
> **This tool predicts geometry, not transmissions.** It never queries transmitter
> status. Several of these are well past design life, amateur payloads get switched
> off, and modes change. Confirm current frequency and activity against AMSAT or
> SatNOGS before a pass. A pass in this table is an opportunity, not a promise of signal.

### Pick a subset

```sh
./predict.sh --satellites meteor           # only the weather birds
./predict.sh --satellites iss              # only the ISS
./predict.sh --satellites stations         # ISS + CSS
./predict.sh --satellites amateur          # the four ham satellites
./predict.sh --satellites iss,m2-4,so-50   # any mix of labels
./predict.sh --satellites 25544            # or raw NORAD IDs
```

Labels, group names and NORAD IDs can be mixed freely and are case-insensitive.
Duplicates collapse, and output always follows catalog order. Omit the flag to get
all eleven.

### Extend the satellite catalog

Use `--catalog catalog.json` to merge local entries with the built-in catalog:

```json
[{"norad": 25544, "label": "ISS", "group": "favorites", "name": "ISS (ZARYA)"}]
```

Each entry requires an integer `norad` and nonempty `label`, `group`, and `name`.
An existing NORAD ID replaces that entry; a new ID adds a satellite without editing
Python. Labels must be unique ignoring case; labels and groups cannot contain commas
or control characters. Custom labels, groups and IDs work with `--satellites`.
For example, `--catalog catalog.json --satellites favorites` selects the ISS above.
New objects need matching CelesTrak data or an element row supplied via `--elements`.
Omitting `--satellites` includes the merged catalog.

---

## Everyday commands

```sh
./predict.sh --date 2026-09-23 --days 3                          # fixed start date
./predict.sh --days 7 --min-elevation 40 --hours 08:00-22:00 --top 5
./predict.sh --days 7 --json passes.json --csv passes.csv        # export
./predict.sh --days 3 --horizon 0                                # geometric AOS/LOS
./predict.sh --days 3 --refresh                                  # force fresh orbits
./predict.sh --days 3 --offline                                  # use cache only
./predict.sh --days 3 --radio --band 137-138                    # optional SatNOGS transmitter catalog
./predict.sh --days 3 --radio --offline                         # use cached radio catalog only
./predict.sh --days 3 --radio-file radio-overrides.json         # local radio metadata, no network
./predict.sh --days 3 --refresh-radio                           # refresh the optional catalog
./predict.sh --help
```

Without `--date` the interval runs from now to the same local time N days later. With
`--date` it starts at local midnight and covers N calendar dates. Daylight-saving is
handled by your timezone. Passes are included by **peak** time, so a window may begin
before or end after the requested interval — `--hours` filters on peak time too, and
overnight ranges like `20:00-06:00` work.

### Calendar events and reminders

```sh
./predict.sh --days 7 --ics passes.ics
./predict.sh --days 7 --ics passes.ics --reminder-minutes 30
./predict.sh --days 7 --ics passes.ics --reminder-minutes 0  # no alarms
```

Import the file into your calendar app. Events span the configured reception window,
include pass geometry, and default to a display alarm 15 minutes before the start.
The calendar app delivers reminders; nextpass does not run in the background.
Timestamps use UTC so calendar apps display them in the appropriate local timezone.
Identical satellite/window times produce stable event IDs; recalculated window times
produce new IDs, so replace an old imported calendar when updating predictions.
Calendar exports contain observing times and should be kept private.

### Visual-pass candidates

```sh
./predict.sh --satellites stations --days 3 --visibility
./predict.sh --satellites stations --days 3 --visible-only
./predict.sh --visible-only --max-sun-altitude -12 --ephemeris /path/to/de421.bsp
```

`--visibility` annotates each pass with satellite sunlight and the observer's Sun
altitude **at peak**. `--visible-only` keeps peaks where the satellite is sunlit and
the Sun is at or below -6° by default. Change the darkness threshold with
`--max-sun-altitude`. Results describe peak conditions, not the entire pass; clouds,
brightness and obstructions are not modeled. Daylight radio passes remain useful.

These options require a planetary ephemeris. First online use downloads Skyfield's
`de421.bsp` into the cache directory; ordinary radio predictions do not download it.
`--ephemeris` uses an existing local BSP. Under `--offline`, a missing BSP produces
an actionable error and no download. Choose a BSP covering the requested dates.
JSON and CSV include the three visibility fields; CSV leaves them blank when this
feature is disabled, and uses the same columns for empty and nonempty results.

---

## Reading the output

- Opportunities sort by **maximum elevation**, then range at peak. A chronological
  schedule follows.
- Reception windows default to **10° elevation** — these are not horizon AOS/LOS. Use
  `--horizon 0` for the horizon times you'll find in older notes.
- Default minimum peak elevation is 20°. Labels: **Excellent** ≥60°, **Good** ≥40°,
  **Fair** ≥20°, **Low** otherwise. Planning labels, not measured RF ratings.
- Azimuth is clockwise from true north: N=0°, E=90°, S=180°, W=270°.
- Range is distance at the elevation maximum, not an independently minimized distance.
- Elevation predicts nothing about SNR, interference, antenna nulls, M2-3 fading or
  transmitter outages.
- Evening passes suit radio and infrared channels; illumination only matters for
  visible imagery.

## Terminal sky plots and colors

The normal command draws the highest-ranked pass plus a compact daily schedule.

```sh
./predict.sh --days 3 --plots 3        # draw the three best passes
./predict.sh --days 3 --plot-rank 2    # draw pass #2 from this run's ranking
./predict.sh --days 3 --no-plot        # schedule only
./predict.sh --days 3 --color never    # plain text
./predict.sh --days 3 --color always | less -R
```

**Anatomy of a plot.** North is up, east is right. The outer circle is the horizon,
inner rings are 30° and 60°, and the center is overhead at 90°. `A` marks the
beginning of the window, `P` the maximum elevation, `B` the end — follow the yellow
`*` track from A to B. With the default 10° window, A and B sit inside the horizon
ring rather than on it. This is a static prediction, not a live position display.

Colors are tuned for a black background: elevation runs bright red (low) → yellow
(moderate) → green (high), describing **geometry, not signal strength**. Each object
keeps a stable color in the schedule, so M2-3 is always cyan and the ISS always green.

ANSI truecolor, as supported by modern macOS terminals. Color turns itself off when
output is redirected, when `TERM=dumb`, or when `NO_COLOR` is set; `--color always`
overrides that. No background color is imposed. Plots track terminal width and
collapse to compact pass cards in narrow windows — 80 columns or wider is best.

Pass rank is recomputed for the selected dates and filters, so use identical arguments
(and a fixed `--date`) when acting on a rank an earlier run printed.

## Optional radio metadata

Pass `--radio` to add published transmitter metadata from the official SatNOGS DB
API. The request is opt-in; ordinary pass predictions never contact SatNOGS. The
metadata is cached as `radio.json` beneath the same XDG cache directory as orbital
data, with an atomic write and a one-day freshness window. `--refresh-radio` forces
a refresh, while `--offline` prevents all network access and uses that cache. A
failed refresh falls back to a valid cache. If no radio cache is available, the
CLI warns and still prints/exports the geometric predictions; JSON records radio
unavailability. Malformed explicit local radio files remain errors. `--band 137-138` filters downlinks by
an overlapping MHz range and requires `--radio`, `--refresh-radio`, or
`--radio-file`. Paginated catalog responses are collected before cache coverage is
recorded. Availability distinguishes missing metadata from records excluded by the band.

SatNOGS records are catalog observations, not live transmitter state. The terminal
and JSON exports label them `catalog-status-not-live`; modes and baud values are
shown only when documented by the source, and protocol remains `unknown` unless
explicitly supplied. Multiple transmitter records are retained independently, with
no “most probable” choice. JSON exports include SatNOGS attribution and the
CC BY-SA 4.0 license provenance.

For an offline supplement or override, pass a local JSON array (or an object with
`results`/`transmitters`) to `--radio-file`:

```json
[{"norad_cat_id": 57166, "frequency_mhz": 137.9,
  "expected_mode": "LRPT", "baud": 72000,
  "protocol": "explicitly documented local note"}]
```

Local values are labeled user-provided and do not imply that the satellite is
currently transmitting. Confirm current frequency and activity against the source
before receiving.

## Orbital-data freshness

Public CelesTrak GP data is downloaded in JSON/OMM format — the modern replacement for
TLE — and propagated with Skyfield/SGP4. Each satellite is cached separately for six
hours. A failed download falls back to a valid cache with an explicit warning; no cache
produces a clear error. Every satellite's epoch is printed and recorded in JSON output.

Dates more than **7 days** from an epoch warn; more than **14 days** are rejected
unless you pass `--allow-stale`. Those are safeguards, not accuracy guarantees —
refresh close to the pass.

For historical work, supply a CelesTrak-format JSON array:

```sh
./predict.sh --date 2026-09-21 --days 1 --elements historical-elements.json
```

Objects **absent from that file are skipped with a warning** rather than aborting the
run, so an old two-satellite element file still works against the full eleven-object
catalog. Pair it with `--satellites` to silence the warnings entirely.

Never use current orbital data for precise predictions months into the past or future;
long-range output under `--allow-stale` is rough planning only.

## Private location

The predictor reads `~/.config/radio/location.json` by default, overridable with
`RADIO_LOCATION_CONFIG` or `--location-config`. The file lives outside the repository
and should be mode `600`. **There is no personal-location fallback in the code** — the
program errors out instead of guessing.

`--lat`, `--lon`, `--altitude` (metres) and `--timezone` override individual fields
from the file. Passing all four works without any config file.

```json
{"lat": 0.0, "lon": 0.0, "altitude": 0, "timezone": "UTC"}
```

Those are neutral example values. Don't copy your private file into the repository.
Tests pass a neutral location explicitly and never touch your config.

> [!CAUTION]
> Generated exports embed the observing location, and **even pass times can reveal
> it**. Keep exports private. `.gitignore` excludes local config, export formats,
> histories, recordings and environments, with only the public orbital-element
> fixtures excepted — but ignore rules don't protect files you force-add or share
> elsewhere. Check staged changes before publishing.

---

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Fifty-six tests cover pass-event geometry, calendar-boundary inclusion, DST, filters,
exports, satellite selection, OMM validation, cache recovery, element-file skipping,
concurrent refreshes and stale-data rejection, plus mocked radio metadata schema,
cache, offline, band, pagination and local-override behavior, plus calendar alarms,
custom catalogs, peak visibility and CLI failure recovery, with no live network access.
CI installs the package and runs the suite on Python 3.9, 3.11 and 3.13. Geometry tests
use saved real METEOR elements; all-catalog plumbing uses explicitly synthetic elements.
Dense time sampling checks event detection independently of the event finder, while
sharing its SGP4 propagator. Saved reference cases add an independent comparison using
PyEphem 4.1.6's libastro propagator: two METEOR satellites, neutral coordinates,
10° reception threshold, low and high passes, and a Pacific/Auckland daylight-saving
transition plus a Europe/Moscow pass that crosses local midnight. The reference
generator is `tests/generate_reference.py`; it is run only in a temporary environment
with `ephem==4.1.6`, `skyfield==1.55` and `sgp4==2.27` and
does not add a production dependency. To reproduce the checked-in fixture:

```sh
python3 -m venv /private/tmp/nextpass-reference-venv
/private/tmp/nextpass-reference-venv/bin/pip install ephem==4.1.6 skyfield==1.55 sgp4==2.27
/private/tmp/nextpass-reference-venv/bin/python tests/generate_reference.py
```

Reference TLEs are exported from the exact saved OMM rows with `sgp4.exporter` 2.27 through Skyfield 1.55; measured differences are below 2 seconds and 0.05° for these cases,
with tests allowing 3 seconds and 0.2° to accommodate two-second reference
sampling, output rounding and implementation differences. Both identical-TLE and
production OMM paths are checked. The timezone cases deliberately use the same
neutral observer at 0° latitude/longitude; their timezone labels do not indicate
observer locations. Agreement is a predictor regression, not
observational truth.

---

## Related

| | |
|---|---|
| [iqscan](https://github.com/gdamdam/iqscan) | Scan the recording you just made for activity, with an interactive offline report |
| [`examples/`](../examples/) | Public orbital elements used by tests; no personal prediction results |

Sources: [Skyfield](https://rhodesmill.org/skyfield/earth-satellites.html) ·
[PyEphem quick reference](https://rhodesmill.org/pyephem/quick.html) ·
[CelesTrak GP formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php) ·
[AMSAT status](https://www.amsat.org/status/) ·
[SatNOGS DB](https://db.satnogs.org/)
