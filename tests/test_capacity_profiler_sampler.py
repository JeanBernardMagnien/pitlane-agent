import unittest
from unittest.mock import patch

from services import capacity_profiler_sampler
from services.capacity_profiler_sampler import build_snapshot
from services.process_supervisor import process_supervisor


class FakeProcess:
    def __init__(self, pid, exited=False):
        self.pid = pid
        self._exited = exited

    def poll(self):
        return None if not self._exited else 0


class FakePsProcess:
    def __init__(self, private_bytes=100 * 1024 * 1024, threads=8, num_handles=None):
        self._private_bytes = private_bytes
        self._threads = threads
        if num_handles is not None:
            self.num_handles = lambda: num_handles

    def memory_info(self):
        private_bytes = self._private_bytes

        class _Mem:
            private = private_bytes
        return _Mem()

    def num_threads(self):
        return self._threads


def _fake_cpu_percent(interval=None, percpu=False):
    return [80.0, 40.0, 30.0, 20.0] if percpu else 45.0


def _fake_virtual_memory():
    class _Mem:
        used = 16 * 1024 * 1024 * 1024
        available = 16 * 1024 * 1024 * 1024
        percent = 50.0
    return _Mem()


def _fake_net_io_counters():
    class _Net:
        bytes_sent = 1_000_000
        bytes_recv = 2_000_000
    return _Net()


def _fake_disk_io_counters():
    class _Disk:
        read_bytes = 500_000
        write_bytes = 700_000
    return _Disk()


