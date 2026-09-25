import re
import unittest
import contextlib
import io
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from terminal_view import Colors, project, sky_plot, render

class TerminalTests(unittest.TestCase):
    def test_long_catalog_label_and_selected_hints(self):
        row = dict(satellite='LONGSATELLITELABEL', norad=99901, rank=1,
                   rise='2026-09-21T00:00:00+00:00', peak='2026-09-21T00:05:00+00:00',
                   set='2026-09-21T00:10:00+00:00', max_elevation_deg=45.0,
                   window_minutes=10.0, rise_azimuth_deg=10, peak_azimuth_deg=90,
                   set_azimuth_deg=170, range_at_peak_km=1000, geometry='Good')
        args = SimpleNamespace(color='never', lat=0, lon=0, altitude=0, timezone='UTC',
                               horizon=10, min_elevation=20, rank_by='elevation', top=1,
                               plots=0, plot_rank=None, ground_track=False, frequency=None)
        sources = [dict(norad=99901, satellite=row['satellite'], epoch_utc='2026-09-21T00:00:00+00:00')]
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('terminal_view.shutil.get_terminal_size', return_value=os.terminal_size((100, 24))):
            render([row], [row], sources, args, datetime.now(timezone.utc),
                   datetime.now(timezone.utc), timezone.utc, {}, None, None,
                   catalog_extra={99901: {'color': (10, 20, 30), 'radio_hint': 'Test downlink 145 MHz.'},
                                  25544: {'radio_hint': 'Unselected hint.'}})
        text = output.getvalue()
        self.assertIn('LONGSATELLITELABEL 00:00:00', text)
        self.assertIn('Test downlink 145 MHz.', ' '.join(text.split()))
        self.assertNotIn('Unselected hint.', text)

    def test_cardinal_projection(self):
        self.assertEqual(project(0,0,20,10),(20,0))
        self.assertEqual(project(90,0,20,10),(40,10))
        self.assertEqual(project(180,0,20,10),(20,20))
        self.assertEqual(project(270,0,20,10),(0,10))
        self.assertEqual(project(120,90,20,10),(20,10))

    def test_color_preserves_plot_alignment_and_markers(self):
        points=[(10,10),(45,40),(90,70),(135,40),(170,10)]
        plain=sky_plot(points,(90,70),57,Colors('never'))
        colored=sky_plot(points,(90,70),57,Colors('always'))
        stripped=re.sub(r'\x1b\[[0-9;]*m','',colored)
        self.assertEqual(plain,stripped)
        self.assertLessEqual(max(map(len,plain.splitlines())),57)
        for marker in 'ABP':
            self.assertEqual(plain.count(marker),1)

    def test_elevation_gradient(self):
        with patch.dict('os.environ', {'COLORTERM': 'truecolor'}):
            colors=Colors('always')
            self.assertIn('255;95;95',colors.elevation('low',0))
            self.assertIn('255;255;95',colors.elevation('mid',45))
            self.assertIn('90;255;95',colors.elevation('high',90))
        with patch.dict('os.environ', {'COLORTERM': ''}):
            self.assertIn('38;5;', Colors('always').elevation('low', 0))
        self.assertEqual(Colors('never').elevation('high',90),'high')
