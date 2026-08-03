import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.season_restart_guard import SeasonRestartGuard


class SeasonRestartGuardTest(unittest.TestCase):
    def _running_info(self, enabled=True):
        process = MagicMock()
        process.poll.return_value = None
        return {
            'process': process,
            'runtime_policy': {'stop_on_season_restart': enabled},
        }

    def test_stops_once_after_confirmed_season_restart(self):
        info = self._running_info()
        observe = MagicMock(return_value={
            'season_restart_count': 1,
            'season_restart_observed_at': '2026-08-03T17:25:00Z',
        })
        stop = MagicMock()
        guard = SeasonRestartGuard(
            lambda: [('server2', info)],
            observe,
            stop,
            {'logs_path': 'logs'},
        )

        self.assertEqual(1, guard.run_once())
        self.assertEqual(0, guard.run_once())
        stop.assert_called_once_with('server2', {'logs_path': 'logs'}, reason='normal')

    def test_does_not_observe_when_policy_is_disabled(self):
        info = self._running_info(enabled=False)
        observe = MagicMock()
        stop = MagicMock()
        guard = SeasonRestartGuard(lambda: [('server2', info)], observe, stop, {})

        self.assertEqual(0, guard.run_once())
        observe.assert_not_called()
        stop.assert_not_called()

    def test_does_not_stop_before_restart_is_confirmed(self):
        info = self._running_info()
        observe = MagicMock(return_value={
            'season_restart_count': 0,
            'season_restart_observed_at': None,
        })
        stop = MagicMock()
        guard = SeasonRestartGuard(lambda: [('server2', info)], observe, stop, {})

        self.assertEqual(0, guard.run_once())
        stop.assert_not_called()

    def test_retries_after_transient_stop_error(self):
        info = self._running_info()
        observation = {
            'season_restart_count': 1,
            'season_restart_observed_at': '2026-08-03T17:25:00Z',
        }
        stop = MagicMock(side_effect=[RuntimeError('busy'), {'status': 'stopped'}])
        guard = SeasonRestartGuard(
            lambda: [('server2', info)],
            MagicMock(return_value=observation),
            stop,
            {},
        )

        with self.assertRaisesRegex(RuntimeError, 'busy'):
            guard.run_once()

        self.assertFalse(info['season_restart_guard_triggered'])
        self.assertEqual(1, guard.run_once())
        self.assertEqual(2, stop.call_count)


if __name__ == '__main__':
    unittest.main()
