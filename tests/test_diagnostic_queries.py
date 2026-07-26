import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.capacity_profiler_store import CapacityProfilerStore
from services.diagnostic_queries import (
    DiagnosticQueryError,
    _downsample,
    execute_diagnostic_query,
)


class DiagnosticQueriesTest(unittest.TestCase):
    def test_technical_history_query_is_bounded_and_versioned(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        store = CapacityProfilerStore(Path(temporary_directory.name) / 'capacity.sqlite3')
        store.insert_technical_history_snapshot({
            'captured_at': '2026-07-24T12:00:00Z',
            'cpu_total_percent': 42,
            'cpu_core_max_percent': 80,
            'cpu_per_core': [80, 20],
            'network_tx_mbps': 1.5,
            'instances': [],
        })

        with (
            patch('services.diagnostic_queries.get_capacity_profiler_store', return_value=store),
            patch('core.config_store.CAPACITY_PROFILER_CFG', {
                'technical_history_interval_seconds': 60,
                'technical_history_retention_days': 30,
            }),
        ):
            payload = execute_diagnostic_query('technical_history', {
                'since': '2026-07-24T11:00:00Z',
                'limit': 100,
            })

        self.assertEqual(2, payload['schema_version'])
        self.assertEqual('agent_sqlite', payload['source'])
        self.assertEqual(60.0, payload['sample_interval_seconds'])
        self.assertEqual(1, len(payload['samples']))
        self.assertEqual(80.0, payload['summary']['cpu_core_max_percent']['p95'])
        self.assertEqual(80.0, payload['summary']['cpu_per_core'][0]['max'])
        self.assertEqual(1.5, payload['summary']['network_tx_mbps']['latest'])

    def test_unknown_or_unbounded_query_is_rejected(self):
        with self.assertRaises(DiagnosticQueryError):
            execute_diagnostic_query('read_any_file', {})

        with self.assertRaises(DiagnosticQueryError):
            execute_diagnostic_query('technical_history', {'limit': 99999})

        with self.assertRaises(DiagnosticQueryError):
            execute_diagnostic_query('technical_history', {'since': 'not-a-date'})

    def test_downsampling_keeps_first_and_last_points(self):
        samples = [{'index': index} for index in range(1000)]

        reduced = _downsample(samples, 120)

        self.assertEqual(120, len(reduced))
        self.assertEqual(0, reduced[0]['index'])
        self.assertEqual(999, reduced[-1]['index'])


if __name__ == '__main__':
    unittest.main()
