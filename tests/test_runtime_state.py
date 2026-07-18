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
                },
            )]),
            patch.object(runtime_state.process_supervisor, 'snapshot_terminated', return_value=[]),
        ):
            path = Path(temporary_directory) / 'runtime_state.json'
            runtime_state.save_runtime_state({'logs_path': temporary_directory})
            payload = json.loads(path.read_text(encoding='utf-8'))

        self.assertEqual(3, payload['schema_version'])
        self.assertEqual(
            '4cf3a345-baa4-43af-a6f0-2f425da4a490',
            payload['running']['server3']['command_id'],
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


if __name__ == '__main__':
    unittest.main()
