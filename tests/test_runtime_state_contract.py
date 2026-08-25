import json
import re
import unittest
from pathlib import Path


class RuntimeStateContractTest(unittest.TestCase):
    def test_v2_example_matches_the_generated_contract_copy(self):
        contract_dir = Path(__file__).resolve().parents[1] / 'contracts' / 'agent'
        schema = json.loads((contract_dir / 'runtime-state.v2.schema.json').read_text(encoding='utf-8'))
        example = json.loads((contract_dir / 'runtime-state.v2.example.json').read_text(encoding='utf-8'))

        self.assertEqual(set(schema['required']), set(example))
        self.assertEqual('runtime_state', example['type'])
        self.assertEqual(2, example['schema_version'])
        self.assertIn(example['mode'], schema['properties']['mode']['enum'])
        self.assertRegex(example['agent_boot_id'], re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
        ))
        self.assertGreater(example['runtime_revision'], 0)


if __name__ == '__main__':
    unittest.main()
