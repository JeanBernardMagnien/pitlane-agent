import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / "agent"
sys.path.insert(0, str(AGENT_ROOT))

from services.acevo_catalog import catalog_snapshot


class AcevoCatalogSnapshotTest(unittest.TestCase):
    def test_returns_build_catalog_and_stable_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cars = {"cars": [{"name": "car-b"}, {"name": "car-a"}]}
            tracks = {"events": [{"track": "Spa", "layout": "GP"}]}
            (root / "cars.json").write_text(json.dumps(cars), encoding="utf-8")
            (root / "events_race_weekend.json").write_text(json.dumps(tracks), encoding="utf-8")
            manifest = root / "appmanifest.acf"
            manifest.write_text('"AppState" { "buildid" "24944328" }', encoding="utf-8")

            first, first_status = catalog_snapshot(
                {"install_path": str(root)},
                {"appmanifest_path": str(manifest)},
            )
            (root / "cars.json").write_text(json.dumps(cars, indent=4), encoding="utf-8")
            second, second_status = catalog_snapshot(
                {"install_path": str(root)},
                {"appmanifest_path": str(manifest)},
            )

            self.assertEqual(200, first_status)
            self.assertEqual(200, second_status)
            self.assertEqual("24944328", first["build_id"])
            self.assertEqual(first["fingerprint"], second["fingerprint"])
            self.assertEqual(64, len(first["fingerprint"]))

    def test_rejects_missing_authoritative_catalog_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "appmanifest.acf"
            manifest.write_text('"buildid" "24944328"', encoding="utf-8")

            payload, status = catalog_snapshot(
                {"install_path": str(root)},
                {"appmanifest_path": str(manifest)},
            )

            self.assertEqual(422, status)
            self.assertIn("introuvable", payload["error"])


if __name__ == "__main__":
    unittest.main()
