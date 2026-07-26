import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.capacity_profiler_maintenance import CapacityProfilerMaintenance
from services.capacity_profiler_store import CapacityProfilerStore


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace('+00:00', 'Z')


class CapacityProfilerMaintenanceTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / 'capacity-profiler.sqlite3'
        self.store = CapacityProfilerStore(self.db_path)
        self.maintenance = CapacityProfilerMaintenance(self.db_path)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _old_completed_run(self, days_ago: int) -> dict:
        run = self.store.create_run({'server_name': 'm1'})
        ended_at = _iso(NOW - timedelta(days=days_ago))
        self.store.finalize_run(run['id'], ended_at, 'completed', 'manual', {})
        return self.store.get_run(run['id'])

    def test_metrics_counts_match_seeded_runs_and_snapshots(self):
        old_run = self._old_completed_run(days_ago=40)
        self.store.insert_snapshot(old_run['id'], {'captured_at': _iso(NOW - timedelta(days=40))})
        self.store.create_run({'server_name': 'active'})

        metrics = self.maintenance.metrics(snapshot_retention_days=30, run_retention_days=365, now=NOW)

        self.assertEqual(2, metrics['total_runs'])
        self.assertEqual(1, metrics['statuses']['running'])
        self.assertEqual(1, metrics['statuses']['completed'])
        self.assertEqual(1, metrics['total_snapshots'])
        self.assertEqual(1, metrics['purgeable_snapshots'])
        self.assertEqual(0, metrics['purgeable_runs'])  # run_retention_days=365, run is only 40 days old
        self.assertGreater(metrics['database_bytes'], 0)

    def test_purge_old_snapshots_is_dry_run_by_default(self):
        old_run = self._old_completed_run(days_ago=40)
        self.store.insert_snapshot(old_run['id'], {'captured_at': _iso(NOW - timedelta(days=40))})

        result = self.maintenance.purge_old_snapshots(retention_days=30, now=NOW)

        self.assertTrue(result['dry_run'])
        self.assertEqual(1, result['candidates'])
        self.assertEqual(0, result['processed'])
        self.assertEqual(1, len(self.store.list_snapshots(old_run['id'])))

    def test_purge_old_snapshots_never_touches_the_active_run(self):
        active_run = self.store.create_run({'server_name': 'active'})
        self.store.insert_snapshot(active_run['id'], {'captured_at': _iso(NOW - timedelta(days=400))})

        result = self.maintenance.purge_old_snapshots(retention_days=30, execute=True, now=NOW)

        self.assertEqual(0, result['candidates'])
        self.assertEqual(1, len(self.store.list_snapshots(active_run['id'])))

    def test_purge_old_snapshots_respects_limit(self):
        old_run = self._old_completed_run(days_ago=40)
        for i in range(5):
            self.store.insert_snapshot(old_run['id'], {'captured_at': _iso(NOW - timedelta(days=40, seconds=i))})

        result = self.maintenance.purge_old_snapshots(retention_days=30, limit=2, execute=True, now=NOW)

        self.assertEqual(2, result['candidates'])
        self.assertEqual(2, result['processed'])
        self.assertEqual(3, len(self.store.list_snapshots(old_run['id'])))

    def test_purge_old_snapshots_execute_actually_deletes(self):
        old_run = self._old_completed_run(days_ago=40)
        self.store.insert_snapshot(old_run['id'], {'captured_at': _iso(NOW - timedelta(days=40))})

        result = self.maintenance.purge_old_snapshots(retention_days=30, execute=True, now=NOW)

        self.assertFalse(result['dry_run'])
        self.assertEqual(1, result['processed'])
        self.assertEqual(0, len(self.store.list_snapshots(old_run['id'])))

    def test_purge_old_runs_cascades_to_snapshots(self):
        old_run = self._old_completed_run(days_ago=400)
        self.store.insert_snapshot(old_run['id'], {'captured_at': _iso(NOW - timedelta(days=400))})

        result = self.maintenance.purge_old_runs(retention_days=365, execute=True, now=NOW)

        self.assertEqual(1, result['processed'])
        self.assertIsNone(self.store.get_run(old_run['id']))

    def test_purge_old_runs_never_touches_the_active_run(self):
        self.store.create_run({'server_name': 'active'})

        # Même avec un retention_days de 1 jour, un run 'running' ne doit jamais être purgé.
        result = self.maintenance.purge_old_runs(retention_days=1, execute=True, now=NOW + timedelta(days=10))

        self.assertEqual(0, result['candidates'])
        self.assertIsNotNone(self.store.active_run())


if __name__ == '__main__':
    unittest.main()
