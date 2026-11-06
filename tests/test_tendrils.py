import unittest
import numpy as np
from scipy.spatial import cKDTree

from laser_art.tendrils import taper_radii, tangent_root, parent_following_root


class TendrilTests(unittest.TestCase):
    def test_taper_is_continuous_monotonic_and_stops_at_cutting_floor(self):
        radii=taper_radii(48,20,500,20)
        self.assertEqual(radii[0],48)
        self.assertEqual(radii[-1],20)
        self.assertTrue(np.all(np.diff(radii)<=0))
        self.assertGreater(radii[100],radii[300])
        self.assertGreaterEqual(radii.min(),20)
        self.assertLess(abs(radii[1]-radii[0]),.001)
        with self.assertRaises(ValueError):taper_radii(48,10,100,20)

    def test_tangent_transition_keeps_far_curve_and_root_position(self):
        t=np.linspace(0,1,300)
        curve=np.column_stack((40*t,60*t*t))
        result=tangent_root(curve,np.array([1.,0.]))
        np.testing.assert_allclose(result[0],curve[0])
        np.testing.assert_allclose(result[-1],curve[-1])
        tangent=result[1]-result[0]
        cosine=abs(tangent[0])/np.linalg.norm(tangent)
        self.assertGreater(cosine,.999)

    def test_root_follows_curved_parent_before_one_sided_departure(self):
        x=np.linspace(0,120,600)
        parent=np.column_stack((x,.004*x*x))
        start=parent[250]
        t=np.linspace(0,1,500)
        child=np.column_stack((start[0]+50*t,start[1]+10*t+70*t*t))
        result=parent_following_root(child,parent,np.full(len(parent),40.))
        tree=cKDTree(parent)
        gap,index=tree.query(result[0])
        self.assertLess(gap,.2)
        parent_tangent=np.gradient(parent,axis=0)[index]
        first=result[1]-result[0]
        cosine=abs(first@parent_tangent)/(np.linalg.norm(first)*np.linalg.norm(parent_tangent))
        self.assertGreater(cosine,.999)
        # The root transition stays on its intended departure side instead of
        # briefly emerging on the opposite side as an unwanted shoulder.
        prefix=result[:140]
        _,indices=tree.query(prefix)
        delta=prefix-parent[indices]
        tangent=np.gradient(parent,axis=0)[indices]
        normal=np.column_stack((-tangent[:,1],tangent[:,0]))
        signed=np.sum(delta*normal,axis=1)/np.linalg.norm(normal,axis=1)
        self.assertGreater(signed.min(),-.03)
        np.testing.assert_allclose(result[-1],child[-1])

    def test_end_attachment_preserves_other_endpoint(self):
        parent=np.column_stack((np.linspace(0,100,300),np.zeros(300)))
        t=np.linspace(0,1,300)
        curve=np.column_stack((80-30*t,40*(1-t)**2))
        result=parent_following_root(curve,parent,np.full(300,40.),at_end=True)
        np.testing.assert_allclose(result[0],curve[0])
        self.assertAlmostEqual(result[-1,1],0.,places=8)


if __name__=='__main__':unittest.main()
