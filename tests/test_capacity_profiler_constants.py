import unittest

from core.capacity_profiler_constants import classify


class CapacityProfilerClassifyTest(unittest.TestCase):
    def test_all_metrics_comfortable_is_ok(self):
        risk_level, limiting_factor = classify(cpu_core_max=40.0, cpu_total=30.0, ram_available_percent=60.0)

        self.assertEqual('OK', risk_level)
        self.assertEqual('none', limiting_factor)

    def test_missing_metrics_do_not_crash_and_default_to_ok(self):
        risk_level, limiting_factor = classify(cpu_core_max=None, cpu_total=None, ram_available_percent=None)

        self.assertEqual('OK', risk_level)
        self.assertEqual('none', limiting_factor)

    def test_any_crash_is_critical_stability_regardless_of_other_metrics(self):
        risk_level, limiting_factor = classify(
            cpu_core_max=10.0, cpu_total=10.0, ram_available_percent=90.0, crash_count=1,
        )

        self.assertEqual('CRITICAL', risk_level)
        self.assertEqual('stability', limiting_factor)

    def test_cpu_core_just_below_watch_threshold_is_ok(self):
        risk_level, limiting_factor = classify(cpu_core_max=74.9, cpu_total=10.0, ram_available_percent=90.0)

        self.assertEqual('OK', risk_level)
        self.assertEqual('none', limiting_factor)

    def test_cpu_core_at_watch_threshold_is_watch(self):
        risk_level, limiting_factor = classify(cpu_core_max=75.0, cpu_total=10.0, ram_available_percent=90.0)

        self.assertEqual('WATCH', risk_level)
        self.assertEqual('cpu_single_core', limiting_factor)

    def test_cpu_core_at_risk_threshold_is_risk(self):
        risk_level, limiting_factor = classify(cpu_core_max=85.0, cpu_total=10.0, ram_available_percent=90.0)

        self.assertEqual('RISK', risk_level)
        self.assertEqual('cpu_single_core', limiting_factor)

    def test_cpu_core_at_critical_threshold_is_critical(self):
        risk_level, limiting_factor = classify(cpu_core_max=95.0, cpu_total=10.0, ram_available_percent=90.0)

        self.assertEqual('CRITICAL', risk_level)
        self.assertEqual('cpu_single_core', limiting_factor)

    def test_ram_below_watch_threshold_is_watch(self):
        risk_level, limiting_factor = classify(cpu_core_max=10.0, cpu_total=10.0, ram_available_percent=24.9)

        self.assertEqual('WATCH', risk_level)
        self.assertEqual('ram', limiting_factor)

    def test_ram_below_risk_threshold_is_risk_not_critical(self):
        risk_level, limiting_factor = classify(cpu_core_max=10.0, cpu_total=10.0, ram_available_percent=14.9)

        self.assertEqual('RISK', risk_level)
        self.assertEqual('ram', limiting_factor)

    def test_cpu_total_alone_never_exceeds_risk(self):
        risk_level, limiting_factor = classify(cpu_core_max=10.0, cpu_total=99.0, ram_available_percent=90.0)

        self.assertEqual('RISK', risk_level)
        self.assertEqual('cpu_global', limiting_factor)

    def test_cpu_single_core_wins_priority_over_ram_at_equal_severity(self):
        # ram is WATCH (20%) and cpu_core is WATCH (80%) -> cpu_single_core must win the tie.
        risk_level, limiting_factor = classify(cpu_core_max=80.0, cpu_total=10.0, ram_available_percent=20.0)

        self.assertEqual('WATCH', risk_level)
        self.assertEqual('cpu_single_core', limiting_factor)

    def test_ram_wins_priority_over_cpu_global_at_equal_severity(self):
        # ram is WATCH (20%) and cpu_total alone would be WATCH (80%) -> ram must win the tie.
        risk_level, limiting_factor = classify(cpu_core_max=10.0, cpu_total=80.0, ram_available_percent=20.0)

        self.assertEqual('WATCH', risk_level)
        self.assertEqual('ram', limiting_factor)

    def test_highest_severity_factor_wins_even_if_lower_priority(self):
        # cpu_global RISK (99%) outranks cpu_single_core WATCH (76%).
        risk_level, limiting_factor = classify(cpu_core_max=76.0, cpu_total=99.0, ram_available_percent=90.0)

        self.assertEqual('RISK', risk_level)
        self.assertEqual('cpu_global', limiting_factor)


if __name__ == '__main__':
    unittest.main()
