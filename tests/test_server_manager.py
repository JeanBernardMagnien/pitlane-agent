import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))
sys.modules.setdefault('psutil', MagicMock())

from services.server_process_command import build_process_args
from services import server_manager


class ServerManagerProcessArgumentsTest(unittest.TestCase):
    def test_stop_is_idempotent_when_instance_is_already_absent(self):
        result = server_manager.stop_instance('missing-instance')

        self.assertEqual('stopped', result['status'])
        self.assertTrue(result['already_stopped'])

    def setUp(self):
        self.executable = Path("C:/AC-EVO/AssettoCorsaEVOServer.exe")

    def test_builds_minimal_public_server_command_by_default(self):
        args = build_process_args(
            self.executable,
            {},
            "server-config",
            "season-definition",
        )

        self.assertEqual(
            [
                str(self.executable),
                "-serverconfig",
                "server-config",
                "-seasondefinition",
                "season-definition",
            ],
            args,
        )

    def test_adds_explicit_diagnostic_options(self):
        args = build_process_args(
            self.executable,
            {
                "no_lobby": True,
                "log_debug": "server,network",
                "write_server_results": True,
            },
            "server-config",
            "season-definition",
        )

        self.assertEqual(
            [
                str(self.executable),
                "-serverconfig",
                "server-config",
                "-seasondefinition",
                "season-definition",
                "-no_lobby",
                "-log_debug",
                "server,network",
                "-write_server_results",
            ],
            args,
        )


if __name__ == "__main__":
    unittest.main()
