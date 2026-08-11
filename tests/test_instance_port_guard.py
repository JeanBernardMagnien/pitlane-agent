import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))
sys.modules.setdefault('psutil', MagicMock())

from services import instance_port_guard


class InstancePortGuardTest(unittest.TestCase):
    def setUp(self):
        self.instance = {
            'id': 'server1',
            'tcp_port': 9700,
            'udp_port': 9700,
            'http_port': 8081,
        }

    def test_reports_only_required_listening_ports(self):
        connections = [
            self._connection(socket.SOCK_STREAM, 9700, 'LISTEN', 101),
            self._connection(socket.SOCK_STREAM, 9700, 'TIME_WAIT', None),
            self._connection(socket.SOCK_STREAM, 8081, 'LISTEN', 101),
            self._connection(socket.SOCK_DGRAM, 9700, '', 101),
            self._connection(socket.SOCK_STREAM, 9999, 'LISTEN', 202),
        ]

        with patch.object(instance_port_guard.psutil, 'net_connections', return_value=connections):
            conflicts = instance_port_guard.inspect_instance_port_conflicts(self.instance)

        self.assertEqual([
            {'protocol': 'TCP', 'port': 8081, 'pid': 101},
            {'protocol': 'TCP', 'port': 9700, 'pid': 101},
            {'protocol': 'UDP', 'port': 9700, 'pid': 101},
        ], conflicts)

    def test_waits_for_a_process_finishing_its_shutdown(self):
        occupied = [self._connection(socket.SOCK_STREAM, 9700, 'LISTEN', 101)]

        with (
            patch.object(
                instance_port_guard.psutil,
                'net_connections',
                side_effect=[occupied, []],
            ),
            patch.object(instance_port_guard.time, 'monotonic', side_effect=[10.0, 10.1]),
            patch.object(instance_port_guard.time, 'sleep') as mocked_sleep,
        ):
            conflicts = instance_port_guard.wait_for_instance_ports(self.instance)

        self.assertEqual([], conflicts)
        mocked_sleep.assert_called_once_with(0.25)

    def test_returns_conflicts_after_timeout(self):
        occupied = [self._connection(socket.SOCK_STREAM, 9700, 'LISTEN', 101)]

        with (
            patch.object(
                instance_port_guard.psutil,
                'net_connections',
                side_effect=[occupied, occupied],
            ),
            patch.object(instance_port_guard.time, 'monotonic', side_effect=[10.0, 10.1, 15.0]),
            patch.object(instance_port_guard.time, 'sleep') as mocked_sleep,
        ):
            conflicts = instance_port_guard.wait_for_instance_ports(self.instance)

        self.assertEqual([
            {'protocol': 'TCP', 'port': 9700, 'pid': 101},
        ], conflicts)
        mocked_sleep.assert_called_once_with(0.25)

    @staticmethod
    def _connection(connection_type, port, status, pid):
        return SimpleNamespace(
            type=connection_type,
            laddr=SimpleNamespace(port=port),
            status=status,
            pid=pid,
        )


if __name__ == '__main__':
    unittest.main()