class CapacityProfilerSamplerTest(unittest.TestCase):
    def setUp(self):
        process_supervisor.running.clear()
        process_supervisor.terminated.clear()

        patcher_cpu = patch('services.capacity_profiler_sampler.psutil.cpu_percent', side_effect=_fake_cpu_percent)
        patcher_mem = patch('services.capacity_profiler_sampler.psutil.virtual_memory', side_effect=_fake_virtual_memory)
        patcher_net = patch('services.capacity_profiler_sampler.psutil.net_io_counters', side_effect=_fake_net_io_counters)
        patcher_disk = patch('services.capacity_profiler_sampler.psutil.disk_io_counters', side_effect=_fake_disk_io_counters)
        self.addCleanup(patcher_cpu.stop)
        self.addCleanup(patcher_mem.stop)
        self.addCleanup(patcher_net.stop)
        self.addCleanup(patcher_disk.stop)
        patcher_cpu.start()
        patcher_mem.start()
        patcher_net.start()
        patcher_disk.start()

    def test_first_tick_has_no_network_disk_baseline(self):
        snapshot, new_state, crash_events = build_snapshot(previous_state=None)

        self.assertIsNone(snapshot['network_tx_mbps'])
        self.assertIsNone(snapshot['network_rx_mbps'])
        self.assertIsNone(snapshot['disk_read_kbps'])
        self.assertIsNone(snapshot['disk_write_kbps'])
        self.assertIn('io', new_state)
        self.assertEqual([], crash_events)

    def test_system_metrics_are_captured(self):
        snapshot, _, _ = build_snapshot(previous_state=None)

        self.assertEqual(45.0, snapshot['cpu_total_percent'])
        self.assertEqual(80.0, snapshot['cpu_core_max_percent'])
        self.assertEqual([80.0, 40.0, 30.0, 20.0], snapshot['cpu_per_core'])
        self.assertEqual(50.0, snapshot['ram_percent'])

    def test_second_tick_computes_correct_network_delta(self):
        _, first_state, _ = build_snapshot(previous_state=None)

        # 2e tick, 10s plus tard, +500_000 bytes envoyés.
        first_state['io']['at'] -= 10
        with patch('services.capacity_profiler_sampler.psutil.net_io_counters') as mocked_net:
            class _Net:
                bytes_sent = first_state['io']['bytes_sent'] + 500_000
                bytes_recv = first_state['io']['bytes_recv']
            mocked_net.return_value = _Net()

            snapshot, _, _ = build_snapshot(previous_state=first_state)

        # 500_000 bytes / 1_000_000 / 10s = 0.05 MB/s
        self.assertEqual(0.05, snapshot['network_tx_mbps'])
        self.assertEqual(0.0, snapshot['network_rx_mbps'])

    def test_counter_reset_yields_none_rate_instead_of_negative(self):
        _, first_state, _ = build_snapshot(previous_state=None)
        first_state['io']['at'] -= 10

        with patch('services.capacity_profiler_sampler.psutil.net_io_counters') as mocked_net:
            class _Net:
                bytes_sent = 0  # compteur système réinitialisé, plus petit que le précédent
                bytes_recv = 0
            mocked_net.return_value = _Net()

            snapshot, _, _ = build_snapshot(previous_state=first_state)

        self.assertIsNone(snapshot['network_tx_mbps'])
        self.assertIsNone(snapshot['network_rx_mbps'])

    def test_instance_snapshot_reuses_resolved_player_count_and_log_observation(self):
        process_supervisor.running['instance-1'] = {
            'process': FakeProcess(pid=4242),
            'instance': {'id': 'instance-1', 'http_port': 8080},
            'started_at': 1000.0,
        }

        with patch('services.capacity_profiler_sampler.observe_player_count', return_value={
            'session_phase': 'race',
            'race_started_at': '2026-07-24T12:00:00Z',
            'crash_detected_at': None,
        }) as mocked_observe, \
             patch('services.capacity_profiler_sampler.read_connected_drivers', return_value={
                'http_connected_drivers': 28, 'http_ok': True,
             }) as mocked_http, \
             patch('services.capacity_profiler_sampler.resolve_player_count', return_value={
                'connected_drivers': 28, 'drivers_source': 'http',
             }) as mocked_resolve, \
             patch.object(capacity_profiler_sampler.process_cpu_sampler, 'cached_process', return_value=FakePsProcess()), \
             patch.object(capacity_profiler_sampler.process_cpu_sampler, 'sample_cpu_percent', return_value=33.3):

            snapshot, _, _ = build_snapshot(previous_state=None)

        self.assertEqual(1, len(snapshot['instances']))
        instance = snapshot['instances'][0]
        self.assertEqual('instance-1', instance['id'])
        self.assertEqual(28, instance['connected_drivers'])
        self.assertEqual('race', instance['session_phase'])
        self.assertEqual('2026-07-24T12:00:00Z', instance['race_started_at'])
        self.assertEqual(33.3, instance['process_cpu_percent'])
        self.assertIsNone(instance['handles'])  # FakePsProcess sans num_handles -> dégrade à None
        self.assertEqual(28, snapshot['total_connected_drivers'])
        self.assertEqual(1, snapshot['instances_with_players_count'])
        mocked_observe.assert_called_once()
        mocked_http.assert_called_once()
        mocked_resolve.assert_called_once()

    def test_exited_process_is_skipped_without_touching_supervisor_state(self):
        process_supervisor.running['instance-2'] = {
            'process': FakeProcess(pid=555, exited=True),
            'instance': {'id': 'instance-2'},
            'started_at': 1000.0,
        }

        snapshot, _, _ = build_snapshot(previous_state=None)

        self.assertEqual([], snapshot['instances'])
        self.assertIsNone(snapshot['total_connected_drivers'])
        # process_supervisor n'a pas été mutée par le sampler : toujours dans running.
        self.assertIn('instance-2', process_supervisor.running)

    def test_crash_event_detected_only_when_stop_was_not_requested(self):
        process_supervisor.terminated['crashed-instance'] = {
            'stop_requested_at': None,
            'stop_reason': None,
            'exit_observed_at': '2026-07-24T12:00:00Z',
        }
        process_supervisor.terminated['stopped-instance'] = {
            'stop_requested_at': '2026-07-24T11:59:00Z',
            'stop_reason': 'manual',
            'exit_observed_at': '2026-07-24T12:00:00Z',
        }

        _, _, crash_events = build_snapshot(previous_state=None)

        self.assertEqual(1, len(crash_events))
        self.assertEqual('crashed-instance', crash_events[0]['instance_id'])

    def test_crash_event_is_not_reported_twice_across_ticks(self):
        process_supervisor.terminated['crashed-instance'] = {
            'stop_requested_at': None,
            'stop_reason': None,
            'exit_observed_at': '2026-07-24T12:00:00Z',
        }

        _, first_state, first_crash_events = build_snapshot(previous_state=None)
        _, _, second_crash_events = build_snapshot(previous_state=first_state)

        self.assertEqual(1, len(first_crash_events))
        self.assertEqual(0, len(second_crash_events))


if __name__ == '__main__':
    unittest.main()
