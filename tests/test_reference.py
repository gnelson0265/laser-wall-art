import tempfile
from pathlib import Path
import unittest

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from laser_art.reference import artwork_from_reference, thin, prepare_reference


class ReferenceTests(unittest.TestCase):
    def test_separate_frame_is_removed_and_left_half_mirrored(self):
        image = Image.new('L', (120, 160), 255)
        draw = ImageDraw.Draw(image)
        draw.rectangle((1, 1, 118, 158), outline=0, width=2)
        draw.rectangle((25, 30, 85, 135), fill=0)
        art, box = artwork_from_reference(image)
        self.assertEqual(box, [25, 30, 95, 136])
        np.testing.assert_array_equal(art, art[:, ::-1])
        self.assertTrue(art.all())

    def test_thinning_preserves_loop_and_connectivity(self):
        mask = np.zeros((90, 90), dtype=bool)
        mask[10:80, 10:80] = True
        mask[25:65, 25:65] = False
        skeleton = thin(mask)
        self.assertLess(skeleton.sum(), mask.sum())
        self.assertEqual(ndi.label(skeleton, np.ones((3, 3)))[1], 1)
        self.assertGreater(ndi.binary_fill_holes(skeleton).sum(), skeleton.sum())

    def test_thinning_preserves_branch_tips(self):
        mask = np.zeros((80, 80), dtype=bool)
        mask[10:20, 10:70] = True
        mask[10:70, 35:45] = True
        skeleton = thin(mask)
        self.assertEqual(ndi.label(skeleton, np.ones((3, 3)))[1], 1)
        self.assertTrue(skeleton[10:20, 10:25].any())
        self.assertTrue(skeleton[50:70, 35:45].any())

    def test_existing_proof_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sentinel = output / 'existing.png'
            sentinel.write_bytes(b'preserve')
            with self.assertRaises(ValueError):
                prepare_reference('missing-source.png', output)
            self.assertEqual(sentinel.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
