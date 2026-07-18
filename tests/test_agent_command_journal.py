import tempfile
import unittest
import uuid
from pathlib import Path

from services.agent_command_journal import (
    AgentCommandConflict,
    AgentCommandJournal,
    StaleAgentCommand,
)


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
