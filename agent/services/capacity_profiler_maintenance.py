import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DEFAULT_SNAPSHOT_RETENTION_DAYS = 30
DEFAULT_RUN_RETENTION_DAYS = 365
DEFAULT_CLEANUP_LIMIT = 5000

RUN_STATUSES = ('running', 'completed', 'interrupted')


class CapacityProfilerMaintenance:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def metrics(
        self,
        snapshot_retention_days: int = DEFAULT_SNAPSHOT_RETENTION_DAYS,
        run_retention_days: int = DEFAULT_RUN_RETENTION_DAYS,
        now: datetime | None = None,
    ) -> dict:
        snapshot_retention_days = max(1, int(snapshot_retention_days))
        run_retention_days = max(1, int(run_retention_days))
        now = self._normalized_datetime(now)
        snapshot_cutoff = self._iso_datetime(now - timedelta(days=snapshot_retention_days))
        run_cutoff = self._iso_datetime(now - timedelta(days=run_retention_days))

        with self._connection() as connection:
            status_rows = connection.execute(
                '''
                SELECT status, COUNT(*) AS run_count
                FROM capacity_profile_runs
                GROUP BY status
                '''
            ).fetchall()
            total_snapshots = connection.execute(
                'SELECT COUNT(*) FROM capacity_profile_snapshots'
            ).fetchone()[0]
            oldest_run_started_at = connection.execute(
                'SELECT MIN(started_at) FROM capacity_profile_runs'
            ).fetchone()[0]
            purgeable_snapshots = connection.execute(
                '''
                SELECT COUNT(*)
                FROM capacity_profile_snapshots s
                JOIN capacity_profile_runs r ON r.id = s.run_id
                WHERE r.status != 'running'
                  AND COALESCE(r.ended_at, r.started_at) <= ?
                ''',
                (snapshot_cutoff,),
            ).fetchone()[0]
            purgeable_runs = connection.execute(
                '''
                SELECT COUNT(*)
                FROM capacity_profile_runs
                WHERE status != 'running'
                  AND COALESCE(ended_at, started_at) <= ?
                ''',
                (run_cutoff,),
            ).fetchone()[0]

        statuses = {status: 0 for status in RUN_STATUSES}
        for row in status_rows:
            statuses[str(row['status'])] = int(row['run_count'])

        return {
            'status': 'healthy',
            'reasons': [],
            'total_runs': sum(statuses.values()),
            'statuses': statuses,
            'total_snapshots': int(total_snapshots),
            'oldest_run_started_at': oldest_run_started_at,
            'purgeable_snapshots': int(purgeable_snapshots),
            'purgeable_runs': int(purgeable_runs),
            'snapshot_retention_days': snapshot_retention_days,
            'run_retention_days': run_retention_days,
            'database_bytes': self._database_size_bytes(),
        }

    def purge_old_snapshots(
        self,
        retention_days: int = DEFAULT_SNAPSHOT_RETENTION_DAYS,
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
                SELECT s.id
                FROM capacity_profile_snapshots s
                JOIN capacity_profile_runs r ON r.id = s.run_id
                WHERE r.status != 'running'
                  AND COALESCE(r.ended_at, r.started_at) <= ?
                ORDER BY s.captured_at ASC
                LIMIT ?
                ''',
                (cutoff, limit),
            ).fetchall()

            processed = 0
            if execute and rows:
                connection.executemany(
                    'DELETE FROM capacity_profile_snapshots WHERE id = ?',
                    [(row['id'],) for row in rows],
                )
                processed = int(connection.total_changes)

            connection.commit()

        return {
            'dry_run': not execute,
            'cutoff': cutoff,
            'candidates': len(rows),
            'processed': processed,
            'snapshot_retention_days': retention_days,
            'limit': limit,
        }

    def purge_old_runs(
        self,
        retention_days: int = DEFAULT_RUN_RETENTION_DAYS,
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
                SELECT id
                FROM capacity_profile_runs
                WHERE status != 'running'
                  AND COALESCE(ended_at, started_at) <= ?
                ORDER BY started_at ASC
                LIMIT ?
                ''',
                (cutoff, limit),
            ).fetchall()

            processed = 0
            if execute and rows:
                # ON DELETE CASCADE (PRAGMA foreign_keys=ON par connexion) supprime aussi les
                # snapshots restants : total_changes compterait ces suppressions en cascade en
                # plus des runs, donc on compte les runs ciblés explicitement.
                connection.executemany(
                    "DELETE FROM capacity_profile_runs WHERE id = ? AND status != 'running'",
                    [(row['id'],) for row in rows],
                )
                processed = len(rows)

            connection.commit()

        return {
            'dry_run': not execute,
            'cutoff': cutoff,
            'candidates': len(rows),
            'processed': processed,
            'run_retention_days': retention_days,
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
