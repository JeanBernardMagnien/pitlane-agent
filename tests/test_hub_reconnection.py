import json
import socket
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import websocket

from services import hub_ws_client
from services.agent_command_journal import AgentCommandJournal
from services.durable_command_executor import DurableCommandCoordinator
from services.runtime_state_session import RuntimeStateSession
from services.runtime_state_tracker import RuntimeStateTracker
from services.websocket_heartbeat import HubHeartbeat


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


class ScriptedSocket:
    def __init__(self, clock, messages=(), on_receive=None):
        self.clock = clock
        self.messages = iter(messages)
        self.on_receive = on_receive
        self.sent = []
        self.closed = False
        self.authenticated = False

    def recv(self):
        if not self.authenticated:
            self.authenticated = True
            return json.dumps({
                'type': 'hello_ack',
                'runtime_protocol_version': 2,
                'capabilities': ['event_driven_runtime_v2'],
            })
        delay, message = next(self.messages, (1, websocket.WebSocketTimeoutException()))
        self.clock.now += delay
        if self.on_receive:
            self.on_receive()
        if isinstance(message, Exception):
            raise message
        return message

    def send(self, raw):
        if self.closed:
            raise websocket.WebSocketConnectionClosedException()
        self.sent.append(json.loads(raw))

    def settimeout(self, timeout):
        self.timeout = timeout

    def close(self, timeout=None):
        self.closed = True
        self.close_timeout = timeout
        self.closed_at = self.clock.now


class HubReconnectionTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.stop = threading.Event()
        self.waits = []
        self.created = []
        self.state = {'agent': {'health': 'healthy'}, 'instances': []}
        self.tracker = RuntimeStateTracker()

    def run_client(self, attempts, runtime_step=None, coordinator=None):
        attempts = iter(attempts)

        def connect(*_args, **_kwargs):
            # An unexpected extra reconnect fails instead of looping indefinitely.
            attempt = next(attempts, None)
            if attempt is None:
                self.stop.set()
                raise AssertionError('unexpected reconnect')
            if isinstance(attempt, Exception):
                raise attempt
            self.created.append(attempt)
            return attempt

        def wait(delay):
            self.assertTrue(all(socket.closed for socket in self.created))
            self.waits.append(delay)
            self.clock.now += delay

        def session(ws, lock):
            instance = RuntimeStateSession(ws, lock, lambda: self.state, self.tracker)
            if runtime_step:
                original = instance.send_if_changed

                def step():
                    runtime_step()
                    return original()

                instance.send_if_changed = step
            return instance

        config = {
            'name': 'test', 'base_url': 'http://hub.invalid',
            'agent_token': 'test-only', 'runtime_scan_interval': 0.5,
        }
        with ExitStack() as stack:
            stack.enter_context(patch.object(hub_ws_client, '_stop_event', self.stop))
            stack.enter_context(patch.object(self.stop, 'wait', side_effect=wait))
            stack.enter_context(patch.object(hub_ws_client, '_find_hub_cfg', return_value=config))
            stack.enter_context(patch.object(hub_ws_client, 'HubHeartbeat', side_effect=lambda: HubHeartbeat(self.clock)))
            stack.enter_context(patch.object(hub_ws_client, 'RuntimeStateSession', side_effect=session))
            stack.enter_context(patch.object(hub_ws_client.time, 'monotonic', self.clock))
            stack.enter_context(patch.object(hub_ws_client, '_send_artifact_notifications'))
            if coordinator is None:
                stack.enter_context(patch.object(hub_ws_client, '_send_pending_command_acknowledgements'))
            else:
                stack.enter_context(patch.object(hub_ws_client, '_get_durable_coordinator', return_value=coordinator))
            stack.enter_context(patch.object(websocket, 'create_connection', side_effect=connect))
            with self.assertLogs(level='INFO') as logs:
                hub_ws_client._run_hub_client('test')
        self.assertNotIn('unexpected reconnect', '\n'.join(logs.output))
        return '\n'.join(logs.output)

    def reconnected_socket(self):
        return ScriptedSocket(
            self.clock, [(1, '{"type":"ping"}')], on_receive=self.stop.set,
        )

    def test_silent_open_socket_reconnects_and_resynchronizes(self):
        silent = ScriptedSocket(self.clock)
        recovered = self.reconnected_socket()

        logs = self.run_client([silent, recovered])

        self.assertIn('Hub silencieux depuis 35 s', logs)
        self.assertEqual(35, silent.closed_at)
        self.assertEqual([1], self.waits)
        for socket in [silent, recovered]:
            self.assertTrue(socket.closed)
            self.assertEqual(0, socket.close_timeout)
            self.assertEqual(['hello', 'runtime_state'], [m['type'] for m in socket.sent[:2]])
            self.assertEqual('sync', socket.sent[1]['mode'])
        self.assertEqual(['hello', 'runtime_state'], [m['type'] for m in silent.sent])
        self.assertEqual('pong', recovered.sent[-1]['type'])

    def test_periodic_pings_keep_stable_runtime_connected_without_reports(self):
        socket = ScriptedSocket(self.clock, [(10, '{"type":"ping"}')] * 12)
        socket.on_receive = lambda: self.stop.set() if self.clock.now >= 120 else None

        self.run_client([socket])

        self.assertEqual([], self.waits)
        self.assertEqual(12, sum(m['type'] == 'pong' for m in socket.sent))
        self.assertEqual(1, sum(m['type'] == 'runtime_state' for m in socket.sent))

    def test_outbound_runtime_changes_do_not_hide_inbound_silence(self):
        silent = ScriptedSocket(self.clock)

        def change():
            self.state['agent']['version'] = str(self.clock.now)

        self.run_client([silent, self.reconnected_socket()], runtime_step=change)

        self.assertEqual(35, silent.closed_at)
        self.assertGreater(sum(m['type'] == 'runtime_state' for m in silent.sent), 1)

    def test_empty_close_frame_reconnects_immediately(self):
        for close_frame in ['', b'', None]:
            with self.subTest(close_frame=close_frame):
                self.setUp()
                closed = ScriptedSocket(self.clock, [(1, close_frame)])
                self.run_client([closed, self.reconnected_socket()])
                self.assertEqual(1, closed.closed_at)
                self.assertEqual([1], self.waits)

    def test_network_failure_keeps_backoff_until_a_new_authenticated_connection(self):
        first = ScriptedSocket(self.clock)
        second = ScriptedSocket(self.clock)
        recovered = self.reconnected_socket()

        self.run_client([first, OSError('unreachable'), OSError('unreachable'), second, recovered])

        self.assertEqual([1, 2, 4, 1], self.waits)
        self.assertEqual(3, len(self.created))

    def test_invalid_or_unknown_messages_do_not_keep_connection_alive(self):
        messages = ['not-json', '[]', '{"type":"unknown"}'] * 12
        socket = ScriptedSocket(self.clock, [(1, message) for message in messages])

        self.run_client([socket, self.reconnected_socket()])

        self.assertEqual(35, socket.closed_at)

    def test_slow_runtime_work_cannot_reset_the_deadline(self):
        socket = ScriptedSocket(self.clock)

        def slow_step():
            self.clock.now += 35

        logs = self.run_client([socket, self.reconnected_socket()], runtime_step=slow_step)

        self.assertIn('Hub silencieux depuis 35 s', logs)
        self.assertEqual([1], self.waits)

    def test_heartbeat_is_independent_for_each_hub_and_uses_monotonic_time(self):
        silent = HubHeartbeat(self.clock)
        active = HubHeartbeat(self.clock)
        with patch('time.time', return_value=-1000000):
            self.clock.now = 30
            active.mark_received()
            silent.require_alive()
            self.clock.now = 35
            with self.assertRaisesRegex(ConnectionError, 'Hub silencieux'):
                silent.require_alive()
            active.require_alive()

    def test_runtime_acknowledgements_also_prove_inbound_activity(self):
        socket = ScriptedSocket(self.clock, [(10, '{"type":"runtime_state_ack"}')] * 12)
        socket.on_receive = lambda: self.stop.set() if self.clock.now >= 120 else None

        self.run_client([socket])

        self.assertEqual([], self.waits)
        self.assertEqual(['hello', 'runtime_state'], [m['type'] for m in socket.sent])

    def test_running_command_does_not_block_reconnection_or_execute_twice(self):
        started = threading.Event()
        release = threading.Event()
        executions = []
        command = {
            'type': 'command', 'schema_version': 2,
            'id': '11111111-1111-4111-8111-111111111111',
            'idempotency_key': 'start-race-once', 'command': 'start_instance',
            'target': {'server_id': 1, 'instance_id': 'race', 'fence': 1},
            'payload': {'instance_id': 'race'}, 'created_at': '2026-09-09T16:00:00Z',
        }
        raw_command = json.dumps(command)
        first = ScriptedSocket(self.clock, [(1, raw_command)])
        recovered = ScriptedSocket(self.clock, [(1, raw_command), (1, '{"type":"ping"}')])
        recovered.on_receive = lambda: self.stop.set() if self.clock.now >= 39 else None

        def execute(name, payload):
            executions.append(name)
            started.set()
            if not release.wait(5):
                raise AssertionError('test did not release command')
            return {'status': 'running'}, 200

        def runtime_step():
            self.assertTrue(started.wait(1))

        with tempfile.TemporaryDirectory() as directory:
            journal = AgentCommandJournal(Path(directory) / 'commands.sqlite3')
            with ThreadPoolExecutor(max_workers=1) as executor:
                coordinator = DurableCommandCoordinator(journal, execute, executor)
                try:
                    self.run_client([first, recovered], runtime_step, coordinator)
                    self.assertEqual(['start_instance'], executions)
                    self.assertEqual('executing', journal.get('test', command['id'])['status'])
                    self.assertIn('pong', [message['type'] for message in recovered.sent])
                    self.assertEqual([1], self.waits)
                finally:
                    release.set()

            # The result remains durable even though the original socket closed.
            acknowledgements = []
            coordinator.replay_pending(
                'test', lambda record, _: acknowledgements.append(record['status']),
            )
            self.assertEqual(['succeeded'], acknowledgements)
            self.assertEqual(['start_instance'], executions)

    def real_socket(self):
        client, hub = socket.socketpair()
        ws = websocket.WebSocket()
        ws.sock = client
        ws.connected = True
        ws.settimeout(0.01)
        self.addCleanup(hub.close)
        self.addCleanup(ws.shutdown)
        return ws, hub

    def test_real_websocket_read_timeouts_expire_even_with_tcp_still_open(self):
        ws, hub = self.real_socket()
        heartbeat = HubHeartbeat(self.clock)
        self.clock.now = 30
        frame = websocket.ABNF.create_frame('{"type":"ping"}', websocket.ABNF.OPCODE_TEXT)
        frame.mask = 0
        hub.sendall(frame.format())

        received = hub_ws_client._receive_available_messages(ws, threading.Lock(), None, 'test', heartbeat)
        self.assertEqual(1, received)
        self.clock.now = 64.9
        self.assertEqual(0, hub_ws_client._receive_available_messages(ws, threading.Lock(), None, 'test', heartbeat))
        self.clock.now = 65
        with self.assertRaisesRegex(ConnectionError, 'Hub silencieux'):
            hub_ws_client._receive_available_messages(ws, threading.Lock(), None, 'test', heartbeat)
        self.assertTrue(ws.connected)

    def test_real_websocket_close_frame_is_propagated_for_reconnection(self):
        ws, hub = self.real_socket()
        frame = websocket.ABNF.create_frame(b'\x03\xe8', websocket.ABNF.OPCODE_CLOSE)
        frame.mask = 0
        hub.sendall(frame.format())

        with self.assertRaises(websocket.WebSocketConnectionClosedException):
            hub_ws_client._receive_available_messages(
                ws, threading.Lock(), None, 'test', HubHeartbeat(self.clock),
            )


if __name__ == '__main__':
    unittest.main()
