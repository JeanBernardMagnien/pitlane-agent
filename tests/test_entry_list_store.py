import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.entry_list_store import materialize_entry_list


class EntryListStoreTest(unittest.TestCase):
    def test_materializes_immutable_native_whitelist_for_launch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            game_cfg = {'configs_path': str(Path(temporary_directory) / 'configs')}
            config = self._runtime_config()

            materialized = materialize_entry_list(config, game_cfg, 42, 'race-1')

            path = Path(materialized['Server']['EntryListPath'])
            self.assertTrue(path.is_file())
            self.assertEqual(
                {
                    'entrylist': [],
                    'steamid_whitelist': [{'steamid': '76561198000000001'}],
                    'steamid_blacklist': [],
                },
                json.loads(path.read_text(encoding='utf-8')),
            )

            second = materialize_entry_list(self._runtime_config(), game_cfg, 42, 'race-1')
            self.assertEqual(path, Path(second['Server']['EntryListPath']))

            changed = self._runtime_config()
            changed['EntryList']['entries'][0]['steam_id'] = '76561198000000002'
            changed['EntryList']['native_payload']['steamid_whitelist'][0]['steamid'] = '76561198000000002'
            with self.assertRaisesRegex(ValueError, 'immuable'):
                materialize_entry_list(changed, game_cfg, 42, 'race-1')

    def test_rejects_metadata_that_diverges_from_native_whitelist(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            config = self._runtime_config()
            config['EntryList']['entries'][0]['steam_id'] = '76561198000000002'

            with self.assertRaisesRegex(ValueError, 'diverge'):
                materialize_entry_list(
                    config,
                    {'configs_path': str(Path(temporary_directory) / 'configs')},
                    42,
                    'race-1',
                )

    def test_disabled_entry_list_keeps_server_path_empty(self):
        config = {
            'Server': {'EntryListPath': 'stale.json'},
            'EntryList': {
                'schema_version': 1,
                'mode': 'disabled',
            },
        }

        materialized = materialize_entry_list(config, {'configs_path': 'unused'}, None, 'quick-1')

        self.assertEqual('', materialized['Server']['EntryListPath'])

    @staticmethod
    def _runtime_config():
        return {
            'Server': {
                'EntryListPath': '',
            },
            'EntryList': {
                'schema_version': 1,
                'mode': 'steamid_whitelist',
                'authorized_count': 1,
                'entries': [
                    {
                        'steam_id': '76561198000000001',
                        'display_name': 'Pilot One',
                    },
                ],
                'native_payload': {
                    'entrylist': [],
                    'steamid_whitelist': [
                        {'steamid': '76561198000000001'},
                    ],
                    'steamid_blacklist': [],
                },
            },
        }


if __name__ == '__main__':
    unittest.main()
