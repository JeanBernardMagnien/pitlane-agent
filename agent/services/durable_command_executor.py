import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from services.agent_command_journal import AgentCommandJournal


AckCallback = Callable[[dict, dict | None], None]
TerminalCallback = Callable[[], None]
ExecuteCommand = Callable[[str, dict], tuple[dict, int]]
NON_REPLAYABLE_AFTER_INTERRUPTION = {
    'steam_update',
    'update_steam',
}


class DurableCommandCoordinator:
    def __init__(
        self,
        journal: AgentCommandJournal,
        execute_command: ExecuteCommand,
        executor=None,
    ):
        self.journal = journal
        self.execute_command = execute_command
        self.executor = executor or ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix='hub-ws-command',
        )
        self._command_locks: dict[str, threading.Lock] = {}
        self._command_locks_guard = threading.Lock()
        self._scheduled_commands: set[tuple[str, str]] = set()
        self._scheduled_commands_guard = threading.Lock()

    def receive(
        self,
        hub_name: str,
        message: dict,
        emit_ack: AckCallback,
        after_terminal: TerminalCallback,
    ) -> dict:
        record, _created = self.journal.receive(hub_name, message)
        emit_ack(record, None)

        if record['status'] == 'received':
            self._schedule(hub_name, record, emit_ack, after_terminal)

        return record

    def confirm(self, hub_name: str, command_id: str, status: str) -> dict:
        return self.journal.confirm(hub_name, command_id, status)

    def replay_pending(
        self,
        hub_name: str,
        emit_ack: AckCallback,
        after_terminal: TerminalCallback | None = None,
        limit: int = 100,
    ) -> int:
        records = self.journal.pending_acknowledgements(hub_name, limit=limit)
        for record in records:
            emit_ack(record, None)
            command_id = str(record['command_id'])

            if record['status'] == 'received':
                self._schedule(
                    hub_name,
                    record,
                    emit_ack,
                    after_terminal or (lambda: None),
                )
            elif (
                record['status'] == 'executing'
                and not self.is_scheduled(hub_name, command_id)
            ):
                if record['command_name'] in NON_REPLAYABLE_AFTER_INTERRUPTION:
                    failed = self.journal.mark_terminal(
                        hub_name,
                        command_id,
                        'failed',
                        {
                            'code': 'execution_interrupted',
                            'error': 'L’agent a redémarré pendant cette commande non rejouable.',
                        },
                        500,
                        error_code='execution_interrupted',
                        error_message='L’agent a redémarré pendant cette commande non rejouable.',
                    )
                    emit_ack(failed, self.journal.response(failed))
                    if after_terminal is not None:
                        after_terminal()
                else:
                    self._schedule(
                        hub_name,
                        record,
                        emit_ack,
                        after_terminal or (lambda: None),
                    )

        return len(records)

    def is_scheduled(self, hub_name: str, command_id: str) -> bool:
        with self._scheduled_commands_guard:
            return (hub_name, command_id) in self._scheduled_commands

    def _schedule(
        self,
        hub_name: str,
        record: dict,
        emit_ack: AckCallback,
        after_terminal: TerminalCallback,
    ) -> None:
        scheduled_key = (hub_name, str(record['command_id']))

        with self._scheduled_commands_guard:
            if scheduled_key in self._scheduled_commands:
                return
            self._scheduled_commands.add(scheduled_key)

        try:
            self.executor.submit(
                self._execute,
                hub_name,
                str(record['command_id']),
                emit_ack,
                after_terminal,
            )
        except Exception:
            with self._scheduled_commands_guard:
                self._scheduled_commands.discard(scheduled_key)
            raise

    def _execute(
        self,
        hub_name: str,
        command_id: str,
        emit_ack: AckCallback,
        after_terminal: TerminalCallback,
    ) -> None:
        scheduled_key = (hub_name, command_id)

        try:
            record = self.journal.get(hub_name, command_id)
            with self._command_lock(str(record['target_key'])):
                record = self.journal.mark_executing(hub_name, command_id)
                emit_ack(record, None)

                try:
                    response, status_code = self.execute_command(
                        str(record['command_name']),
                        {
                            **self.journal.payload(record),
                            '_pitlane_command_id': command_id,
                        },
                    )
                    if not isinstance(response, dict):
                        response = {'error': 'Réponse de commande invalide'}
                        status_code = 500
                except Exception as exc:
                    response = {'error': f'Erreur commande : {exc.__class__.__name__}'}
                    status_code = 500

                succeeded = 200 <= int(status_code) < 300
                error_code = None
                error_message = None
                if not succeeded:
                    raw_code = response.get('code')
                    error_code = str(raw_code) if raw_code is not None else None
                    raw_error = response.get('error')
                    error_message = str(raw_error) if raw_error is not None else 'Commande agent en échec'

                record = self.journal.mark_terminal(
                    hub_name,
                    command_id,
                    'succeeded' if succeeded else 'failed',
                    response,
                    int(status_code),
                    error_code=error_code,
                    error_message=error_message,
                )

                try:
                    emit_ack(record, response)
                    after_terminal()
                except Exception:
                    # SQLite reste l'autorité locale ; l'accusé sera rejoué.
                    pass
        finally:
            with self._scheduled_commands_guard:
                self._scheduled_commands.discard(scheduled_key)

    def _command_lock(self, target_key: str) -> threading.Lock:
        with self._command_locks_guard:
            lock = self._command_locks.get(target_key)
            if lock is None:
                lock = threading.Lock()
                self._command_locks[target_key] = lock
            return lock
