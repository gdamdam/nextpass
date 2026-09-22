<div align="center">

```
 ███╗   ██╗███████╗██╗  ██╗████████╗██████╗  █████╗ ███████╗███████╗
 ████╗  ██║██╔════╝╚██╗██╔╝╚══██╔══╝██╔══██╗██╔══██╗██╔════╝██╔════╝
 ██╔██╗ ██║█████╗   ╚███╔╝    ██║   ██████╔╝███████║███████╗███████╗
 ██║╚██╗██║██╔══╝   ██╔██╗    ██║   ██╔═══╝ ██╔══██║╚════██║╚════██║
 ██║ ╚████║███████╗██╔╝ ██╗   ██║   ██║     ██║  ██║███████║███████║
 ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═╝     ╚═╝  ╚═╝╚══════╝╚══════╝
```

### Know when to point the antenna up.

Pass prediction for weather birds, space stations and amateur satellites —
ranked by geometry, drawn as sky plots in your terminal, with your coordinates
kept entirely outside the repository.

<p>
<img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-1f6feb?style=for-the-badge&logo=python&logoColor=white">
<img alt="Skyfield 1.55" src="https://img.shields.io/badge/skyfield-1.55%20·%20SGP4-7c3aed?style=for-the-badge">
<img alt="nextpass v1.2.0" src="https://img.shields.io/badge/nextpass-v1.2.0-0f766e?style=for-the-badge">
<img alt="21 tests passing" src="https://img.shields.io/badge/tests-21%20passing-2ea043?style=for-the-badge">
</p>
<p>
<img alt="Objects" src="https://img.shields.io/badge/objects-8%20tracked-0f766e?style=flat-square">
<img alt="Data" src="https://img.shields.io/badge/data-CelesTrak%20GP%2FOMM-b45309?style=flat-square">
<img alt="Output" src="https://img.shields.io/badge/output-ANSI%20sky%20plots%20·%20JSON%20·%20CSV-334155?style=flat-square">
<img alt="Coordinates" src="https://img.shields.io/badge/coordinates-never%20in%20this%20repo-be123c?style=flat-square">
</p>

</div>

---

## ⚡ Quickstart

```sh
git clone https://github.com/gdamdam/nextpass.git
cd nextpass
./predict.sh --days 7
```

Python 3.9+. On first use the launcher builds `.venv` and installs Skyfield; the
first run also downloads orbital data. You'll get a ranked list of opportunities, a
day-by-day schedule, and a sky plot of the best pass.

> [!IMPORTANT]
> There is **no location in the code**. Create `~/.config/radio/location.json`
> (mode `600`, outside this repository) before the first run — see
> [Private location](#-private-location) below.

---

## 🛰 What it tracks

Eight objects, in three groups. NORAD IDs were verified against the live CelesTrak
catalog on 2026-09-22.

| Label | Object | NORAD | Group | Why you'd chase it |
|---|---|---|---|---|
| `M2-3` | METEOR-M2 3 | 57166 | `meteor` | LRPT weather imagery, 137.900 MHz / 72k |
| `M2-4` | METEOR-M2 4 | 59051 | `meteor` | LRPT weather imagery, the healthier of the pair |
| `ISS` | ISS (ZARYA) | 25544 | `stations` | SSTV events and APRS digipeater on 2 m; brightest thing in the sky |
| `CSS` | CSS (TIANHE) | 48274 | `stations` | Chinese space station — visual spotting, occasional SSTV |
| `AO-73` | FUNCUBE-1 | 39444 | `amateur` | BPSK telemetry beacon + SSB/CW linear transponder |
| `RS-44` | RS-44 (DOSAAF-85) | 44909 | `amateur` | Excellent high-orbit linear transponder, long passes |
| `SO-50` | SAUDISAT 1C | 27607 | `amateur` | The classic easy FM repeater bird |
| `AO-123` | ASRTU-1 | 61781 | `amateur` | V/U transponder and image downlink |

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
all eight.

---

## 🎛 Everyday commands

```sh
./predict.sh --date 2026-09-23 --days 3                          # fixed start date
./predict.sh --days 7 --min-elevation 40 --hours 08:00-22:00 --top 5
./predict.sh --days 7 --json passes.json --csv passes.csv        # export
./predict.sh --days 3 --horizon 0                                # geometric AOS/LOS
./predict.sh --days 3 --refresh                                  # force fresh orbits
./predict.sh --days 3 --offline                                  # use cache only
./predict.sh --help
```

Without `--date` the interval runs from now to the same local time N days later. With
`--date` it starts at local midnight and covers N calendar dates. Daylight-saving is
handled by your timezone. Passes are included by **peak** time, so a window may begin
before or end after the requested interval — `--hours` filters on peak time too, and
overnight ranges like `20:00-06:00` work.

---

## 📖 Reading the output

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

<details>
<summary><b>🌌 Terminal sky plots and colors</b></summary>

<br>

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

</details>

<details>
<summary><b>🕒 Orbital-data freshness</b></summary>

<br>

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
run, so an old two-satellite element file still works against the full eight-object
catalog. Pair it with `--satellites` to silence the warnings entirely.

Never use current orbital data for precise predictions months into the past or future;
long-range output under `--allow-stale` is rough planning only.

</details>

<details>
<summary><b>🔒 Private location</b></summary>

<br>

The predictor reads `~/.config/radio/location.json` by default, overridable with
`RADIO_LOCATION_CONFIG` or `--location-config`. The file lives outside the repository
and should be mode `600`. **There is no personal-location fallback in the code** — the
program errors out instead of guessing.

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

</details>

---

## 🔬 Validation

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Twenty-one tests cover pass-event geometry, calendar-boundary inclusion, DST, filters,
exports, satellite selection, OMM validation, cache recovery, element-file skipping,
concurrent refreshes and stale-data rejection, with no network access. Geometry tests
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

## 📡 Related

| | |
|---|---|
| [iqscan](https://github.com/gdamdam/iqscan) | Scan the recording you just made for activity, with an interactive offline report |
| `examples/` | Public orbital elements used by tests; no personal prediction results |

Sources: [Skyfield](https://rhodesmill.org/skyfield/earth-satellites.html) ·
[PyEphem quick reference](https://rhodesmill.org/pyephem/quick.html) ·
[CelesTrak GP formats](https://celestrak.org/NORAD/documentation/gp-data-formats.php) ·
[AMSAT status](https://www.amsat.org/status/) ·
[SatNOGS DB](https://db.satnogs.org/)
