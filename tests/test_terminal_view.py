import re
import unittest
from terminal_view import Colors, project, sky_plot

class TerminalTests(unittest.TestCase):
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
        for marker in 'ABP': self.assertEqual(plain.count(marker),1)

    def test_elevation_gradient(self):
        colors=Colors('always')
        self.assertIn('255;95;95',colors.elevation('low',0))
        self.assertIn('255;255;95',colors.elevation('mid',45))
        self.assertIn('90;255;95',colors.elevation('high',90))
        self.assertEqual(Colors('never').elevation('high',90),'high')
