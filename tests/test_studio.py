from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import json
from PIL import Image

from laser_art.studio import validate_options, normalize_reference, prepare, export
from laser_art.model import Manufacturing


class StudioTests(unittest.TestCase):
    def test_options_reject_unsupported_subjects_invalid_counts_and_tip_values(self):
        for args in [('owl',5,True),('ginkgo',1,True),('ginkgo',13,True),('ginkgo',True,True),('ginkgo',5,'yes')]:
            with self.assertRaises(ValueError):validate_options(*args)
        validate_options('A gingko leaf',5,True)

    def test_normalization_white_background_even_width_and_small_image_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.png';target=Path(directory)/'normalized.png'
            Image.new('RGBA',(151,180),(0,0,0,0)).save(source)
            normalize_reference(source,target)
            with Image.open(target) as image:
                self.assertEqual(image.mode,'RGB');self.assertEqual(image.width%2,0)
                self.assertEqual(image.getpixel((0,0)),(255,255,255))
            Image.new('RGB',(20,20),'white').save(source)
            with self.assertRaises(ValueError):normalize_reference(source,target)

    def test_approved_master_is_frozen_and_exported_exactly(self):
        settings=Manufacturing(width=240,boundary=(5,150,234,7049),boundary_width=5)
        def component(id,role,points):
            return {'id':id,'role':role,'priority':id,'strokes':[{'points_xy':points,'radii':[24.]*len(points)}]}
        components=[component(1,'outline',[[70,1000],[169,1000],[169,1500],[70,1500],[70,1000]]),
                    component(2,'main_veins',[[70,1250],[119,1250]]),
                    component(3,'whole_scroll_pair',[[70,1150],[119,1150]]),
                    component(4,'whole_scroll_pair',[[70,1350],[119,1350]])]
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.png';Image.new('RGB',(240,300),'white').save(source)
            workspace=Path(directory)/'session'
            with patch('laser_art.studio.curve_components',return_value=(settings,components,{})):
                preview=prepare(source,'Ginkgo leaf',3,False,workspace)
            self.assertTrue(Path(preview['preview_path']).exists())
            reviewed=(workspace/'reviewed_master.png').read_bytes()
            result=export(workspace)
            self.assertTrue(result['report']['passed'])
            self.assertTrue(result['report']['reviewed_master_unchanged'])
            self.assertEqual(len(result['palette']),3)
            self.assertEqual((workspace/'export'/'layer_01_bottom.png').read_bytes(),reviewed)
            self.assertEqual(len([f for f in result['files'] if f['kind']=='layer']),3)
            self.assertEqual(len([f for f in result['files'] if f['kind']=='bundle']),1)
