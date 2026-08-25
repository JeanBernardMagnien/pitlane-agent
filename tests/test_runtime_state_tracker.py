import unittest

from services.runtime_state_tracker import RuntimeStateTracker, semantic_state_signature


class RuntimeStateTrackerTest(unittest.TestCase):
    def state(self, **overrides):
        instance = {
            'id': 'race-1',
            'status': 'running',
            'pid': 123,
            'connected_drivers': 17,
            'drivers_seen_at': '2026-08-25T12:00:00Z',
            'session_phase': 'practice',
        }
        instance.update(overrides)

        return {
            'agent': {'version': '0.5.0', 'health': 'healthy', 'health_reasons': []},
            'instances': [instance],
        }

    def test_stable_observations_keep_the_same_revision(self):
        tracker = RuntimeStateTracker('11111111-1111-4111-8111-111111111111')

        first = tracker.observe(self.state())
        for second in range(1, 60):
            tracker.observe(self.state(drivers_seen_at=f'2026-08-25T12:00:{second:02d}Z'))

        self.assertEqual(1, first['runtime_revision'])
        self.assertEqual(1, tracker.current()['runtime_revision'])
        self.assertEqual(
            '2026-08-25T12:00:59Z',
            tracker.current()['payload']['instances'][0]['drivers_seen_at'],
        )

    def test_players_phase_process_and_health_changes_increment_once_each(self):
        tracker = RuntimeStateTracker()

        self.assertEqual(1, tracker.observe(self.state())['runtime_revision'])
        self.assertEqual(2, tracker.observe(self.state(connected_drivers=18))['runtime_revision'])
        self.assertEqual(3, tracker.observe(self.state(connected_drivers=18, session_phase='qualifying'))['runtime_revision'])
        self.assertEqual(4, tracker.observe(self.state(connected_drivers=18, session_phase='qualifying', status='stopped', pid=None))['runtime_revision'])

        degraded = self.state(connected_drivers=18, session_phase='qualifying', status='stopped', pid=None)
        degraded['agent'] = {
            'version': '0.5.0',
            'health': 'degraded',
            'health_reasons': ['result_spool_near_limit'],
        }
        self.assertEqual(5, tracker.observe(degraded)['runtime_revision'])

    def test_instance_order_does_not_change_the_signature(self):
        first = self.state()
        second = self.state()
        second['instances'] = [
            {'id': 'race-2', 'status': 'stopped'},
            second['instances'][0],
        ]
        first['instances'].insert(0, {'id': 'race-2', 'status': 'stopped'})

        self.assertEqual(semantic_state_signature(first), semantic_state_signature(second))


if __name__ == '__main__':
    unittest.main()
