import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.current_config_store import (
    current_config_path,
    save_current_config,
    save_launch_history_config,
)


class CurrentConfigStoreTest(unittest.TestCase):
    def test_failed_atomic_replace_preserves_the_previous_current_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            game_cfg = {'configs_path': str(Path(temporary_directory) / 'configs')}
            previous = {'Server': {'ServerName': 'previous'}}
            replacement = {'Server': {'ServerName': 'replacement'}}
            save_current_config(game_cfg, 'server1', previous)

            with patch('services.atomic_json_store.os.replace', side_effect=OSError('interrupted')):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    save_current_config(game_cfg, 'server1', replacement)

            path = current_config_path(game_cfg, 'server1')
            self.assertEqual(previous, json.loads(path.read_text(encoding='utf-8')))
            self.assertEqual([], list(path.parent.glob(f'.{path.name}.*.tmp')))

    def test_launch_history_is_idempotent_but_immutable(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            game_cfg = {'configs_path': str(Path(temporary_directory) / 'configs')}
            config = {'Server': {'ServerName': 'attempt-42'}}

            first_path = save_launch_history_config(game_cfg, 42, 'server1', config)
            second_path = save_launch_history_config(game_cfg, 42, 'server1', config)

            self.assertEqual(first_path, second_path)
            with self.assertRaisesRegex(ValueError, 'immuable'):
                save_launch_history_config(
                    game_cfg,
                    42,
                    'server1',
                    {'Server': {'ServerName': 'different'}},
                )
            self.assertEqual(config, json.loads(first_path.read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
