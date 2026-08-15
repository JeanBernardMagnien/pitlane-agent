import tempfile
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.agent_command_journal import AgentCommandJournal
from services.durable_command_executor import DurableCommandCoordinator


class InlineExecutor:
    def submit(self, callback, *args):
        callback(*args)


class DurableCommandCoordinatorTest(unittest.TestCase):
    def test_command_emits_progressive_acknowledgements_and_executes_once(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            executions = []
            acknowledgements = []
            coordinator = DurableCommandCoordinator(
                journal,
                lambda command, payload: (
                    executions.append((command, payload)) or {'status': 'stopped'},
                    200,
                ),
                executor=InlineExecutor(),
            )
            message = self._message(1)

            coordinator.receive(
                'local',
                message,
                lambda record, response: acknowledgements.append((record['status'], response)),
                lambda: None,
            )
            coordinator.receive(
                'local',
                message,
                lambda record, response: acknowledgements.append((record['status'], response)),
                lambda: None,
            )

            self.assertEqual(1, len(executions))
            self.assertEqual('stop_instance', executions[0][0])
            self.assertEqual('server3', executions[0][1]['instance_id'])
            self.assertEqual(message['id'], executions[0][1]['_pitlane_command_id'])
            self.assertEqual(
                ['received', 'executing', 'succeeded', 'succeeded'],
                [status for status, _response in acknowledgements],
            )

    def test_mutations_for_same_instance_never_overlap(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            concurrency = 0
            maximum_concurrency = 0
            state_lock = threading.Lock()

            def execute(_command, _payload):
                nonlocal concurrency, maximum_concurrency
                with state_lock:
                    concurrency += 1
                    maximum_concurrency = max(maximum_concurrency, concurrency)
                time.sleep(0.05)
                with state_lock:
                    concurrency -= 1
                return {'status': 'ok'}, 200

            with ThreadPoolExecutor(max_workers=2) as executor:
                coordinator = DurableCommandCoordinator(journal, execute, executor=executor)
                first = self._message(1)
                second = self._message(2)
                second['id'] = str(uuid.uuid4())
                second['idempotency_key'] = 'stop-server3-2'

                coordinator.receive('local', first, lambda _record, _response: None, lambda: None)
                coordinator.receive('local', second, lambda _record, _response: None, lambda: None)

            self.assertEqual(1, maximum_concurrency)
            self.assertEqual(
                'succeeded',
                journal.get('local', first['id'])['status'],
            )
            self.assertEqual(
                'succeeded',
                journal.get('local', second['id'])['status'],
            )

    def test_mutations_for_different_instances_can_run_concurrently(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            both_running = threading.Event()
            release = threading.Event()
            running = 0
            state_lock = threading.Lock()

            def execute(_command, _payload):
                nonlocal running
                with state_lock:
                    running += 1
                    if running == 2:
                        both_running.set()
                release.wait(timeout=1)
                with state_lock:
                    running -= 1
                return {'status': 'ok'}, 200

            with ThreadPoolExecutor(max_workers=2) as executor:
                coordinator = DurableCommandCoordinator(journal, execute, executor=executor)
                first = self._message(1)
                second = self._message(1, instance_id='server4')
                second['id'] = str(uuid.uuid4())
                second['idempotency_key'] = 'stop-server4-1'

                coordinator.receive('local', first, lambda _record, _response: None, lambda: None)
                coordinator.receive('local', second, lambda _record, _response: None, lambda: None)

                self.assertTrue(both_running.wait(timeout=1))
                release.set()

    def test_interrupted_replayable_command_reuses_same_command_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            message = self._message(1)
            command, _ = journal.receive('local', message)
            journal.mark_executing('local', command['command_id'])
            journal.confirm('local', command['command_id'], 'executing')
            payloads = []

            coordinator = DurableCommandCoordinator(
                journal,
                lambda _command, payload: (
                    payloads.append(payload) or {'status': 'stopped'},
                    200,
                ),
                executor=InlineExecutor(),
            )

            coordinator.replay_pending(
                'local',
                lambda _record, _response: None,
            )

            self.assertEqual('succeeded', journal.get('local', command['command_id'])['status'])
            self.assertEqual(1, len(payloads))
            self.assertEqual(command['command_id'], payloads[0]['_pitlane_command_id'])

    def test_confirmed_received_command_is_executed_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            message = self._message(1)
            command, _ = journal.receive('local', message)
            journal.confirm('local', command['command_id'], 'received')
            executions = []

            coordinator = DurableCommandCoordinator(
                journal,
                lambda command_name, payload: (
                    executions.append((command_name, payload)) or {'status': 'stopped'},
                    200,
                ),
                executor=InlineExecutor(),
            )

            coordinator.replay_pending('local', lambda _record, _response: None)

            self.assertEqual('succeeded', journal.get('local', command['command_id'])['status'])
            self.assertEqual(1, len(executions))
            self.assertEqual(command['command_id'], executions[0][1]['_pitlane_command_id'])

    def test_interrupted_steam_update_is_not_started_twice(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            journal = AgentCommandJournal(Path(temporary_directory) / 'commands.sqlite3')
            message = self._message(1)
            message['command'] = 'steam_update'
            message['target']['instance_id'] = None
            message['payload'] = {
                'steam_username': 'account',
                'steam_password': 'secret',
            }
            command, _ = journal.receive('local', message)
            journal.mark_executing('local', command['command_id'])
            executions = []

            coordinator = DurableCommandCoordinator(
                journal,
                lambda command_name, payload: (
                    executions.append((command_name, payload)) or {'status': 'started'},
                    202,
                ),
                executor=InlineExecutor(),
            )

            coordinator.replay_pending(
                'local',
                lambda _record, _response: None,
            )

            restored = journal.get('local', command['command_id'])
            self.assertEqual([], executions)
            self.assertEqual('failed', restored['status'])
            self.assertEqual('execution_interrupted', restored['error_code'])

    def _message(self, fence: int, instance_id: str = 'server3') -> dict:
        command_id = str(uuid.uuid4())
        return {
            'schema_version': 2,
            'id': command_id,
            'idempotency_key': f'stop-{instance_id}-{fence}',
            'command': 'stop_instance',
            'target': {
                'server_id': 1,
                'instance_id': instance_id,
                'fence': fence,
            },
            'payload': {
                'instance_id': instance_id,
                'stop_reason': 'manual_stop',
            },
        }


if __name__ == '__main__':
    unittest.main()
