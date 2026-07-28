import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from services import capacity_profiler_runner
from services.capacity_profiler_store import CapacityProfilerStore


def _fake_snapshot(previous_state):
    snapshot = {
        'captured_at': capacity_profiler_runner._utc_now(),
        'total_connected_drivers': 20,
        'active_instances_count': 1,
        'instances_with_players_count': 1,
        'cpu_total_percent': 50.0,
        'cpu_core_max_percent': 60.0,
        'cpu_per_core': [60.0, 40.0],
        'ram_used_mb': 8000.0,
        'ram_available_mb': 24000.0,
        'ram_percent': 25.0,
        'network_tx_mbps': None,
        'network_rx_mbps': None,
        'disk_read_kbps': None,
        'disk_write_kbps': None,
        'instances': [],
    }
    return snapshot, {}, []


class CapacityProfilerRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = CapacityProfilerStore(Path(self.temporary_directory.name) / 'capacity-profiler.sqlite3')

        self.addCleanup(capacity_profiler_runner._active.update, {'run_id': None, 'thread': None, 'stop_event': None})
        capacity_profiler_runner._active.update(run_id=None, thread=None, stop_event=None)

        store_patcher = patch('services.capacity_profiler_runner._store', return_value=self.store)
        self.addCleanup(store_patcher.stop)
        store_patcher.start()

        cfg_patcher = patch.object(
            capacity_profiler_runner.config_store, 'CAPACITY_PROFILER_CFG',
            {'sample_interval_seconds': 0.02, 'max_run_duration_seconds': 3600, 'server_name': 'test-machine'},
        )
        self.addCleanup(cfg_patcher.stop)
        cfg_patcher.start()

        sampler_patcher = patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot', side_effect=_fake_snapshot,
        )
        self.addCleanup(sampler_patcher.stop)
        sampler_patcher.start()

        maintenance_patcher = patch('services.capacity_profiler_runner._maybe_run_maintenance')
        self.addCleanup(maintenance_patcher.stop)
        maintenance_patcher.start()

    def test_start_run_creates_an_active_run(self):
        run, status_code = capacity_profiler_runner.start_run({'test_label': 'Public Spa'})

        self.assertEqual(201, status_code)
        self.assertEqual('running', run['status'])
        self.assertEqual('test-machine', run['server_name'])
        self.assertEqual('Public Spa', run['test_label'])

        capacity_profiler_runner.stop_run(run['id'])

    def test_start_run_rejects_a_second_concurrent_run(self):
        first_run, first_status = capacity_profiler_runner.start_run({})
        second_run, second_status = capacity_profiler_runner.start_run({})

        self.assertEqual(201, first_status)
        self.assertEqual(409, second_status)
        self.assertEqual('run_already_active', second_run['error'])

        capacity_profiler_runner.stop_run(first_run['id'])

    def test_stop_run_on_unknown_run_id_returns_404(self):
        result, status_code = capacity_profiler_runner.stop_run(999999)

        self.assertEqual(404, status_code)
        self.assertEqual('run_not_active', result['error'])

    def test_full_lifecycle_produces_a_completed_run_with_summary(self):
        run, _ = capacity_profiler_runner.start_run({'test_label': 'Endurance 4h'})

        time.sleep(0.15)  # laisse quelques ticks s'accumuler (interval = 0.02s)

        finalized, status_code = capacity_profiler_runner.stop_run(run['id'], stop_reason='manual')

        self.assertEqual(200, status_code)
        self.assertEqual('completed', finalized['status'])
        self.assertEqual('manual', finalized['stop_reason'])
        self.assertIsNotNone(finalized['ended_at'])
        self.assertIsNotNone(finalized['cpu_total_p95'])
        self.assertIn(finalized['risk_level'], ('OK', 'WATCH', 'RISK', 'CRITICAL'))

        snapshots = self.store.list_snapshots(run['id'])
        self.assertGreater(len(snapshots), 0)

        # Le run n'est plus actif après finalisation.
        self.assertIsNone(self.store.active_run())

    def test_current_status_reports_live_risk_while_a_run_is_active(self):
        run, _ = capacity_profiler_runner.start_run({})
        time.sleep(0.1)

        status = capacity_profiler_runner.current_status()

        self.assertTrue(status['active'])
        self.assertEqual(run['id'], status['run']['id'])
        self.assertIn(status['live_risk_level'], ('OK', 'WATCH', 'RISK', 'CRITICAL'))

        capacity_profiler_runner.stop_run(run['id'])

    def test_current_status_is_none_without_an_active_run(self):
        self.assertIsNone(capacity_profiler_runner.current_status())

    def test_history_exposes_exact_cpu_and_ram_peaks(self):
        run = self.store.create_run({
            'server_name': 'test-machine',
            'ram_total_mb': 32000,
        })
        self.store.finalize_run(
            run['id'],
            '2026-07-24T12:10:00Z',
            'completed',
            'manual',
            {
                'cpu_core_max_p95': 88.8,
                'ram_available_min': 25.0,
                'summary_json': json.dumps({
                    'cpu_core_max_percent': {
                        'min': 40.0,
                        'max': 96.4,
                        'mean': 70.0,
                        'count': 10,
                    },
                }),
            },
        )

        history_run = capacity_profiler_runner.list_runs()[0]

        self.assertEqual(96.4, history_run['cpu_core_peak_percent'])
        self.assertEqual(25.0, history_run['ram_available_min_percent'])
        self.assertEqual(75.0, history_run['ram_used_peak_percent'])
        self.assertEqual(8000.0, history_run['ram_available_min_mb'])
        self.assertEqual(24000.0, history_run['ram_used_peak_mb'])

    def test_run_auto_stops_after_max_duration_with_timeout_reason(self):
        with patch.object(
            capacity_profiler_runner.config_store, 'CAPACITY_PROFILER_CFG',
            {'sample_interval_seconds': 0.02, 'max_run_duration_seconds': 0.05},
        ):
            run, _ = capacity_profiler_runner.start_run({})

            # Attend que la boucle d'échantillonnage s'auto-arrête (filet de sécurité).
            for _ in range(50):
                if capacity_profiler_runner._active['run_id'] is None:
                    break
                time.sleep(0.02)

        finalized = self.store.get_run(run['id'])
        self.assertEqual('completed', finalized['status'])
        self.assertEqual('timeout', finalized['stop_reason'])


