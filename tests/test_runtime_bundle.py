import copy
import sys
import unittest
from pathlib import Path


AGENT_ROOT = Path(__file__).resolve().parents[1] / 'agent'
sys.path.insert(0, str(AGENT_ROOT))

from services.runtime_bundle import (
    LEGACY_MATERIALIZED_FIELDS,
    MATERIALIZED_FIELDS,
    RuntimeBundleError,
    calculate_runtime_bundle_hash,
    validate_runtime_bundle,
)


EXPECTED_HASH = '09ba0fed4e9cdf76cf3a76bcedf2d30f74aa316324e0cb3e3ed9b05967a4bdc8'
LEGACY_EXPECTED_HASH = '67b3270f86e8e38ff3fa1ebfc0dae75a11f05bcf5d2b056bf65977d0b32ba26c'


class RuntimeBundleTest(unittest.TestCase):
    def test_hash_matches_the_cross_language_canonical_fixture(self):
        bundle = self._bundle()

        self.assertEqual(EXPECTED_HASH, calculate_runtime_bundle_hash(bundle))

    def test_legacy_schema_one_remains_accepted_during_rollout(self):
        bundle = self._bundle()
        bundle['schema_version'] = 1
        bundle['materialized_fields'] = LEGACY_MATERIALIZED_FIELDS
        bundle['runtime_config']['Server'].pop('EntryListPath')

        confirmed_hash = validate_runtime_bundle(
            bundle,
            LEGACY_EXPECTED_HASH,
            bundle['runtime_config'],
        )

        self.assertEqual(LEGACY_EXPECTED_HASH, confirmed_hash)

    def test_private_values_are_validated_against_the_redacted_bundle(self):
        bundle = self._bundle()
        private_config = copy.deepcopy(bundle['runtime_config'])
        private_config['Server'].update({
            'AdminPassword': 'private-admin',
            'DriverPassword': 'private-driver',
            'LaunchSessionId': 123,
            'EntryListPath': r'C:\private\entrylists\launch_123.json',
            'ResultCorrelationId': '0123456789abcdef0123456789abcdef',
            'ResultsPath': r'C:\private\results\\',
            'ResultsPostUrl': 'https://hub.test/private-token',
            'SpectatorPassword': 'private-spectator',
        })

        confirmed_hash = validate_runtime_bundle(bundle, EXPECTED_HASH, private_config)

        self.assertEqual(EXPECTED_HASH, confirmed_hash)

    def test_functional_difference_is_rejected(self):
        bundle = self._bundle()
        private_config = copy.deepcopy(bundle['runtime_config'])
        private_config['Server']['TcpPort'] = 9700

        with self.assertRaisesRegex(RuntimeBundleError, 'diverge'):
            validate_runtime_bundle(bundle, EXPECTED_HASH, private_config)

    def test_announced_hash_mismatch_is_rejected(self):
        bundle = self._bundle()

        with self.assertRaisesRegex(RuntimeBundleError, 'empreinte'):
            validate_runtime_bundle(bundle, '0' * 64, bundle['runtime_config'])

    @staticmethod
    def _bundle():
        return {
            'schema_version': 2,
            'materialized_fields': MATERIALIZED_FIELDS,
            'runtime_config': {
                'Server': {
                    'AdminPassword': '',
                    'DriverPassword': '',
                    'EntryListPath': '',
                    'LaunchSessionId': None,
                    'ResultCorrelationId': '',
                    'ResultsPath': '',
                    'ResultsPostUrl': '',
                    'SpectatorPassword': '',
                    'ServerName': 'PitLane Épreuve',
                    'TcpPort': 9600,
                },
                'Event': {
                    'ShowOnlySelected': False,
                    'Grip': 0.0,
                },
                'Sessions': [],
            },
        }


if __name__ == '__main__':
    unittest.main()
