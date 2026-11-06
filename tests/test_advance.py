import unittest
from laser_art.advance import removal_plan


class AdvanceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'groups': [
            {'id': 1, 'master_disk_centers': 900},
            {'id': 2, 'master_disk_centers': 1000},
            {'id': 3, 'master_disk_centers': 700},
            {'id': 4, 'master_disk_centers': 30}]}

    def test_advance_keeps_all_previous_removals(self):
        old, new, cumulative = removal_plan(
            self.manifest, {'removed_terminal_scroll_pairs': [1]})
        self.assertEqual(old, [1])
        self.assertEqual(new, [2, 3])
        self.assertEqual(cumulative, [1, 2, 3])

    def test_selected_groups_use_cumulative_state(self):
        old, new, cumulative = removal_plan(
            self.manifest, {'cumulative_removed_terminal_scroll_pairs': [1]}, [3])
        self.assertEqual(new, [3])
        self.assertEqual(cumulative, [1, 3])

    def test_removed_unknown_or_tiny_groups_are_rejected(self):
        state = {'removed_terminal_scroll_pairs': [1]}
        for requested in ([1], [4], [999], []):
            with self.assertRaises(ValueError):
                removal_plan(self.manifest, state, requested)

    def test_exhausted_groups_do_not_create_duplicate_layer(self):
        with self.assertRaises(ValueError):
            removal_plan(self.manifest, {'cumulative_removed_terminal_scroll_pairs': [1, 2, 3]})

    def test_foreign_previous_state_is_rejected(self):
        with self.assertRaises(ValueError):
            removal_plan(self.manifest, {'removed_terminal_scroll_pairs': [999]})


if __name__ == '__main__':
    unittest.main()
