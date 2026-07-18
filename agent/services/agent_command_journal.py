import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

STATUSES = ('received', 'executing', 'succeeded', 'failed')
TERMINAL_STATUSES = ('succeeded', 'failed')
STATUS_RANK = {
    'received': 0,
    'executing': 1,
    'succeeded': 2,
    'failed': 2,
}


class AgentCommandContractError(ValueError):
    pass


class AgentCommandConflict(AgentCommandContractError):
    pass


class StaleAgentCommand(AgentCommandContractError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _canonical_json(payload) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    )


def _payload_fingerprint(command: str, instance_id: str | None, payload: dict) -> str:
    canonical = _canonical_json({
        'command': command,
        'instance_id': instance_id,
        'payload': payload,
    })
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def command_journal_path() -> Path:
    from core import config_store

    configured = config_store.LOGGING_CFG.get('command_journal_path')
    if configured:
        return Path(configured)

    return Path(config_store.LOGGING_CFG.get('logs_path') or 'logs') / 'agent-commands.sqlite3'


class AgentCommandJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._ensure_schema()

    def receive(self, hub_name: str, message: dict) -> tuple[dict, bool]:
        normalized = self._normalize_command(hub_name, message)

        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')

            existing = connection.execute(
                '''
                SELECT *
                FROM agent_command
                WHERE hub_name = ? AND idempotency_key = ?
                ''',
                (normalized['hub_name'], normalized['idempotency_key']),
            ).fetchone()

            if existing is not None:
                record = dict(existing)
                self._assert_same_command(record, normalized)
                connection.commit()
                return record, False

            last_fence = connection.execute(
                '''
                SELECT last_fence
                FROM agent_command_fence
                WHERE hub_name = ? AND target_key = ?
                ''',
                (normalized['hub_name'], normalized['target_key']),
            ).fetchone()
            if last_fence is not None and normalized['fence'] <= int(last_fence['last_fence']):
                connection.rollback()
                raise StaleAgentCommand(
                    f"Fence {normalized['fence']} refusé pour {normalized['target_key']}"
                )

            now = _utc_now()
            connection.execute(
                '''
                INSERT INTO agent_command (
                    hub_name,
                    command_id,
                    idempotency_key,
                    command_name,
                    instance_id,
                    target_key,
                    fence,
                    payload_fingerprint,
                    payload_json,
                    status,
                    confirmed_rank,
                    received_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'received', -1, ?, ?)
                ''',
                (
                    normalized['hub_name'],
                    normalized['command_id'],
                    normalized['idempotency_key'],
                    normalized['command_name'],
                    normalized['instance_id'],
                    normalized['target_key'],
                    normalized['fence'],
                    normalized['payload_fingerprint'],
                    normalized['payload_json'],
                    now,
                    now,
                ),
            )
            connection.execute(
                '''
                INSERT INTO agent_command_fence (hub_name, target_key, last_fence, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(hub_name, target_key)
                DO UPDATE SET last_fence = excluded.last_fence, updated_at = excluded.updated_at
                ''',
                (
                    normalized['hub_name'],
                    normalized['target_key'],
                    normalized['fence'],
                    now,
                ),
            )
            connection.commit()

            return self.get(normalized['hub_name'], normalized['command_id']), True

    def mark_executing(self, hub_name: str, command_id: str) -> dict:
        return self._transition(hub_name, command_id, 'executing')

    def mark_terminal(
        self,
        hub_name: str,
        command_id: str,
        status: str,
        response: dict,
        status_code: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict:
        if status not in TERMINAL_STATUSES:
            raise AgentCommandContractError('État terminal de commande invalide')
        if not isinstance(response, dict):
            raise AgentCommandContractError('La réponse terminale doit être un objet JSON')

        now = _utc_now()
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            record = self._record(connection, hub_name, command_id)

            if record['status'] in TERMINAL_STATUSES:
                if record['status'] != status:
                    connection.rollback()
                    raise AgentCommandConflict('Accusé terminal contradictoire')

                connection.commit()
                return record

            connection.execute(
                '''
                UPDATE agent_command
                SET status = ?,
                    response_json = ?,
                    status_code = ?,
                    error_code = ?,
                    error_message = ?,
                    completed_at = COALESCE(completed_at, ?),
                    updated_at = ?
                WHERE hub_name = ? AND command_id = ?
                ''',
                (
                    status,
                    _canonical_json(response),
                    int(status_code),
                    self._bounded(error_code, 100),
                    self._bounded(error_message, 4000),
                    now,
                    now,
                    hub_name,
                    command_id,
                ),
            )
            connection.commit()

        return self.get(hub_name, command_id)

    def confirm(self, hub_name: str, command_id: str, status: str) -> dict:
        if status not in STATUSES:
            raise AgentCommandContractError('État confirmé invalide')

        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            record = self._record(connection, hub_name, command_id)
            if STATUS_RANK[status] > STATUS_RANK[record['status']]:
                connection.rollback()
                raise AgentCommandConflict('Le Hub confirme un état non atteint localement')
            if (
                status in TERMINAL_STATUSES
                and record['status'] in TERMINAL_STATUSES
                and status != record['status']
            ):
                connection.rollback()
                raise AgentCommandConflict('Le Hub confirme un état terminal contradictoire')

            confirmed_rank = max(int(record['confirmed_rank']), STATUS_RANK[status])

            connection.execute(
                '''
                UPDATE agent_command
                SET confirmed_rank = ?, updated_at = ?
                WHERE hub_name = ? AND command_id = ?
                ''',
                (confirmed_rank, _utc_now(), hub_name, command_id),
            )
            connection.commit()

        return self.get(hub_name, command_id)

    def get(self, hub_name: str, command_id: str) -> dict:
        with self._connection() as connection:
            record = self._record(connection, hub_name, command_id)

        return record

    def pending_acknowledgements(self, hub_name: str, limit: int = 500) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                '''
                SELECT *
                FROM agent_command
                WHERE hub_name = ?
                  AND (
                    (status = 'received' AND confirmed_rank < 0)
                    OR (status = 'executing' AND confirmed_rank < 1)
                    OR (status IN ('succeeded', 'failed') AND confirmed_rank < 2)
                  )
                ORDER BY updated_at ASC
                LIMIT ?
                ''',
                (hub_name, max(1, min(int(limit), 2000))),
            ).fetchall()

        return [dict(row) for row in rows]

    def payload(self, record: dict) -> dict:
        payload = json.loads(record.get('payload_json') or '{}')
        if not isinstance(payload, dict):
            raise AgentCommandContractError('Payload journalisé invalide')
        return payload

    def response(self, record: dict) -> dict:
        response = json.loads(record.get('response_json') or '{}')
        return response if isinstance(response, dict) else {}

    def _transition(self, hub_name: str, command_id: str, status: str) -> dict:
        if status not in ('received', 'executing'):
            raise AgentCommandContractError('Transition de commande invalide')

        now = _utc_now()
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            record = self._record(connection, hub_name, command_id)

            if record['status'] in TERMINAL_STATUSES:
                connection.commit()
                return record
            if STATUS_RANK[status] < STATUS_RANK[record['status']]:
                connection.commit()
                return record

            executing_at = now if status == 'executing' else None
            connection.execute(
                '''
                UPDATE agent_command
                SET status = ?,
                    executing_at = COALESCE(executing_at, ?),
                    updated_at = ?
                WHERE hub_name = ? AND command_id = ?
                ''',
                (status, executing_at, now, hub_name, command_id),
            )
            connection.commit()

        return self.get(hub_name, command_id)

    def _normalize_command(self, hub_name: str, message: dict) -> dict:
        hub_name = str(hub_name or '').strip()
        command_id = str(message.get('id') or '').strip()
        idempotency_key = str(message.get('idempotency_key') or '').strip()
        command_name = str(message.get('command') or '').strip()
        target = message.get('target')
        payload = message.get('payload')

        if not hub_name:
            raise AgentCommandContractError('Nom du hub requis')
        try:
            uuid.UUID(command_id)
        except (ValueError, AttributeError):
            raise AgentCommandContractError('Identifiant de commande invalide') from None
        if not idempotency_key or len(idempotency_key) > 128:
            raise AgentCommandContractError('Clé d’idempotence invalide')
        if not command_name or len(command_name) > 80:
            raise AgentCommandContractError('Nom de commande invalide')
        if not isinstance(target, dict):
            raise AgentCommandContractError('Cible de commande requise')
        if not isinstance(payload, dict):
            raise AgentCommandContractError('Payload de commande invalide')

        instance_id = str(target.get('instance_id') or '').strip() or None
        if instance_id is not None and len(instance_id) > 100:
            raise AgentCommandContractError('Identifiant d’instance invalide')

        try:
            fence = int(target.get('fence'))
        except (TypeError, ValueError):
            raise AgentCommandContractError('Fence de commande invalide') from None
        if fence <= 0:
            raise AgentCommandContractError('Fence de commande invalide')

        target_key = f'instance:{instance_id}' if instance_id else 'server'
        fingerprint = _payload_fingerprint(command_name, instance_id, payload)

        return {
            'hub_name': hub_name,
            'command_id': command_id,
            'idempotency_key': idempotency_key,
            'command_name': command_name,
            'instance_id': instance_id,
            'target_key': target_key,
            'fence': fence,
            'payload_fingerprint': fingerprint,
            'payload_json': _canonical_json(payload),
        }

    def _assert_same_command(self, existing: dict, normalized: dict) -> None:
        if (
            existing['command_id'] != normalized['command_id']
            or existing['command_name'] != normalized['command_name']
            or existing['instance_id'] != normalized['instance_id']
            or existing['payload_fingerprint'] != normalized['payload_fingerprint']
            or int(existing['fence']) != normalized['fence']
        ):
            raise AgentCommandConflict(
                'La clé d’idempotence désigne une autre commande'
            )

    def _record(self, connection, hub_name: str, command_id: str) -> dict:
        row = connection.execute(
            '''
            SELECT *
            FROM agent_command
            WHERE hub_name = ? AND command_id = ?
            ''',
            (str(hub_name), str(command_id)),
        ).fetchone()
        if row is None:
            raise AgentCommandContractError('Commande agent inconnue')

        return dict(row)

    def _connection(self):
        self._ensure_schema()
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 5000')
        return connection

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return

        with self._schema_lock:
            if self._schema_ready:
                return

            with sqlite3.connect(self.path, timeout=5) as connection:
                connection.execute('PRAGMA journal_mode = WAL')
                connection.execute('PRAGMA synchronous = FULL')
                connection.executescript(
                    '''
                    CREATE TABLE IF NOT EXISTS agent_command (
                        hub_name TEXT NOT NULL,
                        command_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        command_name TEXT NOT NULL,
                        instance_id TEXT NULL,
                        target_key TEXT NOT NULL,
                        fence INTEGER NOT NULL,
                        payload_fingerprint TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        status TEXT NOT NULL,
                        confirmed_rank INTEGER NOT NULL DEFAULT -1,
                        response_json TEXT NULL,
                        status_code INTEGER NULL,
                        error_code TEXT NULL,
                        error_message TEXT NULL,
                        received_at TEXT NOT NULL,
                        executing_at TEXT NULL,
                        completed_at TEXT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (hub_name, command_id),
                        UNIQUE (hub_name, idempotency_key)
                    );

                    CREATE TABLE IF NOT EXISTS agent_command_fence (
                        hub_name TEXT NOT NULL,
                        target_key TEXT NOT NULL,
                        last_fence INTEGER NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (hub_name, target_key)
                    );

                    CREATE INDEX IF NOT EXISTS idx_agent_command_pending_ack
                    ON agent_command (hub_name, status, confirmed_rank, updated_at);
                    '''
                )
                connection.execute('PRAGMA user_version = 1')

            self._schema_ready = True

    @staticmethod
    def _bounded(value: str | None, max_length: int) -> str | None:
        value = str(value or '').strip()
        return value[:max_length] if value else None


_journal = None
_journal_lock = threading.Lock()


def get_agent_command_journal() -> AgentCommandJournal:
    global _journal

    if _journal is not None:
        return _journal

    with _journal_lock:
        if _journal is None:
            _journal = AgentCommandJournal(command_journal_path())

    return _journal
