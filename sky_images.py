"""Optional, headless daily sky-path image export."""
import math
from datetime import datetime


def require_matplotlib():
    try:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    except ImportError as exc:
        raise ValueError('Image export requires Matplotlib. Install: python3 -m pip install "nextpass[plots]" (or ".[plots]" from the project directory)') from exc
    return Figure, FigureCanvasAgg


def save_day_plot(rows, satellites, observer, ts, tz, day, path):
    Figure, Canvas = require_matplotlib()
    columns = min(3, max(1, len(rows)))
    nrows = max(1, math.ceil(len(rows) / columns))
    fig = Figure(figsize=(5 * columns, 5.4 * nrows + 1.5), facecolor='white')
    Canvas(fig)
    sat = next(iter(satellites.values()))
    label = rows[0]['satellite'] if rows else sat.name
    fig.suptitle(f'{label} · {day:%Y-%m-%d}', fontsize=20, y=.985)
    fig.text(.5, .95, f'All passes · {tz.key} · North up / east right', ha='center', fontsize=11)
    for index, row in enumerate(rows):
        ax = fig.add_subplot(nrows, columns, index + 1, projection='polar')
        moments = [datetime.fromisoformat(row[k]).astimezone(tz) for k in ('rise', 'peak', 'set')]
        start, peak, end = moments
        times = ts.linspace(ts.from_datetime(start), ts.from_datetime(end), 241)
        alt, az, _ = (satellites[row['norad']] - observer).at(times).altaz()
        theta = [math.radians(float(a)) for a in az.degrees]
        radius = [90 - max(0, min(90, float(a))) for a in alt.degrees]
        color = '#087e8b'
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_ylim(0, 90)
        ax.set_xticks([math.radians(a) for a in range(0, 360, 45)], ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'])
        ax.set_yticks([30, 60, 90], ['60°', '30°', '0°'])
        ax.set_rlabel_position(135)
        ax.grid(color='#cbd5e1', linewidth=.8)
        ax.spines['polar'].set_color('#94a3b8')
        ax.plot(theta, radius, color=color, linewidth=2.5)
        for i in (60, 170):
            ax.annotate('', xy=(theta[i+6], radius[i+6]), xytext=(theta[i], radius[i]), arrowprops=dict(arrowstyle='->', color=color, lw=2))
        for i, marker in ((0, 'o'), (-1, 's')):
            ax.scatter(theta[i], radius[i], s=45, marker=marker, color=color, zorder=5, clip_on=False)
        ax.scatter(math.radians(row['peak_azimuth_deg']), 90-row['max_elevation_deg'], marker='*', s=110, color=color, zorder=6)
        ax.set_title(f"Pass {index+1} · peak {row['max_elevation_deg']:.1f}°\n{peak:%H:%M:%S %Z}", fontsize=12, pad=23)
        # Dates on boundaries prevent ambiguous midnight or DST-crossing windows.
        fmt = '%H:%M:%S %Z' if start.date() == end.date() == peak.date() else '%m-%d %H:%M:%S %Z'
        ax.text(.5, -.19, f'● Rise {start.strftime(fmt)}\n■ Set  {end.strftime(fmt)}', transform=ax.transAxes, ha='center', fontsize=10)
    if not rows:
        fig.text(.5, .5, 'No above-horizon passes with a peak on this local date.', ha='center', fontsize=12)
    fig.text(.5, .055, '● Rise   → Travel direction   ★ Peak   ■ Set\nOuter ring: horizon (0°) · Centre: overhead (90°)', ha='center', fontsize=10)
    fig.text(.5, .015, f'Orbital epoch: {sat.epoch.utc_datetime():%Y-%m-%d %H:%M UTC} · Geometric prediction, not signal strength', ha='center', fontsize=9, color='#475569')
    fig.subplots_adjust(top=1-1.9/(5.4*nrows+1.5), bottom=1.7/(5.4*nrows+1.5), left=.07, right=.93, hspace=.65, wspace=.35)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format=path.suffix.lower()[1:], dpi=170, facecolor='white')
    fig.clear()
