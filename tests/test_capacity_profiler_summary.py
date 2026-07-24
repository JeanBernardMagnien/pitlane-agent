import json
import unittest

from services.capacity_profiler_summary import compute_summary, percentile, ram_available_percent


class PercentileTest(unittest.TestCase):
    def test_empty_list_is_none(self):
        self.assertIsNone(percentile([], 95))

    def test_single_value_returns_that_value(self):
        self.assertEqual(42.0, percentile([42.0], 95))

    def test_all_equal_values_returns_that_value(self):
        self.assertEqual(10.0, percentile([10.0, 10.0, 10.0], 95))

    def test_known_distribution_p95(self):
        values = list(range(1, 101))  # 1..100
        # p95 sur un rang 0-based (len-1)*0.95 = 94.05 -> interpolation entre index 94 (95) et 95 (96)
        self.assertAlmostEqual(95.05, percentile([float(v) for v in values], 95), places=2)

    def test_median_p50(self):
        self.assertEqual(2.0, percentile([1.0, 2.0, 3.0], 50))


class RamAvailablePercentTest(unittest.TestCase):
    def test_uses_available_mb_over_total_when_both_present(self):
        value = ram_available_percent({'ram_available_mb': 8000, 'ram_percent': 60.0}, ram_total_mb=32000)

        self.assertEqual(25.0, value)

    def test_falls_back_to_complement_of_ram_percent_without_total(self):
        value = ram_available_percent({'ram_available_mb': 8000, 'ram_percent': 60.0}, ram_total_mb=None)

        self.assertEqual(40.0, value)

    def test_none_when_nothing_available(self):
        self.assertIsNone(ram_available_percent({}, ram_total_mb=None))


class ComputeSummaryTest(unittest.TestCase):
    def _run_row(self, **overrides):
        run = {
            'started_at': '2026-07-24T12:00:00Z',
            'ram_total_mb': 32000,
            'crash_count': 0,
        }
        run.update(overrides)
        return run

    def test_empty_snapshots_produce_none_metrics_and_ok_risk(self):
        summary = compute_summary(self._run_row(), [], ended_at='2026-07-24T12:10:00Z')

        self.assertEqual(600, summary['duration_seconds'])
        self.assertIsNone(summary['cpu_total_p95'])
        self.assertIsNone(summary['cpu_core_max_p95'])
        self.assertIsNone(summary['max_total_drivers'])
        self.assertEqual('OK', summary['risk_level'])
        self.assertEqual('none', summary['limiting_factor'])

    def test_duration_seconds_computed_from_started_at_to_ended_at(self):
        summary = compute_summary(self._run_row(), [], ended_at='2026-07-24T13:00:00Z')

        self.assertEqual(3600, summary['duration_seconds'])

    def test_aggregates_are_computed_across_snapshots(self):
        snapshots = [
            {
                'captured_at': '2026-07-24T12:00:00Z', 'cpu_total_percent': 30.0, 'cpu_core_max_percent': 60.0,
                'total_connected_drivers': 20, 'active_instances_count': 1,
                'ram_available_mb': 16000, 'network_tx_mbps': 1.0,
            },
            {
                'captured_at': '2026-07-24T12:00:08Z', 'cpu_total_percent': 40.0, 'cpu_core_max_percent': 90.0,
                'total_connected_drivers': 30, 'active_instances_count': 2,
                'ram_available_mb': 8000, 'network_tx_mbps': 3.0,
            },
        ]

        summary = compute_summary(self._run_row(), snapshots, ended_at='2026-07-24T12:01:00Z')

        self.assertEqual(30, summary['max_total_drivers'])
        self.assertEqual(2, summary['max_simultaneous_instances'])
        self.assertEqual(3.0, summary['network_tx_max'])
        self.assertEqual(25.0, summary['ram_available_min'])  # 8000/32000*100
        # cpu_core_max_p95 sur [60, 90] -> RISK (>=85) attendu au niveau classify
        self.assertEqual('RISK', summary['risk_level'])
        self.assertEqual('cpu_single_core', summary['limiting_factor'])

    def test_any_crash_forces_critical_stability_regardless_of_cpu_ram(self):
        summary = compute_summary(self._run_row(crash_count=1), [], ended_at='2026-07-24T12:10:00Z')

        self.assertEqual('CRITICAL', summary['risk_level'])
        self.assertEqual('stability', summary['limiting_factor'])

    def test_sample_quality_ratio(self):
        snapshots = [{'captured_at': f'2026-07-24T12:00:{i:02d}Z'} for i in range(5)]

        # duration 50s, interval 10s -> 5 attendus, 5 obtenus -> qualité 1.0
        summary = compute_summary(
            self._run_row(), snapshots, ended_at='2026-07-24T12:00:50Z', sample_interval_seconds=10,
        )

        self.assertEqual(1.0, summary['sample_quality'])

    def test_sample_quality_is_none_without_interval(self):
        summary = compute_summary(self._run_row(), [], ended_at='2026-07-24T12:10:00Z')

        self.assertIsNone(summary['sample_quality'])

    def test_summary_json_is_valid_json_with_expected_keys(self):
        snapshots = [
            {'captured_at': '2026-07-24T12:00:00Z', 'cpu_total_percent': 30.0},
        ]
        summary = compute_summary(self._run_row(), snapshots, ended_at='2026-07-24T12:01:00Z')

        parsed = json.loads(summary['summary_json'])
        self.assertEqual(1, parsed['snapshot_count'])
        self.assertEqual('2026-07-24T12:00:00Z', parsed['first_captured_at'])


if __name__ == '__main__':
    unittest.main()
