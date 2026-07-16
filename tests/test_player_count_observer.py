import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.player_count_observer import PlayerCountObserver, PlayerCountResolver


class _Process:
    pid = 1234


class PlayerCountObserverTest(unittest.TestCase):
    def setUp(self):
        self.resolver = PlayerCountResolver()

    def test_reads_latest_absolute_player_count_incrementally(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'log_server3_2026-07-16_17-45-09.log'
            log_path.write_text(
                '[2026-07-16 17:45:09.605] [server] [info] Server updated: 0 players\n'
                '[2026-07-16 17:49:03.812] [server] [info] Server updated: 1 players\n',
                encoding='utf-8',
            )
            observer = PlayerCountObserver()
            runtime_info = {
                'process': _Process(),
                'started_at': 1.0,
                'log_path': str(log_path),
            }

            first = observer.observe('server3', runtime_info, temporary_directory)
            self.assertEqual(1, first['log_connected_drivers'])

            with log_path.open('a', encoding='utf-8') as handle:
                handle.write('[2026-07-16 18:06:39.721] [server] [info] Server updated: 0 players\n')

            second = observer.observe('server3', runtime_info, temporary_directory)
            self.assertEqual(0, second['log_connected_drivers'])
            self.assertTrue(second['log_drivers_seen_at'].endswith('Z'))

    def test_fresh_log_and_http_disagreement_is_explicit(self):
        http = {
            'http_connected_drivers': 0,
            'http_drivers_seen_at': '2026-07-16T16:06:28Z',
            'http_ok': True,
        }
        log = {
            'log_connected_drivers': 1,
            'log_drivers_seen_at': '2026-07-16T16:06:28Z',
        }

        with patch('services.player_count_observer._timestamp_age_seconds', return_value=0):
            resolved = self.resolver.resolve('server3', '1234:1', http, log)

        self.assertIsNone(resolved['connected_drivers'])
        self.assertEqual('conflict', resolved['drivers_source'])
        self.assertTrue(resolved['drivers_conflict'])
        self.assertFalse(resolved['drivers_zero_confirmed'])

    def test_http_zero_requires_two_consecutive_observations(self):
        http = {
            'http_connected_drivers': 0,
            'http_drivers_seen_at': '2026-07-16T16:06:39Z',
            'http_ok': True,
        }
        log = {
            'log_connected_drivers': None,
            'log_drivers_seen_at': None,
        }

        first = self.resolver.resolve('server3', '1234:1', http, log)
        second = self.resolver.resolve('server3', '1234:1', http, log)

        self.assertFalse(first['drivers_zero_confirmed'])
        self.assertTrue(second['drivers_zero_confirmed'])
        self.assertEqual('http', second['drivers_source'])


if __name__ == '__main__':
    unittest.main()
