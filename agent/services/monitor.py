import hashlib
import json
import threading
from typing import Callable

from core import config_store
from services.snapshot_builder import build_instances_snapshot


class SnapshotMonitor:
    def __init__(self, interval: int = 5):
        self.interval = interval
        self._thread = None
        self._stop_event = threading.Event()
        self._last_hash = None

    def start(self, on_change: Callable[[list[dict]], None] | None = None):
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(on_change,),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self, on_change):
        while not self._stop_event.wait(self.interval):
            instances = config_store.get_instances()
            snapshot = build_instances_snapshot(instances)
            snapshot_hash = self._hash_snapshot(snapshot)

            if snapshot_hash == self._last_hash:
                continue

            self._last_hash = snapshot_hash

            if on_change:
                try:
                    on_change(snapshot)
                except Exception as exc:
                    print(f'[monitor] callback error: {exc}')

    @staticmethod
    def _hash_snapshot(snapshot: list[dict]) -> str:
        payload = json.dumps(snapshot, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()
