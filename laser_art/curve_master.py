"""Build one master from explicit, independently smooth curve components.

The reference guides curve tracing only. No raster ownership cells or clipping
to its jagged mask are used to define a surviving component's edge.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from types import SimpleNamespace
import zipfile

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
from scipy.interpolate import splprep, splev
from scipy.spatial import cKDTree

from .engine import boundary_mask, validate
from .finish import green_stack, layer_sheet, structural_guide
from .flow_set import remove_group, schedule_ornaments, save_art
from .model import Manufacturing
from .reference import artwork_from_reference, thin
from .reference_layers import disk_union
from .smooth import graph_paths
from .rim import rim_clearance, inward_normals, extend_to_outline


def boundary_loop(solid):
    """Trace the actual exterior pixel polygon, then fit it once as a curve."""
    padded = np.pad(solid, 1)
    solid = padded[1:-1, 1:-1]
    edges = {}
    sides = [((-1, 0), lambda x,y: ((x,y),(x+1,y))),
             ((0, 1), lambda x,y: ((x+1,y),(x+1,y+1))),
             ((1, 0), lambda x,y: ((x+1,y+1),(x,y+1))),
             ((0, -1), lambda x,y: ((x,y+1),(x,y)))]
    h,w = solid.shape
    for (dy,dx), vertices in sides:
        neighbor = padded[1+dy:1+dy+h, 1+dx:1+dx+w]
        for y,x in np.argwhere(solid & ~neighbor):
            a,b = vertices(int(x),int(y))
            edges.setdefault(a,[]).append(b)
    loops = []
    while edges:
        start = next(iter(edges))
        here, path = start, [start]
        while here in edges:
            nxt = edges[here].pop()
            if not edges[here]: del edges[here]
            path.append(nxt)
            here = nxt
            if here == start: break
        if path[-1] == start: loops.append(path)
    if not loops: raise ValueError('Cannot trace source silhouette.')
    return np.asarray(max(loops,key=len),float)[:,::-1] - .5


def fit_curve(points, closed=False, smoothness=1.5):
    points = np.asarray(points,float)
    keep = np.r_[True, np.any(np.diff(points,axis=0)!=0,axis=1)]
    points = points[keep]
    if len(points) < 2: raise ValueError('Curve needs distinct points.')
    if closed and not np.array_equal(points[0],points[-1]):
        points = np.vstack((points,points[0]))
    spline,_ = splprep(points.T, s=len(points)*smoothness, k=min(3,len(points)-1), per=closed)
    length = np.linalg.norm(np.diff(points,axis=0),axis=1).sum()
    t = np.linspace(0,1,max(16,int(length*2)))
    result = np.asarray(splev(t,spline)).T
    if not closed:
        result += (1-t)[:,None]*(points[0]-result[0]) + t[:,None]*(points[-1]-result[-1])
    return result


def sample_stroke(points_yx, radii, scale, offset):
    points_yx = np.asarray(points_yx,float)
    positions = points_yx[:,::-1]*scale + np.asarray(offset)
    return {'points_xy':positions.tolist(), 'radii':np.asarray(radii,float).tolist()}


def round_strokes(strokes, settings):
    radius = settings.radius
    all_points = np.concatenate([np.asarray(s['points_xy']) for s in strokes])
    max_radius = max(max(s['radii']) for s in strokes)
    x0,y0 = np.maximum(0,np.floor(all_points.min(axis=0)-max_radius-4)).astype(int)
    x1,y1 = np.minimum((settings.width,settings.height),np.ceil(all_points.max(axis=0)+max_radius+5)).astype(int)
    seed = Image.new('1',(int(x1-x0),int(y1-y0)))
    draw = ImageDraw.Draw(seed)
    for stroke in strokes:
        points = np.asarray(stroke['points_xy'])-(x0,y0)
        radii = np.asarray(stroke['radii'])-radius
        if np.any(radii < 0): raise ValueError('Stroke below manufacturing width.')
        dy = np.gradient(points[:,1]); dx = np.gradient(points[:,0])
        lengths = np.maximum(np.hypot(dx,dy),1e-6)
        normals = np.column_stack((-dy/lengths,dx/lengths))
        left, right = points+normals*radii[:,None], points-normals*radii[:,None]
        polygon = np.vstack((left,right[::-1]))
        draw.polygon([tuple(p) for p in polygon],fill=1)
        draw.line([tuple(p) for p in points],fill=1,width=1)
        for p,r in ((points[0],radii[0]),(points[-1],radii[-1])):
            if r > 0: draw.ellipse((p[0]-r,p[1]-r,p[0]+r,p[1]+r),fill=1)
    mask = disk_union(np.asarray(seed,dtype=bool),radius)
    return (int(x0),int(y0),int(x1),int(y1)),mask



def raster_strokes(strokes,settings,structural_only=False):
    from .pointed import pointed_parts,draw_pointed_polygon
    bodies,tails=[],[]
    for stroke in strokes:
        if stroke.get('pointed_ends'):
            body,extensions=pointed_parts(stroke,settings.radius)
            bodies.append(body);tails.extend(extensions)
        else:bodies.append(stroke)
    body_box,body_mask=round_strokes(bodies,settings)
    if structural_only or not tails:return body_box,body_mask
    all_points=np.concatenate([np.asarray(s['points_xy']) for s in tails])
    max_radius=max(max(s['radii']) for s in tails)
    lo=np.minimum(body_box[:2],np.floor(all_points.min(axis=0)-max_radius-3)).astype(int)
    hi=np.maximum(body_box[2:],np.ceil(all_points.max(axis=0)+max_radius+4)).astype(int)
    lo=np.maximum(lo,0);hi=np.minimum(hi,(settings.width,settings.height))
    box=tuple(map(int,(*lo,*hi)))
    mask=draw_pointed_polygon(tails,box).copy()
    x0,y0,x1,y1=body_box
    mask[y0-lo[1]:y1-lo[1],x0-lo[0]:x1-lo[0]]|=body_mask
    return box,mask


def curve_components(reference,pointed_tips=False):
    with Image.open(reference) as image: native,crop = artwork_from_reference(image)
    settings = Manufacturing(radius=20)
    scale = min(6000/native.shape[0],5400/native.shape[1])
    width,height = native.shape[1]*scale,native.shape[0]*scale
    offset = ((settings.width-width)/2,(settings.height-height)/2)
    solid = ndi.binary_fill_holes(native)
    inset = ndi.distance_transform_edt(solid) > (27/scale)
    outline = fit_curve(boundary_loop(inset),closed=True,smoothness=1.2)
    core_stroke = sample_stroke(outline,np.full(len(outline),27.),scale,offset)
    _,routes = structural_guide(native,factor=1)
    distance = ndi.distance_transform_edt(native)
    skeleton = thin(native)
    support = np.zeros_like(native)
    parent_curves = [outline]
    parent_radii = [np.full(len(outline),27.)]
    main_strokes = []
    # Each complete primary vein has one smooth centerline and one analytic taper.
    for route in routes:
        points=np.asarray(route,float)
        _,outline_index=cKDTree(outline).query(points[0])
        if outline[outline_index,1]<native.shape[1]*.30 or outline[outline_index,1]>native.shape[1]*.70:
            points,entry_tangent=extend_to_outline(points,outline)
        else:
            points=points.copy();points[0]=outline[outline_index];entry_tangent=None
        curve=fit_curve(points,smoothness=2.)
        if entry_tangent is not None:
            from .tendrils import tangent_root
            curve=tangent_root(curve,entry_tangent)
        radii=23+(90-23)*np.linspace(0,1,len(curve))**1.7
        main_strokes.append(sample_stroke(curve,radii,scale,offset))
        parent_curves.append(curve)
        parent_radii.append(radii)
        ys,xs = np.asarray(route).T
        support[ys,xs] = True
    # The petiole fill is another original component, removed with primary veins.
    root = np.asarray(routes[0][-1],float)
    ys = np.arange(int(root[0]),native.shape[0]-max(2,round(27/scale)))
    trunk = np.column_stack((ys,np.full(len(ys),(native.shape[1]-1)/2)))
    trunk = fit_curve(trunk,smoothness=.5)
    sample_y = np.clip(np.round(trunk[:,0]).astype(int),0,native.shape[0]-1)
    sample_x = np.clip(np.round(trunk[:,1]).astype(int),0,native.shape[1]-1)
    trunk_radii = np.clip(ndi.gaussian_filter1d(distance[sample_y,sample_x]*scale,20),27,100)
    main_strokes.append(sample_stroke(trunk,trunk_radii,scale,offset))
    parent_curves.append(trunk)
    parent_radii.append(trunk_radii)
    support[np.clip(ys,0,native.shape[0]-1),round((native.shape[1]-1)/2)] = True
    support |= support[:,::-1].copy()
    # Mark original outline-adjacent skeleton as support, never a scroll fragment.
    support |= skeleton & (ndi.distance_transform_edt(solid) < 10)
    optional = skeleton & ~support
    labels,count = ndi.label(optional,np.ones((3,3)))
    parent_tree = cKDTree(np.concatenate(parent_curves))
    parent_points = np.concatenate(parent_curves)
    components = [{'id':1,'role':'outline','priority':1e9,'strokes':[core_stroke]},
                  {'id':2,'role':'main_veins','priority':1e6,'strokes':main_strokes}]
    for label in range(1,count+1):
        component = labels==label
        points = np.argwhere(component)
        # Construct one half, then mirror actual raster masks exactly.
        if not len(points) or np.median(points[:,1]) >= native.shape[1]/2: continue
        if len(points)<10: continue
        from .tendrils import make_tendrils
        strokes = make_tendrils(component,support,parent_curves,parent_radii,
                                scale,offset,settings.radius,pointed=pointed_tips)
        if strokes:
            components.append({'id':len(components)+1,'role':'whole_scroll_pair',
                               'priority':float(np.mean(distance[component])), 'strokes':strokes})
    return settings,components,{'source_crop':crop,'scale':scale,'offset':offset}


def draw_component(component,settings,structural_only=False):
    box,mask = raster_strokes(component['strokes'],settings,structural_only=structural_only)
    x0,y0,x1,y1 = box
    full = np.zeros((settings.height,settings.width),bool)
    full[y0:y1,x0:x1] = mask
    # The outline is already closed. Mirroring halves avoids a double shifted edge.
    if component['role'] in ('outline','main_veins'):
        half = full[:,:settings.width//2]
        full = np.concatenate((half,half[:,::-1]),axis=1)
    else:
        full |= full[:,::-1].copy()
    ys,xs = np.where(full)
    box = (int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1)
    x0,y0,x1,y1 = box
    return box,full[y0:y1,x0:x1].copy()



def clean_clipped_body(mask,radius):
    padding=radius+2
    padded=np.pad(mask,padding)
    cleaned=disk_union(ndi.distance_transform_edt(padded)>radius,radius)
    return cleaned[padding:-padding,padding:-padding]


def rasterize_master(settings,components,pointed_tips=False,progress=None):
    border = boundary_mask(settings)
    cache,metadata = {},{c['id']:c for c in components}
    body_cache={}
    body_coverage=np.zeros((settings.height,settings.width),np.uint16) if pointed_tips else None
    silhouette = None
    coverage = np.zeros((settings.height,settings.width),np.uint16)
    for component in components:
        box,mask = draw_component(component,settings)
        x0,y0,x1,y1 = box
        if component['id'] == 1:
            outline_image = np.zeros(coverage.shape,bool)
            outline_image[y0:y1,x0:x1] = mask
            silhouette = ndi.binary_fill_holes(outline_image)
        else:
            # Clip only at the permanent outer silhouette, under its existing
            # outline band. No component edge is clipped at scroll junctions.
            mask &= silhouette[y0:y1,x0:x1]
        if pointed_tips:
            body_box,body_mask=draw_component(component,settings,structural_only=True)
            bx0,by0,bx1,by1=body_box
            body_mask &= silhouette[by0:by1,bx0:bx1]
            clean_body=clean_clipped_body(body_mask,settings.radius)
            old_body=np.zeros(mask.shape,bool);new_body=np.zeros(mask.shape,bool)
            old_body[by0-y0:by1-y0,bx0-x0:bx1-x0]=body_mask
            new_body[by0-y0:by1-y0,bx0-x0:bx1-x0]=clean_body
            mask=new_body | (mask & ~old_body)
            body_cache[component['id']]=(body_box,clean_body)
            body_coverage[by0:by1,bx0:bx1]+=clean_body
        else:
            mask=clean_clipped_body(mask,settings.radius)
        cache[component['id']] = box,mask
        coverage[y0:y1,x0:x1] += mask
        if progress:progress('curves',component['id'],len(components))
    core = np.zeros(coverage.shape,bool)
    (x0,y0,x1,y1),mask = cache[1]; core[y0:y1,x0:x1] = mask
    foundation = core.copy()
    (x0,y0,x1,y1),mask = cache[2]; foundation[y0:y1,x0:x1] |= mask
    if ndi.label(foundation)[1] != 1: raise ValueError('Curve foundation is disconnected.')
    return {'border':border,'cache':cache,'metadata':metadata,'body_cache':body_cache,
            'body_coverage':body_coverage,'silhouette':silhouette,'coverage':coverage,
            'core':core,'foundation':foundation}


def build(reference,output,layers=5,pointed_tips=False,frozen_master=None,progress=None):
    output = Path(output)
    if layers < 2: raise ValueError('At least two layers are required.')
    if output.exists() and any(output.iterdir()): raise ValueError('Use an empty output directory.')
    if frozen_master is None:
        if progress:progress('trace',0,1)
        settings,components,geometry=curve_components(reference,pointed_tips=pointed_tips)
    else:
        if frozen_master['pointed_tips']!=pointed_tips:raise ValueError('Tip setting changed since master review.')
        settings=Manufacturing(**frozen_master['manufacturing'])
        components,geometry=frozen_master['components'],frozen_master['geometry']
    state=rasterize_master(settings,components,pointed_tips,progress)
    border,cache,metadata,body_cache,body_coverage,silhouette,coverage,core,foundation=(
        state[key] for key in ('border','cache','metadata','body_cache','body_coverage',
                              'silhouette','coverage','core','foundation'))
    del state
    optional_area = int(np.count_nonzero((coverage>0)&~foundation))
    stages = ([[group for group in cache if group != 1]] if layers == 2 else
              schedule_ornaments(coverage.copy(),cache,metadata,optional_area,layers-2)+[[2]])
    output.mkdir(parents=True,exist_ok=True)
    paths=[]
    body_paths=[]
    if pointed_tips:(output/'structural_bodies').mkdir()
    for i in range(layers):
        suffix='_bottom' if i==0 else '_top' if i==layers-1 else ''
        path=output/f'layer_{i+1:02d}{suffix}.png'
        if i:
            for group in stages[i-1]:
                remove_group(coverage,cache[group])
                if pointed_tips:remove_group(body_coverage,body_cache[group])
        save_art(coverage>0,border,path);paths.append(path)
        if pointed_tips:
            body_path=output/'structural_bodies'/path.name
            save_art(body_coverage>0,border,body_path);body_paths.append(body_path)
        print('Saved',path.name,flush=True)
        if progress:progress('layers',i+1,layers)
    (output/'master_curves.json').write_text(json.dumps({'source_sha256':hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
        'geometry':geometry,'manufacturing':settings.__dict__,'pointed_tip_exception_enabled':pointed_tips,'components':components,'removal_stages':stages,
        'method':'Complete independent smooth curve components; no raster partition boundaries'},indent=2))
    # Persist exact rendered component masks to demonstrate immutable survivors.
    packed={}
    for group,(box,mask) in cache.items():
        packed[f'group_{group}_box']=np.array(box)
        packed[f'group_{group}_shape']=np.array(mask.shape)
        packed[f'group_{group}_bits']=np.packbits(mask)
    if pointed_tips:
        for group,(box,mask) in body_cache.items():
            packed[f'body_{group}_box']=np.array(box)
            packed[f'body_{group}_shape']=np.array(mask.shape)
            packed[f'body_{group}_bits']=np.packbits(mask)
    np.savez_compressed(output/'master_component_masks.npz',**packed)
    del cache,coverage,foundation,body_cache,body_coverage
    stage_objects=[[SimpleNamespace(id=str(i)) for i in stage] for stage in stages]
    if progress:progress('validate',0,2 if pointed_tips else 1)
    report=validate(paths,core,settings,stage_objects)
    if pointed_tips:
        from .pointed import validate_tip_policy
        (output/'strict_width_diagnostics.json').write_text(json.dumps(report,indent=2))
        if progress:progress('validate',1,2)
        body_report=validate(body_paths,core,settings,stage_objects)
        (output/'structural_bodies_validation.json').write_text(json.dumps(body_report,indent=2))
        report=validate_tip_policy(report,body_report,paths,body_paths,border)
        report['pointed_terminal_count']=2*sum(len(s.get('pointed_ends',[])) for c in components for s in c['strokes'])
    report['outer_silhouette_unchanged'] = True
    for path in paths:
        with Image.open(path) as image:
            artwork = (np.asarray(image.convert('L')) == 0) & ~border
        if np.any(artwork & ~silhouette):
            report['outer_silhouette_unchanged'] = False
    report['passed'] = report['passed'] and report['outer_silhouette_unchanged']
    from .rim import audit_lateral_rim
    with Image.open(paths[0]) as image:
        bottom_art=(np.asarray(image.convert('L'))==0)&~border
    rim_audit=audit_lateral_rim(bottom_art,core,components,settings)
    (output/'lateral_rim_audit.json').write_text(json.dumps(rim_audit,indent=2))
    report['lateral_rim_audit_passed']=rim_audit['passed']
    report['unplanned_lateral_rim_pixels']=rim_audit['unplanned_lateral_rim_pixels']
    report['passed']=report['passed'] and rim_audit['passed']
    junctions=[root for c in components for stroke in c['strokes']
               for root in stroke.get('root_junctions',[])]
    report['authored_roots_checked']=len(junctions)
    report['all_roots_start_inside_parent']=all(root['root_inside_parent'] for root in junctions)
    report['minimum_root_clearance_pixels']=min((root['parent_radius']-root['root_radius']-root['center_offset_pixels'] for root in junctions),default=None)
    report['passed']=report['passed'] and report['all_roots_start_inside_parent']
    report['geometry_method']='Parent-following root transitions and graph-wide continuous taper; immutable curve components'
    (output/'attachment_audit.json').write_text(json.dumps({'roots':junctions,'roots_checked':len(junctions),'all_roots_start_inside_parent':report['all_roots_start_inside_parent'],'minimum_root_clearance_pixels':report['minimum_root_clearance_pixels']},indent=2))
    (output/'validation_report.json').write_text(json.dumps(report,indent=2))
    if not report['passed']: raise ValueError(f'Validation failed: {output}/validation_report.json')
    if progress:progress('previews',0,1)
    legend=green_stack(paths,border,output); layer_sheet(paths,output)
    (output/'green_stack_legend.json').write_text(json.dumps(legend,indent=2))
    for path in paths:
        with Image.open(path) as image:
            preview=image.convert('RGB');preview.thumbnail((600,680));preview.save(output/f'{path.stem}_preview.png')
    if progress:progress('package',0,1)
    bundle_name=f'ginkgo_pointed_tips_{layers}_layers.zip' if pointed_tips else f'ginkgo_tapered_tangent_{layers}_layers.zip'
    with zipfile.ZipFile(output/bundle_name,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.suffix!='.zip': archive.write(path,path.relative_to(output))
    print(json.dumps({'passed':True,'component_groups':len(components),
                      'areas':[r['artwork_pixels'] for r in report['layers']]},indent=2),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference');parser.add_argument('--output',required=True)
    parser.add_argument('--layers',type=int,default=5)
    parser.add_argument('--pointed-tips',action='store_true',help='Allow below-minimum-width decorative terminal extensions; keep structural bodies strict')
    args=parser.parse_args();build(args.reference,args.output,args.layers,pointed_tips=args.pointed_tips)


if __name__=='__main__':main()
