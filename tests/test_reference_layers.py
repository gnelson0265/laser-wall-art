import tempfile
import unittest
from pathlib import Path

import numpy as np
from laser_art.reference_layers import neighbors, terminal_paths, disk_union, create_second_layer


class ReferenceLayerTests(unittest.TestCase):
    def test_raster_corner_has_no_diagonal_shortcut(self):
        skeleton = np.zeros((8, 8), dtype=bool)
        skeleton[2, 2:5] = True
        skeleton[2:5, 4] = True
        self.assertEqual(neighbors(skeleton, (2, 3)), [(2, 2), (2, 4)])

    def test_terminal_trace_stops_at_actual_junction(self):
        skeleton = np.zeros((30, 40), dtype=bool)
        skeleton[10, 3:18] = True
        skeleton[5:20, 17] = True
        paths = terminal_paths(skeleton)
        left = next(p for p in paths if p[0] == (10, 3))
        self.assertEqual(left[-1], (10, 17))
        self.assertEqual(len(left), 15)

    def test_removing_a_whole_disk_group_preserves_subset_and_overlap(self):
        centers = np.zeros((100, 100), dtype=bool)
        centers[50, 20:80] = True
        centers[20:51, 50] = True
        original = disk_union(centers, 6)
        remaining = centers.copy()
        remaining[20:50, 50] = False
        upper = disk_union(remaining, 6)
        self.assertFalse(np.any(upper & ~original))
        self.assertTrue(np.any(original & ~upper))
        expected = np.zeros_like(centers)
        expected[50, 20:80] = True
        np.testing.assert_array_equal(upper, disk_union(expected, 6))

    def test_existing_output_and_invalid_fraction_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            sentinel = path / 'preserve.txt'
            sentinel.write_text('keep')
            with self.assertRaises(ValueError):
                create_second_layer('missing.png', path)
            with self.assertRaises(ValueError):
                create_second_layer('missing.png', path / 'new', 0)
            self.assertEqual(sentinel.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
