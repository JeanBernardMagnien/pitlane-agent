import datetime
import json
import re
import unittest
from pathlib import Path


CONTRACT_ROOT = Path(__file__).resolve().parents[1] / "contracts" / "agent"


class ResultArtifactContractTest(unittest.TestCase):
    def test_v1_example_matches_the_versioned_schema(self):
        schema = self._json_file("result-artifact-available.v1.schema.json")
        example = self._json_file("result-artifact-available.v1.example.json")

        self.assertTrue(set(schema["required"]).issubset(example))
        self.assertTrue(set(example).issubset(schema["properties"]))
        self.assertEqual(schema["properties"]["type"]["const"], example["type"])
        self.assertEqual(
            schema["properties"]["schema_version"]["const"],
            example["schema_version"],
        )
        self.assertRegex(example["artifact_id"], re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            re.IGNORECASE,
        ))
        self.assertRegex(example["result_correlation_id"], r"^[a-f0-9]{32}$")
        self.assertRegex(example["sha256"], r"^[a-f0-9]{64}$")
        self.assertNotRegex(example["filename"], r"[/\\]")
        self.assertIn(
            example["session_type_hint"],
            schema["properties"]["session_type_hint"]["enum"],
        )
        datetime.datetime.fromisoformat(example["created_at"].replace("Z", "+00:00"))

    def _json_file(self, filename):
        return json.loads((CONTRACT_ROOT / filename).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
