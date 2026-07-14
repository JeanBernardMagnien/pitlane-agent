import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))

from services.runtime_config_compiler import finalize_launch_config


class RuntimeConfigCompilerTest(unittest.TestCase):
    def setUp(self):
        self.instance = {
            "id": "instance-contract-test",
            "tcp_port": 9600,
            "udp_port": 9600,
            "http_port": 8081,
        }
        self.runtime_config = {
            "Server": {
                "TcpPort": 9600,
                "UdpPort": 9600,
                "HttpPort": 8081,
                "ResultsPath": "",
            }
        }

    def test_injects_and_creates_instance_results_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_config = copy.deepcopy(self.runtime_config)

            compiled = finalize_launch_config(
                source_config,
                self.instance,
                {
                    "install_path": str(root / "game"),
                    "results_path": str(root / "results"),
                },
            )

            expected_path = root / "results" / self.instance["id"]
            self.assertTrue(expected_path.is_dir())
            self.assertEqual(str(expected_path) + os.sep, compiled["Server"]["ResultsPath"])
            self.assertEqual(self.runtime_config, source_config)

    def test_defaults_results_root_to_game_installation(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            install_path = Path(temporary_directory) / "game"

            compiled = finalize_launch_config(
                self.runtime_config,
                self.instance,
                {"install_path": str(install_path)},
            )

            expected_path = install_path / "Results" / self.instance["id"]
            self.assertTrue(expected_path.is_dir())
            self.assertEqual(str(expected_path) + os.sep, compiled["Server"]["ResultsPath"])


if __name__ == "__main__":
    unittest.main()
