"""Plain ASCII terminal views: no terminal escapes or additional dependencies."""
import math
import os
import sys
import shutil
import textwrap
from datetime import datetime


class Colors:
    def __init__(self, mode='auto'):
        self.enabled = mode == 'always' or (mode == 'auto' and sys.stdout.isatty() and 'NO_COLOR' not in os.environ and os.environ.get('TERM') != 'dumb')

    def paint(self, text, rgb, bold=False):
        if not self.enabled:
            return str(text)
        r,g,b = rgb
        return f"\033[{('1;' if bold else '')}38;2;{r};{g};{b}m{text}\033[0m"

    def elevation(self, text, degrees):
        # Bright red -> yellow -> green, all readable against black.
        t = max(0, min(1, degrees/90))
        rgb = (255, round(95+320*t), 95) if t <= .5 else (round(255-330*(t-.5)),255,95)
        return self.paint(text, rgb, True)


CYAN = (100,220,255)
WHITE = (235,240,250)
MUTED = (155,170,190)
YELLOW = (255,215,100)
GREEN = (110,255,140)
PINK = (245,140,255)
# One stable color per catalog label so a bird keeps its color across runs.
SAT_COLORS = {'M2-3': CYAN, 'M2-4': PINK, 'ISS': GREEN, 'CSS': YELLOW,
              'AO-73': (140,200,255), 'RS-44': (255,175,120),
              'SO-50': (180,255,200), 'AO-123': (215,170,255),
              'METOPB': (255,140,140), 'METOPC': (140,255,220), 'GOES18': (255,200,255)}


def project(azimuth, elevation, radius_x, radius_y):
    """North up, east right, zenith at center; linear elevation rings."""
    r = (90 - max(0, min(90, elevation))) / 90
    az = math.radians(azimuth)
    return round(radius_x + r * radius_x * math.sin(az)), round(radius_y - r * radius_y * math.cos(az))


