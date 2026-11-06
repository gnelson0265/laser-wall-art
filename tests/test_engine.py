import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image
from laser_art.model import Component, Manufacturing, Master, load_master
from laser_art.engine import generate, validate, raster_component, stamp, read_black
from laser_art.subjects import create_master


class ModelTests(unittest.TestCase):
    def test_all_layer_counts_remove_each_component_once_and_parent_last(self):
        master=create_master('gingko leaf')
        for n in (2,3,5,9,len(master.components)+1):
            stages=master.removal_stages(n)
            self.assertEqual(len(stages),n-1)
            self.assertTrue(all(stages))
            ids=[c.id for stage in stages for c in stage]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual(set(ids),{c.id for c in master.components})
            positions={c:i for i,stage in enumerate(stages) for c in [x.id for x in stage]}
            for c in master.components:
                if c.parent:
                    self.assertLessEqual(positions[c.id],positions[c.parent])

    def test_invalid_counts_and_unknown_subject(self):
        master=create_master('ginkgo')
        for n in (0,1,len(master.components)+2):
            with self.assertRaises(ValueError): master.removal_stages(n)
        with self.assertRaises(ValueError): create_master('a castle')

    def test_parent_cannot_be_removed_before_child(self):
        master=create_master('ginkgo')
        master.components[0].priority=0
        with self.assertRaises(ValueError): master.removal_stages(5)


class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.out=Path(cls.temp.name)/'design'
        cls.settings=Manufacturing(width=240,boundary=(5,150,234,7049),boundary_width=5)
        cls.master=Master('fixture',Component('core',999,[[
            (119,1000),(60,1000),(60,1500),(119,1500)]]),[
                Component('detail',10,[[(60,1150),(119,1150)]]),
                Component('structure',20,[[(60,1350),(119,1350)]])],cls.settings)
        cls.report=generate(cls.master,3,cls.out)
        cls.paths=sorted(cls.out.glob('layer_*.png'))
        coverage=np.zeros((7200,240),dtype=np.int16)
        box,mask=raster_component(cls.master.core,cls.settings)
        stamp(coverage,box,mask,True)
        cls.core=coverage>0

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_real_exports_pass_every_mandatory_check(self):
        self.assertTrue(self.report['passed'])
        for r in self.report['layers']:
            self.assertEqual(r['containment_violations'],0)
            self.assertEqual(r['minimum_width_uncovered_pixels'],0)
            self.assertEqual(r['connected_backbones_after_19px_erosion'],1)
        self.assertTrue(self.report['layers'][-1]['top_is_core_only'])
        self.assertEqual(self.report['scaling_boundary_external_height_inches'],11.5)

    def test_export_corruption_is_rejected(self):
        original=self.paths[-1].read_bytes()
        try:
            with Image.open(self.paths[-1]) as image:
                image=image.convert('L')
            image.putpixel((30,800),0)
            image.save(self.paths[-1],dpi=(600,600))
            report=validate(self.paths,self.core,self.settings,self.master.removal_stages(3))
            self.assertFalse(report['passed'])
            top=report['layers'][-1]
            self.assertEqual(top['containment_violations'],1)
            self.assertEqual(top['artwork_connected_components'],2)
            self.assertGreater(top['minimum_width_uncovered_pixels'],0)
            self.assertGreater(top['symmetry_mismatched_pixels'],0)
        finally:
            self.paths[-1].write_bytes(original)

    def test_saved_master_roundtrip_preserves_geometry(self):
        restored=load_master(self.out/'master.json')
        before=raster_component(self.master.core,self.settings)
        after=raster_component(restored.core,restored.settings)
        self.assertEqual(before[0],after[0])
        np.testing.assert_array_equal(before[1],after[1])

    def test_existing_output_is_preserved(self):
        before=(self.out/'master.json').read_bytes()
        with self.assertRaises(ValueError): generate(self.master,3,self.out)
        self.assertEqual((self.out/'master.json').read_bytes(),before)

if __name__=='__main__': unittest.main()
