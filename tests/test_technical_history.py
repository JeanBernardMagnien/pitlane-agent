import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.capacity_profiler_store import CapacityProfilerStore
from services import technical_history


class TechnicalHistoryTest(unittest.TestCase):
    def setUp(self):
        technical_history._last_sample_monotonic = 0.0
        technical_history._last_maintenance_monotonic = 0.0
        technical_history._last_io_state = None

    def test_runtime_report_is_reduced_to_non_sensitive_technical_metrics(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        store = CapacityProfilerStore(Path(temporary_directory.name) / 'capacity.sqlite3')
        report = {
            'agent': {
                'server_time': '2026-07-24T12:00:00Z',
                'cpu_percent': 42.5,
                'cpu_core_max_percent': 78.5,
                'ram_used_gb': 8.25,
                'ram_total_gb': 16,
                'ram_percent': 51.6,
            },
            'instances': [{
                'id': 'server1',
                'status': 'running',
                'cpu_percent': 12.5,
                'ram_mb': 900,
                'connected_drivers': 18,
                'http_ok': True,
                'http_duration_ms': 11,
                'uptime_seconds': 3600,
                'admin_password': 'must-not-be-stored',
                'session_phase': 'race',
            }],
        }

        with (
            patch.object(technical_history, 'get_capacity_profiler_store', return_value=store),
            patch('core.config_store.CAPACITY_PROFILER_CFG', {
                'technical_history_interval_seconds': 60,
                'technical_history_retention_days': 30,
            }),
        ):
            recorded = technical_history.record_runtime_report(report, {
                'cpu_per_core': [78.5, 24.0],
                'network_bytes_sent': 1_000,
                'network_bytes_received': 2_000,
                'disk_read_bytes': 3_000,
                'disk_write_bytes': 4_000,
            }, now=100.0)

        snapshot = store.list_technical_history(limit=1)[0]
        self.assertTrue(recorded)
        self.assertEqual(42.5, snapshot['cpu_total_percent'])
        self.assertEqual(78.5, snapshot['cpu_core_max_percent'])
        self.assertEqual([78.5, 24.0], snapshot['cpu_per_core'])
        self.assertIsNone(snapshot['network_tx_mbps'])
        self.assertEqual(8448.0, snapshot['ram_used_mb'])
        self.assertEqual(1, snapshot['active_instances_count'])
        self.assertEqual(18, snapshot['total_connected_drivers'])
        self.assertNotIn('admin_password', snapshot['instances'][0])
        self.assertNotIn('session_phase', snapshot['instances'][0])

    def test_sampling_is_throttled(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        store = CapacityProfilerStore(Path(temporary_directory.name) / 'capacity.sqlite3')
        report = {'agent': {'server_time': '2026-07-24T12:00:00Z'}, 'instances': []}

        with (
            patch.object(technical_history, 'get_capacity_profiler_store', return_value=store),
            patch('core.config_store.CAPACITY_PROFILER_CFG', {
                'technical_history_interval_seconds': 60,
            }),
        ):
            first_system_sample = {
                'network_bytes_sent': 1_000_000,
                'network_bytes_received': 2_000_000,
                'disk_read_bytes': 1_024,
                'disk_write_bytes': 2_048,
            }
            self.assertTrue(technical_history.record_runtime_report(
                report,
                first_system_sample,
                now=100.0,
            ))
            self.assertFalse(technical_history.record_runtime_report(
                report,
                first_system_sample,
                now=159.0,
            ))
            report['agent']['server_time'] = '2026-07-24T12:01:00Z'
            self.assertTrue(technical_history.record_runtime_report(report, {
                'network_bytes_sent': 1_750_000,
                'network_bytes_received': 2_375_000,
                'disk_read_bytes': 62_464,
                'disk_write_bytes': 124_928,
            }, now=160.0))

        snapshots = store.list_technical_history(limit=10)
        self.assertEqual(2, len(snapshots))
        self.assertEqual(0.013, snapshots[1]['network_tx_mbps'])
        self.assertEqual(0.006, snapshots[1]['network_rx_mbps'])
        self.assertEqual(1.0, snapshots[1]['disk_read_kbps'])
        self.assertEqual(2.0, snapshots[1]['disk_write_kbps'])


if __name__ == '__main__':
    unittest.main()
