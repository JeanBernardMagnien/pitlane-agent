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

    def test_tracks_real_ac_evo_session_markers_and_competitive_start(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'log_server3_2026-07-17_12-00-00.log'
            log_path.write_text(
                '[2026-07-17 12:00:01.000] [gameplay] [info] TimeAttackRemote Practice created\n'
                '[2026-07-17 12:00:02.000] [server] [info] Server updated: 1 players\n'
                '[2026-07-17 12:00:03.000] [gameplay] [info] Outplap split\n',
                encoding='utf-8',
            )
            observer = PlayerCountObserver()
            runtime_info = {
                'process': _Process(),
                'started_at': 1.0,
                'log_path': str(log_path),
            }

            practice = observer.observe('server3', runtime_info, temporary_directory)

            self.assertEqual('practice', practice['session_phase'])
            self.assertIsNone(practice['sport_started_at'])
            self.assertTrue(practice['first_driver_seen_at'].endswith('Z'))
            self.assertTrue(practice['log_observed_from_start'])

            with log_path.open('a', encoding='utf-8') as handle:
                handle.write(
                    '[2026-07-17 12:00:04.000] [gameplay] [info] END_SESSION All cars pitted\n'
                    '[2026-07-17 12:00:05.000] [gameplay] [info] TimeAttackRemote Qualifying created\n'
                    '[2026-07-17 12:00:06.000] [gameplay] [info] Outplap split\n'
                    '[2026-07-17 12:00:07.000] [crash] [critical] Fatal error, simulated crash\n'
                )

            qualifying = observer.observe('server3', runtime_info, temporary_directory)

            self.assertEqual('qualifying', qualifying['session_phase'])
            self.assertTrue(qualifying['sport_started_at'].endswith('Z'))
            self.assertTrue(qualifying['crash_detected_at'].endswith('Z'))
            self.assertIn('Fatal error', qualifying['crash_message'])

    def test_race_waiting_does_not_consume_sport_until_session_phase(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'log_server3_2026-07-17_12-00-00.log'
            log_path.write_text(
                '[2026-07-17 12:00:01.000] [gameplay] [info] TimeAttackRemote Qualifying created\n'
                '[2026-07-17 12:00:02.000] [gameplay] [info] Outplap split\n'
                '[2026-07-17 12:00:03.000] [gameplay] [info] InstantRaceRemote Race created\n'
                '[2026-07-17 12:00:04.000] [gameplay] [info] [SERVER] setSessionPhase Waiting_For_Players\n',
                encoding='utf-8',
            )
            observer = PlayerCountObserver()
            runtime_info = {
                'process': _Process(),
                'started_at': 1.0,
                'log_path': str(log_path),
            }

            waiting = observer.observe('server3', runtime_info, temporary_directory)

            self.assertEqual('race', waiting['session_phase'])
            self.assertTrue(waiting['sport_started_at'].endswith('Z'))
            self.assertIsNone(waiting['race_started_at'])

            with log_path.open('a', encoding='utf-8') as handle:
                handle.write(
                    '[2026-07-17 12:00:05.000] [gameplay] [info] '
                    '[SERVER] setSessionPhase Session\n'
                )

            started = observer.observe('server3', runtime_info, temporary_directory)

            self.assertTrue(started['sport_started_at'].endswith('Z'))
            self.assertTrue(started['race_started_at'].endswith('Z'))
            self.assertNotEqual(started['sport_started_at'], started['race_started_at'])

    def test_tracks_each_explicit_season_restart_incrementally(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'log_server3_2026-07-17_12-00-00.log'
            log_path.write_text(
                '[2026-07-17 12:00:01.000] [gameplay] [info] InstantRaceRemote Race created\n'
                '[2026-07-17 12:00:02.000] [gameplay] [info] [SERVER] setSessionPhase Session\n',
                encoding='utf-8',
            )
            observer = PlayerCountObserver()
            runtime_info = {
                'process': _Process(),
                'started_at': 1.0,
                'log_path': str(log_path),
            }

            before_restart = observer.observe('server3', runtime_info, temporary_directory)
            self.assertEqual(0, before_restart['season_restart_count'])
            self.assertIsNone(before_restart['season_restart_observed_at'])

            with log_path.open('a', encoding='utf-8') as handle:
                handle.write('[2026-07-17 12:01:08.090] [gameplay] [info] Restart Season\n')

            first_restart = observer.observe('server3', runtime_info, temporary_directory)
            repeated_observation = observer.observe('server3', runtime_info, temporary_directory)

            self.assertEqual(1, first_restart['season_restart_count'])
            self.assertTrue(first_restart['season_restart_observed_at'].endswith('Z'))
            self.assertEqual(1, repeated_observation['season_restart_count'])

            with log_path.open('a', encoding='utf-8') as handle:
                handle.write('[2026-07-17 12:02:08.090] [gameplay] [info] Restart Season\n')

            second_restart = observer.observe('server3', runtime_info, temporary_directory)
            self.assertEqual(2, second_restart['season_restart_count'])
            self.assertGreater(
                second_restart['season_restart_observed_at'],
                first_restart['season_restart_observed_at'],
            )

    def test_empty_log_is_a_complete_observation_without_inventing_sport_start(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            log_path = Path(temporary_directory) / 'log_server3_2026-07-17_12-00-00.log'
            log_path.write_text(
                '[2026-07-17 12:00:01.000] [server] [info] Server Config loaded\n',
                encoding='utf-8',
            )
            observer = PlayerCountObserver()

            observation = observer.observe('server3', {
                'process': _Process(),
                'started_at': 1.0,
                'log_path': str(log_path),
            }, temporary_directory)

            self.assertIsNone(observation['first_driver_seen_at'])
            self.assertIsNone(observation['sport_started_at'])
            self.assertTrue(observation['log_observed_from_start'])

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
