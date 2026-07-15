import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


ARTIFACT_NAMESPACE = uuid.UUID('d9ff96cb-f7fb-4c24-82c6-acde89860fe9')


def _utc_iso(timestamp: float | None = None) -> str:
    value = datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp is not None else datetime.now(timezone.utc)
    return value.isoformat().replace('+00:00', 'Z')


def _safe_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


class ResultArtifactSpool:
    def __init__(self, root: str | Path, stable_scans: int = 2):
        self.root = Path(root)
        self.launches_dir = self.root / 'launches'
        self.artifacts_dir = self.root / 'artifacts'
        self.files_dir = self.root / 'files'
        self.stable_scans = max(2, int(stable_scans))
        self._candidates: dict[str, tuple[int, int, int]] = {}
        self._lock = threading.RLock()

        for directory in (self.launches_dir, self.artifacts_dir, self.files_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def register_launch(self, instance_id: str, launch_id: int, runtime_config: dict) -> dict | None:
        server = runtime_config.get('Server') if isinstance(runtime_config, dict) else None
        if not isinstance(server, dict):
            raise ValueError('runtime_config.Server requis pour suivre les résultats')

        if server.get('CollectResults') is False:
            return None

        correlation_id = str(server.get('ResultCorrelationId') or '').strip()
        upload_url = str(server.get('ResultsPostUrl') or '').strip()
        results_path = str(server.get('ResultsPath') or '').strip().rstrip('/\\')

        if launch_id <= 0 or not correlation_id or not upload_url or not results_path:
            raise ValueError('métadonnées de tentative résultat incomplètes')

        with self._lock:
            for _ in range(self.stable_scans):
                self.scan_once()
            path = self._launch_path(launch_id, correlation_id)
            existing = _safe_json(path)
            if existing is not None:
                return existing

            results_dir = Path(results_path)
            baseline = sorted(item.name for item in results_dir.glob('*.json') if item.is_file())
            now = time.time()
            manifest = {
                'schema_version': 1,
                'instance_id': str(instance_id),
                'launch_id': int(launch_id),
                'result_correlation_id': correlation_id,
                'upload_url': upload_url,
                'results_path': str(results_dir),
                'registered_at': _utc_iso(now),
                'registered_at_epoch': now,
                'baseline_files': baseline,
                'observed_files': [],
            }
            self._write_json(path, manifest)
            return manifest

    def scan_once(self) -> list[dict]:
        created = []

        with self._lock:
            launches = self._launch_manifests()
            for index, launch in enumerate(launches):
                next_registered_at = (
                    float(launches[index + 1]['registered_at_epoch'])
                    if index + 1 < len(launches) and launches[index + 1]['instance_id'] == launch['instance_id']
                    else None
                )
                created.extend(self._scan_launch(launch, next_registered_at))

        return created

    def pending(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        with self._lock:
            manifests = []
            for path in sorted(self.artifacts_dir.glob('*.json')):
                manifest = _safe_json(path)
                if not manifest or manifest.get('status') != 'pending':
                    continue
                if float(manifest.get('next_attempt_at') or 0) <= now:
                    manifests.append(manifest)
            return manifests

    def file_path(self, artifact: dict) -> Path:
        return self.files_dir / f"{artifact['artifact_id']}.json"

    def mark_delivered(self, artifact_id: str, response_status: int) -> None:
        with self._lock:
            manifest = self._artifact(artifact_id)
            if not manifest:
                return
            manifest.update({
                'status': 'delivered',
                'delivered_at': _utc_iso(),
                'response_status': int(response_status),
                'last_error': None,
                'next_attempt_at': 0,
            })
            self._write_json(self._artifact_path(artifact_id), manifest)

    def mark_failed(self, artifact_id: str, error: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            manifest = self._artifact(artifact_id)
            if not manifest:
                return
            attempts = int(manifest.get('attempts') or 0) + 1
            manifest.update({
                'status': 'pending',
                'attempts': attempts,
                'last_error': str(error)[:500],
                'next_attempt_at': now + min(2 ** min(attempts, 8), 300),
            })
            self._write_json(self._artifact_path(artifact_id), manifest)

    def resync(
        self,
        instance_id: str | None = None,
        launch_id: int | None = None,
        result_correlation_id: str | None = None,
    ) -> dict:
        self.scan_once()
        reset = 0
        total = 0

        with self._lock:
            for path in sorted(self.artifacts_dir.glob('*.json')):
                manifest = _safe_json(path)
                if not manifest:
                    continue
                if instance_id is not None and manifest.get('instance_id') != str(instance_id):
                    continue
                if launch_id is not None and int(manifest.get('launch_id') or 0) != int(launch_id):
                    continue
                if result_correlation_id is not None and manifest.get('result_correlation_id') != result_correlation_id:
                    continue
                total += 1
                if manifest.get('status') == 'delivered':
                    manifest['status'] = 'pending'
                    manifest['next_attempt_at'] = 0
                    manifest['last_error'] = None
                    self._write_json(path, manifest)
                    reset += 1

        return {'artifacts': total, 'requeued': reset}

    def inventory(
        self,
        instance_id: str | None = None,
        launch_id: int | None = None,
        result_correlation_id: str | None = None,
    ) -> list[dict]:
        with self._lock:
            inventory = []
            for path in sorted(self.artifacts_dir.glob('*.json')):
                manifest = _safe_json(path)
                if not manifest:
                    continue
                if instance_id is not None and manifest.get('instance_id') != str(instance_id):
                    continue
                if launch_id is not None and int(manifest.get('launch_id') or 0) != int(launch_id):
                    continue
                if result_correlation_id is not None and manifest.get('result_correlation_id') != result_correlation_id:
                    continue
                inventory.append({key: manifest.get(key) for key in (
                    'artifact_id', 'instance_id', 'launch_id', 'result_correlation_id',
                    'filename', 'sha256', 'size', 'created_at', 'session_type_hint',
                    'status', 'attempts', 'last_error', 'delivered_at',
                    'purged_at',
                )})
            return inventory

    def storage_usage(self, max_bytes: int = 0, minimum_free_bytes: int = 0) -> dict:
        max_bytes = max(0, int(max_bytes))
        minimum_free_bytes = max(0, int(minimum_free_bytes))

        with self._lock:
            status_counts: dict[str, int] = {}
            for path in self.artifacts_dir.glob('*.json'):
                manifest = _safe_json(path)
                if not manifest:
                    continue
                status = str(manifest.get('status') or 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1

            total_bytes = 0
            file_count = 0
            for directory in (self.launches_dir, self.artifacts_dir, self.files_dir):
                for path in directory.glob('*'):
                    try:
                        if path.is_file():
                            total_bytes += path.stat().st_size
                            file_count += 1
                    except OSError:
                        continue

            try:
                disk = shutil.disk_usage(self.root)
                disk_total_bytes = int(disk.total)
                disk_free_bytes = int(disk.free)
            except OSError:
                disk_total_bytes = None
                disk_free_bytes = None

            critical_reasons = []
            warning_reasons = []
            if max_bytes > 0 and total_bytes >= max_bytes:
                critical_reasons.append('result_spool_limit_reached')
            elif max_bytes > 0 and total_bytes >= int(max_bytes * 0.8):
                warning_reasons.append('result_spool_near_limit')

            if disk_free_bytes is not None and disk_free_bytes <= minimum_free_bytes:
                critical_reasons.append('disk_free_space_below_minimum')
            elif disk_free_bytes is not None and disk_free_bytes <= minimum_free_bytes * 2:
                warning_reasons.append('disk_free_space_near_minimum')

            status = 'critical' if critical_reasons else ('warning' if warning_reasons else 'healthy')

            return {
                'status': status,
                'reasons': critical_reasons + warning_reasons,
                'file_count': file_count,
                'stored_bytes': total_bytes,
                'max_stored_bytes': max_bytes,
                'stored_percent': round(total_bytes / max_bytes * 100, 2) if max_bytes > 0 else None,
                'disk_total_bytes': disk_total_bytes,
                'disk_free_bytes': disk_free_bytes,
                'minimum_free_bytes': minimum_free_bytes,
                'artifacts': status_counts,
            }

    def purge_delivered(
        self,
        artifact_ids: list[str],
        instance_id: str | None = None,
        execute: bool = False,
    ) -> dict:
        requested_ids = list(dict.fromkeys(str(value).strip() for value in artifact_ids if str(value).strip()))
        if len(requested_ids) > 1000:
            raise ValueError('maximum 1000 artefacts par purge')

        summary = {
            'dry_run': not execute,
            'requested': len(requested_ids),
            'eligible': 0,
            'purged': 0,
            'bytes': 0,
            'missing_files': 0,
            'protected': 0,
            'not_found': 0,
        }

        with self._lock:
            for artifact_id in requested_ids:
                manifest = self._artifact(artifact_id)
                if not manifest:
                    summary['not_found'] += 1
                    continue
                if instance_id is not None and manifest.get('instance_id') != str(instance_id):
                    summary['protected'] += 1
                    continue
                if manifest.get('status') != 'delivered' or manifest.get('session_type_hint') not in ('PRACTICE', 'WARMUP'):
                    summary['protected'] += 1
                    continue

                path = self.file_path(manifest)
                try:
                    stored_bytes = path.stat().st_size if path.is_file() else None
                except OSError:
                    stored_bytes = None

                summary['eligible'] += 1
                if stored_bytes is None:
                    summary['missing_files'] += 1
                else:
                    summary['bytes'] += stored_bytes

                if not execute:
                    continue

                try:
                    if path.is_file():
                        path.unlink()
                except OSError as exc:
                    raise RuntimeError(f'impossible de supprimer {artifact_id}: {exc}') from exc

                manifest.update({
                    'status': 'purged',
                    'purged_at': _utc_iso(),
                    'last_error': None,
                    'next_attempt_at': 0,
                })
                self._write_json(self._artifact_path(artifact_id), manifest)
                summary['purged'] += 1

        return summary

    def notification_candidates(self, hub_name: str, hub_base_url: str | None = None) -> list[dict]:
        expected_origin = self._url_origin(hub_base_url) if hub_base_url else None

        with self._lock:
            candidates = []
            for path in sorted(self.artifacts_dir.glob('*.json')):
                manifest = _safe_json(path)
                if not manifest or manifest.get('status') == 'purged' or hub_name in (manifest.get('notified_hubs') or []):
                    continue
                if expected_origin and self._url_origin(manifest.get('upload_url')) != expected_origin:
                    continue
                candidates.append({key: manifest.get(key) for key in (
                    'type', 'schema_version', 'artifact_id', 'instance_id', 'launch_id',
                    'result_correlation_id', 'filename', 'sha256', 'size', 'created_at',
                    'session_type_hint',
                ) if manifest.get(key) is not None})
            return candidates

    def mark_notified(self, artifact_id: str, hub_name: str) -> None:
        with self._lock:
            manifest = self._artifact(artifact_id)
            if not manifest:
                return
            notified_hubs = set(manifest.get('notified_hubs') or [])
            notified_hubs.add(str(hub_name))
            manifest['notified_hubs'] = sorted(notified_hubs)
            self._write_json(self._artifact_path(artifact_id), manifest)

    def _scan_launch(self, launch: dict, next_registered_at: float | None) -> list[dict]:
        results_dir = Path(str(launch['results_path']))
        if not results_dir.is_dir():
            return []

        baseline = set(launch.get('baseline_files') or [])
        observed = set(launch.get('observed_files') or [])
        created = []

        for source_path in sorted(results_dir.glob('*.json')):
            if not source_path.is_file() or source_path.name in baseline or source_path.name in observed:
                continue

            try:
                stat = source_path.stat()
            except OSError:
                continue

            registered_at = float(launch['registered_at_epoch'])
            if stat.st_mtime < registered_at - 2:
                continue
            if next_registered_at is not None and stat.st_mtime >= next_registered_at:
                continue
            if not self._is_stable(source_path, stat.st_size, stat.st_mtime_ns):
                continue

            try:
                raw = source_path.read_bytes()
                payload = json.loads(raw.decode('utf-8-sig'))
                if not isinstance(payload, dict):
                    continue
            except (OSError, UnicodeError, ValueError):
                continue

            artifact = self._enqueue(launch, source_path, raw, stat.st_mtime)
            observed.add(source_path.name)
            launch['observed_files'] = sorted(observed)
            self._write_json(self._launch_path(int(launch['launch_id']), launch['result_correlation_id']), launch)
            created.append(artifact)

        return created

    def _is_stable(self, path: Path, size: int, mtime_ns: int) -> bool:
        key = str(path.resolve())
        previous = self._candidates.get(key)
        count = previous[2] + 1 if previous and previous[:2] == (size, mtime_ns) else 1
        self._candidates[key] = (size, mtime_ns, count)
        return count >= self.stable_scans

    def _enqueue(self, launch: dict, source_path: Path, raw: bytes, created_timestamp: float) -> dict:
        sha256 = hashlib.sha256(raw).hexdigest()
        identity = f"{launch['launch_id']}:{launch['result_correlation_id']}:{source_path.name}:{sha256}"
        artifact_id = str(uuid.uuid5(ARTIFACT_NAMESPACE, identity))
        target_path = self.files_dir / f'{artifact_id}.json'
        if not target_path.exists():
            temporary_path = target_path.with_suffix('.tmp')
            temporary_path.write_bytes(raw)
            os.replace(temporary_path, target_path)

        artifact = {
            'type': 'result_artifact_available',
            'schema_version': 1,
            'artifact_id': artifact_id,
            'instance_id': launch['instance_id'],
            'launch_id': int(launch['launch_id']),
            'result_correlation_id': launch['result_correlation_id'],
            'filename': source_path.name,
            'sha256': sha256,
            'size': len(raw),
            'created_at': _utc_iso(created_timestamp),
            'session_type_hint': self._session_type_hint(source_path.name),
            'upload_url': launch['upload_url'],
            'status': 'pending',
            'attempts': 0,
            'next_attempt_at': 0,
            'last_error': None,
            'delivered_at': None,
            'notified_hubs': [],
        }
        self._write_json(self._artifact_path(artifact_id), artifact)
        return artifact

    def _launch_manifests(self) -> list[dict]:
        manifests = [manifest for path in self.launches_dir.glob('*.json') if (manifest := _safe_json(path))]
        return sorted(manifests, key=lambda item: (str(item.get('instance_id')), float(item.get('registered_at_epoch') or 0)))

    def _artifact(self, artifact_id: str) -> dict | None:
        return _safe_json(self._artifact_path(artifact_id))

    def _launch_path(self, launch_id: int, result_correlation_id: str) -> Path:
        safe_correlation_id = ''.join(character for character in str(result_correlation_id).lower() if character in '0123456789abcdef')
        if not safe_correlation_id:
            raise ValueError('result_correlation_id invalide')
        return self.launches_dir / f'launch-{int(launch_id)}-{safe_correlation_id}.json'

    def _artifact_path(self, artifact_id: str) -> Path:
        return self.artifacts_dir / f'{Path(str(artifact_id)).name}.json'

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(path.suffix + '.tmp')
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary_path, path)

    @staticmethod
    def _session_type_hint(filename: str) -> str | None:
        normalized = filename.lower()
        for marker, session_type in (
            ('_practice.', 'PRACTICE'),
            ('_qualify.', 'QUALIFYING'),
            ('_qualifying.', 'QUALIFYING'),
            ('_warmup.', 'WARMUP'),
            ('_race.', 'RACE'),
        ):
            if marker in normalized:
                return session_type
        return None

    @staticmethod
    def _url_origin(value: str | None) -> tuple[str, str] | None:
        parsed = urlsplit(str(value or '').strip())
        if not parsed.scheme or not parsed.netloc:
            return None
        return parsed.scheme.lower(), parsed.netloc.lower()
