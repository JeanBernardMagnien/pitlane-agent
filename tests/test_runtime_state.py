import sys
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
