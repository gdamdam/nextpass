import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import macos_reminders


class MacServiceTests(unittest.TestCase):
    def test_install_writes_user_agent_and_starts_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            location = home / '.config' / 'radio' / 'location.json'
            location.parent.mkdir(parents=True)
            location.write_text('{}')
            with patch.object(macos_reminders.sys, 'platform', 'darwin'), \
                 patch.object(macos_reminders.Path, 'home', return_value=home), \
                 patch.object(macos_reminders.subprocess, 'run', return_value=Mock(returncode=0)) as run:
                self.assertEqual(macos_reminders.main(['install']), 0)
            agent = home / 'Library' / 'LaunchAgents' / 'org.nextpass.reminders.plist'
            data = plistlib.loads(agent.read_bytes())
            self.assertTrue(data['RunAtLoad'])
            self.assertIn('--watch', data['ProgramArguments'])
            self.assertTrue(any(call.args[0][1] == 'bootstrap' for call in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
