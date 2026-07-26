import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.capacity_profiler_store import CapacityProfilerStore


def _store() -> tuple[CapacityProfilerStore, tempfile.TemporaryDirectory]:
    temporary_directory = tempfile.TemporaryDirectory()
    store = CapacityProfilerStore(Path(temporary_directory.name) / 'capacity-profiler.sqlite3')
    return store, temporary_directory


class CapacityProfilerStoreTest(unittest.TestCase):
    def test_schema_creation_is_idempotent(self):
        store, temporary_directory = _store()
        with temporary_directory:
            # Ré-instancier sur le même fichier ne doit pas lever d'erreur (CREATE TABLE IF NOT EXISTS).
            CapacityProfilerStore(store.path)

    def test_technical_history_schema_is_extended_without_losing_existing_rows(self):
        temporary_directory = tempfile.TemporaryDirectory()
        with temporary_directory:
            path = Path(temporary_directory.name) / 'capacity-profiler.sqlite3'
            with sqlite3.connect(path) as connection:
                connection.execute(
                    '''
                    CREATE TABLE technical_history_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        captured_at TEXT NOT NULL,
                        cpu_total_percent REAL NULL,
                        ram_used_mb REAL NULL,
                        ram_total_mb REAL NULL,
                        ram_percent REAL NULL,
                        active_instances_count INTEGER NOT NULL DEFAULT 0,
                        total_connected_drivers INTEGER NOT NULL DEFAULT 0,
                        instances_json TEXT NOT NULL
                    )
                    '''
                )
                connection.execute(
                    '''
                    INSERT INTO technical_history_snapshots (
                        captured_at, instances_json
                    ) VALUES ('2026-07-24T12:00:00Z', '[]')
                    '''
                )

            store = CapacityProfilerStore(path)
            existing = store.list_technical_history(limit=1)[0]
            store.insert_technical_history_snapshot({
                'captured_at': '2026-07-24T12:01:00Z',
                'cpu_per_core': [75, 20],
                'network_tx_mbps': 1.25,
                'instances': [],
            })
            extended = store.list_technical_history(limit=1)[0]

            self.assertEqual('2026-07-24T12:00:00Z', existing['captured_at'])
            self.assertIsNone(existing['cpu_per_core'])
            self.assertEqual([75, 20], extended['cpu_per_core'])
            self.assertEqual(1.25, extended['network_tx_mbps'])

    def test_create_run_defaults_to_running_status_and_manual_start_reason(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'test-machine', 'test_label': 'Public Spa'})

            self.assertEqual('running', run['status'])
            self.assertEqual('manual', run['start_reason'])
            self.assertEqual('test-machine', run['server_name'])
            self.assertEqual(0, run['crash_count'])
            self.assertIsNotNone(run['id'])

    def test_active_run_returns_the_running_row(self):
        store, temporary_directory = _store()
        with temporary_directory:
            created = store.create_run({'server_name': 'm1'})

            active = store.active_run()

            self.assertIsNotNone(active)
            self.assertEqual(created['id'], active['id'])

    def test_active_run_is_none_when_nothing_running(self):
        store, temporary_directory = _store()
        with temporary_directory:
            self.assertIsNone(store.active_run())

    def test_single_active_run_index_rejects_a_second_concurrent_running_row(self):
        store, temporary_directory = _store()
        with temporary_directory:
            store.create_run({'server_name': 'm1'})

            with self.assertRaises(sqlite3.IntegrityError):
                store.create_run({'server_name': 'm2'})

    def test_finalize_run_after_stop_frees_the_active_slot(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.finalize_run(
                run['id'], '2026-07-24T12:00:00Z', 'completed', 'manual',
                {'duration_seconds': 120, 'risk_level': 'OK', 'limiting_factor': 'none'},
            )

            self.assertIsNone(store.active_run())
            second_run = store.create_run({'server_name': 'm2'})
            self.assertIsNotNone(second_run)

    def test_finalize_run_persists_summary_fields(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            finalized = store.finalize_run(
                run['id'], '2026-07-24T12:00:00Z', 'completed', 'manual',
                {
                    'duration_seconds': 300,
                    'max_total_drivers': 42,
                    'max_simultaneous_instances': 3,
                    'cpu_total_p95': 55.5,
                    'cpu_core_max_p95': 88.8,
                    'ram_available_min': 20.0,
                    'network_tx_max': 12.3,
                    'sample_quality': 0.95,
                    'risk_level': 'RISK',
                    'limiting_factor': 'cpu_single_core',
                    'summary_json': '{"note": "ok"}',
                },
            )

            self.assertEqual('completed', finalized['status'])
            self.assertEqual('manual', finalized['stop_reason'])
            self.assertEqual(300, finalized['duration_seconds'])
            self.assertEqual(42, finalized['max_total_drivers'])
            self.assertEqual('RISK', finalized['risk_level'])
            self.assertEqual('cpu_single_core', finalized['limiting_factor'])

    def test_insert_snapshot_and_list_snapshots_roundtrip(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.insert_snapshot(run['id'], {
                'captured_at': '2026-07-24T12:00:00Z',
                'total_connected_drivers': 30,
                'cpu_total_percent': 40.0,
                'cpu_core_max_percent': 70.0,
                'cpu_per_core': [70.0, 40.0, 30.0, 20.0],
                'instances': [{'id': 'instance-1', 'connected_drivers': 30}],
            })
            store.insert_snapshot(run['id'], {
                'captured_at': '2026-07-24T12:00:08Z',
                'total_connected_drivers': 32,
                'cpu_total_percent': 42.0,
                'cpu_core_max_percent': 72.0,
            })

            snapshots = store.list_snapshots(run['id'])

            self.assertEqual(2, len(snapshots))
            self.assertEqual([70.0, 40.0, 30.0, 20.0], snapshots[0]['cpu_per_core'])
            self.assertEqual([{'id': 'instance-1', 'connected_drivers': 30}], snapshots[0]['instances'])
            self.assertIsNone(snapshots[1]['cpu_per_core'])
            # Ordre chronologique croissant.
            self.assertEqual('2026-07-24T12:00:00Z', snapshots[0]['captured_at'])
            self.assertEqual('2026-07-24T12:00:08Z', snapshots[1]['captured_at'])

    def test_list_snapshots_since_filters_out_earlier_rows(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:00Z'})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:08Z'})

            snapshots = store.list_snapshots(run['id'], since='2026-07-24T12:00:00Z')

            self.assertEqual(1, len(snapshots))
            self.assertEqual('2026-07-24T12:00:08Z', snapshots[0]['captured_at'])

    def test_snapshot_values_returns_only_non_null_numeric_column_in_order(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:00Z', 'cpu_core_max_percent': 70.0})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:08Z', 'cpu_core_max_percent': None})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:16Z', 'cpu_core_max_percent': 82.0})

            values = store.snapshot_values(run['id'], 'cpu_core_max_percent')

            self.assertEqual([70.0, 82.0], values)

    def test_snapshot_values_rejects_unknown_column(self):
        store, temporary_directory = _store()
        with temporary_directory:
            with self.assertRaises(ValueError):
                store.snapshot_values(1, 'summary_json')

    def test_list_runs_orders_most_recent_first(self):
        store, temporary_directory = _store()
        with temporary_directory:
            first = store.create_run({'server_name': 'm1'})
            store.finalize_run(first['id'], '2026-07-24T12:00:00Z', 'completed', 'manual', {})
            second = store.create_run({'server_name': 'm2'})
            store.finalize_run(second['id'], '2026-07-24T13:00:00Z', 'completed', 'manual', {})

            runs = store.list_runs()

            self.assertEqual(second['id'], runs[0]['id'])
            self.assertEqual(first['id'], runs[1]['id'])

    def test_reconcile_orphaned_runs_finalizes_leftover_running_rows(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:00Z', 'cpu_total_percent': 20.0})

            reconciled_ids = store.reconcile_orphaned_runs()

            self.assertEqual([run['id']], reconciled_ids)
            reconciled = store.get_run(run['id'])
            self.assertEqual('interrupted', reconciled['status'])
            self.assertEqual('agent_restart', reconciled['stop_reason'])
            self.assertIsNotNone(reconciled['ended_at'])
            self.assertIsNone(store.active_run())

    def test_reconcile_orphaned_runs_is_a_noop_when_nothing_is_running(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.finalize_run(run['id'], '2026-07-24T12:00:00Z', 'completed', 'manual', {})

            reconciled_ids = store.reconcile_orphaned_runs()

            self.assertEqual([], reconciled_ids)

    def test_increment_crash_count_only_affects_running_run(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.increment_crash_count(run['id'])
            store.increment_crash_count(run['id'])

            self.assertEqual(2, store.get_run(run['id'])['crash_count'])

            store.finalize_run(run['id'], '2026-07-24T12:00:00Z', 'completed', 'manual', {})
            store.increment_crash_count(run['id'])  # ignoré: run n'est plus 'running'

            self.assertEqual(2, store.get_run(run['id'])['crash_count'])


    def test_latest_snapshot_returns_the_most_recent_row_not_the_oldest(self):
        store, temporary_directory = _store()
        with temporary_directory:
            run = store.create_run({'server_name': 'm1'})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:00Z', 'cpu_total_percent': 10.0})
            store.insert_snapshot(run['id'], {'captured_at': '2026-07-24T12:00:08Z', 'cpu_total_percent': 20.0})

            latest = store.latest_snapshot(run['id'])

            self.assertEqual('2026-07-24T12:00:08Z', latest['captured_at'])
            self.assertEqual(20.0, latest['cpu_total_percent'])

    def test_latest_snapshot_is_none_without_snapshots(self):
        store, temporary_directory = _store()
        with temporary_directory:
            self.assertIsNone(store.latest_snapshot(999999))

    def test_technical_history_returns_latest_window_in_chronological_order(self):
        store, temporary_directory = _store()
        with temporary_directory:
            for minute in range(4):
                store.insert_technical_history_snapshot({
                    'captured_at': f'2026-07-24T12:0{minute}:00Z',
                    'cpu_total_percent': 20.0 + minute,
                    'cpu_core_max_percent': 40.0 + minute,
                    'cpu_per_core': [40.0 + minute, 20.0 + minute],
                    'network_tx_mbps': 0.5 + minute,
                    'disk_write_kbps': 10.0 + minute,
                    'active_instances_count': 2,
                    'total_connected_drivers': minute,
                    'instances': [{
                        'id': 'server1',
                        'cpu_percent': 10.0 + minute,
                        'connected_drivers': minute,
                    }],
                })

            snapshots = store.list_technical_history(limit=2)

            self.assertEqual(
                ['2026-07-24T12:02:00Z', '2026-07-24T12:03:00Z'],
                [snapshot['captured_at'] for snapshot in snapshots],
            )
            self.assertEqual('server1', snapshots[0]['instances'][0]['id'])
            self.assertEqual(42.0, snapshots[0]['cpu_core_max_percent'])
            self.assertEqual([42.0, 22.0], snapshots[0]['cpu_per_core'])
            self.assertEqual(2.5, snapshots[0]['network_tx_mbps'])
            self.assertEqual(12.0, snapshots[0]['disk_write_kbps'])
            self.assertNotIn('instances_json', snapshots[0])

    def test_technical_history_since_and_purge_are_bounded(self):
        store, temporary_directory = _store()
        with temporary_directory:
            for minute in range(3):
                store.insert_technical_history_snapshot({
                    'captured_at': f'2026-07-24T12:0{minute}:00Z',
                    'instances': [],
                })

            snapshots = store.list_technical_history(
                since='2026-07-24T12:01:00Z',
                limit=10,
            )
            purged = store.purge_technical_history(
                before='2026-07-24T12:02:00Z',
                limit=1,
            )

            self.assertEqual(2, len(snapshots))
            self.assertEqual(1, purged)
            self.assertEqual(2, len(store.list_technical_history(limit=10)))

    def test_get_settings_seeds_defaults_from_config_on_first_call(self):
        store, temporary_directory = _store()
        with temporary_directory:
            fake_cfg = {
                'auto_start_enabled': True,
                'auto_start_driver_threshold': 15,
                'auto_start_grace_seconds': 30,
                'auto_stop_grace_seconds': 45,
            }
            with patch('core.config_store.CAPACITY_PROFILER_CFG', fake_cfg):
                settings = store.get_settings()

            self.assertTrue(settings['auto_start_enabled'])
            self.assertEqual(15, settings['driver_threshold'])
            self.assertEqual(30, settings['start_grace_seconds'])
            self.assertEqual(45, settings['stop_grace_seconds'])

    def test_get_settings_is_seeded_only_once(self):
        store, temporary_directory = _store()
        with temporary_directory:
            with patch('core.config_store.CAPACITY_PROFILER_CFG', {'auto_start_driver_threshold': 15}):
                store.get_settings()
            with patch('core.config_store.CAPACITY_PROFILER_CFG', {'auto_start_driver_threshold': 99}):
                settings = store.get_settings()

            self.assertEqual(15, settings['driver_threshold'])

    def test_update_settings_persists_changes(self):
        store, temporary_directory = _store()
        with temporary_directory:
            with patch('core.config_store.CAPACITY_PROFILER_CFG', {}):
                store.get_settings()

            updated = store.update_settings({
                'auto_start_enabled': True,
                'driver_threshold': 20,
                'start_grace_seconds': 90,
                'stop_grace_seconds': 120,
            })

            self.assertTrue(updated['auto_start_enabled'])
            self.assertEqual(20, updated['driver_threshold'])
            self.assertEqual(90, updated['start_grace_seconds'])
            self.assertEqual(120, updated['stop_grace_seconds'])
            self.assertEqual(updated, store.get_settings())

    def test_update_settings_tolerates_invalid_values_by_keeping_the_previous_ones(self):
        store, temporary_directory = _store()
        with temporary_directory:
            with patch('core.config_store.CAPACITY_PROFILER_CFG', {}):
                store.get_settings()
            store.update_settings({'driver_threshold': 20})

            updated = store.update_settings({'driver_threshold': 'not-a-number', 'start_grace_seconds': -5})

            self.assertEqual(20, updated['driver_threshold'])  # invalide -> valeur précédente conservée
            self.assertEqual(60, updated['start_grace_seconds'])  # négatif -> valeur précédente conservée


if __name__ == '__main__':
    unittest.main()
