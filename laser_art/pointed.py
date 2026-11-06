"""Render explicitly authorized non-load-bearing pointed terminal extensions."""
import numpy as np
from PIL import Image, ImageDraw
from .rim import smootherstep


def pointed_parts(stroke,minimum):
    points=np.asarray(stroke['points_xy'],float)
    radii=np.asarray(stroke['radii'],float).copy()
    ends=stroke.get('pointed_ends',[])
    if set(ends)&{r['end'] for r in stroke.get('root_junctions',[])}:
        raise ValueError('A load-bearing root cannot be given a pointed-tip exception.')
    arc=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    tail_length=min(240.,arc[-1]*.65)
    for end in ends:
        d=arc if end==0 else arc[-1]-arc
        radii*=smootherstep(d/max(tail_length,1e-6))
    adequate=np.flatnonzero(radii>=minimum-1e-8)
    if not len(adequate):raise ValueError('Pointed stroke has no manufacturing-width body.')
    a,b=int(adequate[0]),int(adequate[-1])
    body_points=points[a:b+1];body_radii=np.maximum(minimum,radii[a:b+1])
    if len(body_points)==1:
        body_points=np.repeat(body_points,2,axis=0);body_radii=np.repeat(body_radii,2)
    body={'points_xy':body_points.tolist(),'radii':body_radii.tolist()}
    tails=[]
    for end in ends:
        if end==0:
            last=min(len(points)-1,int(np.searchsorted(arc,arc[a]+30)))
            indices=slice(0,last+1)
        else:
            first=max(0,int(np.searchsorted(arc,arc[b]-30)))
            indices=slice(first,len(points))
        tails.append({'points_xy':points[indices].tolist(),'radii':radii[indices].tolist(),
                      'terminal_end':end,'terminal_length_limit_pixels':tail_length})
    return body,tails


def draw_pointed_polygon(strokes,box):
    x0,y0,x1,y1=box
    image=Image.new('1',(x1-x0,y1-y0));draw=ImageDraw.Draw(image)
    for stroke in strokes:
        points=np.asarray(stroke['points_xy'])-(x0,y0)
        radii=np.asarray(stroke['radii'])
        delta=np.gradient(points,axis=0)
        normals=np.column_stack((-delta[:,1],delta[:,0]))
        normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-9)
        polygon=np.vstack((points+normals*radii[:,None],(points-normals*radii[:,None])[::-1]))
        draw.polygon([tuple(p) for p in np.round(polygon).astype(int)],fill=1)
        # One-pixel supercover keeps the very fine raster apex four-connected.
        # It does not add a circular cap or enlarge a structural bridge.
        previous=None
        for a,b in zip(points[:-1],points[1:]):
            count=max(2,int(np.max(np.abs(b-a))*3)+2)
            for point in np.linspace(a,b,count):
                x,y=map(int,np.round(point))
                if previous is not None:
                    px,py=previous
                    draw.line((px,py,x,py),fill=1,width=1)
                    draw.line((x,py,x,y),fill=1,width=1)
                draw.point((x,y),fill=1)
                previous=(x,y)
    return np.asarray(image,dtype=bool)


def validate_tip_policy(full_report,body_report,paths,body_paths,border):
    """Validate structural material strictly and disclose localized tip waivers."""
    import copy
    report=copy.deepcopy(full_report)
    for row,body_row,path,body_path in zip(report['layers'],body_report['layers'],paths,body_paths):
        with Image.open(path) as image:full=(np.asarray(image.convert('L'))==0)&~border
        with Image.open(body_path) as image:body=(np.asarray(image.convert('L'))==0)&~border
        body_subset=not bool(np.any(body&~full))
        extension_pixels=int(np.count_nonzero(full&~body))
        raw_width_pass=(row['minimum_width_uncovered_pixels']==0 and row['connected_backbones_after_19px_erosion']==1)
        row['uniform_width_without_exceptions_passed']=bool(raw_width_pass)
        row['terminal_extension_pixels']=extension_pixels
        row['structural_body_is_subset']=body_subset
        row['structural_width_passed']=bool(body_row['minimum_width_uncovered_pixels']==0 and
                                            body_row['connected_backbones_after_19px_erosion']==1)
        row['structural_body_validation_passed']=body_row['passed']
        row['guaranteed_stroke_diameter_pixels']=None if extension_pixels else row['guaranteed_stroke_diameter_pixels']
        row['minimum_structural_stroke_diameter_pixels']=body_row['guaranteed_stroke_diameter_pixels']
        row['tip_width_exception']='Only rendered terminal extensions; roots, body, core and bridges remain strict'
        # Exact opening is monotone: an opening-invariant body contained in the
        # full image proves that no width violation can lie outside extensions.
        row['width_violations_outside_terminal_extensions']=0 if body_row['minimum_width_uncovered_pixels']==0 and body_subset else None
        metadata=(row['dimensions']==body_row['dimensions'] and row['dpi'] and body_row['dpi'] and
                  all(abs(a-b)<.02 for a,b in zip(row['dpi'],body_row['dpi'])))
        nonwidth=(metadata and row['containment_violations']==0 and row['missing_core_pixels']==0 and
                  row['symmetry_mismatched_pixels']==0 and row['artwork_connected_components']==1 and
                  row['meaningful_removal'] and row['binary_colors'] and row['registration_exact'] and
                  row['registration_separate'] and row['top_is_core_only'] is not False)
        row['passed']=bool(nonwidth and body_row['passed'] and body_subset)
    report['pointed_tip_exception_enabled']=True
    report['uniform_minimum_width_for_entire_design_passed']=all(r['uniform_width_without_exceptions_passed'] for r in report['layers'])
    report['structural_bodies_validation_file']='structural_bodies_validation.json'
    report['policy']='Decorative free tips may taper to a point; all structural bodies and bridges must satisfy the original 38-pixel minimum'
    report['passed']=bool(all(r['passed'] for r in report['layers']) and body_report['passed'])
    return report
