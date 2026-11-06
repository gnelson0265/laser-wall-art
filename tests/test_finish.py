import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from laser_art.finish import green_stack, rgb_color, structural_guide


class FinishTests(unittest.TestCase):
    def test_green_stack_uses_highest_visible_layer_color(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = []
            for i, inset in enumerate((3, 5, 7, 9, 11)):
                a = np.full((31, 31), 255, dtype=np.uint8)
                a[inset:31-inset, inset:31-inset] = 0
                path = output / f'layer_{i}.png'
                Image.fromarray(a).save(path)
                paths.append(path)
            border = np.zeros((31, 31), dtype=bool)
            # This registration pixel must stay white in the assembled artwork.
            border[3, 3] = True
            report = green_stack(paths, border, output)
            with Image.open(output / 'stacked_green.png') as image:
                result = np.asarray(image)
            self.assertEqual(tuple(result[3, 4]), rgb_color('#123d24'))
            self.assertEqual(tuple(result[5, 6]), rgb_color('#216b3a'))
            self.assertEqual(tuple(result[15, 15]), rgb_color('#a7dca0'))
            self.assertEqual(tuple(result[3, 3]), (255, 255, 255))
            self.assertTrue(report['all_five_shades_visible'])
            self.assertTrue(all(n > 0 for n in report['visible_pixels_per_layer']))

    def test_green_stack_supports_other_layer_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = []
            for i, inset in enumerate((2, 5, 8)):
                pixels = np.full((25, 25), 255, dtype=np.uint8)
                pixels[inset:25-inset, inset:25-inset] = 0
                path = output / f'layer_{i}.png'
                Image.fromarray(pixels).save(path)
                paths.append(path)
            report = green_stack(paths, np.zeros((25, 25), bool), output)
            self.assertEqual(len(report['colors_bottom_to_top']), 3)
            self.assertEqual(len(report['visible_pixels_per_layer']), 3)

    def test_structural_route_selection_is_symmetric_and_uses_existing_guide(self):
        art = np.zeros((200, 200), dtype=bool)
        art[15:185, 15:185] = True
        art[30:170, 30:170] = False
        art[20:190, 94:106] = True
        selected, routes = structural_guide(art, factor=2)
        np.testing.assert_array_equal(selected, selected[:, ::-1])
        self.assertEqual(len(routes), 6)
        self.assertTrue(all(route for route in routes))
        # Route guides select centers only; no artwork is rendered by this step.
        self.assertEqual(selected.dtype, np.bool_)


if __name__ == '__main__':
    unittest.main()
