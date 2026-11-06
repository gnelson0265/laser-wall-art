import unittest
import numpy as np
from scipy import ndimage as ndi
from laser_art.curve_master import raster_strokes,clean_clipped_body
from laser_art.model import Manufacturing
from laser_art.pointed import pointed_parts
from laser_art.reference_layers import disk_union
from laser_art.rim import rim_clearance,extend_to_outline,inward_normals


class PointedTests(unittest.TestCase):
    def stroke(self):
        x=np.linspace(55,255,400)
        return {'points_xy':np.column_stack((x,np.full(len(x),80.))).tolist(),
                'radii':np.linspace(38,20,len(x)).tolist(),'pointed_ends':[-1]}

    def test_terminal_taper_reaches_zero_and_keeps_body_at_minimum(self):
        body,tails=pointed_parts(self.stroke(),20)
        self.assertGreaterEqual(min(body['radii']),20)
        self.assertEqual(tails[0]['radii'][-1],0)
        self.assertEqual(tails[0]['points_xy'][-1],[255.,80.])
        self.assertLessEqual(tails[0]['terminal_length_limit_pixels'],240)

    def test_apex_has_no_round_cap_and_body_remains_strict(self):
        settings=Manufacturing(width=320,height=170,radius=20)
        full_box,full_mask=raster_strokes([self.stroke()],settings)
        body_box,body_mask=raster_strokes([self.stroke()],settings,structural_only=True)
        full=np.zeros((170,320),bool);body=np.zeros_like(full)
        x0,y0,x1,y1=full_box;full[y0:y1,x0:x1]=full_mask
        x0,y0,x1,y1=body_box;body[y0:y1,x0:x1]=body_mask
        self.assertFalse(np.any(body&~full))
        self.assertTrue(np.any(full&~body))
        self.assertEqual(int(full[:,255].sum()),1)
        self.assertFalse(full[:,256:].any())
        self.assertEqual(ndi.label(full)[1],1)
        np.testing.assert_array_equal(body,disk_union(ndi.distance_transform_edt(body)>20,20))

    def test_component_cleanup_preserves_disk_width_and_removes_fringe(self):
        seeds=np.zeros((110,150),bool)
        seeds[55,35:115]=True
        body=disk_union(seeds,20)
        body[55,14]=True
        cleaned=clean_clipped_body(body,20)
        self.assertFalse(np.any(cleaned&~body))
        self.assertFalse(cleaned[55,14])
        np.testing.assert_array_equal(cleaned,disk_union(ndi.distance_transform_edt(cleaned)>20,20))

    def test_vein_extends_to_rim_along_its_existing_tangent(self):
        outline=np.array([[0,0],[0,100],[100,100],[100,0],[0,0]],float)
        x=np.linspace(50,90,40)
        points=np.column_stack((np.full(40,50.),x))
        extended,tangent=extend_to_outline(points,outline)
        np.testing.assert_allclose(extended[0],[50,0])
        np.testing.assert_allclose(extended[1:],points)
        np.testing.assert_allclose(tangent,[0,1])

    def test_no_point_exception_at_load_bearing_root(self):
        stroke=self.stroke();stroke['root_junctions']=[{'end':-1}]
        with self.assertRaises(ValueError):pointed_parts(stroke,20)

    def test_rim_clearance_leaves_gap_and_preserves_anchor(self):
        theta=np.linspace(0,2*np.pi,1000)
        outline=np.column_stack((100+80*np.sin(theta),100+80*np.cos(theta)))
        t=np.linspace(.2,.7,200)
        curve=np.column_stack((100+76*np.sin(t),100+76*np.cos(t)))
        moved=rim_clearance(curve,np.full(200,20.),outline,scale=5.)
        radial=np.linalg.norm(moved-(100,100),axis=1)
        self.assertLess(radial.max(),67.)
        anchored=rim_clearance(curve,np.full(200,20.),outline,scale=5.,root_ends=(0,))
        np.testing.assert_allclose(anchored[0],curve[0])


if __name__=='__main__':unittest.main()


class LateralRimAuditTests(unittest.TestCase):
    def fixture(self):
        from laser_art.rim import audit_lateral_rim
        settings=Manufacturing(width=1600,height=1800)
        core=np.zeros((1800,1600),bool)
        core[150:1650,150:200]=True;core[150:1650,1400:1450]=True
        core[150:200,150:1450]=True;core[1600:1650,150:1450]=True
        outline=[]
        for a,b in (((175,175),(1425,175)),((1425,175),(1425,1625)),
                    ((1425,1625),(175,1625)),((175,1625),(175,175))):
            outline.extend(np.linspace(a,b,300).tolist())
        components=[{'role':'outline','strokes':[{'points_xy':outline}]},
                    {'role':'main_veins','strokes':[{'points_xy':[[800,700],[800,1300]]}]}]
        return audit_lateral_rim,settings,core,components

    def test_clear_rim_passes(self):
        audit,settings,core,components=self.fixture()
        self.assertTrue(audit(core.copy(),core,components,settings)['passed'])

    def test_unplanned_parallel_strip_is_rejected(self):
        audit,settings,core,components=self.fixture()
        art=core.copy();art[900:1000,201:204]=True
        result=audit(art,core,components,settings)
        self.assertFalse(result['passed'])
        self.assertGreater(result['unplanned_lateral_rim_pixels'],0)
