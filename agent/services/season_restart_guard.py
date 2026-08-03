import logging
import threading

from core import config_store
from services.player_count_observer import observe_player_count
from services.process_supervisor import process_supervisor


DEFAULT_GUARD_INTERVAL_SECONDS = 0.2


class SeasonRestartGuard:
    """Applique hors réseau un arrêt local préautorisé par le Hub."""

    def __init__(self, snapshot_running, observe, stop, logging_cfg: dict):
        self._snapshot_running = snapshot_running
        self._observe = observe
        self._stop = stop
        self._logging_cfg = logging_cfg

    def run_once(self) -> int:
        stopped = 0

        for instance_id, info in self._snapshot_running():
            process = info.get('process')
            policy = info.get('runtime_policy') or {}
            if (
                process is None
                or process.poll() is not None
                or policy.get('stop_on_season_restart') is not True
                or info.get('season_restart_guard_triggered') is True
            ):
                continue

            observation = self._observe(
                instance_id,
                info,
                self._logging_cfg.get('logs_path') or 'logs',
            )
            info['game_observation'] = observation

            if (
                int(observation.get('season_restart_count') or 0) < 1
                or not observation.get('season_restart_observed_at')
            ):
                continue

            # Réserver la décision avant l'arrêt rend la garde idempotente même
            # si la commande normale du Hub arrive au même instant.
            info['season_restart_guard_triggered'] = True
            logging.warning(
                '[season-restart-guard] Arrêt local préautorisé de %s après Restart Season',
                instance_id,
            )
            try:
                self._stop(instance_id, self._logging_cfg, reason='normal')
            except Exception:
                # Une erreur transitoire ne doit pas désarmer définitivement
                # le garde-fou : la prochaine itération retentera l'arrêt.
                info['season_restart_guard_triggered'] = False
                raise
            stopped += 1

        return stopped


_guard_thread = None
_stop_event = threading.Event()


def _run_loop() -> None:
    from services.server_manager import stop_instance

    guard = SeasonRestartGuard(
        process_supervisor.snapshot_running,
        observe_player_count,
        stop_instance,
        config_store.LOGGING_CFG,
    )

    while not _stop_event.is_set():
        try:
            guard.run_once()
        except Exception as exc:
            logging.error('[season-restart-guard] Erreur boucle: %s', exc)
        _stop_event.wait(DEFAULT_GUARD_INTERVAL_SECONDS)


def start_season_restart_guard() -> None:
    global _guard_thread

    if _guard_thread and _guard_thread.is_alive():
        return

    _stop_event.clear()
    _guard_thread = threading.Thread(
        target=_run_loop,
        daemon=True,
        name='season-restart-guard',
    )
    _guard_thread.start()
    logging.info('[season-restart-guard] Garde locale active')
