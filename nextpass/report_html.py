"""Self-contained HTML pass report for sharing and saving on a phone.

Charts are inline SVG built here so the report needs no plotting library and
opens offline in any browser; the browser's own "Save as PDF" covers print.
"""
import math
from datetime import datetime
from html import escape

CSS = """
:root{--bg:#f8fafc;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;
--grid:#cbd5e1;--track:#087e8b;--mask:#94a3b8;--low:#dc2626;--mid:#ca8a04;--high:#16a34a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b1120;--card:#111827;
--ink:#e5e7eb;--muted:#94a3b8;--line:#1f2937;--grid:#334155;--track:#2dd4bf;--mask:#475569;
--low:#f87171;--mid:#facc15;--high:#4ade80}}
:root[data-theme="dark"]{--bg:#0b1120;--card:#111827;--ink:#e5e7eb;--muted:#94a3b8;--line:#1f2937;
--grid:#334155;--track:#2dd4bf;--mask:#475569;--low:#f87171;--mid:#facc15;--high:#4ade80}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.1rem;margin:1.6em 0 .6em}
.muted{color:var(--muted);font-size:.88rem}
.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
.card h3{margin:0 0 .2em;font-size:1rem}
.card svg{display:block;width:100%;max-width:300px;margin:6px auto}
dl{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:.4em 0;font-size:.9rem}
dt{color:var(--muted)}dd{margin:0;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:12px}
table{border-collapse:collapse;width:100%;font-size:.88rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 5px;text-align:left;white-space:nowrap;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600}tr.day td{font-weight:700;background:var(--bg)}
.low{color:var(--low)}.mid{color:var(--mid)}.high{color:var(--high)}
.note{font-size:.85rem;color:var(--muted);margin:.3em 0}
svg .grid{fill:none;stroke:var(--grid)}svg .lbl{fill:var(--muted);font-size:11px}
svg .mask{fill:var(--mask);opacity:.5}svg .trk{fill:none;stroke:var(--track);stroke-width:2.5}
svg .pt{fill:var(--track)}
@media print{body{background:#fff}.card,.scroll{break-inside:avoid;border-color:#ccc}}
"""

SIZE, CENTER, RADIUS = 260, 130, 110


def _xy(azimuth, elevation):
    r = (90 - max(0.0, min(90.0, float(elevation)))) / 90 * RADIUS
    a = math.radians(float(azimuth))
    return CENTER + r * math.sin(a), CENTER - r * math.cos(a)


def _points(pairs):
    return ' '.join(f'{x:.1f},{y:.1f}' for x, y in (_xy(a, e) for a, e in pairs))


