import unittest

from services.websocket_inbox import drain_available_messages


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


class HubWebSocketClientTest(unittest.TestCase):
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
