import json
import threading


class RuntimeStateSession:
    """Serializes one Hub connection's sync and semantic changes."""

    def __init__(self, ws, send_lock: threading.Lock, state_builder=None, tracker=None):
        if state_builder is None or tracker is None:
            from services.runtime_reporter import build_semantic_runtime_state
            from services.runtime_state_tracker import runtime_state_tracker

            state_builder = state_builder or build_semantic_runtime_state
            tracker = tracker or runtime_state_tracker

        self.ws = ws
        self.send_lock = send_lock
        self.state_builder = state_builder
        self.tracker = tracker
        self.last_sent_revision = 0
        self._runtime_lock = threading.RLock()

    def send_sync(self) -> bool:
        with self._runtime_lock:
            observed = self.tracker.observe(self.state_builder())
            self._send('sync', observed)
            return True

    def send_if_changed(self) -> bool:
        with self._runtime_lock:
            observed = self.tracker.observe(self.state_builder())
            if observed['runtime_revision'] <= self.last_sent_revision:
                return False

            self._send('change', observed)
            return True

    def _send(self, mode: str, observed: dict) -> None:
        raw = json.dumps({
            'type': 'runtime_state',
            'schema_version': 2,
            'mode': mode,
            **observed,
        }, ensure_ascii=False)
        with self.send_lock:
            self.ws.send(raw)
        self.last_sent_revision = observed['runtime_revision']
