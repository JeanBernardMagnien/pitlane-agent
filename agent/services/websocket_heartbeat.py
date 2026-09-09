import time
from collections.abc import Callable


HUB_SILENCE_TIMEOUT_SECONDS = 35.0


class HubHeartbeat:
    """Bound inbound silence independently of outgoing runtime changes."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._last_received_at = clock()

    def mark_received(self) -> None:
        self._last_received_at = self._clock()

    def require_alive(self) -> None:
        if self._clock() - self._last_received_at >= HUB_SILENCE_TIMEOUT_SECONDS:
            raise ConnectionError('Hub silencieux depuis 35 s, reconnexion')
