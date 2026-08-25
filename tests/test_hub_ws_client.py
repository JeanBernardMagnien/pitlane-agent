import unittest
import json
import threading
from unittest.mock import patch

from services import runtime_reporter
from services.runtime_state_session import RuntimeStateSession
from services.runtime_state_tracker import RuntimeStateTracker
from services.websocket_inbox import drain_available_messages
from services.websocket_authentication import (
    HubAuthenticationError,
    ReconnectBackoff,
    await_hello_acknowledgement,
    require_event_driven_runtime,
)


class FakeWebSocketTimeoutException(Exception):
    pass


class FakeWebSocketConnectionClosedException(Exception):
    pass


class FakeWebSocket:
    def __init__(self, messages):
        self._messages = iter(messages)

    def recv(self):
        try:
            return next(self._messages)
        except StopIteration:
            raise FakeWebSocketTimeoutException()


class AuthenticationWebSocket:
    def __init__(self, message):
        self.message = message

    def recv(self):
        return self.message


class OutboundWebSocket:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(json.loads(message))


class HubWebSocketClientTest(unittest.TestCase):
    def test_connection_is_authenticated_only_after_hello_ack(self):
        acknowledgement = await_hello_acknowledgement(AuthenticationWebSocket(
            '{"type":"hello_ack","server_id":12,"server_name":"Beta"}',
        ))

        self.assertEqual('hello_ack', acknowledgement['type'])
        self.assertEqual(12, acknowledgement['server_id'])

    def test_authentication_error_is_exposed_without_server_message(self):
        with self.assertRaisesRegex(HubAuthenticationError, r'ip_blocked'):
            await_hello_acknowledgement(AuthenticationWebSocket(
                '{"type":"error","code":"ip_blocked","error":"internal detail"}',
            ))

    def test_event_driven_runtime_requires_an_explicit_hub_capability(self):
        require_event_driven_runtime({
            'runtime_protocol_version': 2,
            'capabilities': ['event_driven_runtime_v2'],
        })

        with self.assertRaisesRegex(HubAuthenticationError, 'incompatible'):
            require_event_driven_runtime({'type': 'hello_ack'})

    def test_closed_socket_is_not_an_authenticated_connection(self):
        with self.assertRaisesRegex(HubAuthenticationError, 'avant acquittement'):
            await_hello_acknowledgement(AuthenticationWebSocket(None))

    def test_failed_authentication_keeps_exponential_backoff_until_acknowledged(self):
        backoff = ReconnectBackoff()

        self.assertEqual([1, 2, 4, 8, 16, 30, 30], [
            backoff.next_failure_delay() for _ in range(7)
        ])

        backoff.reset_after_authentication()
        self.assertEqual(1, backoff.next_failure_delay())

    def test_available_messages_are_drained_in_the_same_cycle(self):
        ws = FakeWebSocket(['first', 'second', 'third'])
        messages = []

        received = drain_available_messages(
            ws,
            messages.append,
            FakeWebSocketTimeoutException,
            FakeWebSocketConnectionClosedException,
            limit=100,
        )

        self.assertEqual(3, received)
        self.assertEqual(['first', 'second', 'third'], messages)

    def test_batch_limit_preserves_time_for_periodic_tasks(self):
        ws = FakeWebSocket(['first', 'second', 'third'])
        messages = []

        received = drain_available_messages(
            ws,
            messages.append,
            FakeWebSocketTimeoutException,
            FakeWebSocketConnectionClosedException,
            limit=2,
        )

        self.assertEqual(2, received)
        self.assertEqual(['first', 'second'], messages)

    def test_closed_connection_is_propagated_to_reconnect_loop(self):
        ws = FakeWebSocket([None])

        with self.assertRaises(FakeWebSocketConnectionClosedException):
            drain_available_messages(
                ws,
                lambda _message: None,
                FakeWebSocketTimeoutException,
                FakeWebSocketConnectionClosedException,
                limit=100,
            )

    def test_stable_runtime_sends_one_sync_then_no_periodic_update(self):
        ws = OutboundWebSocket()
        tracker = RuntimeStateTracker('11111111-1111-4111-8111-111111111111')
        state = {
            'agent': {'version': '0.5.0', 'health': 'healthy', 'health_reasons': []},
            'instances': [{
                'id': 'race-1',
                'status': 'running',
                'connected_drivers': 17,
                'drivers_seen_at': '2026-08-25T12:00:00Z',
            }],
        }

        session = RuntimeStateSession(ws, threading.Lock(), lambda: state, tracker)
        session.send_sync()
        for _ in range(60):
            self.assertFalse(session.send_if_changed())

        state['instances'][0]['connected_drivers'] = 18
        self.assertTrue(session.send_if_changed())

        reconnected_ws = OutboundWebSocket()
        RuntimeStateSession(reconnected_ws, threading.Lock(), lambda: state, tracker).send_sync()

        self.assertEqual(['sync', 'change'], [message['mode'] for message in ws.messages])
        self.assertEqual(18, ws.messages[1]['payload']['instances'][0]['connected_drivers'])
        self.assertEqual(['sync'], [message['mode'] for message in reconnected_ws.messages])

    def test_hub_facing_state_does_not_sample_diagnostic_cpu_or_ram(self):
        detailed_instance = {
            'id': 'race-1',
            'status': 'running',
            'pid': 123,
            'connected_drivers': 17,
            'cpu_percent': 75.0,
            'ram_mb': 2048.0,
            'uptime_seconds': 30,
        }

        with patch.object(
            runtime_reporter,
            '_runtime_health_sources',
            return_value=({'status': 'healthy'}, {'status': 'healthy'}),
        ), patch.object(
            runtime_reporter,
            '_running_instance_reports',
            return_value=[detailed_instance],
        ) as instance_reports:
            state = runtime_reporter.build_semantic_runtime_state()

        instance_reports.assert_called_once_with()
        self.assertNotIn('cpu_percent', state['instances'][0])
        self.assertNotIn('ram_mb', state['instances'][0])
        self.assertNotIn('uptime_seconds', state['instances'][0])


if __name__ == '__main__':
    unittest.main()
