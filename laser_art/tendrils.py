"""Tangent-rooted tendrils with continuous, network-aware taper profiles."""
import numpy as np
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from .reference_layers import neighbors
from .smooth import graph_paths


def taper_radii(start, end, count, minimum):
    if min(start,end) < minimum: raise ValueError('Taper falls below material minimum.')
    t = np.linspace(0.,1.,count)
    return start+(end-start)*(3*t*t-2*t*t*t)


def tangent_root(curve, tangent, at_end=False):
    """Replace only the root transition with a tangent-matched cubic segment."""
    curve = np.asarray(curve,float)
    if at_end: curve = curve[::-1].copy()
    arc = np.r_[0,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]
    if arc[-1] < 1: return curve[::-1] if at_end else curve
    cut = min(28.,arc[-1]*.30)
    k = max(2,min(len(curve)-2,int(np.searchsorted(arc,cut))))
    a,d = curve[0],curve[k]
    tangent = np.asarray(tangent,float)
    tangent /= max(np.linalg.norm(tangent),1e-9)
    if np.dot(tangent,d-a) < 0: tangent = -tangent
    end_tangent = curve[min(k+1,len(curve)-1)]-curve[k-1]
    end_tangent /= max(np.linalg.norm(end_tangent),1e-9)
    handle = np.linalg.norm(d-a)*.30
    b,c = a+tangent*handle,d-end_tangent*handle
    t = np.linspace(0,1,max(80,k))[:,None]
    bridge = (1-t)**3*a+3*(1-t)**2*t*b+3*(1-t)*t*t*c+t**3*d
    result = np.vstack((bridge[:-1],curve[k:]))
    return result[::-1] if at_end else result


