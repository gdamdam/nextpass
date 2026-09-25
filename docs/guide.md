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
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
nextpass --days 7
```

Python 3.9+. The first run downloads orbital data. You'll get a ranked list of opportunities, a
day-by-day schedule, and a sky plot of the best pass.

On Windows PowerShell, install into a virtual environment with:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\Activate.ps1
nextpass --days 7
```

Installed runs cache orbital elements in `$XDG_CACHE_HOME/nextpass` when
`XDG_CACHE_HOME` is set, or `~/.cache/nextpass` otherwise. To keep a source checkout's cache inside the repository,
pass `--cache-dir .cache`.

> [!IMPORTANT]
> There is **no location in the code**. Create `~/.config/radio/location.json`
> (mode `600`, outside this repository) before the first run — see
> [Private location](#private-location) below.

---

## What it tracks

The built-in objects live in [`catalog.json`](../catalog.json), with a verification
date for each NORAD ID. Extend or override them with `--catalog`.

Run `nextpass --list-satellites` for every built-in label, group, NORAD ID,
object name, and verification date. The JSON file is the source of truth, so a
catalog addition does not require a documentation table update.

> [!NOTE]
> **Geostationary objects such as GOES-18, GOES-19, and Elektro-L 3 do not traverse the sky.** They orbit once per day above the equator and sit at a
> fixed point in your sky and never rise or set. Instead of passes, nextpass prints
> the azimuth and elevation to aim a fixed dish at (or says it is below your horizon;
> visibility depends on your location). JSON lists them under `stationary`.
> `--day-plot` rejects them.

> [!WARNING]
> **This tool predicts geometry, not transmissions.** It does not query live transmitter
> operation. Several of these are well past design life, amateur payloads get switched
> off, and modes change. Confirm current frequency and activity against AMSAT or
> SatNOGS before a pass. A predicted pass is an opportunity, not a promise of signal.

### Pick a subset

```sh
nextpass --satellites meteor           # only the weather birds
nextpass --satellites iss              # only the ISS
nextpass --satellites stations         # ISS + CSS
nextpass --satellites amateur          # the curated ham group
nextpass --satellites iss,m2-4,so-50   # any mix of labels
nextpass --satellites 25544            # or raw NORAD IDs
```

Labels, group names and NORAD IDs can be mixed freely and are case-insensitive.
Duplicates collapse, and output always follows catalog order. Omit the flag to get
all built-ins.

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
Optional `color` (RGB array), `radio_hint` (short sentence), and `verified`
(`YYYY-MM-DD`) fields control terminal presentation and record the catalog check.
The same fields are accepted in user `--catalog` files. A bare NORAD number in
`--satellites` can also fetch an object without creating a catalog entry.
Omitting `--satellites` includes the merged catalog.

---

## Everyday commands

```sh
nextpass --date 2026-09-23 --days 3                          # fixed start date
nextpass --days 7 --min-elevation 40 --hours 08:00-22:00 --top 5
nextpass --days 7 --json passes.json --csv passes.csv        # export
nextpass --days 3 --horizon 0                                # geometric AOS/LOS
nextpass --days 3 --refresh                                  # force fresh orbits
nextpass --days 3 --offline                                  # use cache only
nextpass --days 3 --radio --band 137-138                    # optional SatNOGS transmitter catalog
nextpass --days 3 --radio --offline                         # use cached radio catalog only
nextpass --days 3 --radio-file radio-overrides.json         # local radio metadata, no network
nextpass --days 3 --refresh-radio                           # refresh the optional catalog
nextpass --help
```

Without `--date` the interval runs from now to the same local time N days later. With
`--date` it starts at local midnight and covers N calendar dates. Daylight-saving is
handled by your timezone. Passes are included by **peak** time, so a window may begin
before or end after the requested interval — `--hours` filters on peak time too, and
overnight ranges like `20:00-06:00` work.

### Calendar events and reminders

```sh
nextpass --days 7 --ics passes.ics
nextpass --days 7 --ics passes.ics --reminder-minutes 30
nextpass --days 7 --ics passes.ics --reminder-minutes 0  # no alarms
```

Import the file into your calendar app. Events span the configured reception window,
include pass geometry, and default to a display alarm 15 minutes before the start.
The calendar app delivers reminders for an imported ICS file. For direct desktop
notifications, use the separate `--watch` mode described below.
Timestamps use UTC so calendar apps display them in the appropriate local timezone.
When an existing nextpass calendar is regenerated at the same path, passes from the
same satellite with peaks within 20 minutes retain their event IDs. Calendar apps
may still require replacing an old import. Large orbit corrections can create new IDs.
Calendar exports contain observing times and should be kept private.

For desktop notifications without a calendar import, run `nextpass --watch`
under a macOS LaunchAgent or Linux user service. It checks the schedule every 30
seconds, refreshes predictions every six hours, and uses the configured reminder
lead time. It has no persistent queue when the computer is asleep or stopped.
On macOS, install and start the LaunchAgent with
`nextpass --service install`; remove it with the same command
ending in `uninstall`. The service uses your saved location file and keeps logs
in `~/.cache/nextpass`. On Linux, run `nextpass --watch --no-plot` under a
user service manager. Live tracking and reminders need the computer to be awake.

### Visual-pass candidates

```sh
nextpass --satellites stations --days 3 --visibility
nextpass --satellites stations --days 3 --visible-only
nextpass --visible-only --max-sun-altitude -12 --ephemeris /path/to/de421.bsp
```

`--visibility` annotates each pass with satellite sunlight and the observer's Sun
altitude at peak, plus candidate times sampled through the reception window.
`--visible-only` keeps passes with a sampled instant where the satellite is sunlit
and the Sun is at or below -6° by default. Change the darkness threshold with
`--max-sun-altitude`. Samples are approximate; clouds and
brightness are not modeled, and local obstructions are modeled only when a
horizon mask has been surveyed (see "Local horizon mask" below). Daylight radio passes remain useful.

These options require a planetary ephemeris. First online use downloads Skyfield's
`de421.bsp` into the cache directory; ordinary radio predictions do not download it.
`--ephemeris` uses an existing local BSP. Under `--offline`, a missing BSP produces
an actionable error and no download. Choose a BSP covering the requested dates.
JSON and CSV include the three visibility fields; CSV leaves them blank when this
feature is disabled, and uses the same columns for empty and nonempty results.

---

## Reading the output

- Opportunities sort by **maximum elevation**, then range at peak, unless
  `--rank-by duration` sorts by reception-window length or `--rank-by imagery`
  sorts by sampled daylight beneath the satellite. A chronological schedule follows.
- Reception windows default to **10° elevation** — these are not horizon AOS/LOS. Use
  `--horizon 0` for the horizon times you'll find in older notes.
- Default minimum peak elevation is 20°. Labels: **Excellent** ≥60°, **Good** ≥40°,
  **Fair** ≥20°, **Low** otherwise. Planning labels, not measured RF ratings.
- Azimuth is clockwise from true north: N=0°, E=90°, S=180°, W=270°.
- Range is distance at the elevation maximum, not an independently minimized distance.
- Elevation and window length predict nothing about SNR, interference, antenna nulls, M2-3 fading or
  transmitter outages.
- Evening passes suit radio and infrared channels. Visible-channel weather imagery
  needs daylight beneath the satellite; use `--rank-by imagery` with a planetary
  ephemeris. This is distinct from `--visible-only`, which seeks a dark observer.

## Local horizon mask (field survey)

`--horizon` and `--min-elevation` assume a flat, unobstructed horizon. If a
tree, roofline or hill blocks part of your sky, survey it once and nextpass
applies that mask to every later run: predicted windows, peaks, fixed-dish
pointing, plots and (where noted) live output all account for it.

**Survey procedure.** Stand at the antenna location. For each obstacle's top
edge, and for each gap between obstacles, read the compass azimuth and the
elevation angle with a level or a phone clinometer app. 8-16 points around
the compass are usually enough to describe a horizon. Note your magnetic
declination beforehand: true azimuth = magnetic azimuth + declination (east
positive) — or set your compass app to true north and skip declination.

Run the interactive survey:

```sh
nextpass --survey-horizon
```

It first asks for the declination (Enter for 0 if your compass already reads
true north), then loops asking for `compass azimuth, obstacle top elevation`
pairs (e.g. `135 22`) until you press Enter on an empty line. It prints an
ASCII elevation-by-azimuth profile and saves the mask into your location file
under the `"horizon"` key. `--survey-horizon` needs no orbital elements or
network access.

Use `--horizon-file mask.json` to store or load the mask from a separate file
instead of the location file — either a JSON list of `{"az", "el"}` points or
an object with a `"horizon"` key. It overrides any `"horizon"` key in the
location file for that run.

Once a mask is present, reported reception windows, peaks and azimuths are
clipped to the samples that clear the mask (not just the flat `--horizon`
elevation); a pass entirely behind an obstacle is dropped. Each affected pass
schedule line adds `clear_minutes` and, when part of the window is
intermittently blocked, a line noting how many minutes were blocked. Sky
plots mark the mask with a dim red `#` line under the track, and `--day-plot`
images shade the blocked zone in grey. Fixed-dish (geostationary) pointing
reports when a satellite is above the geometric horizon but still behind a
surveyed obstacle instead of printing a pointing angle.

### Doppler, live pointing, and ground tracks

```sh
nextpass --satellites M2-4 --frequency 137.9 --track-csv meteor-track.csv
nextpass --satellites M2-4 --live --frequency 137.9
nextpass --satellites M2-4 --live --live-format jsonl
nextpass --satellites M2-4 --ground-track
```

`--frequency` takes a nominal downlink in MHz. Nextpass estimates received Hz
from the changing slant range; it is a first-order Doppler calculation, not an
automatic receiver retune. `--track-csv` samples each reception window every
30 seconds by default (`--track-step` changes the interval). Its azimuth and
elevation columns can be imported by rotor software; nextpass does not send
commands to a rotor. `--live-format jsonl` emits only one JSON object per
satellite and refresh, with time, azimuth, elevation, range, ground position,
footprint radius, and Doppler fields when `--frequency` is set. The ordinary
`--live` mode is a table refreshed until Ctrl-C.

`--ground-track` prints the subpoint and geometric horizon footprint radius at
peak and a small map of the best pass. The footprint is not a terrain or antenna
coverage guarantee. The schedule marks overlapping reception windows on
different satellites to help single-SDR operators choose a target.

## Terminal sky plots and colors

The normal command draws the highest-ranked pass plus a compact daily schedule.

```sh
nextpass --days 3 --plots 3        # draw the three best passes
nextpass --days 3 --plot-rank 2    # draw pass #2 from this run's ranking
nextpass --days 3 --no-plot        # schedule only
nextpass --days 3 --color never    # plain text
nextpass --days 3 --color always | less -R
```

**Anatomy of a plot.** North is up, east is right. The outer circle is the horizon,
inner rings are 30° and 60°, and the center is overhead at 90°. `A` marks the
beginning of the window, `P` the maximum elevation, `B` the end — follow the yellow
`*` track from A to B. With the default 10° window, A and B sit inside the horizon
ring rather than on it. This plot is a static prediction; use `--live` for
current azimuth, elevation and range refreshed in the terminal.

Colors are tuned for a black background: elevation runs bright red (low) → yellow
(moderate) → green (high), describing **geometry, not signal strength**. Each object
keeps a stable color in the schedule, so M2-3 is always cyan and the ISS always green.

Nextpass uses truecolor when `COLORTERM` advertises it, otherwise 256-color ANSI. Color turns itself off when
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

`--recent-reports` adds AMSAT volunteer reception reports from the past 24 hours
for matching satellites. These are separate from SatNOGS transmitter records and
can disagree. A report describes a past observation elsewhere, not current local
reception. Results are cached for one hour; `--offline` uses the cache.

## Orbital-data freshness

Public CelesTrak GP data is downloaded in JSON/OMM format — the modern replacement for
TLE — and propagated with Skyfield/SGP4. Each satellite is cached separately for six
hours. A failed download falls back to a valid cache with an explicit warning; no cache
produces a clear error. Every satellite's epoch is printed and recorded in JSON output.
After a CelesTrak HTTP error, nextpass stops further requests in that run and
uses valid caches where available. It does not automatically retry those errors,
following [CelesTrak's usage policy](https://celestrak.org/usage-policy.php).

Dates more than **7 days** from an epoch warn; more than **14 days** are rejected
unless you pass `--allow-stale`. Those are safeguards, not accuracy guarantees —
refresh close to the pass.

For historical work, supply a CelesTrak-format JSON array:

```sh
nextpass --date 2026-09-21 --days 1 --elements historical-elements.json
```

Objects **absent from that file are skipped with a warning** rather than aborting the
run, so an old two-satellite element file still works against the full built-in
catalog. Pair it with `--satellites` to silence the warnings entirely.

Never use current orbital data for precise predictions months into the past or future;
long-range output under `--allow-stale` is rough planning only.

## Private location

The predictor reads `~/.config/radio/location.json` by default, overridable with
`RADIO_LOCATION_CONFIG` or `--location-config`. The file lives outside the repository
and should be mode `600`. **There is no personal-location fallback in the code** — the
program errors out instead of guessing.

Create the private file from the command line with
`nextpass --save-location --lat LAT --lon LON --altitude METRES --timezone AREA/CITY`.

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

The test suite covers pass-event geometry, calendar-boundary inclusion, DST, filters,
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
