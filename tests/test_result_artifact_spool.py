import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.result_artifact_spool import ResultArtifactSpool
from services.result_pipeline import ResultPipeline


class _Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class ResultArtifactSpoolTest(unittest.TestCase):
    def test_scan_ignores_baseline_and_enqueues_only_stable_json(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results = root / 'results' / 'server3'
            results.mkdir(parents=True)
            (results / 'results_old_practice.json').write_text('{"old":true}', encoding='utf-8')

            spool = ResultArtifactSpool(root / 'spool', stable_scans=2)
            spool.register_launch('server3', 42, self._runtime_config(results))

            result_path = results / 'results_20260714_141322_race.json'
            result_path.write_text('{"session_type":"Race",', encoding='utf-8')
            self.assertEqual([], spool.scan_once())

            result_path.write_text('{"session_type":"Race","is_completed":true}\n', encoding='utf-8')
            self.assertEqual([], spool.scan_once())
            created = spool.scan_once()

            self.assertEqual(1, len(created))
            artifact = created[0]
            self.assertEqual('RACE', artifact['session_type_hint'])
            self.assertEqual('pending', artifact['status'])
            self.assertEqual(result_path.name, artifact['filename'])
            self.assertEqual(result_path.read_bytes(), spool.file_path(artifact).read_bytes())
            self.assertEqual([artifact['artifact_id']], [item['artifact_id'] for item in spool.pending()])

            restored_spool = ResultArtifactSpool(root / 'spool', stable_scans=2)
            self.assertEqual([], restored_spool.scan_once())
            self.assertEqual(1, len(restored_spool.inventory(launch_id=42)))

    def test_pipeline_uploads_then_resync_requeues_same_artifact(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results = root / 'results' / 'server3'
            results.mkdir(parents=True)
            spool = ResultArtifactSpool(root / 'spool', stable_scans=2)
            spool.register_launch('server3', 42, self._runtime_config(results))
            (results / 'results_20260714_141322_race.json').write_text(
                json.dumps({'session_type': 'Race', 'is_completed': True}),
                encoding='utf-8',
            )
            spool.scan_once()
            spool.scan_once()

            pipeline = ResultPipeline(spool)
            with patch('services.result_pipeline.urllib.request.urlopen', return_value=_Response()) as urlopen:
                outcome = pipeline.run_once()

            self.assertEqual({'created': 0, 'delivered': 1}, outcome)
            request = urlopen.call_args.args[0]
            inventory = spool.inventory(launch_id=42)
            self.assertEqual('delivered', inventory[0]['status'])
            self.assertEqual(inventory[0]['artifact_id'], request.get_header('X-pitlane-artifact-id'))

            self.assertEqual({'artifacts': 1, 'requeued': 1}, spool.resync('server3', 42))
            self.assertEqual(1, len(spool.pending()))

    def test_new_launch_boundary_captures_previous_result_and_allows_hub_id_collision(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results = root / 'results' / 'server3'
            results.mkdir(parents=True)
            spool = ResultArtifactSpool(root / 'spool', stable_scans=2)

            first_correlation = '0123456789abcdef0123456789abcdef'
            second_correlation = 'fedcba9876543210fedcba9876543210'
            spool.register_launch('server3', 42, self._runtime_config(results, first_correlation))
            (results / 'results_20260714_141322_race.json').write_text(
                '{"session_type":"Race","is_completed":true}',
                encoding='utf-8',
            )

            spool.register_launch('server3', 42, self._runtime_config(results, second_correlation))

            inventory = spool.inventory('server3', 42)
            self.assertEqual(1, len(inventory))
            self.assertEqual(first_correlation, inventory[0]['result_correlation_id'])
            self.assertEqual(2, len(list((root / 'spool' / 'launches').glob('*.json'))))

    def test_notification_targets_only_the_upload_hub(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            results = root / 'results' / 'server3'
            results.mkdir(parents=True)
            spool = ResultArtifactSpool(root / 'spool', stable_scans=2)
            spool.register_launch('server3', 42, self._runtime_config(results))
            (results / 'results_20260714_141322_race.json').write_text(
                '{"session_type":"Race","is_completed":true}',
                encoding='utf-8',
            )
            spool.scan_once()
            spool.scan_once()

            self.assertEqual(1, len(spool.notification_candidates('local', 'https://hub.test')))
            self.assertEqual(0, len(spool.notification_candidates('production', 'https://pitlane.example')))

    def _runtime_config(
        self,
        results_path: Path,
        correlation_id: str = '0123456789abcdef0123456789abcdef',
    ) -> dict:
        return {
            'Server': {
                'LaunchSessionId': 42,
                'ResultCorrelationId': correlation_id,
                'ResultsPostUrl': 'https://hub.test/api/agent/results/42?token=signed',
                'ResultsPath': str(results_path),
            },
        }


if __name__ == '__main__':
    unittest.main()
