from collections.abc import Callable


def drain_available_messages(
    ws,
    handle_message: Callable[[str], None],
    timeout_exception: type[Exception],
    closed_exception: type[Exception],
    limit: int,
) -> int:
    """Drain a bounded batch so periodic work still gets execution time."""
    received = 0

    for _ in range(max(1, limit)):
        try:
            raw_message = ws.recv()
        except timeout_exception:
            break

        if raw_message is None:
            raise closed_exception()

        handle_message(raw_message)
        received += 1

    return received
