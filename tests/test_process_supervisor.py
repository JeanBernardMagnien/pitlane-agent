import sys
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.process_supervisor import ProcessSupervisor


class _Process:
    pid = 1234

    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class ProcessSupervisorTest(unittest.TestCase):
    def test_expected_stop_preserves_reason_and_exit_code(self):
        supervisor = ProcessSupervisor()
        process = _Process()
        supervisor.register('race-1', {
            'process': process,
            'instance': {'id': 'race-1'},
            'exit_code_available': True,
            'game_observation': {'log_observed_from_start': True},
        })

        supervisor.request_stop('race-1', 'manual_stop')
        process.exit_code = 0
        terminal = supervisor.observe_exit('race-1')

        self.assertEqual('manual_stop', terminal['stop_reason'])
        self.assertEqual(0, terminal['exit_code'])
        self.assertIsNotNone(terminal['stop_requested_at'])
        self.assertIsNotNone(terminal['exit_observed_at'])
        self.assertNotIn('race-1', supervisor.running)

    def test_unexpected_exit_has_no_stop_intent(self):
        supervisor = ProcessSupervisor()
        process = _Process(exit_code=-1)
        supervisor.register('race-1', {
            'process': process,
            'instance': {'id': 'race-1'},
            'exit_code_available': True,
        })

        terminal = supervisor.observe_exit('race-1')

        self.assertIsNone(terminal['stop_reason'])
        self.assertIsNone(terminal['stop_requested_at'])
        self.assertEqual(-1, terminal['exit_code'])
        self.assertEqual('process_exit', terminal['exit_origin'])

    def test_forget_removes_only_a_terminated_instance(self):
        supervisor = ProcessSupervisor()
        supervisor.restore_terminated('stopped', {'instance': {'id': 'stopped'}})
        supervisor.register('running', {
            'process': _Process(),
            'instance': {'id': 'running'},
        })

        self.assertTrue(supervisor.forget('stopped'))
        self.assertIsNone(supervisor.terminal('stopped'))
        self.assertFalse(supervisor.forget('running'))
        self.assertIn('running', supervisor.running)


if __name__ == '__main__':
    unittest.main()
