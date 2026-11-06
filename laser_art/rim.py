"""Author interior curves with clear separation from the permanent rim."""
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree


def smootherstep(t):
    t=np.clip(t,0.,1.)
    return t*t*t*(10+t*(-15+6*t))


def inward_normals(outline):
    outline=np.asarray(outline,float)
    tangent=np.gradient(outline,axis=0)
    normal=np.column_stack((tangent[:,1],-tangent[:,0]))
    xy=outline[:,::-1]
    area=np.sum(xy[:-1,0]*xy[1:,1]-xy[1:,0]*xy[:-1,1])
    if area<0:normal=-normal
    return normal/np.maximum(np.linalg.norm(normal,axis=1)[:,None],1e-9)


def rim_clearance(curve,radii,outline,scale,root_ends=(),gap=24.,core_radius=27.):
    """Move only new-master interior centerlines; keep authored roots fixed.

    The displacement has zero first and second derivatives at attachments.
    This is never used to modify a surviving curve while simplifying layers.
    """
    curve=np.asarray(curve,float)
    outline=np.asarray(outline,float)
    normals=inward_normals(outline)
    _,index=cKDTree(outline).query(curve)
    normal=normals[index]
    signed=np.sum((curve-outline[index])*normal,axis=1)
    required=(np.asarray(radii)+core_radius+gap)/scale
    correction=np.maximum(0,required-signed)
    arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]*scale
    weight=np.ones(len(curve))
    if 0 in root_ends:weight*=smootherstep(arc/180.)
    if -1 in root_ends:weight*=smootherstep((arc[-1]-arc)/180.)
    mean_step=max(arc[-1]/max(1,len(curve)-1),.1)
    correction=ndi.gaussian_filter1d(correction,sigma=max(1,15./mean_step))
    return curve+normal*(correction*weight)[:,None]


def audit_lateral_rim(art,core,components,settings):
    """Detect near-rim colour slivers away from intentional fan attachments."""
    from PIL import Image,ImageDraw
    silhouette=ndi.binary_fill_holes(core)
    band=silhouette&~core&(ndi.distance_transform_edt(~core)<=8)
    outline=np.asarray(components[0]['strokes'][0]['points_xy'])
    tree=cKDTree(outline)
    allowed=Image.new('1',(settings.width,settings.height));draw=ImageDraw.Draw(allowed)
    for component in components[1:]:
        for stroke in component['strokes']:
            points=np.asarray(stroke['points_xy'])
            for point in (points[0],points[-1]):
                distance,_=tree.query(point)
                if distance<80:
                    for x,y in (point,(settings.width-1-point[0],point[1])):
                        draw.ellipse((x-180,y-180,x+180,y+180),fill=1)
    main=next(c for c in components if c['role']=='main_veins')
    ymax=min(s['points_xy'][-1][1] for s in main['strokes'])-180
    band[int(ymax):]=False
    band[:,int(settings.width*.42):int(settings.width*.58)]=False
    unplanned=art&band&~np.asarray(allowed,dtype=bool)
    count=int(unplanned.sum())
    return {'scope':'Lateral fan rim; excludes deliberate attachment windows, central notch and stem',
            'tested_inner_band_pixels':8,'attachment_window_radius_pixels':180,
            'fan_cutoff_y':float(ymax),'unplanned_lateral_rim_pixels':count,'passed':count==0}


def extend_to_outline(points,outline):
    """Continue the existing vein's tangent to the rim instead of snapping sideways."""
    points=np.asarray(points,float);outline=np.asarray(outline,float)
    tangent=points[min(16,len(points)-1)]-points[0]
    tangent/=max(np.linalg.norm(tangent),1e-9)
    direction=-tangent
    segments=outline[1:]-outline[:-1]
    delta=outline[:-1]-points[0]
    def cross(a,b):return a[...,0]*b[...,1]-a[...,1]*b[...,0]
    denominator=cross(direction,segments)
    valid=np.abs(denominator)>1e-9
    t=np.full(len(segments),np.inf);u=np.full(len(segments),np.inf)
    t[valid]=cross(delta[valid],segments[valid])/denominator[valid]
    u[valid]=cross(delta[valid],direction)/denominator[valid]
    eligible=valid&(t>=0)&(u>=0)&(u<=1)
    if eligible.any():
        t[~eligible]=np.inf
        anchor=points[0]+direction*t[np.argmin(t)]
    else:
        _,index=cKDTree(outline).query(points[0]);anchor=outline[index]
    return np.vstack((anchor,points)),tangent
