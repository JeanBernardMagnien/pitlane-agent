import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


RUN_COLUMNS = (
    'id', 'started_at', 'ended_at', 'duration_seconds', 'status',
    'server_name', 'cpu_model', 'cpu_cores', 'cpu_threads', 'ram_total_mb',
    'test_label', 'track', 'allowed_cars_mode', 'server_profile_type',
    'start_reason', 'stop_reason',
    'max_total_drivers', 'max_simultaneous_instances',
    'cpu_total_p95', 'cpu_core_max_p95', 'ram_available_min', 'network_tx_max',
    'crash_count', 'sample_quality', 'risk_level', 'limiting_factor', 'summary_json',
    'created_at', 'updated_at',
)

# Colonnes numériques exploitables par snapshot_values() pour les calculs de percentile.
SNAPSHOT_VALUE_COLUMNS = (
    'total_connected_drivers', 'active_instances_count', 'instances_with_players_count',
    'cpu_total_percent', 'cpu_core_max_percent',
    'ram_used_mb', 'ram_available_mb', 'ram_percent',
    'network_tx_mbps', 'network_rx_mbps', 'disk_read_kbps', 'disk_write_kbps',
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _decode_snapshot_row(row) -> dict:
    snapshot = dict(row)
    snapshot['cpu_per_core'] = (
        json.loads(snapshot['cpu_per_core_json']) if snapshot.get('cpu_per_core_json') else None
    )
    snapshot['instances'] = (
        json.loads(snapshot['instances_json']) if snapshot.get('instances_json') else None
    )
    return snapshot


def _coerce_non_negative_int(value, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default

    return parsed if parsed >= 0 else default


def capacity_profiler_db_path() -> Path:
    from core import config_store

    configured = config_store.CAPACITY_PROFILER_CFG.get('db_path')
    if configured:
        return Path(configured)

    return Path(config_store.LOGGING_CFG.get('logs_path') or 'logs') / 'capacity-profiler.sqlite3'


class CapacityProfilerStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._schema_ready = False
        self._ensure_schema()

    def create_run(self, meta: dict) -> dict:
        now = _utc_now()

        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            cursor = connection.execute(
                '''
                INSERT INTO capacity_profile_runs (
                    started_at, status, server_name, cpu_model, cpu_cores, cpu_threads,
                    ram_total_mb, test_label, track, allowed_cars_mode, server_profile_type,
                    start_reason, crash_count, created_at, updated_at
                ) VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                ''',
                (
                    now,
                    meta.get('server_name'),
                    meta.get('cpu_model'),
                    meta.get('cpu_cores'),
                    meta.get('cpu_threads'),
                    meta.get('ram_total_mb'),
                    meta.get('test_label'),
                    meta.get('track'),
                    meta.get('allowed_cars_mode'),
                    meta.get('server_profile_type'),
                    meta.get('start_reason') or 'manual',
                    now,
                    now,
                ),
            )
            run_id = cursor.lastrowid
            connection.commit()

        return self.get_run(run_id)

    def insert_snapshot(self, run_id: int, snapshot: dict) -> None:
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute(
                '''
                INSERT INTO capacity_profile_snapshots (
                    run_id, captured_at, total_connected_drivers, active_instances_count,
                    instances_with_players_count, cpu_total_percent, cpu_core_max_percent,
                    cpu_per_core_json, ram_used_mb, ram_available_mb, ram_percent,
                    network_tx_mbps, network_rx_mbps, disk_read_kbps, disk_write_kbps,
                    instances_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    run_id,
                    snapshot.get('captured_at') or _utc_now(),
                    snapshot.get('total_connected_drivers'),
                    snapshot.get('active_instances_count'),
                    snapshot.get('instances_with_players_count'),
                    snapshot.get('cpu_total_percent'),
                    snapshot.get('cpu_core_max_percent'),
                    json.dumps(snapshot.get('cpu_per_core')) if snapshot.get('cpu_per_core') is not None else None,
                    snapshot.get('ram_used_mb'),
                    snapshot.get('ram_available_mb'),
                    snapshot.get('ram_percent'),
                    snapshot.get('network_tx_mbps'),
                    snapshot.get('network_rx_mbps'),
                    snapshot.get('disk_read_kbps'),
                    snapshot.get('disk_write_kbps'),
                    json.dumps(snapshot.get('instances')) if snapshot.get('instances') is not None else None,
                ),
            )
            connection.commit()

    def increment_crash_count(self, run_id: int) -> None:
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute(
                '''
                UPDATE capacity_profile_runs
                SET crash_count = crash_count + 1, updated_at = ?
                WHERE id = ? AND status = 'running'
                ''',
                (_utc_now(), run_id),
            )
            connection.commit()

    def finalize_run(
        self,
        run_id: int,
        ended_at: str,
        status: str,
        stop_reason: str,
        summary_fields: dict,
    ) -> dict:
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute(
                '''
                UPDATE capacity_profile_runs
                SET ended_at = ?,
                    status = ?,
                    stop_reason = ?,
                    duration_seconds = ?,
                    max_total_drivers = ?,
                    max_simultaneous_instances = ?,
                    cpu_total_p95 = ?,
                    cpu_core_max_p95 = ?,
                    ram_available_min = ?,
                    network_tx_max = ?,
                    sample_quality = ?,
                    risk_level = ?,
                    limiting_factor = ?,
                    summary_json = ?,
                    updated_at = ?
                WHERE id = ?
                ''',
                (
                    ended_at,
                    status,
                    stop_reason,
                    summary_fields.get('duration_seconds'),
                    summary_fields.get('max_total_drivers'),
                    summary_fields.get('max_simultaneous_instances'),
                    summary_fields.get('cpu_total_p95'),
                    summary_fields.get('cpu_core_max_p95'),
                    summary_fields.get('ram_available_min'),
                    summary_fields.get('network_tx_max'),
                    summary_fields.get('sample_quality'),
                    summary_fields.get('risk_level'),
                    summary_fields.get('limiting_factor'),
                    summary_fields.get('summary_json'),
                    _utc_now(),
                    run_id,
                ),
            )
            connection.commit()

        return self.get_run(run_id)

    def active_run(self) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM capacity_profile_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()

        return dict(row) if row else None

    def get_run(self, run_id: int) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM capacity_profile_runs WHERE id = ?', (run_id,)
            ).fetchone()

        return dict(row) if row else None

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        offset = max(0, int(offset))

        with self._connection() as connection:
            rows = connection.execute(
                '''
                SELECT * FROM capacity_profile_runs
                ORDER BY started_at DESC
                LIMIT ? OFFSET ?
                ''',
                (limit, offset),
            ).fetchall()

        return [dict(row) for row in rows]

    def list_snapshots(self, run_id: int, since: str | None = None, limit: int = 500) -> list[dict]:
        limit = max(1, min(int(limit), 5000))
        params: list = [run_id]
        since_sql = ''
        if since:
            since_sql = 'AND captured_at > ?'
            params.append(since)
        params.append(limit)

        with self._connection() as connection:
            rows = connection.execute(
                f'''
                SELECT * FROM capacity_profile_snapshots
                WHERE run_id = ? {since_sql}
                ORDER BY captured_at ASC
                LIMIT ?
                ''',
                params,
            ).fetchall()

        return [_decode_snapshot_row(row) for row in rows]

    def latest_snapshot(self, run_id: int) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                '''
                SELECT * FROM capacity_profile_snapshots
                WHERE run_id = ?
                ORDER BY captured_at DESC
                LIMIT 1
                ''',
                (run_id,),
            ).fetchone()

        return _decode_snapshot_row(row) if row else None

    def get_settings(self) -> dict:
        with self._connection() as connection:
            row = connection.execute(
                'SELECT * FROM capacity_profile_settings WHERE id = 1'
            ).fetchone()

            if row is None:
                from core import config_store

                defaults = config_store.CAPACITY_PROFILER_CFG
                connection.execute('BEGIN IMMEDIATE')
                connection.execute(
                    '''
                    INSERT OR IGNORE INTO capacity_profile_settings (
                        id, auto_start_enabled, driver_threshold,
                        start_grace_seconds, stop_grace_seconds, updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?)
                    ''',
                    (
                        1 if defaults.get('auto_start_enabled') else 0,
                        int(defaults.get('auto_start_driver_threshold') or 10),
                        int(defaults.get('auto_start_grace_seconds') or 60),
                        int(defaults.get('auto_stop_grace_seconds') or 60),
                        _utc_now(),
                    ),
                )
                connection.commit()
                row = connection.execute(
                    'SELECT * FROM capacity_profile_settings WHERE id = 1'
                ).fetchone()

        settings = dict(row)
        settings['auto_start_enabled'] = bool(settings['auto_start_enabled'])
        return settings

    def update_settings(self, patch: dict) -> dict:
        current = self.get_settings()
        auto_start_enabled = bool(patch.get('auto_start_enabled', current['auto_start_enabled']))
        driver_threshold = _coerce_non_negative_int(patch.get('driver_threshold'), current['driver_threshold'])
        start_grace_seconds = _coerce_non_negative_int(
            patch.get('start_grace_seconds'), current['start_grace_seconds'],
        )
        stop_grace_seconds = _coerce_non_negative_int(
            patch.get('stop_grace_seconds'), current['stop_grace_seconds'],
        )

        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute(
                '''
                UPDATE capacity_profile_settings
                SET auto_start_enabled = ?, driver_threshold = ?,
                    start_grace_seconds = ?, stop_grace_seconds = ?, updated_at = ?
                WHERE id = 1
                ''',
                (int(auto_start_enabled), driver_threshold, start_grace_seconds, stop_grace_seconds, _utc_now()),
            )
            connection.commit()

        return self.get_settings()

    def snapshot_values(self, run_id: int, column: str) -> list[float]:
        if column not in SNAPSHOT_VALUE_COLUMNS:
            raise ValueError(f'Colonne de snapshot non exploitable pour un percentile: {column}')

        with self._connection() as connection:
            rows = connection.execute(
                f'''
                SELECT {column} AS value FROM capacity_profile_snapshots
                WHERE run_id = ? AND {column} IS NOT NULL
                ORDER BY captured_at ASC
                ''',
                (run_id,),
            ).fetchall()

        return [float(row['value']) for row in rows]

    def reconcile_orphaned_runs(self) -> list[int]:
        from services import capacity_profiler_summary

        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id FROM capacity_profile_runs WHERE status = 'running'"
            ).fetchall()

        reconciled_ids = []
        for row in rows:
            run_id = int(row['id'])
            run = self.get_run(run_id)
            if run is None:
                continue

            snapshots = self.list_snapshots(run_id, limit=5000)
            ended_at = _utc_now()
            summary_fields = capacity_profiler_summary.compute_summary(run, snapshots, ended_at=ended_at)
            self.finalize_run(run_id, ended_at, 'interrupted', 'agent_restart', summary_fields)
            reconciled_ids.append(run_id)

        return reconciled_ids

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
                    CREATE TABLE IF NOT EXISTS capacity_profile_runs (
                        id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                        started_at                  TEXT NOT NULL,
                        ended_at                    TEXT NULL,
                        duration_seconds            INTEGER NULL,
                        status                      TEXT NOT NULL DEFAULT 'running',
                        server_name                 TEXT NULL,
                        cpu_model                   TEXT NULL,
                        cpu_cores                   INTEGER NULL,
                        cpu_threads                 INTEGER NULL,
                        ram_total_mb                INTEGER NULL,
                        test_label                  TEXT NULL,
                        track                       TEXT NULL,
                        allowed_cars_mode           TEXT NULL,
                        server_profile_type         TEXT NULL,
                        start_reason                TEXT NOT NULL DEFAULT 'manual',
                        stop_reason                 TEXT NULL,
                        max_total_drivers           INTEGER NULL,
                        max_simultaneous_instances  INTEGER NULL,
                        cpu_total_p95               REAL NULL,
                        cpu_core_max_p95            REAL NULL,
                        ram_available_min           REAL NULL,
                        network_tx_max              REAL NULL,
                        crash_count                 INTEGER NOT NULL DEFAULT 0,
                        sample_quality              REAL NULL,
                        risk_level                  TEXT NULL,
                        limiting_factor             TEXT NULL,
                        summary_json                TEXT NULL,
                        created_at                  TEXT NOT NULL,
                        updated_at                  TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_capacity_profile_runs_started_at
                    ON capacity_profile_runs (started_at);

                    CREATE INDEX IF NOT EXISTS idx_capacity_profile_runs_status
                    ON capacity_profile_runs (status);

                    CREATE UNIQUE INDEX IF NOT EXISTS idx_capacity_profile_runs_single_active
                    ON capacity_profile_runs (status) WHERE status = 'running';

                    CREATE TABLE IF NOT EXISTS capacity_profile_snapshots (
                        id                            INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id                        INTEGER NOT NULL REFERENCES capacity_profile_runs(id) ON DELETE CASCADE,
                        captured_at                   TEXT NOT NULL,
                        total_connected_drivers       INTEGER NULL,
                        active_instances_count        INTEGER NULL,
                        instances_with_players_count  INTEGER NULL,
                        cpu_total_percent             REAL NULL,
                        cpu_core_max_percent          REAL NULL,
                        cpu_per_core_json             TEXT NULL,
                        ram_used_mb                   REAL NULL,
                        ram_available_mb              REAL NULL,
                        ram_percent                   REAL NULL,
                        network_tx_mbps               REAL NULL,
                        network_rx_mbps               REAL NULL,
                        disk_read_kbps                REAL NULL,
                        disk_write_kbps               REAL NULL,
                        instances_json                TEXT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_capacity_profile_snapshots_run_id
                    ON capacity_profile_snapshots (run_id, captured_at);

                    CREATE TABLE IF NOT EXISTS capacity_profile_settings (
                        id                    INTEGER PRIMARY KEY CHECK (id = 1),
                        auto_start_enabled    INTEGER NOT NULL DEFAULT 0,
                        driver_threshold      INTEGER NOT NULL DEFAULT 10,
                        start_grace_seconds   INTEGER NOT NULL DEFAULT 60,
                        stop_grace_seconds    INTEGER NOT NULL DEFAULT 60,
                        updated_at            TEXT NOT NULL
                    );
                    '''
                )
                connection.execute('PRAGMA user_version = 2')

            self._schema_ready = True


_store = None
_store_lock = threading.Lock()


def get_capacity_profiler_store() -> CapacityProfilerStore:
    global _store

    if _store is not None:
        return _store

    with _store_lock:
        if _store is None:
            _store = CapacityProfilerStore(capacity_profiler_db_path())

    return _store
