import hashlib
import logging
import threading
import urllib.error
import urllib.request
from pathlib import Path

from services.result_artifact_spool import ResultArtifactSpool


_pipeline = None
_pipeline_thread = None
_stop_event = threading.Event()


class ResultPipeline:
    def __init__(self, spool: ResultArtifactSpool, scan_interval: float = 1.0, upload_timeout: float = 10.0):
        self.spool = spool
        self.scan_interval = max(0.2, float(scan_interval))
        self.upload_timeout = max(1.0, float(upload_timeout))

    def run_once(self) -> dict:
        created = self.spool.scan_once()
        delivered = 0

        for artifact in self.spool.pending():
            try:
                status = self._upload(artifact)
                self.spool.mark_delivered(artifact['artifact_id'], status)
                delivered += 1
            except Exception as exc:
                self.spool.mark_failed(artifact['artifact_id'], f'{exc.__class__.__name__}: {exc}')

        return {'created': len(created), 'delivered': delivered}

    def _upload(self, artifact: dict) -> int:
        path = self.spool.file_path(artifact)
        raw = path.read_bytes()
        if len(raw) != int(artifact['size']) or hashlib.sha256(raw).hexdigest() != artifact['sha256']:
            raise ValueError('copie spool corrompue')

        request = urllib.request.Request(
            str(artifact['upload_url']),
            data=raw,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'PitLane-Agent/0.3',
                'X-Pitlane-Artifact-Id': artifact['artifact_id'],
                'X-Pitlane-Instance-Id': artifact['instance_id'],
                'X-Pitlane-Result-Correlation-Id': artifact['result_correlation_id'],
                'X-Pitlane-Artifact-Filename': artifact['filename'],
                'X-Pitlane-Artifact-Sha256': artifact['sha256'],
                'X-Pitlane-Artifact-Size': str(artifact['size']),
                'X-Pitlane-Artifact-Created-At': artifact['created_at'],
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(request, timeout=self.upload_timeout) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f'HTTP {response.status}')
                return int(response.status)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'HTTP {exc.code}') from exc


def _spool_root() -> Path:
    from core import config_store

    configured = config_store.LOGGING_CFG.get('results_spool_path')
    if configured:
        return Path(str(configured))
    return Path(config_store.LOGGING_CFG['logs_path']) / 'result-spool'


def get_result_pipeline() -> ResultPipeline:
    global _pipeline
    if _pipeline is None:
        from core import config_store

        _pipeline = ResultPipeline(
            ResultArtifactSpool(
                _spool_root(),
                stable_scans=int(config_store.GAME_CFG.get('result_stable_scans', 2)),
            ),
            scan_interval=float(config_store.GAME_CFG.get('result_scan_interval', 1.0)),
            upload_timeout=float(config_store.GAME_CFG.get('result_upload_timeout', 10.0)),
        )
    return _pipeline


def register_result_launch(instance_id: str, launch_id: int | None, runtime_config: dict) -> dict | None:
    if launch_id in (None, ''):
        return None
    return get_result_pipeline().spool.register_launch(instance_id, int(launch_id), runtime_config)


def resync_result_artifacts(
    instance_id: str | None = None,
    launch_id: int | None = None,
    result_correlation_id: str | None = None,
) -> dict:
    pipeline = get_result_pipeline()
    result = pipeline.spool.resync(instance_id, launch_id, result_correlation_id)
    result['inventory'] = pipeline.spool.inventory(instance_id, launch_id, result_correlation_id)
    return result


def _run_loop() -> None:
    pipeline = get_result_pipeline()
    while not _stop_event.is_set():
        try:
            result = pipeline.run_once()
            if result['created'] or result['delivered']:
                logging.info('[result-pipeline] nouveaux=%d envoyés=%d', result['created'], result['delivered'])
        except Exception as exc:
            logging.error('[result-pipeline] Erreur boucle: %s', exc)
        _stop_event.wait(pipeline.scan_interval)


def start_result_pipeline() -> None:
    global _pipeline_thread
    if _pipeline_thread and _pipeline_thread.is_alive():
        return

    _stop_event.clear()
    _pipeline_thread = threading.Thread(target=_run_loop, daemon=True, name='result-pipeline')
    _pipeline_thread.start()
    logging.info('[result-pipeline] Activé, spool=%s', _spool_root())
