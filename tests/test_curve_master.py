import unittest
import numpy as np
from scipy import ndimage as ndi

from laser_art.curve_master import fit_curve, boundary_loop, raster_strokes
from laser_art.flow_set import remove_group
from laser_art.model import Manufacturing
from laser_art.reference_layers import disk_union


class CurveMasterTests(unittest.TestCase):
    def test_curve_fit_holds_attachment_points_exactly(self):
        t = np.linspace(0,1,35)
        points = np.column_stack((20+90*t, 15+70*t*t))
        curve = fit_curve(points,smoothness=1.5)
        np.testing.assert_allclose(curve[0],points[0],atol=1e-9)
        np.testing.assert_allclose(curve[-1],points[-1],atol=1e-9)
        tangent = np.diff(curve,axis=0)
        angles = np.unwrap(np.arctan2(tangent[:,0],tangent[:,1]))
        self.assertLess(np.max(np.abs(np.diff(angles))),.1)

    def test_outline_traces_closed_notched_subject(self):
        solid = np.zeros((80,100),bool)
        solid[10:70,10:90] = True
        solid[10:35,45:55] = False
        loop = boundary_loop(solid)
        np.testing.assert_array_equal(loop[0],loop[-1])
        self.assertTrue(np.any((loop[:,0]>30)&(loop[:,0]<36)&(loop[:,1]>43)&(loop[:,1]<56)))

    def test_tapered_parent_survives_scroll_removal_bit_for_bit(self):
        settings = Manufacturing(width=300,height=260)
        x = np.linspace(60,240,200)
        parent = {'points_xy':np.column_stack((x,np.full(len(x),130))).tolist(),
                  'radii':np.linspace(40,24,len(x)).tolist()}
        t = np.linspace(0,1,200)
        scroll = {'points_xy':np.column_stack((140+60*t,130-65*np.sin(t))).tolist(),
                  'radii':np.full(len(t),24.).tolist()}
        parent_box,parent_mask = raster_strokes([parent],settings)
        scroll_box,scroll_mask = raster_strokes([scroll],settings)
        coverage = np.zeros((260,300),np.uint16)
        expected = np.zeros_like(coverage,dtype=bool)
        x0,y0,x1,y1 = parent_box
        coverage[y0:y1,x0:x1] += parent_mask
        expected[y0:y1,x0:x1] = parent_mask
        x0,y0,x1,y1 = scroll_box
        coverage[y0:y1,x0:x1] += scroll_mask
        self.assertTrue(np.any((coverage>0)&~expected))
        remove_group(coverage,(scroll_box,scroll_mask))
        np.testing.assert_array_equal(coverage>0,expected)
        # No clipping at junctions; the variable-width parent passes the same
        # fixed-disk minimum-width test as manufacturing layers.
        opened = disk_union(ndi.distance_transform_edt(expected)>24,24)
        np.testing.assert_array_equal(expected,opened)

    def test_strokes_below_material_floor_are_rejected(self):
        stroke = {'points_xy':[[30,30],[50,50]],'radii':[12,12]}
        with self.assertRaises(ValueError):
            raster_strokes([stroke],Manufacturing(width=100,height=100))


if __name__ == '__main__':
    unittest.main()
