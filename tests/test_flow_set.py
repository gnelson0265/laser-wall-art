import unittest
import numpy as np
from laser_art.flow_set import cache_groups, remove_group, schedule_ornaments
from laser_art.reference_layers import disk_union
from laser_art.smooth import graph_paths, raster_smooth_centerlines
from laser_art.flow_structure import smooth_support, anchored_centers


class SmoothTests(unittest.TestCase):
    def test_smoothing_preserves_mirrored_branch_junctions(self):
        skeleton = np.zeros((30, 40), dtype=bool)
        skeleton[7, 5:35] = True
        skeleton[7:25, 19:21] = True
        result = raster_smooth_centerlines(skeleton, (120, 90), 8)
        np.testing.assert_array_equal(result, result[:, ::-1])
        self.assertTrue(result[27:34, 63:73].any())
        self.assertTrue(result[76:84, 63:73].any())

    def test_smoothed_structure_selects_only_original_centers(self):
        art = np.zeros((120, 120), dtype=bool)
        art[10:110, 40:80] = True
        centers = np.zeros_like(art)
        centers[15:105, 45:75] = True
        routes = [[[y, 11] for y in range(3, 21)]]
        selected = smooth_support(art, centers, routes, radius=3)
        self.assertFalse(np.any(selected & ~centers))
        np.testing.assert_array_equal(selected, selected[:, ::-1])
        self.assertTrue(selected.any())

    def test_weakly_attached_tip_remains_optional_without_widening(self):
        core = np.zeros((110, 140), dtype=bool)
        structure = np.zeros_like(core)
        core[55, 40] = True
        structure[55, 80] = True
        anchored = anchored_centers(core, structure, 24)
        self.assertFalse(anchored.any())
        self.assertFalse(np.any(anchored & ~structure))

    def test_closed_loop_is_traced_without_losing_edges(self):
        skeleton = np.zeros((30, 30), dtype=bool)
        skeleton[5, 5:25] = True
        skeleton[24, 5:25] = True
        skeleton[5:25, 5] = True
        skeleton[5:25, 24] = True
        paths = graph_paths(skeleton)
        self.assertTrue(any(path[0] == path[-1] for path in paths))
        visited = {tuple(point) for path in paths for point in path}
        self.assertEqual(visited, {tuple(point) for point in np.argwhere(skeleton)})


class FlowSetTests(unittest.TestCase):
    def test_cached_groups_reconstruct_master_and_preserve_overlap(self):
        centers = np.zeros((80, 80), dtype=bool)
        owners = np.zeros((80, 80), dtype=np.uint16)
        centers[40, 10:70] = True
        owners[40, 10:40] = 1
        owners[40, 40:70] = 3
        cache, coverage = cache_groups(centers, owners, 5)
        np.testing.assert_array_equal(coverage > 0, disk_union(centers, 5))
        remove_group(coverage, cache[3])
        np.testing.assert_array_equal(coverage > 0, disk_union(centers & (owners == 1), 5))
        with self.assertRaises(ValueError):
            remove_group(coverage, cache[3])

    def test_balanced_schedule_removes_whole_groups_once(self):
        coverage = np.ones((10, 30), dtype=np.uint16)
        cache, metadata = {}, {}
        # Nine equal features, each with two uniquely covered pixels.
        coverage[:] = 0
        for i in range(3, 12):
            x = (i-3)*3
            mask = np.ones((2, 1), dtype=bool)
            cache[i] = ((x, 0, x+1, 2), mask)
            coverage[0:2, x:x+1] = 1
            metadata[i] = {'priority': i}
        stages = schedule_ornaments(coverage, cache, metadata, 18, 3)
        self.assertEqual([len(stage) for stage in stages], [3, 3, 3])
        self.assertEqual(sorted(i for stage in stages for i in stage), list(range(3, 12)))
        self.assertFalse(coverage.any())

    def test_too_many_stages_rejected_before_removal(self):
        coverage = np.ones((2, 2), dtype=np.uint16)
        before = coverage.copy()
        with self.assertRaises(ValueError):
            schedule_ornaments(coverage, {}, {}, 4, 3)
        np.testing.assert_array_equal(coverage, before)


if __name__ == '__main__':
    unittest.main()
