import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))
sys.modules.setdefault('psutil', MagicMock())

from services import runtime_state


class _PsProcess:
    def __init__(self, create_time=100.0, executable='C:/AC-EVO/AssettoCorsaEVOServer.exe'):
        self._create_time = create_time
        self._executable = executable

    def is_running(self):
        return True

    def status(self):
        return 'running'

    def create_time(self):
        return self._create_time

    def exe(self):
        return self._executable

    def name(self):
        return Path(self._executable).name


class RuntimeStateIdentityTest(unittest.TestCase):
    def setUp(self):
        runtime_state.process_supervisor.running.clear()
        runtime_state.process_supervisor.terminated.clear()

    def tearDown(self):
        runtime_state.process_supervisor.running.clear()
        runtime_state.process_supervisor.terminated.clear()

    def test_saved_runtime_identity_includes_durable_command_id(self):
        process = MagicMock()
        process.pid = 1234
        process.poll.return_value = None

        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch.object(runtime_state.process_supervisor, 'snapshot_running', return_value=[(
                'server3',
                {
                    'process': process,
                    'instance': {'id': 'server3'},
                    'command_id': '4cf3a345-baa4-43af-a6f0-2f425da4a490',
                    'runtime_policy': {'stop_on_season_restart': True},
                },
            )]),
            patch.object(runtime_state.process_supervisor, 'snapshot_terminated', return_value=[]),
        ):
            path = Path(temporary_directory) / 'runtime_state.json'
            runtime_state.save_runtime_state({'logs_path': temporary_directory})
            payload = json.loads(path.read_text(encoding='utf-8'))

        self.assertEqual(4, payload['schema_version'])
        self.assertEqual(
            '4cf3a345-baa4-43af-a6f0-2f425da4a490',
            payload['running']['server3']['command_id'],
        )
        self.assertEqual(
            {'stop_on_season_restart': True},
            payload['running']['server3']['runtime_policy'],
        )

    def test_restoration_rejects_reused_pid_with_different_creation_time(self):
        process = _PsProcess(create_time=200.0)

        with (
            patch.object(runtime_state.psutil, 'pid_exists', return_value=True),
            patch.object(runtime_state.psutil, 'Process', return_value=process),
        ):
            restored = runtime_state._validated_process(1234, {
                'process_create_time': 100.0,
                'executable_path': process.exe(),
            }, {})

        self.assertIsNone(restored)

    def test_reused_pid_proves_that_original_process_is_missing(self):
        process = _PsProcess(create_time=200.0)

        with (
            patch.object(runtime_state.psutil, 'pid_exists', return_value=True),
            patch.object(runtime_state.psutil, 'Process', return_value=process),
        ):
            restored, missing = runtime_state._inspect_process(1234, {
                'process_create_time': 100.0,
                'executable_path': process.exe(),
            }, {})

        self.assertIsNone(restored)
        self.assertTrue(missing)

    def test_inaccessible_executable_does_not_fabricate_a_missing_process(self):
        process = _PsProcess()

        with (
            patch.object(runtime_state.psutil, 'pid_exists', return_value=True),
            patch.object(runtime_state.psutil, 'Process', return_value=process),
            patch.object(runtime_state, '_safe_executable_path', return_value=None),
        ):
            restored, missing = runtime_state._inspect_process(1234, {
                'process_create_time': 100.0,
                'executable_path': process.exe(),
            }, {})

        self.assertIsNone(restored)
        self.assertFalse(missing)

    def test_restoration_accepts_matching_process_identity(self):
        process = _PsProcess()

        with (
            patch.object(runtime_state.psutil, 'pid_exists', return_value=True),
            patch.object(runtime_state.psutil, 'Process', return_value=process),
        ):
            restored = runtime_state._validated_process(1234, {
                'process_create_time': 100.0,
                'executable_path': process.exe(),
            }, {})

        self.assertIs(process, restored)

    def test_restoration_reports_missing_tracked_process_as_crash(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / 'runtime_state.json'
            path.write_text(json.dumps({
                'schema_version': 4,
                'running': {
                    'server2': {
                        'pid': 1234,
                        'instance': {'id': 'server2', 'name': 'Server 2'},
                        'started_at': 100.0,
                        'config': 'launch-215.json',
                        'process_create_time': 100.0,
                        'executable_path': 'C:/AC-EVO/AssettoCorsaEVOServer.exe',
                        'stop_requested_at': None,
                        'stop_reason': None,
                        'game_observation': {
                            'session_phase': 'practice',
                            'log_observed_from_start': True,
                        },
                    },
                },
                'terminated': {},
            }), encoding='utf-8')

            with patch.object(runtime_state.psutil, 'pid_exists', return_value=False):
                restored = runtime_state.restore_runtime_state({'logs_path': temporary_directory}, {})

            persisted = json.loads(path.read_text(encoding='utf-8'))

        self.assertEqual(0, restored)
        terminal = persisted['terminated']['server2']
        self.assertIsNone(terminal['exit_code'])
        self.assertIsNotNone(terminal['exit_observed_at'])
        self.assertEqual('practice', terminal['game_observation']['session_phase'])
        self.assertTrue(terminal['game_observation']['log_observed_from_start'])
        self.assertIsNotNone(terminal['game_observation']['crash_detected_at'])
        self.assertIn('redémarrage', terminal['game_observation']['crash_message'])

    def test_restoration_keeps_persisted_stop_intent_without_fabricating_crash(self):
        terminal = runtime_state._missing_process_terminal('server2', {
            'instance': {'id': 'server2'},
            'stop_requested_at': '2026-08-03T18:27:20Z',
            'stop_reason': 'normal',
            'game_observation': {'session_phase': 'race'},
        })

        self.assertEqual('normal', terminal['stop_reason'])
        self.assertNotIn('crash_detected_at', terminal['game_observation'])
        self.assertNotIn('crash_message', terminal['game_observation'])


if __name__ == '__main__':
    unittest.main()
