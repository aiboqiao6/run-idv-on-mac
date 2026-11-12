import unittest
from input_state import InputState


class InputStateTests(unittest.TestCase):
    def test_release_and_focus_loss(self):
        s = InputState()
        self.assertEqual(s.update({'seq': 1, 'active': True, 'keys': [87, 68]}), [(4, 68), (4, 87)])
        self.assertEqual(s.update({'seq': 2, 'active': True, 'keys': [87]}), [(5, 68)])
        self.assertEqual(s.update({'seq': 3, 'active': False, 'keys': [87]}), [(5, 87)])

    def test_modifier_precedes_normal_key_and_releases_last(self):
        s = InputState()
        self.assertEqual(s.update({'seq': 1, 'active': True, 'keys': [49, 17]}), [(4, 17), (4, 49)])
        self.assertEqual(s.update({'seq': 2, 'active': True, 'keys': []}), [(5, 49), (5, 17)])

    def test_invalid_snapshot_is_atomic(self):
        s = InputState()
        s.update({'seq': 1, 'active': True, 'keys': [87]})
        with self.assertRaises(ValueError):
            s.update({'seq': 2, 'active': True, 'keys': [999]})
        self.assertEqual(s.keys, {87})

    def test_out_of_order_snapshot_is_ignored(self):
        s = InputState()
        s.update({'seq': 2, 'active': True, 'keys': [87]})
        self.assertEqual(s.update({'seq': 1, 'active': True, 'keys': []}), [])
        self.assertEqual(s.keys, {87})

    def test_watchdog_release(self):
        s = InputState()
        s.update({'seq': 1, 'active': True, 'keys': [87, 16]})
        self.assertEqual(s.release(), [(5, 87), (5, 16)])
        self.assertEqual(s.release(), [])

    def test_held_space_does_not_repeat_after_scene_or_watchdog_release(self):
        s = InputState()
        self.assertEqual(s.update(dict(seq=1, active=True, keys=[32])), [(4, 32)])
        self.assertEqual(s.release(suppress_held=True), [(5, 32)])
        self.assertEqual(s.update(dict(seq=2, active=True, keys=[32])), [])
        self.assertEqual(s.update(dict(seq=3, active=True, keys=[])), [])
        self.assertEqual(s.update(dict(seq=4, active=True, keys=[32])), [(4, 32)])

    def test_space_held_through_focus_loss_requires_a_physical_release(self):
        s = InputState()
        s.update(dict(seq=1, active=True, keys=[32]))
        self.assertEqual(s.update(dict(seq=2, active=False, keys=[])), [(5, 32)])
        s.update(dict(seq=3, active=False, keys=[]))
        self.assertEqual(s.update(dict(seq=4, active=True, keys=[32])), [])
        s.update(dict(seq=5, active=True, keys=[]))
        self.assertEqual(s.update(dict(seq=6, active=True, keys=[32])), [(4, 32)])


if __name__ == '__main__':
    unittest.main()
