import sqlite3
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

from services.agent_command_journal import (
    AgentCommandContractError,
    AgentCommandConflict,
    AgentCommandJournal,
    StaleAgentCommand,
)
from services.agent_command_maintenance import AgentCommandMaintenance


class AgentCommandJournalTest(unittest.TestCase):
    def test_duplicate_command_is_not_inserted_twice(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            message = self._message(fence=1)

            first, created = journal.receive('local', message)
            duplicate, duplicate_created = journal.receive('local', message)

            self.assertTrue(created)
            self.assertFalse(duplicate_created)
            self.assertEqual(first['command_id'], duplicate['command_id'])
            self.assertEqual('received', duplicate['status'])

    def test_same_idempotency_key_with_other_payload_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            first = self._message(fence=1)
            journal.receive('local', first)

            conflicting = dict(first)
            conflicting['payload'] = {
                'instance_id': 'server3',
                'stop_reason': 'preempted',
            }

            with self.assertRaises(AgentCommandConflict):
                journal.receive('local', conflicting)

    def test_stale_fence_is_rejected_for_same_target(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            journal.receive('local', self._message(fence=10))

            stale = self._message(fence=9)
            stale['id'] = str(uuid.uuid4())
            stale['idempotency_key'] = 'stop-server3-stale'

            with self.assertRaises(StaleAgentCommand):
                journal.receive('local', stale)

    def test_acknowledgement_is_replayed_until_confirmed(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            message = self._message(fence=1)
            command, _ = journal.receive('local', message)

            journal.mark_executing('local', command['command_id'])
            journal.mark_terminal(
                'local',
                command['command_id'],
                'succeeded',
                {'status': 'stopped'},
                200,
            )

            pending = journal.pending_acknowledgements('local')
            self.assertEqual(1, len(pending))
            self.assertEqual('succeeded', pending[0]['status'])

            journal.confirm('local', command['command_id'], 'succeeded')

            self.assertEqual([], journal.pending_acknowledgements('local'))

    def test_terminal_result_survives_reopening_database(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / 'commands.sqlite3'
            journal = AgentCommandJournal(path)
            message = self._message(fence=1)
            command, _ = journal.receive('local', message)
            journal.mark_terminal(
                'local',
                command['command_id'],
                'failed',
                {'error': 'test'},
                409,
                error_code='TEST',
                error_message='test',
            )

            restored = AgentCommandJournal(path).get('local', command['command_id'])

            self.assertEqual('failed', restored['status'])
            self.assertEqual({'error': 'test'}, journal.response(restored))
            self.assertEqual(409, restored['status_code'])

    def test_hub_cannot_confirm_state_not_reached_by_agent(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            command, _ = journal.receive('local', self._message(fence=1))

            with self.assertRaises(AgentCommandConflict):
                journal.confirm('local', command['command_id'], 'succeeded')

    def test_metrics_expose_statuses_pending_acknowledgements_and_size(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            succeeded, _ = journal.receive('local', self._message(fence=1))
            journal.mark_terminal(
                'local',
                succeeded['command_id'],
                'succeeded',
                {'status': 'stopped'},
                200,
            )
            journal.confirm('local', succeeded['command_id'], 'succeeded')

            pending_message = self._message(fence=2)
            pending_message['idempotency_key'] = 'stop-server3-pending'
            pending, _ = journal.receive('local', pending_message)
            journal.mark_terminal(
                'local',
                pending['command_id'],
                'failed',
                {'error': 'test'},
                409,
            )

            metrics = AgentCommandMaintenance(journal.path).metrics(
                now=datetime.now(timezone.utc),
            )

            self.assertEqual('healthy', metrics['status'])
            self.assertEqual(2, metrics['total'])
            self.assertEqual(1, metrics['statuses']['succeeded'])
            self.assertEqual(1, metrics['statuses']['failed'])
            self.assertEqual(1, metrics['pending_acknowledgements'])
            self.assertGreater(metrics['database_bytes'], 0)

    def test_cleanup_deletes_only_old_hub_confirmed_successes(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / 'commands.sqlite3'
            journal = AgentCommandJournal(path)

            succeeded, _ = journal.receive('local', self._message(fence=1))
            journal.mark_terminal('local', succeeded['command_id'], 'succeeded', {}, 200)
            journal.confirm('local', succeeded['command_id'], 'succeeded')

            failed_message = self._message(fence=2)
            failed_message['idempotency_key'] = 'stop-server3-failed'
            failed, _ = journal.receive('local', failed_message)
            journal.mark_terminal('local', failed['command_id'], 'failed', {}, 500)
            journal.confirm('local', failed['command_id'], 'failed')

            unconfirmed_message = self._message(fence=3)
            unconfirmed_message['idempotency_key'] = 'stop-server3-unconfirmed'
            unconfirmed, _ = journal.receive('local', unconfirmed_message)
            journal.mark_terminal('local', unconfirmed['command_id'], 'succeeded', {}, 200)

            with sqlite3.connect(path) as connection:
                connection.execute(
                    "UPDATE agent_command SET updated_at = '2025-01-01T00:00:00Z'"
                )

            now = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
            maintenance = AgentCommandMaintenance(journal.path)
            dry_run = maintenance.purge_confirmed_successes(
                retention_days=365,
                execute=False,
                now=now,
            )
            executed = maintenance.purge_confirmed_successes(
                retention_days=365,
                execute=True,
                now=now,
            )

            self.assertEqual(1, dry_run['candidates'])
            self.assertEqual(0, dry_run['processed'])
            self.assertEqual(1, executed['candidates'])
            self.assertEqual(1, executed['processed'])
            with self.assertRaises(AgentCommandContractError):
                journal.get('local', succeeded['command_id'])
            self.assertEqual('failed', journal.get('local', failed['command_id'])['status'])
            self.assertEqual('succeeded', journal.get('local', unconfirmed['command_id'])['status'])

    def _message(self, fence: int) -> dict:
        command_id = str(uuid.uuid4())
        return {
            'schema_version': 2,
            'id': command_id,
            'idempotency_key': f'stop-server3-{fence}',
            'command': 'stop_instance',
            'target': {
                'server_id': 1,
                'instance_id': 'server3',
                'fence': fence,
            },
            'payload': {
                'instance_id': 'server3',
                'stop_reason': 'manual_stop',
            },
        }


if __name__ == '__main__':
    unittest.main()
