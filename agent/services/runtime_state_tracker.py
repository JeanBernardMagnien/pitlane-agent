import json
import threading
import uuid


def semantic_state_signature(state: dict) -> str:
    """Return the stable identity of the facts exported to the Hub."""
    comparable = json.loads(json.dumps(state))

    for instance in comparable.get('instances', []):
        if not isinstance(instance, dict):
            continue

        # Observation timestamps prove when the current value was sampled. They
        # do not turn an otherwise identical value into a business change.
        instance.pop('drivers_seen_at', None)
        instance.pop('log_drivers_seen_at', None)

    comparable.get('instances', []).sort(
        key=lambda instance: str(instance.get('id') or '') if isinstance(instance, dict) else '',
    )

    return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class RuntimeStateTracker:
    """Owns one boot identity and one monotonic semantic revision."""

    def __init__(self, boot_id: str | None = None):
        self.boot_id = boot_id or str(uuid.uuid4())
        self._revision = 0
        self._signature = None
        self._state = None
        self._lock = threading.RLock()

    def observe(self, state: dict) -> dict:
        signature = semantic_state_signature(state)

        with self._lock:
            if self._state is None or signature != self._signature:
                self._revision += 1
                self._signature = signature

            # Non-semantic evidence timestamps may advance without incrementing
            # the revision. Keep them current for the next explicit sync.
            self._state = state

            return self._snapshot()

    def current(self) -> dict | None:
        with self._lock:
            return self._snapshot() if self._state is not None else None

    def _snapshot(self) -> dict:
        return {
            'agent_boot_id': self.boot_id,
            'runtime_revision': self._revision,
            'payload': self._state,
        }


runtime_state_tracker = RuntimeStateTracker()
