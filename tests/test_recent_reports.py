import json
import tempfile
import unittest
from pathlib import Path

from recent_reports import load_recent_reports


class RecentReportsTests(unittest.TestCase):
    def test_offline_cache_matches_base_label_and_preserves_report_status(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'amsat-reports.json').write_text(json.dumps({'data': [
                {'name': 'SO-50_[FM]', 'report': 'Heard', 'report_count': 3},
                {'name': 'OTHER_[FM]', 'report': 'Not Heard', 'report_count': 1},
            ]}))
            reports = load_recent_reports(['SO-50', 'AO-73'], directory, offline=True)
        self.assertEqual(reports['satellites']['SO-50'][0]['report'], 'Heard')
        self.assertNotIn('OTHER', reports['satellites'])
        self.assertNotIn('AO-73', reports['satellites'])


if __name__ == '__main__':
    unittest.main()
