import sys
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))

from services.server_process_command import build_process_args


class ServerManagerProcessArgumentsTest(unittest.TestCase):
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
