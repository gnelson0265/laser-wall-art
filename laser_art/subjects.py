"""Subject renderers create a master once; the layer engine is subject-independent.

Add a renderer to RENDERERS to support another subject. Each child feature must
attach to its parent and have a strictly earlier removal priority.
"""
import math
from .model import Component, Master, bezier

RENDERERS = {}

def register(*names):
    def decorator(fn):
        for name in names:
            RENDERERS[name] = fn
        return fn
    return decorator

@register("ginkgo", "gingko", "ginkgo leaf", "gingko leaf", "a ginkgo leaf", "a gingko leaf")
def ginkgo(subject):
    # One half of a fan-shaped, scalloped, notched leaf and its petiole.
    segments = [
        ((3199, 6460),(3140, 6460),(3095, 6450),(3090, 6380)),
        ((3090,6380),(3085,6080),(3100,5810),(2980,5600)),
        ((2980,5600),(2320,5400),(1040,4130),(650,2480)),
        ((650,2480),(570,2210),(600,2010),(800,1930)),
        ((800,1930),(750,1650),(930,1450),(1180,1500)),
        ((1180,1500),(1190,1210),(1470,1100),(1700,1210)),
        ((1700,1210),(1840,940),(2110,940),(2320,1090)),
        ((2320,1090),(2520,880),(2760,1060),(2890,1280)),
        ((2890,1280),(3040,1490),(3090,1700),(3199,1830)),
    ]
    left = []
    for seg in segments:
        left.extend(bezier(*seg))
    core = Component("outline", 9999, [left], mirror=True)
    components = [Component("spine", 1000, [[(3199,6460),(3199,5450)]])]
    # Veins radiate from the petiole into the fan; ornaments inherit vein anchors.
    tips = [(675,2470),(805,1935),(1185,1505),(1705,1215),(2325,1095),(2890,1290)]
    base = (3199,5500)
    for i, tip in enumerate(tips):
        vein = bezier(base, (2600-i*32,4300), (tip[0]+200,tip[1]+900),tip,220)
        vid = f"vein_{i:02d}"
        components.append(Component(vid, 800+i, [vein], "spine"))
        for j, t in enumerate((0.32,0.48,0.64,0.79)):
            k = int(t*220)
            anchor = vein[k]
            dx,dy = vein[k+2][0]-vein[k-2][0],vein[k+2][1]-vein[k-2][1]
            angle = math.atan2(dy,dx)
            sign = 1 if j%2 else -1
            # A smooth expanding spiral starts exactly on its parent vein.
            size = 105 + (i%3)*15 + j*10
            pts=[]
            for q in range(181):
                u=q/180
                theta=angle+sign*u*math.pi*3.3
                r=size*u
                pts.append((anchor[0]+r*math.cos(theta),anchor[1]+r*math.sin(theta)))
            cid=f"scroll_{i:02d}_{j}"
            components.append(Component(cid, 300+j*12+i,[pts],vid))
            # Nested teardrop tendril, attached to the spiral at a shared point.
            a=pts[110]
            direction=angle+sign*0.8
            def local(x,y):
                return (a[0]+x*math.cos(direction)-y*math.sin(direction),
                        a[1]+x*math.sin(direction)+y*math.cos(direction))
            tear=bezier(a,local(200,-110),local(290,60),local(210,180))
            tear+=bezier(local(210,180),local(100,150),local(20,60),a)
            components.append(Component(f"teardrop_{i:02d}_{j}",100+j*12+i,[tear],cid))
    return Master(subject,core,components)


def create_master(subject):
    renderer=RENDERERS.get(subject.lower().strip())
    if not renderer:
        raise ValueError("No renderer for that subject yet. Available: ginkgo leaf. "
                         "Add a subject renderer in laser_art/subjects.py.")
    return renderer(subject)