def make_tendrils(component, support, parent_curves, parent_radii, scale, offset, minimum, pointed=False):
    from .curve_master import fit_curve, sample_stroke
    points = np.concatenate(parent_curves)
    radii = np.concatenate(parent_radii)
    tangents = np.concatenate([np.gradient(c,axis=0) for c in parent_curves])
    curve_ids = np.concatenate([np.full(len(c),i,int) for i,c in enumerate(parent_curves)])
    parent_tree = cKDTree(points)
    anchors = component & ndi.binary_dilation(support,np.ones((3,3)))
    degree = np.zeros(component.shape,np.uint8)
    for p in np.argwhere(component): degree[tuple(p)] = len(neighbors(component,tuple(p)))
    # Contract pixel-scale junction clusters so they cannot become independent
    # fat micro-strokes. Every incident curve shares one real attachment vertex.
    junction_area = component & ndi.binary_dilation((degree>=3)|anchors,iterations=2)
    cluster_labels,cluster_count = ndi.label(junction_area,np.ones((3,3)))
    vertices,root_info = {},{}
    def vertex(p):
        cluster = int(cluster_labels[tuple(p)])
        key = ('junction',cluster) if cluster else ('point',int(p[0]),int(p[1]))
        if key not in vertices:
            position = np.argwhere(cluster_labels==cluster).mean(axis=0) if cluster else np.asarray(p,float)
            root = bool(np.any(anchors & (cluster_labels==cluster))) if cluster else bool(anchors[tuple(p)])
            if root:
                _,i = parent_tree.query(position)
                position = points[i].copy()
                root_info[key] = {'parent_curve_id':int(curve_ids[i]),'parent_tangent':tangents[i].copy(),
                                  'parent_radius':float(radii[i]),
                                  'radius':float(max(minimum,min(50,radii[i]-4)))}
            vertices[key] = position
        return key
    edges = []
    paths = graph_paths(component,breakpoints={tuple(p) for p in np.argwhere(anchors)})
    for path in paths:
        if len(path)<3: continue
        a,b = vertex(path[0]),vertex(path[-1])
        if a==b: continue
        p = np.asarray(path,float)
        if cluster_labels[tuple(path[0])]:
            same = cluster_labels[p[:,0].astype(int),p[:,1].astype(int)] == cluster_labels[tuple(path[0])]
            first_outside = np.flatnonzero(~same)
            if len(first_outside): p = p[max(0,first_outside[0]-1):]
        if cluster_labels[tuple(path[-1])]:
            same = cluster_labels[p[:,0].astype(int),p[:,1].astype(int)] == cluster_labels[tuple(path[-1])]
            outside = np.flatnonzero(~same)
            if len(outside): p = p[:min(len(p),outside[-1]+2)]
        if len(p)<2: continue
        p[0],p[-1] = vertices[a],vertices[b]
        if np.linalg.norm(np.diff(p,axis=0),axis=1).sum()<5: continue
        curve = fit_curve(p,smoothness=1.)
        if a in root_info:
            ci=root_info[a]['parent_curve_id']
            if ci==0:
                from .rim import inward_normals
                _,oi=cKDTree(parent_curves[0]).query(curve[0])
                curve=tangent_root(curve,inward_normals(parent_curves[0])[oi])
            else:
                curve=parent_following_root(curve,parent_curves[ci],parent_radii[ci])
        if b in root_info:
            ci=root_info[b]['parent_curve_id']
            if ci==0:
                from .rim import inward_normals
                _,oi=cKDTree(parent_curves[0]).query(curve[-1])
                curve=tangent_root(curve,inward_normals(parent_curves[0])[oi],at_end=True)
            else:
                curve=parent_following_root(curve,parent_curves[ci],parent_radii[ci],at_end=True)
        for key,end in ((a,0),(b,-1)):
            if key in root_info:
                ci=root_info[key]['parent_curve_id']
                gap,index=cKDTree(parent_curves[ci]).query(curve[end])
                cap=float(parent_radii[ci][index]-4-gap*scale)
                root_info[key]['radius']=max(minimum,min(root_info[key]['radius'],cap))
        length = float(np.linalg.norm(np.diff(curve,axis=0),axis=1).sum())
        edges.append((a,b,curve,length))
    if not edges or not root_info: return []
    active = {key for a,b,_,_ in edges for key in (a,b)}
    ids = {key:i for i,key in enumerate(active)}
    rows,columns,weights = [],[],[]
    counts = {key:0 for key in active}
    for a,b,curve,length in edges:
        rows.extend((ids[a],ids[b]));columns.extend((ids[b],ids[a]));weights.extend((length,length))
        counts[a]+=1;counts[b]+=1
    graph = csr_matrix((weights,(rows,columns)),shape=(len(ids),len(ids)))
    root_keys = [key for key in active if key in root_info]
    if not root_keys: return []
    root_ids = [ids[key] for key in root_keys]
    distances = dijkstra(graph,indices=root_ids)
    nearest_root = np.argmin(distances,axis=0)
    nearest_distance = distances[nearest_root,np.arange(len(ids))]
    finite = nearest_distance[np.isfinite(nearest_distance)]
    if not len(finite): return []
    depth = max(float(finite.max()),1.)
    widths = {}
    for key,index in ids.items():
        if key in root_info: widths[key] = root_info[key]['radius']
        elif counts[key]==1: widths[key] = float(minimum)
        else:
            root = root_keys[int(nearest_root[index])]
            widths[key] = float(minimum+(root_info[root]['radius']-minimum)*np.exp(-nearest_distance[index]/depth))
    strokes = []
    for a,b,curve,length in edges:
        if not np.isfinite(nearest_distance[ids[a]]) or not np.isfinite(nearest_distance[ids[b]]): continue
        width = taper_radii(widths[a],widths[b],len(curve),minimum)
        from .rim import rim_clearance
        root_ends=tuple(end for key,end in ((a,0),(b,-1)) if key in root_info)
        curve=rim_clearance(curve,width,parent_curves[0],scale,root_ends=root_ends)
        stroke = sample_stroke(curve,width,scale,offset)
        stroke['pointed_ends']=[end for key,end in ((a,0),(b,-1)) if pointed and counts[key]==1 and key not in root_info]
        stroke['tip_exception_role']='Non-load-bearing terminal only' if stroke['pointed_ends'] else None
        stroke['taper_method'] = 'Continuous smoothstep radii on contracted tendril graph; free tips at material minimum'
        stroke['root_junctions'] = []
        for key,end in ((a,0),(b,-1)):
            if key in root_info:
                info=root_info[key]
                ci=info['parent_curve_id']
                gap,index=cKDTree(parent_curves[ci]).query(curve[end])
                actual_parent_radius=float(parent_radii[ci][index])
                actual_tangent=np.gradient(parent_curves[ci],axis=0)[index]
                stroke['root_junctions'].append({'end':end,'parent_radius':actual_parent_radius,
                    'root_radius':float(width[end]),'parent_tangent_yx':actual_tangent.tolist(),
                    'center_offset_pixels':float(gap*scale),
                    'root_inside_parent':bool(width[end]+gap*scale<=actual_parent_radius)})
        strokes.append(stroke)
    return strokes