def _snapshot_with_drivers(drivers):
    def _build(previous_state):
        snapshot = {
            'captured_at': capacity_profiler_runner._utc_now(),
            'total_connected_drivers': drivers,
            'active_instances_count': 1 if drivers else 0,
            'instances_with_players_count': 1 if drivers else 0,
            'cpu_total_percent': 30.0,
            'cpu_core_max_percent': 40.0,
            'cpu_per_core': [40.0, 20.0],
            'ram_used_mb': 8000.0,
            'ram_available_mb': 24000.0,
            'ram_percent': 25.0,
            'network_tx_mbps': None,
            'network_rx_mbps': None,
            'disk_read_kbps': None,
            'disk_write_kbps': None,
            'instances': [],
        }
        return snapshot, {}, []
    return _build


def _register_fake_active_run(run_id):
    # Enregistre un run comme "actif" pour le runner sans passer par un vrai thread
    # d'échantillonnage, pour tester _evaluate_auto_trigger de façon déterministe : quand un
    # run est actif, cette fonction ne rappelle jamais build_snapshot (elle relit le dernier
    # snapshot déjà en base), donc aucun mock ni thread réel n'est nécessaire ici.
    stop_event = threading.Event()
    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    capacity_profiler_runner._active.update(run_id=run_id, thread=thread, stop_event=stop_event)


class CapacityProfilerAutoTriggerTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = CapacityProfilerStore(Path(self.temporary_directory.name) / 'capacity-profiler.sqlite3')

        self.addCleanup(capacity_profiler_runner._active.update, {'run_id': None, 'thread': None, 'stop_event': None})
        capacity_profiler_runner._active.update(run_id=None, thread=None, stop_event=None)

        store_patcher = patch('services.capacity_profiler_runner._store', return_value=self.store)
        self.addCleanup(store_patcher.stop)
        store_patcher.start()

        # sample_interval_seconds volontairement énorme : une fois le run auto démarré, son
        # thread d'échantillonnage insère un premier snapshot puis reste endormi pendant toute
        # la durée du test, ce qui laisse le test contrôler exactement le dernier snapshot lu
        # par le watcher via des insertions manuelles, sans course avec le thread réel.
        cfg_patcher = patch.object(
            capacity_profiler_runner.config_store, 'CAPACITY_PROFILER_CFG',
            {'sample_interval_seconds': 3600, 'max_run_duration_seconds': 999999, 'server_name': 'test-machine'},
        )
        self.addCleanup(cfg_patcher.stop)
        cfg_patcher.start()

        maintenance_patcher = patch('services.capacity_profiler_runner._maybe_run_maintenance')
        self.addCleanup(maintenance_patcher.stop)
        maintenance_patcher.start()

        self.store.update_settings({
            'auto_start_enabled': True,
            'driver_threshold': 5,
            'start_grace_seconds': 60,
            'stop_grace_seconds': 60,
        })

    def test_disabled_auto_start_does_nothing(self):
        self.store.update_settings({'auto_start_enabled': False})

        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(20),
        ):
            above, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)

        self.assertIsNone(above)
        self.assertIsNone(below)
        self.assertIsNone(self.store.active_run())

    def test_start_not_triggered_before_grace_period_elapses(self):
        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(20),
        ):
            above, _, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)

        self.assertEqual(0, above)
        self.assertIsNone(self.store.active_run())

    def test_start_triggered_once_grace_period_elapses(self):
        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(20),
        ):
            above, _, io_state = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)
            above, _, _ = capacity_profiler_runner._evaluate_auto_trigger(above, None, io_state, now=61)

        self.assertIsNone(above)
        run = self.store.active_run()
        self.assertIsNotNone(run)
        self.assertEqual('auto_threshold', run['start_reason'])

    def test_start_timer_resets_when_drivers_drop_below_threshold_before_grace(self):
        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(20),
        ):
            above, _, io_state = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)

        self.assertEqual(0, above)

        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(1),  # repasse sous le seuil (5) avant les 60s de grâce
        ):
            above, _, io_state = capacity_profiler_runner._evaluate_auto_trigger(above, None, io_state, now=30)

        self.assertIsNone(above)

        # Même après 61s au total, comme le chronomètre a été remis à zéro, pas de démarrage.
        with patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot',
            side_effect=_snapshot_with_drivers(20),
        ):
            capacity_profiler_runner._evaluate_auto_trigger(above, None, io_state, now=61)

        self.assertIsNone(self.store.active_run())

    def test_stop_not_triggered_before_grace_period_elapses_for_auto_started_run(self):
        run = self.store.create_run({'server_name': 'm1', 'start_reason': 'auto_threshold'})
        _register_fake_active_run(run['id'])
        self.store.insert_snapshot(run['id'], {'captured_at': capacity_profiler_runner._utc_now(), 'total_connected_drivers': 0})

        _, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)

        self.assertEqual(0, below)
        self.assertEqual('running', self.store.get_run(run['id'])['status'])

    def test_stop_triggered_once_grace_period_elapses_for_auto_started_run(self):
        run = self.store.create_run({'server_name': 'm1', 'start_reason': 'auto_threshold'})
        _register_fake_active_run(run['id'])
        self.store.insert_snapshot(run['id'], {'captured_at': capacity_profiler_runner._utc_now(), 'total_connected_drivers': 0})

        _, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)
        capacity_profiler_runner._evaluate_auto_trigger(None, below, None, now=61)

        finalized = self.store.get_run(run['id'])
        self.assertEqual('completed', finalized['status'])
        self.assertEqual('auto_threshold', finalized['stop_reason'])
        self.assertIsNone(self.store.active_run())

    def test_stop_timer_resets_when_drivers_climb_back_above_threshold_before_grace(self):
        run = self.store.create_run({'server_name': 'm1', 'start_reason': 'auto_threshold'})
        _register_fake_active_run(run['id'])
        self.store.insert_snapshot(run['id'], {'captured_at': capacity_profiler_runner._utc_now(), 'total_connected_drivers': 0})

        _, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)
        self.assertEqual(0, below)

        # Les pilotes reviennent au-dessus du seuil avant la fin des 60s de grâce.
        self.store.insert_snapshot(run['id'], {'captured_at': capacity_profiler_runner._utc_now(), 'total_connected_drivers': 20})
        _, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, below, None, now=30)
        self.assertIsNone(below)

        # Même à 61s au total, le chronomètre a été remis à zéro : pas d'arrêt.
        capacity_profiler_runner._evaluate_auto_trigger(None, below, None, now=61)
        self.assertEqual('running', self.store.get_run(run['id'])['status'])

    def test_manual_run_is_never_auto_stopped_by_watcher(self):
        run = self.store.create_run({'server_name': 'm1', 'start_reason': 'manual'})
        _register_fake_active_run(run['id'])
        self.store.insert_snapshot(run['id'], {'captured_at': capacity_profiler_runner._utc_now(), 'total_connected_drivers': 0})

        above, below, _ = capacity_profiler_runner._evaluate_auto_trigger(None, None, None, now=0)
        self.assertIsNone(above)
        self.assertIsNone(below)

        capacity_profiler_runner._evaluate_auto_trigger(above, below, None, now=1000)

        self.assertEqual('running', self.store.get_run(run['id'])['status'])


class CapacityProfilerStartReasonTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.store = CapacityProfilerStore(Path(self.temporary_directory.name) / 'capacity-profiler.sqlite3')

        self.addCleanup(capacity_profiler_runner._active.update, {'run_id': None, 'thread': None, 'stop_event': None})
        capacity_profiler_runner._active.update(run_id=None, thread=None, stop_event=None)

        store_patcher = patch('services.capacity_profiler_runner._store', return_value=self.store)
        self.addCleanup(store_patcher.stop)
        store_patcher.start()

        cfg_patcher = patch.object(
            capacity_profiler_runner.config_store, 'CAPACITY_PROFILER_CFG',
            {'sample_interval_seconds': 3600, 'max_run_duration_seconds': 999999},
        )
        self.addCleanup(cfg_patcher.stop)
        cfg_patcher.start()

        sampler_patcher = patch(
            'services.capacity_profiler_runner.capacity_profiler_sampler.build_snapshot', side_effect=_fake_snapshot,
        )
        self.addCleanup(sampler_patcher.stop)
        sampler_patcher.start()

        maintenance_patcher = patch('services.capacity_profiler_runner._maybe_run_maintenance')
        self.addCleanup(maintenance_patcher.stop)
        maintenance_patcher.start()

    def test_start_run_accepts_a_custom_start_reason(self):
        run, status_code = capacity_profiler_runner.start_run({}, start_reason='auto_threshold')
        self.addCleanup(capacity_profiler_runner.stop_run, run['id'])

        self.assertEqual(201, status_code)
        self.assertEqual('auto_threshold', run['start_reason'])

    def test_start_run_defaults_to_manual(self):
        run, _ = capacity_profiler_runner.start_run({})
        self.addCleanup(capacity_profiler_runner.stop_run, run['id'])

        self.assertEqual('manual', run['start_reason'])


if __name__ == '__main__':
    unittest.main()
