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
    def tearDown(self):
        server_manager._running.clear()

    def test_same_durable_command_recovers_existing_process_without_restarting(self):
        process = MagicMock()
        process.pid = 4321
        process.poll.return_value = None
        server_manager._running['server3'] = {
            'process': process,
            'command_id': '4cf3a345-baa4-43af-a6f0-2f425da4a490',
        }

        result = server_manager.already_executed_command(
            'server3',
            '4cf3a345-baa4-43af-a6f0-2f425da4a490',
        )

        self.assertEqual({
            'status': 'started',
            'pid': 4321,
            'already_executed': True,
        }, result)

    def test_other_command_does_not_reuse_existing_process(self):
        process = MagicMock()
        process.poll.return_value = None
        server_manager._running['server3'] = {
            'process': process,
            'command_id': '4cf3a345-baa4-43af-a6f0-2f425da4a490',
        }

        self.assertIsNone(server_manager.already_executed_command(
            'server3',
            'c4b8a3df-082a-428c-81ee-f57c1c560a14',
        ))

    def test_stop_is_idempotent_when_instance_is_already_absent(self):
        result = server_manager.stop_instance('missing-instance')

        self.assertEqual('stopped', result['status'])
        self.assertTrue(result['already_stopped'])

    def test_terminal_payload_keeps_short_crash_diagnostic(self):
        payload = server_manager.terminal_process_payload({
            'exit_code': -1,
            'exit_observed_at': '2026-08-02T18:05:00Z',
            'game_observation': {
                'crash_detected_at': '2026-08-02T18:04:59Z',
                'crash_message': '[crash] Fatal error while loading session',
            },
        })

        self.assertEqual('[crash] Fatal error while loading session', payload['crash_message'])
        self.assertEqual('2026-08-02T18:04:59Z', payload['crash_detected_at'])

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