def parent_following_root(curve, parent, parent_radii, at_end=False):
    """Author a C2 root in the parent's local frame before a one-sided peel."""
    from scipy.interpolate import CubicSpline, CubicHermiteSpline
    curve = np.asarray(curve,float)
    if at_end: curve = curve[::-1].copy()
    parent = np.asarray(parent,float)
    arc = np.r_[0,np.cumsum(np.linalg.norm(np.diff(parent,axis=0),axis=1))]
    keep = np.r_[True,np.diff(arc)>1e-8]
    parent,arc,profile = parent[keep],arc[keep],np.asarray(parent_radii)[keep]
    spline = CubicSpline(arc,parent,axis=0)
    tree = cKDTree(parent)
    _,root_i = tree.query(curve[0])
    curve_arc = np.r_[0,np.cumsum(np.linalg.norm(np.diff(curve,axis=0),axis=1))]
    k = max(2,min(len(curve)-2,int(np.searchsorted(curve_arc,min(32.,curve_arc[-1]*.35)))))
    q = curve[k]
    _,q_i = tree.query(q)
    u_root,u_q = arc[root_i],arc[q_i]
    direction = 1 if u_q>=u_root else -1
    u_start = float(np.clip(u_root-direction*18.,arc[0],arc[-1]))
    if abs(u_q-u_start)<1e-3:
        return tangent_root(curve,np.gradient(parent,axis=0)[root_i],at_end=False)[::-1] if at_end else tangent_root(curve,np.gradient(parent,axis=0)[root_i])
    p_q = spline(u_q)
    tangent_q = spline(u_q,1);tangent_q /= max(np.linalg.norm(tangent_q),1e-9)
    normal_q = np.array([-tangent_q[1],tangent_q[0]])
    displacement = float((q-p_q)@normal_q)
    residual = q-p_q-normal_q*displacement
    child_tangent = curve[min(k+1,len(curve)-1)]-curve[k-1]
    child_tangent /= max(np.linalg.norm(child_tangent),1e-9)
    length = max(curve_arc[k],abs(u_q-u_start))
    derivative = child_tangent*length
    second = spline(u_q,2)
    curvature = float(second@normal_q)
    denom = max(.25,1-curvature*displacement)
    du_end = float(np.clip((derivative@tangent_q)/denom,
                          -3*abs(u_q-u_start),3*abs(u_q-u_start)))
    u = CubicHermiteSpline([0.,1.],[u_start,u_q],[u_q-u_start,du_end])
    t = np.linspace(0.,1.,max(160,k))
    values = u(t)
    base = spline(values)
    tangent = spline(values,1)
    tangent /= np.maximum(np.linalg.norm(tangent,axis=1)[:,None],1e-9)
    normal = np.column_stack((-tangent[:,1],tangent[:,0]))
    # Zero initial normal offset, first derivative, and second derivative.
    # Match the departure derivative at the far end of the authored transition.
    d_end = float(derivative@normal_q)
    coeff = np.linalg.solve(np.array([[1,1,1],[3,4,5],[6,12,20]],float),
                            np.array([displacement,d_end,0.]))
    departure = coeff[0]*t**3+coeff[1]*t**4+coeff[2]*t**5
    # Numerical overshoot may not create a root on the opposite side of a vein.
    departure = np.maximum(0,departure) if displacement>=0 else np.minimum(0,departure)
    blend = 10*t**3-15*t**4+6*t**5
    bridge = base+normal*departure[:,None]+blend[:,None]*residual
    bridge[-1]=q
    result = np.vstack((bridge[:-1],curve[k:]))
    return result[::-1] if at_end else result
