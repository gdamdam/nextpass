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
<img alt="nextpass v1.4.0" src="https://img.shields.io/badge/nextpass-v1.4.0-0f766e?style=for-the-badge">
<a href="https://github.com/gdamdam/nextpass/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/gdamdam/nextpass/actions/workflows/tests.yml/badge.svg"></a>
<a href="LICENSE"><img alt="GPL-3.0-only" src="https://img.shields.io/badge/license-GPL--3.0--only-blue?style=flat-square"></a>
</p>
<p>
<img alt="Objects" src="https://img.shields.io/badge/objects-8%20tracked-0f766e?style=flat-square">
<img alt="Data" src="https://img.shields.io/badge/data-CelesTrak%20GP%2FOMM-b45309?style=flat-square">
</p>

</div>

---

## ⚡ Quick start

### 1. Get the project

```sh
git clone https://github.com/gdamdam/nextpass.git
cd nextpass
```

### 2. Set your private location

Create `~/.config/radio/location.json` outside the repository, using this structure:

```json
{"lat": 0.0, "lon": 0.0, "altitude": 0, "timezone": "UTC"}
```

Replace the neutral example with your latitude and longitude in degrees, altitude
in metres, and IANA timezone. Restrict access to the file:

```sh
chmod 600 ~/.config/radio/location.json
```

### 3. Predict passes

```sh
./predict.sh --days 7
```

The launcher creates `.venv` and installs dependencies on first use. It then
downloads orbital data and prints your schedule. No personal location is built in.

---

## 🛰 Choose satellites

| Group | Built-in satellites |
|---|---|
| `meteor` | METEOR-M2 3, METEOR-M2 4 |
| `stations` | ISS, CSS |
| `amateur` | AO-73, RS-44, SO-50, AO-123 |

```sh
./predict.sh --satellites meteor --days 3
./predict.sh --satellites iss,m2-4,so-50 --days 3
```

Omit `--satellites` to include all eight. You can also use NORAD IDs or a
[custom catalog](docs/guide.md#extend-the-satellite-catalog).

---

## 🎛 Common tasks

Add these options to `./predict.sh --days 7`:

| Task | Options |
|---|---|
| Find higher passes during convenient hours | `--min-elevation 40 --hours 08:00-22:00` |
| Export a calendar with a 30-minute reminder | `--ics passes.ics --reminder-minutes 30` |
| Export results for other tools | `--json passes.json --csv passes.csv` |
| Show possible visual passes | `--satellites stations --visible-only` |
| Include radio frequency information | `--radio` |
| Use previously cached data without downloads | `--offline` |
| Show the schedule without sky plots | `--no-plot` |

Calendar reminders are delivered by your calendar app after import. Visual-pass
filtering downloads a planetary ephemeris on first use. See all options with
`./predict.sh --help`.

---

## 📖 Read the results

Passes rank by maximum elevation. By default, reception windows start and end at
10° elevation, and only passes peaking at 20° or higher are included.

Predictions describe satellite geometry. They do not guarantee an active
transmitter or a receivable signal. Refresh orbital data with `--refresh` before
an observing session.

**Keep exports private:** coordinates and even pass times can reveal your location.
Keep your location file outside Git; generated files being ignored is only a precaution.

---

## 📚 Learn more

- [Sky plots and output fields](docs/guide.md#reading-the-output)
- [Calendar exports and visual passes](docs/guide.md#calendar-events-and-reminders)
- [Radio metadata](docs/guide.md#optional-radio-metadata) · [Orbital data and caching](docs/guide.md#orbital-data-freshness)
- [Location configuration](docs/guide.md#private-location)
- [Pip installation](docs/guide.md#quickstart) · [Tests and validation](docs/guide.md#validation)

Use [iqscan](https://github.com/gdamdam/iqscan) to inspect the recording afterward.
