import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))
sys.modules.setdefault('psutil', MagicMock())

from core import config_store
from services import server_manager
from services.agent_commands import reset_instance_assignment_command
from services.current_config_store import current_config_path, save_current_config
from services.process_supervisor import process_supervisor


class InstanceAssignmentResetTest(unittest.TestCase):
    def tearDown(self):
        server_manager._running.clear()
        server_manager._last_config.clear()
        process_supervisor.terminated.clear()

    def test_reset_removes_materialized_config_and_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            game_cfg = {'configs_path': str(Path(temporary_directory) / 'configs')}
            logging_cfg = {'logs_path': str(Path(temporary_directory) / 'logs')}
            save_current_config(
                game_cfg,
                'server1',
                {'Server': {'ServerName': 'ancienne organisation'}},
            )
            log_path = Path(logging_cfg['logs_path']) / 'log_server1_2026-07-26_10-00-00.log'
            log_path.parent.mkdir(parents=True)
            log_path.write_text('Ancien journal', encoding='utf-8')
            server_manager._last_config['server1'] = {'config': 'old.json'}
            process_supervisor.restore_terminated(
                'server1',
                {'instance': {'id': 'server1', 'name': 'Ancien nom'}},
            )

            with (
                patch.object(config_store, 'GAME_CFG', game_cfg),
                patch.object(config_store, 'LOGGING_CFG', logging_cfg),
            ):
                response, status_code = reset_instance_assignment_command('server1', {})

            self.assertEqual(200, status_code)
            self.assertEqual('assignment_reset', response['status'])
            self.assertTrue(response['current_config_removed'])
            self.assertEqual(1, response['archived_logs'])
            self.assertFalse(current_config_path(game_cfg, 'server1').exists())
            self.assertFalse(log_path.exists())
            archived_logs = list(
                (Path(logging_cfg['logs_path']) / 'assignment-history' / 'server1')
                .glob('*/log_server1_*.log')
            )
            self.assertEqual(1, len(archived_logs))
            self.assertEqual('Ancien journal', archived_logs[0].read_text(encoding='utf-8'))
            self.assertNotIn('server1', server_manager._last_config)
            self.assertIsNone(process_supervisor.terminal('server1'))

    def test_reset_refuses_a_running_instance_without_deleting_its_config(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            game_cfg = {'configs_path': str(Path(temporary_directory) / 'configs')}
            save_current_config(
                game_cfg,
                'server1',
                {'Server': {'ServerName': 'toujours active'}},
            )
            process = MagicMock()
            process.poll.return_value = None
            server_manager._running['server1'] = {'process': process}

            with (
                patch.object(config_store, 'GAME_CFG', game_cfg),
                patch.object(config_store, 'LOGGING_CFG', {}),
            ):
                response, status_code = reset_instance_assignment_command('server1', {})

            self.assertEqual(409, status_code)
            self.assertIn('Arrêtez', response['error'])
            self.assertTrue(current_config_path(game_cfg, 'server1').exists())


if __name__ == '__main__':
    unittest.main()
