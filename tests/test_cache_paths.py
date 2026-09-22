import os
import unittest
from pathlib import Path
from unittest.mock import patch

import meteor_passes as app


class CachePathTests(unittest.TestCase):
    def test_xdg_cache_home_is_namespaced_for_nextpass(self):
        with patch.dict(os.environ, {'XDG_CACHE_HOME': '/tmp/test-xdg-cache'}):
            self.assertEqual(app.default_cache_dir(), Path('/tmp/test-xdg-cache/nextpass'))
            self.assertEqual(app.parser().parse_args([]).cache_dir,
                             Path('/tmp/test-xdg-cache/nextpass'))

    def test_missing_xdg_cache_home_uses_user_cache(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'home', return_value=Path('/tmp/test-home')):
            self.assertEqual(app.default_cache_dir(), Path('/tmp/test-home/.cache/nextpass'))
            self.assertEqual(app.parser().parse_args([]).cache_dir,
                             Path('/tmp/test-home/.cache/nextpass'))

