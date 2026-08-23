import unittest

from services.websocket_inbox import drain_available_messages
from services.websocket_authentication import (
    HubAuthenticationError,
    ReconnectBackoff,
    await_hello_acknowledgement,
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


if __name__ == '__main__':
    unittest.main()
