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


if __name__ == '__main__':
    unittest.main()
