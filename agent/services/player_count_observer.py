import re
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


PLAYER_COUNT_PATTERN = re.compile(
    r'^\[(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\].*?Server updated:\s*(?P<count>\d+)\s+players?\s*$',
    re.IGNORECASE,
)
SESSION_CREATED_PATTERN = re.compile(
    r'\b(?:TimeAttackRemote|InstantRaceRemote)\s+'
    r'(?P<phase>Practice|Qualifying|Warmup|Race)\s+created\b',
    re.IGNORECASE,
)
TIMED_SESSION_STARTED_PATTERN = re.compile(r'\bOutplap split\b', re.IGNORECASE)
RACE_STARTED_PATTERN = re.compile(r'\bsetSessionPhase\s+Session\s*$', re.IGNORECASE)
CRASH_PATTERN = re.compile(r'\[(?:crash)\]|\bFatal error\b', re.IGNORECASE)
LOG_PLAYER_COUNT_FRESH_SECONDS = 30


def _utc_iso_from_log_timestamp(value: str) -> str:
    local_time = datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f').astimezone()
    return local_time.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


class PlayerCountObserver:
    """Observe incrémentalement les faits runtime fiables exposés par le log AC EVO."""

    def __init__(self):
        self._states: dict[str, dict] = {}
        self._lock = Lock()

    def observe(self, instance_id: str, runtime_info: dict, logs_path: str | Path) -> dict:
        log_path = self._resolve_log_path(instance_id, runtime_info, logs_path)
        if log_path is None:
            return self._empty_observation()

        process = runtime_info.get('process')
        pid = getattr(process, 'pid', None)
        process_started_at = runtime_info.get('started_at')
        identity = (str(log_path), pid, process_started_at)

        with self._lock:
            state = self._states.get(instance_id)
            if state is None or state.get('identity') != identity:
                state = {
                    'identity': identity,
                    'offset': 0,
                    'buffer': '',
                    'count': None,
                    'observed_at': None,
                    'first_driver_seen_at': None,
                    'session_phase': None,
                    'session_observed_at': None,
                    'sport_started_at': None,
                    'crash_detected_at': None,
                    'crash_message': None,
                    'log_observed_from_start': True,
                }
                self._states[instance_id] = state

            self._read_appended_lines(log_path, state)

            return {
                'log_connected_drivers': state.get('count'),
                'log_drivers_seen_at': state.get('observed_at'),
                'first_driver_seen_at': state.get('first_driver_seen_at'),
                'session_phase': state.get('session_phase'),
                'session_observed_at': state.get('session_observed_at'),
                'sport_started_at': state.get('sport_started_at'),
                'crash_detected_at': state.get('crash_detected_at'),
                'crash_message': state.get('crash_message'),
                'log_observed_from_start': bool(state.get('log_observed_from_start')),
            }

    def forget(self, instance_id: str) -> None:
        with self._lock:
            self._states.pop(instance_id, None)

    def _resolve_log_path(self, instance_id: str, runtime_info: dict, logs_path: str | Path) -> Path | None:
        configured_path = runtime_info.get('log_path')
        if configured_path:
            path = Path(configured_path)
            if path.is_file():
                return path

        log_file = runtime_info.get('log_file')
        file_name = getattr(log_file, 'name', None)
        if file_name:
            path = Path(file_name)
            if path.is_file():
                return path

        candidates = sorted(
            Path(logs_path).glob(f'log_{instance_id}_*.log'),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _read_appended_lines(self, log_path: Path, state: dict) -> None:
        try:
            size = log_path.stat().st_size
            if size < int(state.get('offset') or 0):
                state.update(
                    offset=0,
                    buffer='',
                    count=None,
                    observed_at=None,
                    first_driver_seen_at=None,
                    session_phase=None,
                    session_observed_at=None,
                    sport_started_at=None,
                    crash_detected_at=None,
                    crash_message=None,
                    log_observed_from_start=False,
                )

            with log_path.open('r', encoding='utf-8', errors='replace') as handle:
                handle.seek(int(state.get('offset') or 0))
                appended = handle.read()
                state['offset'] = handle.tell()
        except OSError:
            return

        content = f"{state.get('buffer') or ''}{appended}"
        lines = content.splitlines(keepends=True)
        state['buffer'] = ''

        if lines and not lines[-1].endswith(('\n', '\r')):
            state['buffer'] = lines.pop()

        for line in lines:
            stripped_line = line.strip()
            timestamp = self._line_timestamp(stripped_line)
            player_count_match = PLAYER_COUNT_PATTERN.search(stripped_line)
            if player_count_match is not None:
                count = int(player_count_match.group('count'))
                observed_at = _utc_iso_from_log_timestamp(player_count_match.group('timestamp'))
                state['count'] = count
                state['observed_at'] = observed_at
                if count > 0 and state.get('first_driver_seen_at') is None:
                    state['first_driver_seen_at'] = observed_at

            session_created_match = SESSION_CREATED_PATTERN.search(stripped_line)
            if session_created_match is not None:
                state['session_phase'] = self._normalize_phase(session_created_match.group('phase'))
                state['session_observed_at'] = timestamp

            if (
                TIMED_SESSION_STARTED_PATTERN.search(stripped_line) is not None
                and state.get('session_phase') == 'qualifying'
            ):
                state['sport_started_at'] = state.get('sport_started_at') or timestamp

            if (
                RACE_STARTED_PATTERN.search(stripped_line) is not None
                and state.get('session_phase') == 'race'
            ):
                state['sport_started_at'] = state.get('sport_started_at') or timestamp

            if CRASH_PATTERN.search(stripped_line) is not None:
                state['crash_detected_at'] = timestamp
                state['crash_message'] = stripped_line[-500:]

    @staticmethod
    def _line_timestamp(line: str) -> str | None:
        match = re.match(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]', line)
        return _utc_iso_from_log_timestamp(match.group(1)) if match else None

    @staticmethod
    def _normalize_phase(value: str) -> str:
        normalized = value.strip().lower()
        return {
            'practice': 'practice',
            'qualify': 'qualifying',
            'qualifying': 'qualifying',
            'qualification': 'qualifying',
            'warmup': 'warmup',
            'race': 'race',
        }.get(normalized, normalized)

    @staticmethod
    def _empty_observation() -> dict:
        return {
            'log_connected_drivers': None,
            'log_drivers_seen_at': None,
            'first_driver_seen_at': None,
            'session_phase': None,
            'session_observed_at': None,
            'sport_started_at': None,
            'crash_detected_at': None,
            'crash_message': None,
            'log_observed_from_start': False,
        }


def _timestamp_age_seconds(value: str | None) -> float | None:
    if not value:
        return None

    try:
        observed_at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None

    return max(0.0, (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds())


class PlayerCountResolver:
    """Fusionne les sources sans transformer une divergence en faux zéro."""

    def __init__(self):
        self._http_states: dict[str, dict] = {}
        self._lock = Lock()

    def resolve(
        self,
        instance_id: str,
        process_identity: str,
        http_observation: dict,
        log_observation: dict,
    ) -> dict:
        http_count = http_observation.get('http_connected_drivers')
        http_seen_at = http_observation.get('http_drivers_seen_at')
        log_count = log_observation.get('log_connected_drivers')
        log_seen_at = log_observation.get('log_drivers_seen_at')
        log_age = _timestamp_age_seconds(log_seen_at)
        log_is_fresh = log_count is not None and log_age is not None and log_age <= LOG_PLAYER_COUNT_FRESH_SECONDS

        with self._lock:
            state = self._http_states.get(instance_id)
            if state is None or state.get('process_identity') != process_identity:
                state = {'process_identity': process_identity, 'zero_streak': 0}
                self._http_states[instance_id] = state

            if http_count == 0:
                state['zero_streak'] = int(state.get('zero_streak') or 0) + 1
            else:
                state['zero_streak'] = 0
            http_zero_confirmed = state['zero_streak'] >= 2

        conflict = bool(log_is_fresh and http_count is not None and int(log_count) != int(http_count))
        if conflict:
            effective_count = None
            effective_seen_at = max(filter(None, [log_seen_at, http_seen_at]), default=None)
            source = 'conflict'
            zero_confirmed = False
        elif log_is_fresh:
            effective_count = int(log_count)
            effective_seen_at = log_seen_at
            source = 'game_log'
            zero_confirmed = effective_count == 0
        elif http_count is not None:
            effective_count = int(http_count)
            effective_seen_at = http_seen_at
            source = 'http'
            zero_confirmed = effective_count == 0 and http_zero_confirmed
        else:
            effective_count = None
            effective_seen_at = None
            source = None
            zero_confirmed = False

        return {
            **http_observation,
            **log_observation,
            'connected_drivers': effective_count,
            'drivers_seen_at': effective_seen_at,
            'drivers_source': source,
            'drivers_conflict': conflict,
            'drivers_zero_confirmed': zero_confirmed,
        }


_observer = PlayerCountObserver()
_resolver = PlayerCountResolver()


def observe_player_count(instance_id: str, runtime_info: dict, logs_path: str | Path) -> dict:
    return _observer.observe(instance_id, runtime_info, logs_path)


def forget_player_count(instance_id: str) -> None:
    _observer.forget(instance_id)


def resolve_player_count(
    instance_id: str,
    process_identity: str,
    http_observation: dict,
    log_observation: dict,
) -> dict:
    return _resolver.resolve(instance_id, process_identity, http_observation, log_observation)
