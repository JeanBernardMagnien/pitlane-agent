import sys
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.runtime_policy import normalize_runtime_policy


class RuntimePolicyTest(unittest.TestCase):
    def test_missing_policy_keeps_local_guard_disabled(self):
        self.assertEqual(
            {'stop_on_season_restart': False},
            normalize_runtime_policy(None),
        )

    def test_explicit_season_restart_guard_is_accepted(self):
        self.assertEqual(
            {'stop_on_season_restart': True},
            normalize_runtime_policy({'stop_on_season_restart': True}),
        )

    def test_unknown_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inconnue'):
            normalize_runtime_policy({'stop_on_disconnect': True})

    def test_non_boolean_policy_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'booléen'):
            normalize_runtime_policy({'stop_on_season_restart': 1})


if __name__ == '__main__':
    unittest.main()