def sky_plot(points, peak, width=57, colors=None):
    colors = colors or Colors("never")
    # Terminal cells are typically about twice as tall as they are wide.
    rx = max(10, min(26, (width - 5) // 2))
    ry = rx // 2
    grid = [[' ']*(2*rx+1) for _ in range(2*ry+1)]
    for y in range(2*ry+1):
        for x in range(2*rx+1):
            radius = math.hypot((x-rx)/rx, (y-ry)/ry)
            if any(abs(radius-ring) < .025 for ring in (1, 2/3, 1/3)):
                grid[y][x] = '.'
            elif radius < 1 and (x == rx or y == ry):
                grid[y][x] = '|' if x == rx else '-'
    grid[ry][rx] = '+'
    coords = [project(az, el, rx, ry) for az, el in points]
    for a, b in zip(coords, coords[1:]):
        steps = max(abs(a[0]-b[0]), abs(a[1]-b[1]), 1)
        for i in range(steps+1):
            x = round(a[0]+(b[0]-a[0])*i/steps)
            y = round(a[1]+(b[1]-a[1])*i/steps)
            grid[y][x] = '*'
    for symbol, point in [('A',coords[0]),('B',coords[-1]),('P',project(*peak,rx,ry))]:
        grid[point[1]][point[0]] = symbol
    lines = [' '*(rx+2)+'N']
    for y, row in enumerate(grid):
        lines.append(('W ' if y == ry else '  ') + ''.join(row) + (' E' if y == ry else ''))
    lines.append(' '*(rx+2)+'S')
    palette = {'.':(95,135,180), '|':(85,110,145), '-':(85,110,145), '+':WHITE,
               '*':YELLOW, 'A':CYAN, 'B':PINK, 'P':GREEN, 'N':WHITE, 'E':WHITE, 'S':WHITE, 'W':WHITE}
    return '\n'.join(''.join(colors.paint(ch,palette[ch],ch in 'ABP') if ch in palette else ch for ch in line.rstrip()) for line in lines)


def stamp(row, key, tz):
    return datetime.fromisoformat(row[key]).astimezone(tz)


def render(rows, ranked, sources, args, start, end, tz, satellites, observer, ts, radio=None,
           stationary=()):
    width = max(40, min(100, shutil.get_terminal_size((80,24)).columns))
    colors = Colors(args.color)
    def paragraph(text, rgb=None):
        wrapped = textwrap.fill(text, width=width)
        print(colors.paint(wrapped,rgb) if rgb else wrapped)
    def heading(text):
        print(colors.paint(text,CYAN,True))
    heading('\nNEXTPASS - SATELLITE PASS PLANNER')
    print(colors.paint('='*min(width,78),MUTED))
    paragraph(f'{args.lat:.3f}, {args.lon:.3f} | {args.altitude:g} m | {args.timezone}')
    paragraph(f'{start:%Y-%m-%d %H:%M %Z} -> {end:%Y-%m-%d %H:%M %Z}')
    paragraph(f'Windows above {args.horizon:g} deg; peak >= {args.min_elevation:g} deg. Ranked by geometry, not guaranteed signal strength.')
    heading('\nBEST OPPORTUNITIES')
    paragraph('Elevation: red = low | yellow = moderate | green = high', MUTED)
    for r in ranked[:args.top]:
        peak = stamp(r,'peak',tz)
        paragraph(f"#{r['rank']}  {r['satellite']}  {peak:%a %b %d, %H:%M:%S %Z}")
        detail = f"    Peak {r['max_elevation_deg']:.1f} deg | {r['geometry']} | range {r['range_at_peak_km']:.0f} km"
        wrapped = textwrap.fill(detail,width=width)
        value = f"{r['max_elevation_deg']:.1f} deg"
        print(wrapped.replace(value, colors.elevation(value,r['max_elevation_deg'])).replace(r['geometry'], colors.elevation(r['geometry'],r['max_elevation_deg'])))
    heading('\nPASS SCHEDULE (local time; rank # matches plots)')
    last_day = None
    for r in rows:
        peak = stamp(r,'peak',tz)
        day = peak.strftime('%A %Y-%m-%d')
        if day != last_day:
            print(colors.paint('\n'+day,WHITE,True))
            if width >= 76:
                print(colors.paint('  # Sat     Start     Peak      End        Elev   Window  Direction',MUTED))
            last_day = day
        a,b = stamp(r,'rise',tz),stamp(r,'set',tz)
        from meteor_passes import direction
        path = f"{direction(r['rise_azimuth_deg'])}>{direction(r['peak_azimuth_deg'])}>{direction(r['set_azimuth_deg'])}"
        if width >= 76:
            el = colors.elevation(f"{r['max_elevation_deg']:5.1f}",r['max_elevation_deg'])
            satellite = colors.paint(f"{r['satellite']:<6}", SAT_COLORS.get(r['satellite'], WHITE))
            print(f"{r['rank']:3} {satellite} {a:%H:%M:%S}  {peak:%H:%M:%S}  {b:%H:%M:%S}  {el}  {r['window_minutes']:5.1f}m  {path}")
        else:
            line = textwrap.fill(f"#{r['rank']} {r['satellite']} | peak {peak:%H:%M:%S %Z} | {r['max_elevation_deg']:.1f} deg", width=width)
            value = f"{r['max_elevation_deg']:.1f} deg"
            print(line.replace(value,colors.elevation(value,r['max_elevation_deg'])))
            paragraph(f"  {a:%H:%M:%S} -> {b:%H:%M:%S} | {r['window_minutes']:.1f} min | {path}")
        if 'visible_at_peak' in r:
            paragraph(f"  At peak: satellite {'sunlit' if r['satellite_sunlit_at_peak'] else 'in shadow'}; Sun {r['sun_altitude_at_peak_deg']:.1f} deg; visual candidate {'yes' if r['visible_at_peak'] else 'no'}.")
        if a.date()!=peak.date() or b.date()!=peak.date() or a.utcoffset()!=b.utcoffset():
            paragraph(f'  Full window: {a:%Y-%m-%d %H:%M:%S %Z} -> {b:%Y-%m-%d %H:%M:%S %Z}')
    if not rows and not stationary:
        paragraph('No matching passes. Try a longer range or lower minimum elevation.')
    if stationary:
        from meteor_passes import direction
        heading('\nFIXED-POSITION (GEOSTATIONARY) SATELLITES')
        for g in stationary:
            lon = g['subsatellite_longitude_deg']
            paragraph(f"{g['satellite']} is geostationary: it circles the Earth once a day above the "
                      f"equator at {abs(lon):.1f} deg {'W' if lon < 0 else 'E'}, so it does not move across "
                      "your sky and has no passes. Aim a fixed antenna once and leave it.")
            if g['above_horizon']:
                paragraph(f"  Point at azimuth {g['azimuth_deg']:.1f} deg ({direction(g['azimuth_deg'])}), "
                          f"elevation {g['elevation_deg']:.1f} deg; range {g['range_km']:.0f} km.")
                if args.plots:
                    # One-point path: sky_plot draws A, B and P on the same cell, leaving P.
                    position = (g['azimuth_deg'], g['elevation_deg'])
                    print(sky_plot([position], position, min(width,57), colors))
                    paragraph('P = fixed position. North up; east right. Rings: 0 / 30 / 60 deg; center: 90 deg (overhead).')
            else:
                paragraph(f"  Below your horizon (elevation {g['elevation_deg']:.1f} deg): not receivable from this location.")
    selected = [r for r in ranked if r['rank']==args.plot_rank] if args.plot_rank else ranked[:args.plots]
    if args.plot_rank and not selected:
        paragraph(f'No pass with rank #{args.plot_rank} in this result.')
    for r in selected:
        print(colors.paint('\n'+'-'*min(width,78),MUTED))
        paragraph(f"SKY PATH #{r['rank']} | {r['satellite']} | {stamp(r,'peak',tz):%a %Y-%m-%d %H:%M:%S %Z}")
        sat = satellites[r['norad']]
        from meteor_passes import sample_track
        az, alt = sample_track(sat, observer, ts, r['rise'], r['set'])
        print(sky_plot(list(zip(az,alt)),(r['peak_azimuth_deg'],r['max_elevation_deg']),min(width,57),colors))
        paragraph('A = start  ->  * = predicted path  ->  B = end; P = peak')
        paragraph('North up; east right. Rings: 0 / 30 / 60 deg; center: 90 deg (overhead). Static forecast, not live tracking.')
        for label,key,azkey in [('A','rise','rise_azimuth_deg'),('P','peak','peak_azimuth_deg'),('B','set','set_azimuth_deg')]:
            paragraph(f"{label}  {stamp(r,key,tz):%H:%M:%S %Z}  az {r[azkey]:.1f} deg {direction(r[azkey])}")
    heading('\nORBITAL DATA')
    for s in sources:
        paragraph(f"{s['satellite']} epoch: {s['epoch_utc']} (UTC)")
    if radio is not None and radio.get('status') == 'unavailable':
        paragraph('Radio metadata unavailable; geometric predictions are unaffected.')
    if radio is not None and radio.get('status') != 'unavailable':
        heading('\nRADIO CATALOG (PUBLISHED DATA; NOT LIVE STATUS)')
        if radio.get('band_mhz'):
            paragraph(f"Downlinks overlapping {radio['band_mhz'][0]:g}-{radio['band_mhz'][1]:g} MHz")
        for norad, records in radio.get('satellites', {}).items():
            label = next((s['satellite'] for s in sources if str(s['norad']) == str(norad)), str(norad))
            if not records:
                info = radio.get('availability', {}).get(str(norad), {})
                status = info.get('status', 'unavailable')
                fetched = f"; fetched {info['fetched_at_utc']}" if info.get('fetched_at_utc') else ''
                paragraph(f'{label}: ' + ('catalog has no transmitter records' if status == 'empty' else 'no downlinks match the requested band' if status == 'filtered' else 'radio metadata unavailable') + fetched)
                continue
            paragraph(f'{label}:')
            for tx in records:
                low, high = tx.get('downlink_low_hz'), tx.get('downlink_high_hz')
                if low is None:
                    frequency = 'frequency unknown'
                elif low == high:
                    frequency = f'{low / 1_000_000:g} MHz'
                else:
                    frequency = f'{low / 1_000_000:g}-{high / 1_000_000:g} MHz'
                baud = tx.get('baud')
                baud_text = 'baud unknown' if baud is None else f'{baud:g} baud'
                description = tx.get('description', 'unknown')
                catalog_status = tx.get('catalog_transmitter_status', 'unknown')
                fetched = tx.get('fetched_at_utc', radio.get('fetched_at_utc', 'unknown'))
                transmitter_id = tx.get('transmitter_id', 'unknown')
                paragraph(f"  {transmitter_id} {description} | {frequency} | mode {tx.get('expected_mode', 'unknown')} | {baud_text} | protocol {tx.get('protocol', 'unknown')} | catalog status {catalog_status} | fetched {fetched} | published catalog; not live")
        paragraph(f"Source: {radio.get('attribution', 'radio catalog')}; license: {radio.get('license', 'unknown')}. Catalog data is not a live transmitter claim.")
    paragraph('Verify active transmitter frequency/mode against AMSAT or SatNOGS before the pass (METEOR LRPT starting tune: 137.900 MHz / 72k). Refresh orbital data before receiving.')
    paragraph('Use --plots 3 for more sky paths; --plot-rank 2 for a specific ranked pass; --no-plot for schedule only.')