def sky_svg(az, alt, peak, mask=None):
    """Polar sky chart: north up, east right, horizon on the rim, zenith at centre."""
    parts = [f'<svg viewBox="0 0 {SIZE} {SIZE}" role="img" aria-label="Sky path">',
             '<defs><marker id="arr" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="5" '
             'markerHeight="5" orient="auto"><path d="M0,0L10,5L0,10z" class="pt"/></marker></defs>']
    if mask:
        from nextpass.horizon import mask_elevation
        # Even-odd fill between the rim and the mask profile shades obstacles.
        rim = ' '.join(f'{x:.1f},{y:.1f}' for x, y in (_xy(a, 0) for a in range(0, 360, 2)))
        inner = _points((a, mask_elevation(mask, a)) for a in range(0, 360, 2))
        parts.append(f'<path class="mask" fill-rule="evenodd" d="M{rim}Z M{inner}Z"/>')
    for elevation in (0, 30, 60):
        parts.append(f'<circle class="grid" cx="{CENTER}" cy="{CENTER}" r="{(90 - elevation) / 90 * RADIUS:.1f}"/>')
    parts.append(f'<path class="grid" d="M{CENTER - RADIUS},{CENTER}H{CENTER + RADIUS}M{CENTER},{CENTER - RADIUS}V{CENTER + RADIUS}"/>')
    for label, x, y in (('N', CENTER, 12), ('E', SIZE - 8, CENTER + 4), ('S', CENTER, SIZE - 3), ('W', 8, CENTER + 4)):
        parts.append(f'<text class="lbl" x="{x}" y="{y}" text-anchor="middle">{label}</text>')
    for elevation in (30, 60):
        x, y = _xy(135, elevation)
        parts.append(f'<text class="lbl" x="{x + 3:.1f}" y="{y:.1f}">{elevation}°</text>')
    pairs = list(zip(az, alt))
    if pairs:
        half = max(1, len(pairs) // 2)
        # Split at the midpoint so the arrowhead shows travel direction.
        parts.append(f'<polyline class="trk" marker-end="url(#arr)" points="{_points(pairs[:half + 1])}"/>')
        parts.append(f'<polyline class="trk" points="{_points(pairs[half:])}"/>')
        x, y = _xy(*pairs[0])
        parts.append(f'<circle class="pt" cx="{x:.1f}" cy="{y:.1f}" r="4.5"/>')
        x, y = _xy(*pairs[-1])
        parts.append(f'<rect class="pt" x="{x - 4:.1f}" y="{y - 4:.1f}" width="8" height="8"/>')
    x, y = _xy(*peak)
    parts.append(f'<text class="pt" x="{x:.1f}" y="{y + 6:.1f}" text-anchor="middle" font-size="18">★</text>')
    parts.append('</svg>')
    return ''.join(parts)


def _level(elevation):
    return 'low' if elevation < 30 else 'mid' if elevation < 60 else 'high'


def _local(row, key, tz):
    return datetime.fromisoformat(row[key]).astimezone(tz)


def _card(row, tz, satellites, observer, ts, args, mask):
    from nextpass.meteor_passes import direction, sample_track
    rise, peak, end = (_local(row, k, tz) for k in ('rise', 'peak', 'set'))
    az, alt = sample_track(satellites[row['norad']], observer, ts, row['rise'], row['set'])
    elevation = row['max_elevation_deg']
    items = [
        ('Start', f"{rise:%H:%M:%S} · {row['rise_azimuth_deg']:.0f}° {direction(row['rise_azimuth_deg'])}"),
        ('Peak', f"{peak:%H:%M:%S} · {row['peak_azimuth_deg']:.0f}° {direction(row['peak_azimuth_deg'])}"),
        ('End', f"{end:%H:%M:%S} · {row['set_azimuth_deg']:.0f}° {direction(row['set_azimuth_deg'])}"),
        ('Window', f"{row['window_minutes']:.1f} min"),
        ('Range', f"{row['range_at_peak_km']:.0f} km at peak"),
    ]
    if 'visible_at_peak' in row:
        visible = row.get('visible_during_pass', row['visible_at_peak'])
        visual = 'candidate' if visible else 'no'
        if visible and row.get('visual_candidate_start') and row.get('visual_candidate_end'):
            candidate_start = _local(row, 'visual_candidate_start', tz)
            candidate_end = _local(row, 'visual_candidate_end', tz)
            visual += f' ({candidate_start:%H:%M}–{candidate_end:%H:%M})'
        items.append(('Visual', visual))
    if 'daylight_ground_track_minutes' in row:
        items.append(('Daylit track', f"{row['daylight_ground_track_minutes']:.1f} min"))
    if args.frequency is not None and row.get('doppler_schedule_hz'):
        # Offsets from nominal are what you actually dial in; absolute Hz is unreadable.
        s = {k: round((v - args.frequency * 1e6) / 1e3, 1) + 0.0 for k, v in row['doppler_schedule_hz'].items()}
        items.append((f'{args.frequency:g} MHz', f"{s['rise']:+.1f} / {s['peak']:+.1f} / {s['set']:+.1f} kHz"))
    if row.get('horizon_mask') and row.get('blocked_minutes', 0) > 0:
        items.append(('Blocked', f"{row['blocked_minutes']:.1f} min by local horizon"))
    if row.get('overlaps'):
        items.append(('Overlaps', ', '.join(row['overlaps'])))
    body = ''.join(f'<dt>{escape(k)}</dt><dd>{escape(v)}</dd>' for k, v in items)
    return (f'<article class="card"><h3>#{row["rank"]} {escape(row["satellite"])}</h3>'
            f'<div class="muted">{peak:%a %d %b %Y} · peak <span class="{_level(elevation)}">{elevation:.1f}°</span>'
            f' · {escape(row["geometry"])}</div>'
            + sky_svg(az, alt, (row['peak_azimuth_deg'], elevation), mask)
            + f'<dl>{body}</dl></article>')


def _schedule(rows, tz):
    from nextpass.meteor_passes import direction
    out = ['<div class="scroll"><table><thead><tr><th>#</th><th>Sat</th><th>Start</th>'
           '<th>Peak</th><th>End</th><th>Elev</th><th>Min</th><th>Path</th></tr></thead><tbody>']
    last_day = None
    for row in rows:
        rise, peak, end = (_local(row, k, tz) for k in ('rise', 'peak', 'set'))
        day = f'{peak:%A %Y-%m-%d}'
        if day != last_day:
            out.append(f'<tr class="day"><td colspan="8">{day}</td></tr>')
            last_day = day
        path = '›'.join(direction(row[k]) for k in ('rise_azimuth_deg', 'peak_azimuth_deg', 'set_azimuth_deg'))
        elevation = row['max_elevation_deg']
        out.append(f'<tr><td>{row["rank"]}</td><td>{escape(row["satellite"])}</td><td>{rise:%H:%M}</td>'
                   f'<td>{peak:%H:%M}</td><td>{end:%H:%M}</td>'
                   f'<td class="{_level(elevation)}">{elevation:.1f}°</td><td>{row["window_minutes"]:.1f}</td>'
                   f'<td>{path}</td></tr>')
    out.append('</tbody></table></div>')
    return ''.join(out)


def _radio(radio, sources):
    if not radio or radio.get('status') == 'unavailable':
        return ''
    out = ['<h2>Radio catalog</h2><p class="note">Published SatNOGS data, not live transmitter status.</p>']
    for norad, records in radio.get('satellites', {}).items():
        label = next((s['satellite'] for s in sources if str(s['norad']) == str(norad)), str(norad))
        lines = []
        for tx in records:
            low, high = tx.get('downlink_low_hz'), tx.get('downlink_high_hz')
            freq = ('frequency unknown' if low is None else f'{low / 1e6:g} MHz' if low == high
                    else f'{low / 1e6:g}-{high / 1e6:g} MHz')
            lines.append(f"<li>{escape(freq)} · {escape(str(tx.get('expected_mode', 'unknown')))} · "
                         f"{escape(str(tx.get('description', '')))}</li>")
        out.append(f'<p><strong>{escape(label)}</strong></p><ul>{"".join(lines) or "<li>No matching downlinks</li>"}</ul>')
    return ''.join(out)


def write_report(path, rows, ranked, sources, args, start, end, tz, satellites, observer, ts,
                 radio=None, stationary=(), mask=None):
    from nextpass.version import APP_VERSION
    names = ', '.join(dict.fromkeys(s['satellite'] for s in sources)) or 'No satellites'
    mask_note = f' Local horizon mask: {len(mask)} survey points, shaded grey.' if mask else ''
    top = ranked[:args.top]
    html = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>NextPass {start:%Y-%m-%d}</title><style>{CSS}</style></head><body><main>',
        f'<h1>NextPass · {escape(names)}</h1>',
        f'<p class="muted">{args.lat:.3f}, {args.lon:.3f} · {args.altitude:g} m · {escape(args.timezone)}<br>'
        f'{start:%Y-%m-%d %H:%M %Z} → {end:%Y-%m-%d %H:%M %Z}<br>'
        f'Windows above {args.horizon:g}°, peak ≥ {args.min_elevation:g}°, ranked by {escape(args.rank_by)}.'
        f'{escape(mask_note)}</p>',
    ]
    if top:
        html.append(f'<h2>Top {len(top)} passes</h2><p class="note">● start · → direction · ★ peak · ■ end. '
                    'North up, east right. Rim is the horizon, centre is overhead.</p><div class="cards">')
        html += [_card(row, tz, satellites, observer, ts, args, mask) for row in top]
        html.append('</div>')
    html.append('<h2>All passes (local time)</h2><p class="note">Times truncated to the minute; the top-pass cards show seconds and azimuths.</p>')
    html.append(_schedule(rows, tz) if rows else '<p>No matching passes.</p>')
    if stationary:
        html.append('<h2>Fixed-position satellites</h2><ul>')
        for g in stationary:
            where = (f"azimuth {g['azimuth_deg']:.1f}°, elevation {g['elevation_deg']:.1f}°" if g['above_horizon']
                     else 'behind a surveyed obstacle' if g.get('blocked_by_horizon_mask') else 'below your horizon')
            html.append(f"<li>{escape(g['satellite'])}: {where}</li>")
        html.append('</ul>')
    html.append(_radio(radio, sources))
    epochs = ' · '.join(f"{escape(s['satellite'])} {escape(s['epoch_utc'])}" for s in sources)
    html.append(f'<p class="note">Orbital epochs (UTC): {epochs}</p>'
                '<p class="note">Geometric prediction, not signal strength. Refresh orbital data and verify '
                f'transmitter frequency before the pass. Generated by nextpass {APP_VERSION}.</p>')
    html.append('</main></body></html>\n')
    path.write_text(''.join(html), encoding='utf-8')
