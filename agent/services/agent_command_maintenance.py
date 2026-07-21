import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


STATUSES = ('received', 'executing', 'succeeded', 'failed')
DEFAULT_SUCCESS_RETENTION_DAYS = 365
DEFAULT_STALE_ACK_SECONDS = 300
DEFAULT_CLEANUP_LIMIT = 5000


class AgentCommandMaintenance:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def metrics(
        self,
        hub_name: str | None = None,
        retention_days: int = DEFAULT_SUCCESS_RETENTION_DAYS,
        stale_ack_seconds: int = DEFAULT_STALE_ACK_SECONDS,
        now: datetime | None = None,
    ) -> dict:
        retention_days = max(1, int(retention_days))
        stale_ack_seconds = max(1, int(stale_ack_seconds))
        now = self._normalized_datetime(now)
        purge_cutoff = self._iso_datetime(now - timedelta(days=retention_days))
        stale_cutoff = self._iso_datetime(now - timedelta(seconds=stale_ack_seconds))
        scope_sql = 'hub_name = ? AND ' if hub_name else ''
        scope_params = [str(hub_name)] if hub_name else []
        pending_sql = '''
            (
                (status = 'received' AND confirmed_rank < 0)
                OR (status = 'executing' AND confirmed_rank < 1)
                OR (status IN ('succeeded', 'failed') AND confirmed_rank < 2)
            )
        '''

        with self._connection() as connection:
            status_rows = connection.execute(
                f'''
                SELECT status, COUNT(*) AS command_count
                FROM agent_command
                {'WHERE hub_name = ?' if hub_name else ''}
                GROUP BY status
                ''',
                scope_params,
            ).fetchall()
            pending_row = connection.execute(
                f'''
                SELECT COUNT(*) AS command_count, MIN(updated_at) AS oldest_at
                FROM agent_command
                WHERE {scope_sql}{pending_sql}
                ''',
                scope_params,
            ).fetchone()
            stale_count = connection.execute(
                f'''
                SELECT COUNT(*)
                FROM agent_command
                WHERE {scope_sql}{pending_sql}
                  AND updated_at <= ?
                ''',
                [*scope_params, stale_cutoff],
            ).fetchone()[0]
            purgeable_count = connection.execute(
                f'''
                SELECT COUNT(*)
                FROM agent_command
                WHERE {scope_sql}status = 'succeeded'
                  AND confirmed_rank >= 2
                  AND updated_at <= ?
                ''',
                [*scope_params, purge_cutoff],
            ).fetchone()[0]

        statuses = {status: 0 for status in STATUSES}
        for row in status_rows:
            statuses[str(row['status'])] = int(row['command_count'])

        reasons = []
        status = 'healthy'
        if int(stale_count) > 0:
            status = 'warning'
            reasons.append('acknowledgement_pending_too_long')

        return {
            'status': status,
            'reasons': reasons,
            'total': sum(statuses.values()),
            'statuses': statuses,
            'pending_acknowledgements': int(pending_row['command_count']),
            'stale_acknowledgements': int(stale_count),
            'oldest_pending_ack_at': pending_row['oldest_at'],
            'purgeable_succeeded': int(purgeable_count),
            'success_retention_days': retention_days,
            'database_bytes': self._database_size_bytes(),
        }

    def purge_confirmed_successes(
        self,
        retention_days: int = DEFAULT_SUCCESS_RETENTION_DAYS,
        limit: int = DEFAULT_CLEANUP_LIMIT,
        execute: bool = False,
        now: datetime | None = None,
    ) -> dict:
        retention_days = max(1, int(retention_days))
        limit = max(1, min(int(limit), 5000))
        now = self._normalized_datetime(now)
        cutoff = self._iso_datetime(now - timedelta(days=retention_days))

        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = connection.execute(
                '''
                SELECT hub_name, command_id
                FROM agent_command
                WHERE status = 'succeeded'
                  AND confirmed_rank >= 2
                  AND updated_at <= ?
                ORDER BY updated_at ASC
                LIMIT ?
                ''',
                (cutoff, limit),
            ).fetchall()

            processed = 0
            if execute and rows:
                connection.executemany(
                    '''
                    DELETE FROM agent_command
                    WHERE hub_name = ? AND command_id = ?
                      AND status = 'succeeded' AND confirmed_rank >= 2
                    ''',
                    [(row['hub_name'], row['command_id']) for row in rows],
                )
                processed = int(connection.total_changes)

            connection.commit()

        return {
            'dry_run': not execute,
            'cutoff': cutoff,
            'candidates': len(rows),
            'processed': processed,
            'success_retention_days': retention_days,
            'limit': limit,
        }

    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        connection.execute('PRAGMA busy_timeout = 5000')
        return connection

    @staticmethod
    def _normalized_datetime(value: datetime | None) -> datetime:
        value = value or datetime.now(timezone.utc)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso_datetime(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')

    def _database_size_bytes(self) -> int:
        return sum(
            path.stat().st_size
            for path in (self.path, Path(f'{self.path}-wal'))
            if path.exists()
        )


def positive_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed > 0 else default
